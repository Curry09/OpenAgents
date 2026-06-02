"""RFC-0001 T3: GitHub 集成（gh CLI 封装）的契约测试。

所有 gh 子进程一律 mock（monkeypatch subprocess.run），不真实调用 gh。
每个函数覆盖：正常解析路径 + gh 返回非零的错误路径。
"""

import json
import subprocess
from dataclasses import dataclass

import pytest

from openagents.github import (
    PR,
    CheckStatus,
    Comment,
    GithubError,
    Issue,
    check_status,
    create_pr,
    create_repo,
    get_issue,
    is_merged,
    list_comments,
    post_comment,
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


def test_create_pr_unparsable_url_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="not-a-pr-url\n"))
    with pytest.raises(GithubError):
        create_pr(branch="b", title="t", body="b")


# --------------------------------------------------------------------------- #
# list_comments
# --------------------------------------------------------------------------- #


def test_list_comments_parses(monkeypatch):
    payload = json.dumps(
        {
            "comments": [
                {"id": 1, "author": {"login": "alice"}, "body": "first"},
                {"id": 2, "author": {"login": "bob"}, "body": "second"},
            ]
        }
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    comments = list_comments(pr_number=42)

    assert [c.id for c in comments] == [1, 2]
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
        subprocess, "run", _fake_run(returncode=1, stdout="", stderr="no checks reported")
    )
    with pytest.raises(GithubError):
        check_status(pr_number=42)


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
