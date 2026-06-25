"""RFC-0001 T3: GitHub 集成（gh CLI 封装）的契约测试。

所有 gh 子进程一律 mock（monkeypatch subprocess.run），不真实调用 gh。
每个函数覆盖：正常解析路径 + gh 返回非零的错误路径。
"""

import json
import subprocess
from dataclasses import dataclass

import pytest

from openagents import github as ghmod
from openagents.github import (
    _GH_RETRY_BACKOFF_BASE,
    _GH_RETRY_MAX_ATTEMPTS,
    PR,
    CheckStatus,
    Comment,
    GithubError,
    Issue,
    Mergeability,
    _is_transient_gh_error,
    _run_gh,
    add_label,
    branch_ci_green,
    check_status,
    close_issue,
    create_issue,
    create_pr,
    create_repo,
    ensure_label,
    find_pr_by_branch,
    get_issue,
    has_label,
    is_closed,
    is_merged,
    list_comments,
    list_issues,
    list_open_prs,
    mark_ready,
    merge_pr,
    mergeability,
    post_comment,
    update_branch,
)


@dataclass
class _FakeProc:
    """伪 subprocess.CompletedProcess。"""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    """返回一个 subprocess.run 替身，并记录最后一次调用的参数。"""
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    runner.calls = calls
    return runner


def _fake_run_sequence(results):
    """subprocess.run 替身：按序返回 results 中每一项，耗尽后重复最后一项。

    每项为 _FakeProc → 返回该进程；为 BaseException 实例 → 抛出（用于注入
    subprocess.TimeoutExpired）。记录每次调用的参数到 .calls，供断言重试次数。
    """
    calls: list[list[str]] = []
    seq = list(results)

    def runner(args, **kwargs):
        calls.append(list(args))
        item = seq[len(calls) - 1] if len(calls) <= len(seq) else seq[-1]
        if isinstance(item, BaseException):
            raise item
        return item

    runner.calls = calls
    return runner


# --------------------------------------------------------------------------- #
# create_repo
# --------------------------------------------------------------------------- #


def test_create_repo_private_passes_private_flag(monkeypatch):
    runner = _fake_run(stdout="https://github.com/acme/widget\n")
    monkeypatch.setattr(subprocess, "run", runner)

    url = create_repo(name="acme/widget", private=True)

    assert url == "https://github.com/acme/widget"
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "repo", "create"]
    assert "acme/widget" in cmd
    assert "--private" in cmd
    assert "--public" not in cmd


def test_create_repo_public_passes_public_flag(monkeypatch):
    runner = _fake_run(stdout="https://github.com/acme/widget\n")
    monkeypatch.setattr(subprocess, "run", runner)

    create_repo(name="acme/widget", private=False)

    cmd = runner.calls[-1]
    assert "--public" in cmd
    assert "--private" not in cmd


def test_create_repo_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="name exists"))
    with pytest.raises(GithubError):
        create_repo(name="acme/widget", private=True)


# --------------------------------------------------------------------------- #
# get_issue
# --------------------------------------------------------------------------- #


def test_get_issue_parses_json(monkeypatch):
    payload = json.dumps({"number": 7, "title": "Fix bug", "body": "details"})
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    issue = get_issue(number=7)

    assert isinstance(issue, Issue)
    assert issue.number == 7
    assert issue.title == "Fix bug"
    assert issue.body == "details"
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "issue", "view"]
    assert "7" in cmd
    assert "--json" in cmd


def test_get_issue_null_body_becomes_empty(monkeypatch):
    payload = json.dumps({"number": 7, "title": "T", "body": None})
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    issue = get_issue(number=7)

    assert issue.body == ""


def test_get_issue_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not found"))
    with pytest.raises(GithubError):
        get_issue(number=999)


# --------------------------------------------------------------------------- #
# create_issue
# --------------------------------------------------------------------------- #


