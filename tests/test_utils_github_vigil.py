"""Spec-0065/T2：守夜 level-triggered `_sense` 依赖的四类原生读的契约测试。

覆盖本 spec 新增的 8 个函数：pr_for_branch / pr_snapshot / _head_committed_at /
check_snapshot / check_logs / issue_rest_id / list_blocked_by / add_blocked_by。

所有 gh 子进程一律 mock（monkeypatch subprocess.run），不真实调用 gh——沿用既有 github
测试的房规（见 tests/test_github_claim_label.py / test_github_is_open_draft.py）。

这里断言的是**解析不变量**：守夜的分支表（`_classify`）建立在这些字段的语义之上，任一解析
漂移都会让调度器做出错误决策（例如把已合并的 issue 重做一遍、或把「零个 check」读成「CI 绿了」
直接合并一份没跑过 CI 的代码）。
"""

import json
import subprocess
from dataclasses import dataclass

import pytest

from openagents.utils.github import (
    Blocker,
    CheckSnapshot,
    GithubError,
    PRSnapshot,
    _head_committed_at,
    add_blocked_by,
    check_logs,
    check_snapshot,
    issue_rest_id,
    list_blocked_by,
    pr_for_branch,
    pr_snapshot,
)


@dataclass
class _FakeProc:
    """伪 subprocess.CompletedProcess。"""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    """单一响应的 subprocess.run 替身；`runner.calls` 记录每次的 argv（供断言 gh 参数）。"""
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    runner.calls = calls
    return runner


def _fake_run_seq(*, responses):
    """按调用顺序逐个回放响应的 subprocess.run 替身（供一次业务调用发多次 gh 的场景）。

    responses: list[_FakeProc]——`add_blocked_by` 先 `issue_rest_id`（GET）再 POST，两次 gh
    的 stdout 不同，单一响应的 _fake_run 表达不了。
    """
    calls: list[list[str]] = []
    queue = list(responses)

    def runner(args, **kwargs):
        calls.append(list(args))
        return queue.pop(0) if queue else _FakeProc()

    runner.calls = calls
    return runner


# --------------------------------------------------------------------------- #
# pr_for_branch（Spec-0065/T2：**状态无关**——merged/closed 的 PR 也必须看得见）
# --------------------------------------------------------------------------- #


def test_pr_for_branch_uses_state_all(monkeypatch):
    # 核心回归闸：查法必须是 `--state all`。若退回 open-only，PR 一合并就从列表消失，守夜下一圈
    # 会把该 issue 读成「还没有 PR」→ 走分支④再开一个 PR 把同一个 issue 重做一遍。
    payload = json.dumps([{"number": 164, "url": "https://github.com/o/r/pull/164"}])
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    pr_for_branch(branch="openagents/issue-150")

    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "list"]
    assert cmd[cmd.index("--state") + 1] == "all"
    assert cmd[cmd.index("--head") + 1] == "openagents/issue-150"


