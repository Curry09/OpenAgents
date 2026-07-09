"""Spec-0061/T3: recipes.vigil 发现→分诊→派单 控制流单测——假 backend 喂 triager 裁决。

证明架构契约：vigil 只按 triager 的结构化裁决路由（actionable→dispatch / 否→_park 挂 needs-human）、
自身零业务判断；去重三闸（本地 run 记录 / 远端分支 / needs-human 标签）确定性滤「新」。全程假
backend + 打桩 github/git，不触真实 LLM/网络/仓库；派单动作走注入的假 dispatch（不建真 worktree）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from openagents.backends.base import AgentResult
from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import CLAIM_EXPIRY_SECONDS, Vigil
from openagents.runtime.state import RuntimeState
from openagents.utils.github import Comment, Issue
from openagents.utils.identity import build_claim_note


class _TriagerBackend:
    """假 backend：按 triager 的 task 文本回 canned 末行 JSON。

    task 是 triager.PROMPT 填好占位符后的串，含 issue 正文；正文里带 "PARK" → 判不可派单
    （actionable=false），否则可派单（actionable=true）。据此在单测里逐 issue 驱动两条路由。
    """

    name = "triager-fake"

    def __init__(self) -> None:
        self.tasks: list[str] = []

    def run(self, *, work_dir, task, context):
        self.tasks.append(task)
        actionable = "PARK" not in task
        return AgentResult(
            changed=False,
            summary=json.dumps({"actionable": actionable, "reason": "分诊理由R"}),
        )


class _GithubRecorder:
    """记录 vigil 对 github 写侧（打标签 / 贴评论）的调用，供 _park 路由断言。"""

    def __init__(self) -> None:
        self.added_labels: list[tuple[int, str]] = []
        self.comments: list[tuple[int, str]] = []

    def issue_add_label(self, *, number, name):
        self.added_labels.append((number, name))

    def issue_comment(self, *, number, body):
        self.comments.append((number, body))


def _patch(monkeypatch, *, issues, remote_exists=False):
    """打桩 vigil 依赖的 github.list_issues / git.remote_branch_exists，返回 github 写侧记录器。"""
    monkeypatch.setattr(vigil_module.github, "list_issues", lambda *, labels: list(issues))
    monkeypatch.setattr(
        vigil_module.git, "remote_branch_exists", lambda *, work_dir, branch: remote_exists
    )
    recorder = _GithubRecorder()
    monkeypatch.setattr(vigil_module.github, "issue_add_label", recorder.issue_add_label)
    monkeypatch.setattr(vigil_module.github, "issue_comment", recorder.issue_comment)
    return recorder


def _vigil(tmp_path, *, backend=None, dispatch_calls=None):
    """构造一个 Vigil：真 RuntimeState（tmp 文件）+ 注入假 dispatch（记录派单、不建真 worktree）。"""
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    calls = dispatch_calls if dispatch_calls is not None else []

    def _fake_dispatch(*, issue_number, base, backend, state, work_dir):
        calls.append({"issue_number": issue_number, "base": base})
        return {"delivered": True}

    vigil = Vigil(
        backend=backend or _TriagerBackend(),
        state=state,
        work_dir=tmp_path,
        dispatch=_fake_dispatch,
    )
    return vigil, state, calls


def test_actionable_issue_is_dispatched(monkeypatch, tmp_path):
    issue = Issue(number=145, title="重构", body="正文明确无矛盾")
    _patch(monkeypatch, issues=[issue])
    vigil, _state, calls = _vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == [145]
    assert calls == [{"issue_number": 145, "base": "main"}]


def test_non_actionable_issue_is_parked(monkeypatch, tmp_path):
    issue = Issue(number=145, title="含糊", body="修法自相矛盾 PARK")
    recorder = _patch(monkeypatch, issues=[issue])
    vigil, state, calls = _vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    # 不可派单：不 dispatch，改为 _park —— 打 needs-human + 贴对齐评论 + 记 blocked run。
    assert dispatched == []
    assert calls == []
    assert recorder.added_labels == [(145, vigil_module.github.BLOCKED_LABEL)]
    assert len(recorder.comments) == 1
    assert "分诊理由R" in recorder.comments[0][1]
    run = state.get_run(issue_number=145)
    assert run["status"] == "blocked"


def test_dedup_gate_local_run_record(monkeypatch, tmp_path):
    # 闸①：本地已有 run 记录 → 判非新，triager 不被调、不派单。
    issue = Issue(number=145, title="t", body="b")
    _patch(monkeypatch, issues=[issue])
    backend = _TriagerBackend()
    vigil, state, calls = _vigil(tmp_path, backend=backend)
    state.set_run(issue_number=145, status="solving", branch="openagents/issue-145", pr_number=None)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == []
    assert calls == []
    assert backend.tasks == []  # triager 从未被派


def test_dedup_gate_remote_branch_exists(monkeypatch, tmp_path):
    # 闸②：远端已有该 issue 分支 → 判非新，不派单。
    issue = Issue(number=145, title="t", body="b")
    _patch(monkeypatch, issues=[issue], remote_exists=True)
    backend = _TriagerBackend()
    vigil, _state, calls = _vigil(tmp_path, backend=backend)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == []
    assert calls == []
    assert backend.tasks == []


def test_dedup_gate_blocked_label(monkeypatch, tmp_path):
    # 闸③：issue 已挂 needs-human → 判非新（人摘标签前不重判），不派单。
    issue = Issue(number=145, title="t", body="b", labels=(vigil_module.github.BLOCKED_LABEL,))
    _patch(monkeypatch, issues=[issue])
    backend = _TriagerBackend()
    vigil, _state, calls = _vigil(tmp_path, backend=backend)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == []
    assert calls == []
    assert backend.tasks == []


def test_run_once_invokes_discover_then_poll(monkeypatch, tmp_path):
    # Vigil.run(once=True) 跑一轮发现段后调一次注入的守候段 poll，即返回。
    issue = Issue(number=145, title="t", body="b 正常")
    _patch(monkeypatch, issues=[issue])
    vigil, _state, calls = _vigil(tmp_path)
    poll_calls = {"n": 0}

    def _poll():
        poll_calls["n"] += 1

    vigil.run(interval=1, labels=["openagents"], base="main", once=True, poll=_poll)

    assert calls == [{"issue_number": 145, "base": "main"}]
    assert poll_calls["n"] == 1


def test_run_once_none_poll_only_discovers(monkeypatch, tmp_path):
    # poll=None 时只跑发现段，不因缺守候段报错。
    issue = Issue(number=145, title="t", body="b")
    _patch(monkeypatch, issues=[issue])
    vigil, _state, calls = _vigil(tmp_path)

    vigil.run(interval=1, labels=["openagents"], base="main", once=True, poll=None)

    assert calls == [{"issue_number": 145, "base": "main"}]


# --------------------------------------------------------------------------- #
# Spec-0062/T3: 认领归属闸④——他人未过期 → 跳过；他人过期 / 无便签 / 自己残留 → 「新」
# --------------------------------------------------------------------------- #

SELF_ID = "agent-self"
_NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


def _iso(*, ago_seconds):
    """构造相对 _NOW 早 ago_seconds 秒的 ISO 8601 UTC 时戳（now 注入 → 判定确定性、不读墙钟）。"""
    return (_NOW - timedelta(seconds=ago_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _claim_comment(*, owner, ago_seconds):
    """owner 在 ago_seconds 秒前贴的一条署名认领便签评论。"""
    return Comment(
        id="IC",
        author=owner,
        body=build_claim_note(agent_id=owner),
        created_at=_iso(ago_seconds=ago_seconds),
    )


def _patch_comments(monkeypatch, comments):
    monkeypatch.setattr(
        vigil_module.github, "list_issue_comments", lambda *, number: list(comments)
    )


def _claim_vigil(tmp_path, *, agent_id=SELF_ID, claim_expiry_seconds=CLAIM_EXPIRY_SECONDS):
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    return Vigil(
        backend=_TriagerBackend(),
        state=state,
        work_dir=tmp_path,
        agent_id=agent_id,
        dispatch=lambda **kw: None,
        claim_expiry_seconds=claim_expiry_seconds,
    )


def _dispatch_labeled_issue():
    return Issue(number=9, title="t", body="b 正常", labels=(vigil_module.github.DISPATCH_LABEL,))


def test_claim_other_fresh_is_skipped(monkeypatch, tmp_path):
    # 他人未过期认领 → 判非新，不派单、triager 不被调。
    _patch(monkeypatch, issues=[_dispatch_labeled_issue()])
    _patch_comments(monkeypatch, [_claim_comment(owner="agent-other", ago_seconds=5)])
    vigil = _claim_vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main", now=_NOW)

    assert dispatched == []
    assert vigil._backend.tasks == []


def test_claim_other_expired_is_reclaimed_as_fresh(monkeypatch, tmp_path):
    # 他人过期认领（僵尸）→ 回收视同新 → 正常派单。
    _patch(monkeypatch, issues=[_dispatch_labeled_issue()])
    _patch_comments(
        monkeypatch, [_claim_comment(owner="agent-other", ago_seconds=CLAIM_EXPIRY_SECONDS + 60)]
    )
    vigil = _claim_vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main", now=_NOW)

    assert dispatched == [9]


def test_claim_own_residue_is_reclaimed_as_fresh(monkeypatch, tmp_path):
    # 最近便签是自己的残留 → 重认领、不跳过。
    _patch(monkeypatch, issues=[_dispatch_labeled_issue()])
    _patch_comments(monkeypatch, [_claim_comment(owner=SELF_ID, ago_seconds=5)])
    vigil = _claim_vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main", now=_NOW)

    assert dispatched == [9]


def test_claim_no_valid_note_is_fresh(monkeypatch, tmp_path):
    # 带认领标签但无有效认领便签（只有粗标签、无归属凭证）→ 可认领。
    _patch(monkeypatch, issues=[_dispatch_labeled_issue()])
    _patch_comments(
        monkeypatch, [Comment(id="IC", author="human", body="+1", created_at=_iso(ago_seconds=1))]
    )
    vigil = _claim_vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main", now=_NOW)

    assert dispatched == [9]


def test_claim_latest_note_wins_other_newer_over_own_older(monkeypatch, tmp_path):
    # 自己旧便签 + 他人更晚便签 → 最近是他人且未过期 → 跳过（末位 created_at 定胜负）。
    _patch(monkeypatch, issues=[_dispatch_labeled_issue()])
    _patch_comments(
        monkeypatch,
        [
            _claim_comment(owner=SELF_ID, ago_seconds=100),
            _claim_comment(owner="agent-other", ago_seconds=5),
        ],
    )
    vigil = _claim_vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main", now=_NOW)

    assert dispatched == []


def test_claim_comments_query_error_is_conservative_skip(monkeypatch, tmp_path):
    # 读评论失败 → 不上抛、保守判「他人活认领」→ 跳过（不拖垮整轮）。
    _patch(monkeypatch, issues=[_dispatch_labeled_issue()])

    def _boom(*, number):
        raise vigil_module.github.GithubError("gh issue view failed")

    monkeypatch.setattr(vigil_module.github, "list_issue_comments", _boom)
    vigil = _claim_vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main", now=_NOW)

    assert dispatched == []


def test_claim_gate_skipped_without_dispatch_label(monkeypatch, tmp_path):
    # 无 DISPATCH_LABEL → 认领闸罕见路径不触发、不读评论（常态扫描不拖慢）。
    issue = Issue(number=9, title="t", body="b 正常", labels=("openagents",))
    _patch(monkeypatch, issues=[issue])

    def _boom(*, number):
        raise AssertionError("无认领标签时不应读评论")

    monkeypatch.setattr(vigil_module.github, "list_issue_comments", _boom)
    vigil = _claim_vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main", now=_NOW)

    assert dispatched == [9]


def test_claim_expiry_threshold_is_injectable(monkeypatch, tmp_path):
    # 调大阈值后，原本超时的他人认领龄变为未超时 → 从回收翻转为跳过（阈值参与判定）。
    _patch(monkeypatch, issues=[_dispatch_labeled_issue()])
    _patch_comments(
        monkeypatch, [_claim_comment(owner="agent-other", ago_seconds=CLAIM_EXPIRY_SECONDS + 100)]
    )
    vigil = _claim_vigil(tmp_path, claim_expiry_seconds=CLAIM_EXPIRY_SECONDS + 1000)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main", now=_NOW)

    assert dispatched == []


# --------------------------------------------------------------------------- #
# Spec-0062/T3: 守候段——先回应评论（poll）再推进合并（merge），merge 收到携 issue 归属的 runs
# --------------------------------------------------------------------------- #


def test_watch_runs_poll_then_merge_with_issue_runs(monkeypatch, tmp_path):
    _patch(monkeypatch, issues=[])  # 无新 issue，专测守候段
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    state.set_run(issue_number=145, status="done", branch="openagents/issue-145", pr_number=154)
    vigil = Vigil(
        backend=_TriagerBackend(), state=state, work_dir=tmp_path, dispatch=lambda **kw: None
    )

    order: list[str] = []
    seen: dict = {}

    def _poll():
        order.append("poll")

    def _merge(*, runs, now):
        order.append("merge")
        seen["runs"] = runs
        seen["now"] = now

    vigil.run(interval=1, labels=["openagents"], base="main", once=True, poll=_poll, merge=_merge)

    # 次序固定：先回应评论，再推进合并。
    assert order == ["poll", "merge"]
    # merge 收到据本地 run 投影出的、携 issue 归属的 runs。
    assert len(seen["runs"]) == 1
    run = seen["runs"][0]
    assert run.pr_number == 154
    assert run.issue_number == 145
    assert run.branch == "openagents/issue-145"
    assert run.status == "open"  # done → open（喂 merge_pr 推进合并）
    assert isinstance(seen["now"], datetime)


def test_watch_merge_skips_runs_without_pr(monkeypatch, tmp_path):
    # 无 pr_number（求解中、尚无 PR）→ 不投影进 merge 的 runs。
    _patch(monkeypatch, issues=[])
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    state.set_run(issue_number=145, status="solving", branch="openagents/issue-145", pr_number=None)
    vigil = Vigil(
        backend=_TriagerBackend(), state=state, work_dir=tmp_path, dispatch=lambda **kw: None
    )

    seen: dict = {}

    def _merge(*, runs, now):
        seen["runs"] = runs

    vigil.run(interval=1, labels=["openagents"], base="main", once=True, poll=None, merge=_merge)

    assert seen["runs"] == []


def test_watch_blocked_run_maps_to_blocked_status(monkeypatch, tmp_path):
    # blocked run → merge Run 状态 blocked（短路），不当 open 重跑闸。
    _patch(monkeypatch, issues=[])
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    state.set_run(issue_number=9, status="blocked", branch="openagents/issue-9", pr_number=77)
    vigil = Vigil(
        backend=_TriagerBackend(), state=state, work_dir=tmp_path, dispatch=lambda **kw: None
    )

    seen: dict = {}

    def _merge(*, runs, now):
        seen["runs"] = runs

    vigil.run(interval=1, labels=["openagents"], base="main", once=True, poll=None, merge=_merge)

    assert seen["runs"][0].status == "blocked"