def test_create_issue_parses_number_and_reuses_inputs(monkeypatch):
    runner = _fake_run(stdout="https://github.com/acme/widget/issues/13\n")
    monkeypatch.setattr(subprocess, "run", runner)

    issue = create_issue(title="Login broken", body="steps to repro", labels=[])

    assert isinstance(issue, Issue)
    assert issue.number == 13
    assert issue.title == "Login broken"
    assert issue.body == "steps to repro"
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "issue", "create"]
    assert "--title" in cmd
    assert "Login broken" in cmd
    assert "--body" in cmd
    assert "steps to repro" in cmd
    assert "--label" not in cmd


def test_create_issue_passes_each_label(monkeypatch):
    runner = _fake_run(stdout="https://github.com/acme/widget/issues/1\n")
    monkeypatch.setattr(subprocess, "run", runner)

    create_issue(title="T", body="", labels=["bug", "p1"])

    cmd = runner.calls[-1]
    # 每个 label 都应展开成一对 --label <value>
    assert cmd.count("--label") == 2
    assert "bug" in cmd
    assert "p1" in cmd


def test_create_issue_unparsable_url_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="not-an-issue-url\n"))
    with pytest.raises(GithubError):
        create_issue(title="T", body="b", labels=[])


def test_create_issue_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="label not found"))
    with pytest.raises(GithubError):
        create_issue(title="T", body="b", labels=["nope"])


# --------------------------------------------------------------------------- #
# ensure_label（RFC-0002 决策 6：提 issue 前确保发现标签存在）
# --------------------------------------------------------------------------- #


def test_ensure_label_creates_when_missing(monkeypatch):
    runner = _fake_run(stdout="")
    monkeypatch.setattr(subprocess, "run", runner)

    ensure_label(name="openagents")

    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "label", "create"]
    assert "openagents" in cmd


def test_ensure_label_ignores_already_exists(monkeypatch):
    # gh label create 在标签已存在时以非零退出并报 "already exists" → 视为成功，不抛、不覆盖。
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(returncode=1, stderr="label with name openagents already exists; use `--force`"),
    )
    ensure_label(name="openagents")  # 不应抛异常


def test_ensure_label_reraises_other_errors(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="HTTP 500 server error"))
    with pytest.raises(GithubError):
        ensure_label(name="openagents")


# --------------------------------------------------------------------------- #
# close_issue（RFC-0017 T1：合进 test 后框架显式关 issue + 幂等容错）
# --------------------------------------------------------------------------- #


def test_close_issue_invokes_gh(monkeypatch):
    runner = _fake_run(stdout="")
    monkeypatch.setattr(subprocess, "run", runner)

    close_issue(number=41)

    cmd = runner.calls[-1]
    assert cmd == ["gh", "issue", "close", "41"]


def test_close_issue_ignores_already_closed(monkeypatch):
    # gh issue close 对已关闭的 issue 以非零退出并报 "already closed" → 幂等 no-op，不抛。
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(returncode=1, stderr="! Issue #41 (foo) is already closed"),
    )
    close_issue(number=41)  # 不应抛异常


def test_close_issue_ignores_absent(monkeypatch):
    # 不存在的 issue：gh 走 GraphQL，报 "Could not resolve to an Issue ..." → 幂等 no-op。
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            returncode=1, stderr="GraphQL: Could not resolve to an Issue with the number of 99999."
        ),
    )
    close_issue(number=99999)  # 不应抛异常


def test_close_issue_reraises_other_errors(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401 must authenticate")
    )
    with pytest.raises(GithubError):
        close_issue(number=41)


# --------------------------------------------------------------------------- #
# create_pr
# --------------------------------------------------------------------------- #


def test_create_pr_parses_number_and_url(monkeypatch):
    runner = _fake_run(stdout="https://github.com/acme/widget/pull/42\n")
    monkeypatch.setattr(subprocess, "run", runner)

    pr = create_pr(branch="feature/x", title="Add x", body="why")

    assert isinstance(pr, PR)
    assert pr.number == 42
    assert pr.url == "https://github.com/acme/widget/pull/42"
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "create"]
    assert "feature/x" in cmd
    assert "Add x" in cmd
    assert "why" in cmd


def test_create_pr_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="no commits"))
    with pytest.raises(GithubError):
        create_pr(branch="b", title="t", body="b")