def test_pr_for_branch_returns_merged_pr(monkeypatch):
    # merged 是 `_classify` 的终止条件——终止条件只能从「那个 PR 现在是什么状态」读出来，
    # 故已合并的 PR 必须照样被返回（而不是 None）。
    payload = json.dumps([{"number": 164, "url": "https://github.com/o/r/pull/164"}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    pr = pr_for_branch(branch="openagents/issue-150")

    assert pr is not None
    assert pr.number == 164
    assert pr.url == "https://github.com/o/r/pull/164"


def test_pr_for_branch_returns_closed_pr(monkeypatch):
    # 人主动关掉的 PR 同样要看得见（否则守夜会重开一个）。
    payload = json.dumps([{"number": 99, "url": "https://github.com/o/r/pull/99"}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    pr = pr_for_branch(branch="openagents/issue-9")

    assert pr is not None and pr.number == 99


def test_pr_for_branch_none_when_never_opened(monkeypatch):
    # 从没开过 PR（空列表）→ None，这才是「该走分支④开 PR」的唯一合法信号。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))

    assert pr_for_branch(branch="openagents/issue-1") is None


def test_pr_for_branch_none_when_number_missing(monkeypatch):
    # 行里缺 number 属残缺结构 → 保守当作「没有 PR」，不抛。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps([{"url": "u"}])))

    assert pr_for_branch(branch="b") is None


def test_pr_for_branch_none_when_payload_not_list(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"oops": 1})))

    assert pr_for_branch(branch="b") is None


def test_pr_for_branch_takes_most_recent_only(monkeypatch):
    # `--limit 1`：gh 按新→旧排，只取最近一个。
    runner = _fake_run(stdout=json.dumps([{"number": 3, "url": "u3"}]))
    monkeypatch.setattr(subprocess, "run", runner)

    assert pr_for_branch(branch="b").number == 3
    cmd = runner.calls[-1]
    assert cmd[cmd.index("--limit") + 1] == "1"


def test_pr_for_branch_raises_on_gh_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401"))

    with pytest.raises(GithubError):
        pr_for_branch(branch="b")


# --------------------------------------------------------------------------- #
# pr_snapshot（Spec-0065/T2：同源一次往返的 PR 现态；head_pushed_at 是看门狗的唯一时间戳）
# --------------------------------------------------------------------------- #


def _pr_view_payload(**overrides):
    """一份真实形状的 `gh pr view --json …` 响应；按需覆盖单个字段。"""
    payload = {
        "number": 164,
        "state": "OPEN",
        "headRefOid": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "labels": [{"name": "openagents"}, {"name": "review-approved:a1b2c3d"}],
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "commits": [
            {"oid": "old", "committedDate": "2026-07-14T09:00:00Z"},
            {"oid": "head", "committedDate": "2026-07-14T10:30:00Z"},
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_pr_snapshot_parses_every_field(monkeypatch):
    runner = _fake_run(stdout=_pr_view_payload())
    monkeypatch.setattr(subprocess, "run", runner)

    snap = pr_snapshot(pr_number=164)

    assert isinstance(snap, PRSnapshot)
    assert snap.number == 164
    assert snap.state == "OPEN"
    assert snap.head_sha == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    assert snap.labels == ("openagents", "review-approved:a1b2c3d")
    assert snap.mergeable == "MERGEABLE"
    assert snap.merge_state_status == "CLEAN"
    # head_pushed_at 取 commits **末条**（= head）的 committedDate，不是首条。
    assert snap.head_pushed_at == "2026-07-14T10:30:00Z"
    # Spec-0017/T1: isDraft 缺省 → is_draft 默认 False（既有构造点/payload 零改动仍可实例化）。
    assert snap.is_draft is False
    # 所有字段必须在同一次 `gh pr view` 里取回（同源快照，不会读到自相矛盾的中间态）。
    cmd = runner.calls[-1]
    assert cmd[:4] == ["gh", "pr", "view", "164"]
    fields = cmd[cmd.index("--json") + 1].split(",")
    assert set(fields) == {
        "number",
        "state",
        "headRefOid",
        "labels",
        "mergeable",
        "mergeStateStatus",
        "commits",
        "isDraft",  # Spec-0017/T1: draft 与其余现态同源一次往返读入
    }
    assert len(runner.calls) == 1


def test_pr_snapshot_is_draft_true(monkeypatch):
    # Spec-0017/T1: isDraft=true → is_draft True（draft 升为一等快照事实）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(isDraft=True)))
    assert pr_snapshot(pr_number=164).is_draft is True


def test_pr_snapshot_is_draft_false(monkeypatch):
    # Spec-0017/T1: isDraft=false → is_draft False（已转正的 PR）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(isDraft=False)))
    assert pr_snapshot(pr_number=164).is_draft is False


def test_pr_snapshot_is_draft_non_bool_defaults_false(monkeypatch):
    # Spec-0017/T1: isDraft 非布尔（异常结构）→ 容错默认 False（比照 is_draft 容错风格）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(isDraft="yes")))
    assert pr_snapshot(pr_number=164).is_draft is False


def test_pr_snapshot_state_and_mergeable_upcased(monkeypatch):
    # 原值大写、不归一化为布尔——「哪种组合算冲突」的判定属调用方（recipes.vigil）。
    payload = _pr_view_payload(state="merged", mergeable="conflicting", mergeStateStatus="dirty")
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = pr_snapshot(pr_number=164)

    assert snap.state == "MERGED"
    assert snap.mergeable == "CONFLICTING"
    assert snap.merge_state_status == "DIRTY"


def test_pr_snapshot_mergeable_unknown_is_legal(monkeypatch):
    # UNKNOWN（GitHub 异步尚未算完，刚 push 常见）是合法值，如实回传、不抛。
    payload = _pr_view_payload(mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = pr_snapshot(pr_number=164)

    assert snap.mergeable == "UNKNOWN"
    assert snap.merge_state_status == "UNKNOWN"


def test_pr_snapshot_missing_mergeable_defaults_to_unknown(monkeypatch):
    # 与 mergeability() 不同：字段缺失/为 null 在快照里落到 "UNKNOWN"（守夜按「还没算完」处理，
    # 下一圈再看），不因此炸掉整轮 _sense。
    payload = _pr_view_payload(mergeable=None, mergeStateStatus=None)
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = pr_snapshot(pr_number=164)

    assert snap.mergeable == "UNKNOWN"
    assert snap.merge_state_status == "UNKNOWN"


def test_pr_snapshot_empty_labels(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(labels=[])))

    assert pr_snapshot(pr_number=164).labels == ()


def test_pr_snapshot_head_pushed_at_empty_when_no_commits(monkeypatch):
    # 无 commits（异常/残缺结构）→ 空串：看门狗据此「不看门」，而不是拿 None 去算时差炸掉。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(commits=[])))

    assert pr_snapshot(pr_number=164).head_pushed_at == ""


def test_pr_snapshot_fresh_pr_has_timestamp_from_head_commit(monkeypatch):
    # 「刚推上去、CI 一个 check 都没起、也无任何评论」的 PR：除了 head commit 自己没有任何时间戳
    # 可读。缺了它 last_progress_at 恒为 None → 看门狗永不响 →「CI 永不启动」这条死法静默烂掉。
    payload = _pr_view_payload(
        commits=[{"oid": "head", "committedDate": "2026-07-14T11:00:00Z"}],
        labels=[],
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert pr_snapshot(pr_number=164).head_pushed_at == "2026-07-14T11:00:00Z"


def test_pr_snapshot_raises_on_non_dict(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps(["oops"])))

    with pytest.raises(GithubError):
        pr_snapshot(pr_number=164)


def test_pr_snapshot_raises_when_number_missing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "OPEN"})))

    with pytest.raises(GithubError):
        pr_snapshot(pr_number=164)


# --------------------------------------------------------------------------- #
# _head_committed_at（Spec-0065/T2：head 时间戳的解析纯函数——直接单测，免绕 gh）
# --------------------------------------------------------------------------- #


def test_head_committed_at_takes_last_commit():
    commits = [
        {"committedDate": "2026-07-14T09:00:00Z"},
        {"committedDate": "2026-07-14T10:00:00Z"},
    ]
    assert _head_committed_at(commits=commits) == "2026-07-14T10:00:00Z"


def test_head_committed_at_empty_for_empty_or_bad_shapes():
    # 空列表 / None / 非列表 / 末条非 dict / 缺 committedDate —— 一律空串（fail-soft）。
    assert _head_committed_at(commits=[]) == ""
    assert _head_committed_at(commits=None) == ""
    assert _head_committed_at(commits={"committedDate": "x"}) == ""
    assert _head_committed_at(commits=["not-a-dict"]) == ""
    assert _head_committed_at(commits=[{"oid": "abc"}]) == ""


# --------------------------------------------------------------------------- #
# check_snapshot（Spec-0065/T2：**count 不能省**——零个 check ≠ 全绿）
# --------------------------------------------------------------------------- #


def test_check_snapshot_zero_checks_is_not_green_by_count(monkeypatch):
    # 最关键的一条：gh 返回空列表时 state 仍是 "pass"（沿用 _classify_checks 的旧口径），但
    # **count == 0** 让调用方能把它读成「还在等 CI」而非「CI 绿了」——否则守夜会直接合并一份
    # 一个 check 都没跑过的代码。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))

    snap = check_snapshot(pr_number=164)

    assert isinstance(snap, CheckSnapshot)
    assert snap.count == 0
    assert snap.latest_started_at == ""
    # count 是区分「零个 check」与「全绿」的唯一凭据——state 本身分不开这两者。
    assert snap.state == "pass"