def test_create_pr_default_base_is_main(monkeypatch):
    # Spec-0023/T1：test 门控退役后 base 默认 main → --base main。
    runner = _fake_run(stdout="https://github.com/acme/widget/pull/42\n")
    monkeypatch.setattr(subprocess, "run", runner)

    create_pr(branch="b", title="t", body="x")

    cmd = runner.calls[-1]
    assert "--base" in cmd
    assert cmd[cmd.index("--base") + 1] == "main"


def test_create_pr_base_override_passed_through(monkeypatch):
    runner = _fake_run(stdout="https://github.com/acme/widget/pull/42\n")
    monkeypatch.setattr(subprocess, "run", runner)

    create_pr(branch="b", title="t", body="x", base="release/v1.2.0")

    cmd = runner.calls[-1]
    assert cmd[cmd.index("--base") + 1] == "release/v1.2.0"


def test_create_pr_unparsable_url_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="not-a-pr-url\n"))
    with pytest.raises(GithubError):
        create_pr(branch="b", title="t", body="b")


# --------------------------------------------------------------------------- #
# list_comments
# --------------------------------------------------------------------------- #


def test_list_comments_parses(monkeypatch):
    # gh 返回的 comment id 是 node id 字符串，并带 createdAt。
    payload = json.dumps(
        {
            "comments": [
                {
                    "id": "IC_aaa",
                    "author": {"login": "alice"},
                    "body": "first",
                    "createdAt": "2026-06-03T01:00:00Z",
                },
                {
                    "id": "IC_bbb",
                    "author": {"login": "bob"},
                    "body": "second",
                    "createdAt": "2026-06-03T02:00:00Z",
                },
            ]
        }
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    comments = list_comments(pr_number=42)

    assert [c.id for c in comments] == ["IC_aaa", "IC_bbb"]
    assert [c.created_at for c in comments] == ["2026-06-03T01:00:00Z", "2026-06-03T02:00:00Z"]
    assert comments[0].author == "alice"
    assert comments[1].body == "second"
    assert all(isinstance(c, Comment) for c in comments)
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "view"]
    assert "42" in cmd


def test_list_comments_empty(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"comments": []})))
    assert list_comments(pr_number=42) == []


def test_list_comments_missing_author_login(monkeypatch):
    payload = json.dumps({"comments": [{"id": 3, "author": {}, "body": "x"}]})
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    comments = list_comments(pr_number=1)

    assert comments[0].author == ""


def test_list_comments_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="boom"))
    with pytest.raises(GithubError):
        list_comments(pr_number=42)


# --------------------------------------------------------------------------- #
# post_comment
# --------------------------------------------------------------------------- #


def test_post_comment_invokes_gh(monkeypatch):
    runner = _fake_run(stdout="https://github.com/acme/widget/pull/42#issuecomment-1\n")
    monkeypatch.setattr(subprocess, "run", runner)

    assert post_comment(pr_number=42, body="hello") is None

    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "comment"]
    assert "42" in cmd
    assert "--body" in cmd
    assert "hello" in cmd


def test_post_comment_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="boom"))
    with pytest.raises(GithubError):
        post_comment(pr_number=42, body="hi")


# --------------------------------------------------------------------------- #
# check_status
# --------------------------------------------------------------------------- #


def test_check_status_all_pass(monkeypatch):
    payload = json.dumps(
        [
            {"name": "build", "state": "SUCCESS", "link": "u1"},
            {"name": "test", "state": "SUCCESS", "link": "u2"},
        ]
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    status = check_status(pr_number=42)

    assert isinstance(status, CheckStatus)
    assert status.state == "pass"
    assert status.failed_logs == []
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "checks"]
    assert "42" in cmd


def test_check_status_failure_collects_logs(monkeypatch):
    payload = json.dumps(
        [
            {"name": "build", "state": "SUCCESS", "link": "u1"},
            {"name": "lint", "state": "FAILURE", "link": "http://ci/lint"},
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    status = check_status(pr_number=42)

    assert status.state == "fail"
    assert len(status.failed_logs) == 1
    assert "lint" in status.failed_logs[0]
    assert "http://ci/lint" in status.failed_logs[0]


def test_check_status_pending(monkeypatch):
    payload = json.dumps(
        [
            {"name": "build", "state": "SUCCESS", "link": "u1"},
            {"name": "deploy", "state": "PENDING", "link": "u2"},
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    status = check_status(pr_number=42)

    assert status.state == "pending"
    assert status.failed_logs == []


def test_check_status_no_checks_is_pass(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps([])))

    status = check_status(pr_number=42)

    assert status.state == "pass"
    assert status.failed_logs == []


def test_check_status_failure_takes_priority_over_pending(monkeypatch):
    payload = json.dumps(
        [
            {"name": "lint", "state": "FAILURE", "link": "u1"},
            {"name": "deploy", "state": "PENDING", "link": "u2"},
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    status = check_status(pr_number=42)

    assert status.state == "fail"


def test_check_status_gh_exit_8_means_pending(monkeypatch):
    # gh pr checks 在仍有 check 进行中时以退出码 8 返回，stdout 仍含 JSON。
    payload = json.dumps([{"name": "build", "state": "PENDING", "link": "u1"}])
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=8, stdout=payload))

    status = check_status(pr_number=42)

    assert status.state == "pending"


def test_check_status_real_error_raises(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stdout="", stderr="pull request not found")
    )
    with pytest.raises(GithubError):
        check_status(pr_number=42)


def test_check_status_no_checks_reported_is_pass(monkeypatch):
    # 仓库无 CI 时 gh pr checks 非零退出并报 "no checks reported"，应视为 pass。
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(returncode=1, stderr="no checks reported on the 'feat/x' branch"),
    )
    status = check_status(pr_number=42)
    assert status.state == "pass"
    assert status.failed_logs == []


def test_is_merged_true_when_state_merged(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "MERGED"})))
    assert is_merged(pr_number=7) is True


def test_is_merged_false_when_open(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "OPEN"})))
    assert is_merged(pr_number=7) is False


def test_is_merged_gh_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not found"))
    with pytest.raises(GithubError):
        is_merged(pr_number=7)


# --------------------------------------------------------------------------- #
# mergeability（Spec-0022/T1：如实回传 mergeable / mergeStateStatus）
# --------------------------------------------------------------------------- #


def test_mergeability_conflicting_dirty_passthrough(monkeypatch):
    runner = _fake_run(stdout=json.dumps({"mergeable": "CONFLICTING", "mergeStateStatus": "DIRTY"}))
    monkeypatch.setattr(subprocess, "run", runner)
    result = mergeability(pr_number=61)
    assert result == Mergeability(mergeable="CONFLICTING", merge_state_status="DIRTY")
    # 断言传给 gh 的参数恰为 pr view <n> --json mergeable,mergeStateStatus。
    assert runner.calls[-1] == [
        "gh",
        "pr",
        "view",
        "61",
        "--json",
        "mergeable,mergeStateStatus",
    ]


def test_mergeability_clean_passthrough(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(stdout=json.dumps({"mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN"})),
    )
    assert mergeability(pr_number=7) == Mergeability(
        mergeable="MERGEABLE", merge_state_status="CLEAN"
    )


def test_mergeability_unknown_is_valid_not_error(monkeypatch):
    # GitHub 异步尚未算完（刚 push 常见）：UNKNOWN 是合法返回值，照实回传、不抛错。
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(stdout=json.dumps({"mergeable": "UNKNOWN", "mergeStateStatus": "UNKNOWN"})),
    )
    assert mergeability(pr_number=7) == Mergeability(
        mergeable="UNKNOWN", merge_state_status="UNKNOWN"
    )


def test_mergeability_non_dict_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps([1, 2, 3])))
    with pytest.raises(GithubError):
        mergeability(pr_number=7)


def test_mergeability_missing_field_raises(monkeypatch):
    # 缺字段属结构异常（区别于 UNKNOWN）：比照 is_merged 抛 GithubError。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"mergeable": "MERGEABLE"})))
    with pytest.raises(GithubError):
        mergeability(pr_number=7)


# --------------------------------------------------------------------------- #
# is_closed（RFC-0006：关闭但未合并的 PR 是终止信号）
# --------------------------------------------------------------------------- #