def test_check_snapshot_no_checks_reported_is_swallowed_with_zero_count(monkeypatch):
    # 仓库无任何 CI 时 gh 非零退出并报 "no checks reported"——吞掉，但计数如实为 0。
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="no checks reported on the 'x' branch")
    )

    snap = check_snapshot(pr_number=164)

    assert snap == CheckSnapshot(state="pass", count=0, latest_started_at="")


def test_check_snapshot_all_green_has_nonzero_count(monkeypatch):
    # 「全绿」与「零个 check」的 state 相同，靠 count 区分：这里 count == 2。
    payload = json.dumps(
        [
            {
                "name": "test",
                "state": "SUCCESS",
                "link": "https://x/1",
                "startedAt": "2026-07-14T10:00:00Z",
            },
            {
                "name": "lint",
                "state": "SKIPPED",
                "link": "https://x/2",
                "startedAt": "2026-07-14T10:05:00Z",
            },
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = check_snapshot(pr_number=164)

    assert snap.state == "pass"
    assert snap.count == 2
    # latest_started_at 取最近一次开始时间（ISO 字典序即时间序）。
    assert snap.latest_started_at == "2026-07-14T10:05:00Z"


def test_check_snapshot_pending_rollup(monkeypatch):
    # 任一 check 仍在跑（IN_PROGRESS / QUEUED / PENDING 等非 pass 非 fail 态）→ pending。
    payload = json.dumps(
        [
            {
                "name": "test",
                "state": "SUCCESS",
                "link": "",
                "startedAt": "2026-07-14T10:00:00Z",
            },
            {
                "name": "e2e",
                "state": "IN_PROGRESS",
                "link": "",
                "startedAt": "2026-07-14T10:02:00Z",
            },
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = check_snapshot(pr_number=164)

    assert snap.state == "pending"
    assert snap.count == 2
    assert snap.latest_started_at == "2026-07-14T10:02:00Z"


def test_check_snapshot_failure_beats_pending(monkeypatch):
    # 失败优先于进行中（同 _classify_checks）：一失一跑 → fail。
    payload = json.dumps(
        [
            {
                "name": "e2e",
                "state": "IN_PROGRESS",
                "link": "",
                "startedAt": "2026-07-14T10:02:00Z",
            },
            {"name": "test", "state": "FAILURE", "link": "https://x/9", "startedAt": ""},
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = check_snapshot(pr_number=164)

    assert snap.state == "fail"
    assert snap.count == 2


def test_check_snapshot_pending_returncode_8_is_allowed(monkeypatch):
    # gh 在仍有 check 进行中时以退出码 8 返回，stdout 仍是合法 JSON——不能当错误抛。
    payload = json.dumps(
        [{"name": "test", "state": "QUEUED", "link": "", "startedAt": "2026-07-14T10:00:00Z"}]
    )
    runner = _fake_run(returncode=8, stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    snap = check_snapshot(pr_number=164)

    assert snap.state == "pending"
    assert snap.count == 1
    cmd = runner.calls[-1]
    assert cmd[:4] == ["gh", "pr", "checks", "164"]
    # startedAt 必须在 --json 请求里，否则 latest_started_at 恒为空、_Clock 失明。
    assert "startedAt" in cmd[cmd.index("--json") + 1].split(",")


def test_check_snapshot_missing_started_at_tolerated(monkeypatch):
    payload = json.dumps([{"name": "test", "state": "SUCCESS", "link": ""}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert check_snapshot(pr_number=164).latest_started_at == ""


def test_check_snapshot_reraises_other_gh_errors(monkeypatch):
    # 只吞 "no checks reported"，鉴权等真错误照抛（判定要「窄」）。
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401 must authenticate")
    )

    with pytest.raises(GithubError):
        check_snapshot(pr_number=164)


# --------------------------------------------------------------------------- #
# check_logs（Spec-0065/T2：失败 check 摘要，喂回 fix-ci 的 agent）
# --------------------------------------------------------------------------- #


def test_check_logs_returns_failed_summaries(monkeypatch):
    payload = json.dumps(
        [
            {"name": "test", "state": "FAILURE", "link": "https://x/run/1"},
            {"name": "lint", "state": "SUCCESS", "link": "https://x/run/2"},
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    logs = check_logs(pr_number=164)

    assert logs == ["test [FAILURE] https://x/run/1"]


def test_check_logs_empty_when_all_green(monkeypatch):
    payload = json.dumps([{"name": "test", "state": "SUCCESS", "link": "https://x/1"}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert check_logs(pr_number=164) == []


def test_check_logs_empty_when_no_checks(monkeypatch):
    # 空 payload / 无 CI 的仓库 → 无失败摘要（不抛）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))
    assert check_logs(pr_number=164) == []

    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="no checks reported on the 'x' branch")
    )
    assert check_logs(pr_number=164) == []


# --------------------------------------------------------------------------- #
# issue_rest_id（Spec-0065/T2：REST 数字 id ≠ issue number）
# --------------------------------------------------------------------------- #


def test_issue_rest_id_happy_path(monkeypatch):
    # REST id（3372285600）与 issue number（150）是两个数——依赖 API 的请求体要的是前者。
    runner = _fake_run(stdout=json.dumps({"id": 3372285600}))
    monkeypatch.setattr(subprocess, "run", runner)

    assert issue_rest_id(number=150) == 3372285600

    cmd = runner.calls[-1]
    assert cmd[:2] == ["gh", "api"]
    assert cmd[2] == "repos/{owner}/{repo}/issues/150"


def test_issue_rest_id_raises_when_id_missing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"number": 150})))

    with pytest.raises(GithubError):
        issue_rest_id(number=150)


def test_issue_rest_id_raises_on_empty_payload(monkeypatch):
    # gh 输出为空 → _gh_json 得到 None → 非 dict → GithubError（不能静默返回 0）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=""))

    with pytest.raises(GithubError):
        issue_rest_id(number=150)


def test_issue_rest_id_raises_on_gh_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="HTTP 404 Not Found"))

    with pytest.raises(GithubError):
        issue_rest_id(number=150)


# --------------------------------------------------------------------------- #
# list_blocked_by（Spec-0065/T2：GitHub 原生依赖边——一次调用给出「边」+「blocker 关没关」）
# --------------------------------------------------------------------------- #


def test_list_blocked_by_parses_edges_and_states(monkeypatch):
    # 响应自带 state → deps_done 直接算出，无需第二轮查询。
    payload = json.dumps(
        [
            {"number": 151, "state": "closed", "title": "T1 底座"},
            {"number": 152, "state": "open", "title": "T2 github"},
        ]
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    blockers = list_blocked_by(number=150)

    assert blockers == [Blocker(number=151, state="CLOSED"), Blocker(number=152, state="OPEN")]
    cmd = runner.calls[-1]
    assert cmd[:2] == ["gh", "api"]
    assert cmd[2] == "repos/{owner}/{repo}/issues/150/dependencies/blocked_by"


def test_list_blocked_by_empty_list(monkeypatch):
    # 无依赖 → []（该 issue 立即可调度）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))

    assert list_blocked_by(number=150) == []


def test_list_blocked_by_404_becomes_empty(monkeypatch):
    # 仓库未开启依赖特性 → 404 归成「无依赖」，不抛（依赖是可选特性）。
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="gh: Not Found (HTTP 404)")
    )

    assert list_blocked_by(number=150) == []


def test_list_blocked_by_skips_rows_without_number(monkeypatch):
    payload = json.dumps([{"state": "open"}, {"number": 152, "state": "open"}, "junk"])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert list_blocked_by(number=150) == [Blocker(number=152, state="OPEN")]


def test_list_blocked_by_missing_state_becomes_empty_string(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps([{"number": 152}])))

    assert list_blocked_by(number=150) == [Blocker(number=152, state="")]


def test_list_blocked_by_non_list_payload_becomes_empty(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"message": "x"})))

    assert list_blocked_by(number=150) == []