def test_is_closed_true_when_state_closed(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "CLOSED"})))
    assert is_closed(pr_number=7) is True


def test_is_closed_false_when_open(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "OPEN"})))
    assert is_closed(pr_number=7) is False


def test_is_closed_false_when_merged(monkeypatch):
    # 已合并的 PR state 是 MERGED，不算 closed（避免与 merged 终态语义混淆）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "MERGED"})))
    assert is_closed(pr_number=7) is False


def test_is_closed_gh_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not found"))
    with pytest.raises(GithubError):
        is_closed(pr_number=7)


# --------------------------------------------------------------------------- #
# find_pr_by_branch（RFC-0003 决策 8）
# --------------------------------------------------------------------------- #


def test_find_pr_by_branch_returns_pr_when_open_exists(monkeypatch):
    runner = _fake_run(
        stdout=json.dumps([{"number": 5, "url": "https://github.com/acme/widget/pull/5"}])
    )
    monkeypatch.setattr(subprocess, "run", runner)

    pr = find_pr_by_branch(branch="openagents/issue-3")

    assert pr == PR(number=5, url="https://github.com/acme/widget/pull/5")
    cmd = runner.calls[-1]
    assert cmd[:4] == ["gh", "pr", "list", "--head"]
    assert "openagents/issue-3" in cmd
    assert "--state" in cmd and "open" in cmd


def test_find_pr_by_branch_returns_none_when_no_pr(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))
    assert find_pr_by_branch(branch="openagents/issue-9") is None


def test_find_pr_by_branch_gh_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="boom"))
    with pytest.raises(GithubError):
        find_pr_by_branch(branch="openagents/issue-1")


# --------------------------------------------------------------------------- #
# create_pr --draft（RFC-0005 决策 2）
# --------------------------------------------------------------------------- #


def test_create_pr_draft_passes_draft_flag(monkeypatch):
    runner = _fake_run(stdout="https://github.com/acme/widget/pull/42\n")
    monkeypatch.setattr(subprocess, "run", runner)

    create_pr(branch="b", title="t", body="x", draft=True)

    assert "--draft" in runner.calls[-1]


def test_create_pr_default_is_not_draft(monkeypatch):
    runner = _fake_run(stdout="https://github.com/acme/widget/pull/42\n")
    monkeypatch.setattr(subprocess, "run", runner)

    create_pr(branch="b", title="t", body="x")

    assert "--draft" not in runner.calls[-1]


# --------------------------------------------------------------------------- #
# mark_ready（RFC-0005 决策 2）
# --------------------------------------------------------------------------- #


def test_mark_ready_invokes_gh_pr_ready(monkeypatch):
    runner = _fake_run(stdout="")
    monkeypatch.setattr(subprocess, "run", runner)

    assert mark_ready(pr_number=42) is None
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "ready"]
    assert "42" in cmd


def test_mark_ready_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="boom"))
    with pytest.raises(GithubError):
        mark_ready(pr_number=42)


# --------------------------------------------------------------------------- #
# has_label（RFC-0005 决策 4）
# --------------------------------------------------------------------------- #


def test_has_label_true_when_present(monkeypatch):
    payload = json.dumps({"labels": [{"name": "rfc-approved"}, {"name": "bug"}]})
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert has_label(pr_number=7, name="rfc-approved") is True


def test_has_label_false_when_absent(monkeypatch):
    payload = json.dumps({"labels": [{"name": "bug"}]})
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert has_label(pr_number=7, name="rfc-approved") is False


def test_has_label_false_when_no_labels(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"labels": []})))

    assert has_label(pr_number=7, name="rfc-approved") is False


def test_has_label_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not found"))
    with pytest.raises(GithubError):
        has_label(pr_number=7, name="rfc-approved")


# --------------------------------------------------------------------------- #
# RFC-0011 T6：current_login 已随签名机制取代而下线，全仓不应再有引用。


def test_current_login_removed_from_github_module():
    from openagents import github as ghmod

    assert not hasattr(ghmod, "current_login")


# --------------------------------------------------------------------------- #
# list_issues（RFC-0004 T1：标签门控的 issue 发现）
# --------------------------------------------------------------------------- #


def test_list_issues_parses_multiple(monkeypatch):
    payload = json.dumps(
        [
            {"number": 9, "title": "守夜人模式", "body": "details"},
            {"number": 7, "title": "rebase", "body": ""},
        ]
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    issues = list_issues(labels=[])

    assert [i.number for i in issues] == [9, 7]
    assert all(isinstance(i, Issue) for i in issues)
    assert issues[0].title == "守夜人模式"
    assert issues[1].body == ""
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "issue", "list"]
    assert "--state" in cmd and "open" in cmd
    assert "--json" in cmd
    # 无 label 时不应带 --label
    assert "--label" not in cmd


def test_list_issues_passes_each_label(monkeypatch):
    runner = _fake_run(stdout="[]")
    monkeypatch.setattr(subprocess, "run", runner)

    list_issues(labels=["openagents", "vigil"])

    cmd = runner.calls[-1]
    # 每个 label 展开成一对 --label <value>；gh 以并集语义处理。
    assert cmd.count("--label") == 2
    assert "openagents" in cmd
    assert "vigil" in cmd


def test_list_issues_custom_state(monkeypatch):
    runner = _fake_run(stdout="[]")
    monkeypatch.setattr(subprocess, "run", runner)

    list_issues(labels=[], state="closed")

    cmd = runner.calls[-1]
    assert "--state" in cmd
    assert "closed" in cmd


def test_list_issues_empty_result(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))
    assert list_issues(labels=["openagents"]) == []


def test_list_issues_null_body_becomes_empty(monkeypatch):
    payload = json.dumps([{"number": 5, "title": "T", "body": None}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    issues = list_issues(labels=[])

    assert issues[0].body == ""


def test_list_issues_gh_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="boom"))
    with pytest.raises(GithubError):
        list_issues(labels=[])


# --------------------------------------------------------------------------- #
# RFC-0010 T1：_run_gh 瞬时错误重试 + 指数退避
# --------------------------------------------------------------------------- #


def test_is_transient_gh_error_hits_server_markers():
    # 各服务端瞬时故障标记串（大小写无关）均应判为瞬时。
    for stderr in (
        "HTTP 502 Bad Gateway",
        "HTTP 503",
        "HTTP 504: 504 Gateway Timeout (https://api.github.com/graphql)",
        "Gateway Timeout",
        "Bad Gateway",
        "Service Unavailable",
    ):
        assert _is_transient_gh_error(stderr=stderr) is True


def test_is_transient_gh_error_misses_business_errors():
    # 业务错误绝不算瞬时——否则会把确定性失败反复重试（决策 2）。
    for stderr in ("pull request not found", "no checks reported", "", "label already exists"):
        assert _is_transient_gh_error(stderr=stderr) is False