def test_list_blocked_by_reraises_other_gh_errors(monkeypatch):
    # 只吞 404，鉴权等真错误照抛。
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401 must authenticate")
    )

    with pytest.raises(GithubError):
        list_blocked_by(number=150)


# --------------------------------------------------------------------------- #
# add_blocked_by（Spec-0065/T2：POST 依赖边；请求体要 blocker 的 REST id，不是 number）
# --------------------------------------------------------------------------- #


def test_add_blocked_by_posts_rest_id_not_number(monkeypatch):
    # 两次 gh：① GET blocker 的 REST id ② POST 到**被挡 issue** 的 blocked_by 端点。
    runner = _fake_run_seq(
        responses=[
            _FakeProc(stdout=json.dumps({"id": 3372285600})),  # issue_rest_id(151)
            _FakeProc(stdout="{}"),  # POST
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    assert add_blocked_by(number=150, blocker_number=151) is None
    assert len(runner.calls) == 2

    # ① 换 id 的那次读的是 blocker（151），不是被挡的 issue（150）。
    lookup = runner.calls[0]
    assert lookup[2] == "repos/{owner}/{repo}/issues/151"

    # ② POST 落在被挡 issue（150）的端点上，且请求体带的是 blocker 的 REST id（3372285600），
    #    而不是它的 issue number（151）——搞反了 GitHub 会把边落到别的 issue 上。
    post = runner.calls[1]
    assert post[:2] == ["gh", "api"]
    assert post[post.index("--method") + 1] == "POST"
    assert "repos/{owner}/{repo}/issues/150/dependencies/blocked_by" in post
    assert "issue_id=3372285600" in post
    assert "issue_id=151" not in post


def test_add_blocked_by_swallows_already_exists(monkeypatch):
    # 边已存在时 GitHub 返回 4xx → 幂等吞掉（同 ensure_label 吞 "already exists"）。
    runner = _fake_run_seq(
        responses=[
            _FakeProc(stdout=json.dumps({"id": 1})),
            _FakeProc(returncode=1, stderr="HTTP 422: Issue dependency already exists"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    assert add_blocked_by(number=150, blocker_number=151) is None


def test_add_blocked_by_swallows_duplicate(monkeypatch):
    runner = _fake_run_seq(
        responses=[
            _FakeProc(stdout=json.dumps({"id": 1})),
            _FakeProc(returncode=1, stderr="HTTP 422: duplicate dependency"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    assert add_blocked_by(number=150, blocker_number=151) is None


def test_add_blocked_by_reraises_other_gh_errors(monkeypatch):
    runner = _fake_run_seq(
        responses=[
            _FakeProc(stdout=json.dumps({"id": 1})),
            _FakeProc(returncode=1, stderr="HTTP 403 Resource not accessible"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    with pytest.raises(GithubError):
        add_blocked_by(number=150, blocker_number=151)


def test_add_blocked_by_propagates_rest_id_lookup_failure(monkeypatch):
    # 换不到 blocker 的 id → 不能猜、不能拿 number 顶上，直接抛（且不发 POST）。
    runner = _fake_run_seq(responses=[_FakeProc(returncode=1, stderr="HTTP 404 Not Found")])
    monkeypatch.setattr(subprocess, "run", runner)

    with pytest.raises(GithubError):
        add_blocked_by(number=150, blocker_number=151)
    assert len(runner.calls) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