def test_run_gh_retries_transient_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(ghmod.time, "sleep", lambda s: sleeps.append(s))
    runner = _fake_run_sequence(
        [
            _FakeProc(returncode=1, stderr="HTTP 504: 504 Gateway Timeout"),
            _FakeProc(returncode=0, stdout="ok"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    result = _run_gh(["pr", "checks", "1"], allow_returncodes=set())

    assert result.stdout == "ok"
    assert len(runner.calls) == 2  # 首败 + 次成
    assert len(sleeps) == 1  # 仅一次退避


def test_run_gh_exhausts_retries_then_raises(monkeypatch):
    monkeypatch.setattr(ghmod.time, "sleep", lambda s: None)
    runner = _fake_run_sequence([_FakeProc(returncode=1, stderr="HTTP 503 Service Unavailable")])
    monkeypatch.setattr(subprocess, "run", runner)

    with pytest.raises(GithubError):
        _run_gh(["pr", "checks", "1"], allow_returncodes=set())

    assert len(runner.calls) == _GH_RETRY_MAX_ATTEMPTS  # 持续瞬时失败 → 尝试到上限


def test_run_gh_backoff_is_exponential(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(ghmod.time, "sleep", lambda s: sleeps.append(s))
    runner = _fake_run_sequence([_FakeProc(returncode=1, stderr="HTTP 504")])
    monkeypatch.setattr(subprocess, "run", runner)

    with pytest.raises(GithubError):
        _run_gh(["pr", "checks", "1"], allow_returncodes=set())

    # 3 次尝试 → 2 次退避：base·2^0、base·2^1。
    assert sleeps == [_GH_RETRY_BACKOFF_BASE, _GH_RETRY_BACKOFF_BASE * 2]


def test_run_gh_timeout_is_retried_then_normalized(monkeypatch):
    # subprocess.TimeoutExpired 视为瞬时、重试；耗尽后归一化为 GithubError（非 TimeoutExpired）。
    monkeypatch.setattr(ghmod.time, "sleep", lambda s: None)
    runner = _fake_run_sequence([subprocess.TimeoutExpired(cmd="gh", timeout=30)])
    monkeypatch.setattr(subprocess, "run", runner)

    with pytest.raises(GithubError):
        _run_gh(["pr", "checks", "1"], allow_returncodes=set())

    assert len(runner.calls) == _GH_RETRY_MAX_ATTEMPTS


def test_run_gh_timeout_then_success(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(ghmod.time, "sleep", lambda s: sleeps.append(s))
    runner = _fake_run_sequence(
        [
            subprocess.TimeoutExpired(cmd="gh", timeout=30),
            _FakeProc(returncode=0, stdout="ok"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    result = _run_gh(["pr", "checks", "1"], allow_returncodes=set())

    assert result.stdout == "ok"
    assert len(sleeps) == 1


def test_run_gh_non_transient_error_not_retried(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(ghmod.time, "sleep", lambda s: sleeps.append(s))
    runner = _fake_run_sequence([_FakeProc(returncode=1, stderr="pull request not found")])
    monkeypatch.setattr(subprocess, "run", runner)

    with pytest.raises(GithubError):
        _run_gh(["pr", "view", "1"], allow_returncodes=set())

    assert len(runner.calls) == 1  # 业务错误立即抛、不重试
    assert sleeps == []


def test_run_gh_allow_returncode_not_retried(monkeypatch):
    # allow_returncodes 放行的退出码（如 pending=8）不触发重试，行为与现状一致。
    sleeps: list[float] = []
    monkeypatch.setattr(ghmod.time, "sleep", lambda s: sleeps.append(s))
    runner = _fake_run_sequence([_FakeProc(returncode=8, stdout="[]")])
    monkeypatch.setattr(subprocess, "run", runner)

    result = _run_gh(["pr", "checks", "1"], allow_returncodes={8})

    assert result.returncode == 8
    assert len(runner.calls) == 1
    assert sleeps == []


# --------------------------------------------------------------------------- #
# list_open_prs（RFC-0009 T1：枚举所有 open PR 供合并后同步扇出）
# --------------------------------------------------------------------------- #


def test_list_open_prs_parses_multiple(monkeypatch):
    payload = json.dumps(
        [
            {"number": 5, "url": "https://github.com/acme/widget/pull/5"},
            {"number": 8, "url": "https://github.com/acme/widget/pull/8"},
        ]
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    prs = list_open_prs()

    assert prs == [
        PR(number=5, url="https://github.com/acme/widget/pull/5"),
        PR(number=8, url="https://github.com/acme/widget/pull/8"),
    ]
    cmd = runner.calls[-1]
    assert cmd[:4] == ["gh", "pr", "list", "--state"]
    assert "open" in cmd
    assert "--json" in cmd


def test_list_open_prs_empty(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))
    assert list_open_prs() == []


def test_list_open_prs_skips_rows_without_number(monkeypatch):
    payload = json.dumps(
        [{"url": "https://github.com/acme/widget/pull/1"}, {"number": 2, "url": ""}]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    prs = list_open_prs()

    assert prs == [PR(number=2, url="")]


def test_list_open_prs_gh_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="boom"))
    with pytest.raises(GithubError):
        list_open_prs()


# --------------------------------------------------------------------------- #
# update_branch（RFC-0009 T1 决策 2/5：三态——更新 / 已最新 / 冲突）
# --------------------------------------------------------------------------- #


def test_update_branch_updated_returns_true_default_merge(monkeypatch):
    runner = _fake_run(stdout="")
    monkeypatch.setattr(subprocess, "run", runner)

    assert update_branch(pr_number=42) is True
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "update-branch"]
    assert "42" in cmd
    # 默认走 merge，不应带 --rebase。
    assert "--rebase" not in cmd


def test_update_branch_rebase_passes_flag(monkeypatch):
    runner = _fake_run(stdout="")
    monkeypatch.setattr(subprocess, "run", runner)

    assert update_branch(pr_number=42, rebase=True) is True
    assert "--rebase" in runner.calls[-1]


def test_update_branch_already_up_to_date_returns_false(monkeypatch):
    # gh 在分支已与 base 同步时以非零退出并报 "already up to date" → 吞为 False，不抛。
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(returncode=1, stderr="The branch is already up to date with the base branch"),
    )
    assert update_branch(pr_number=42) is False


def test_update_branch_conflict_raises(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(returncode=1, stderr="merge conflict between base and head"),
    )
    with pytest.raises(GithubError):
        update_branch(pr_number=42)


# --------------------------------------------------------------------------- #
# merge_pr（RFC-0012 决策 1：代码闸 PASS 后自动合入 test）
# --------------------------------------------------------------------------- #


def test_merge_pr_default_method_merge(monkeypatch):
    runner = _fake_run(stdout="")
    monkeypatch.setattr(subprocess, "run", runner)

    assert merge_pr(pr_number=42) is None
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "merge"]
    assert "42" in cmd
    assert "--merge" in cmd


def test_merge_pr_custom_method(monkeypatch):
    runner = _fake_run(stdout="")
    monkeypatch.setattr(subprocess, "run", runner)

    merge_pr(pr_number=42, method="squash")

    assert "--squash" in runner.calls[-1]


def test_merge_pr_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not mergeable"))
    with pytest.raises(GithubError):
        merge_pr(pr_number=42)


# --------------------------------------------------------------------------- #
# add_label（RFC-0012 决策 1/3/5：自动打 rfc-approved / needs-human）
# --------------------------------------------------------------------------- #


def test_add_label_invokes_gh_pr_edit(monkeypatch):
    runner = _fake_run(stdout="")
    monkeypatch.setattr(subprocess, "run", runner)

    assert add_label(pr_number=7, name="rfc-approved") is None
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "edit"]
    assert "7" in cmd
    assert "--add-label" in cmd
    assert "rfc-approved" in cmd


def test_add_label_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="boom"))
    with pytest.raises(GithubError):
        add_label(pr_number=7, name="needs-human")


# --------------------------------------------------------------------------- #
# branch_ci_green（RFC-0012 决策 7；Spec-0023/T1：release 预检 main 分支 CI 全绿）
# --------------------------------------------------------------------------- #


def test_branch_ci_green_all_success_true(monkeypatch):
    payload = json.dumps(
        [
            {"name": "build", "status": "completed", "conclusion": "success"},
            {"name": "test", "status": "completed", "conclusion": "skipped"},
        ]
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    assert branch_ci_green(branch="main") is True
    cmd = runner.calls[-1]
    assert cmd[:2] == ["gh", "api"]


def test_branch_ci_green_failure_false(monkeypatch):
    payload = json.dumps(
        [
            {"name": "build", "status": "completed", "conclusion": "success"},
            {"name": "lint", "status": "completed", "conclusion": "failure"},
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert branch_ci_green(branch="main") is False


def test_branch_ci_green_pending_false(monkeypatch):
    # 未完成的 check（status != completed）算非绿——pending 不放行。
    payload = json.dumps([{"name": "deploy", "status": "in_progress", "conclusion": None}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert branch_ci_green(branch="main") is False


def test_branch_ci_green_no_checks_is_green(monkeypatch):
    # 无任何 check → 视为绿（与 check_status「无 check 视为 pass」一致）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))

    assert branch_ci_green(branch="main") is True


def test_branch_ci_green_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not found"))
    with pytest.raises(GithubError):
        branch_ci_green(branch="main")
