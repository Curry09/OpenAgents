"""Spec-0043/T1:issue level reviews the export github.issue_comment unit test.

All gh subprocesses are always mock (monkeywatch subprocess.run), not actually called gh. Overwrite:
- issue_comment walk `gh issue comment <number> --body <body>`, correct parameters;
- gh failed to take Github Error;
- post_comment is still on `gh pr comment` (no behavior change, two paths without interference).
"""

import subprocess
from dataclasses import dataclass

import pytest

from openagents.utils import github
from openagents.utils.github import GithubError, issue_comment, post_comment


@dataclass
class _FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    runner.calls = calls
    return runner


def test_issue_comment_invokes_gh_issue_comment(monkeypatch):
    runner = _fake_run()
    monkeypatch.setattr(subprocess, "run", runner)

    assert issue_comment(number=111, body="Get in line.") is None

    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "issue", "comment"]
    # Number as a position parameter, body is passed through --body.
    assert "111" in cmd
    assert cmd[cmd.index("--body") + 1] == "Get in line."
    # Is a grade exit, never miss pr company.
    assert "pr" not in cmd


def test_issue_comment_reraises_gh_error(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401 must authenticate")
    )
    with pytest.raises(GithubError):
        issue_comment(number=9, body="x")


def test_post_comment_still_targets_pr(monkeypatch):
    # Zero regression: The PR-level comment exit is not affected, but `gh pr comment` is still on the way.
    runner = _fake_run()
    monkeypatch.setattr(subprocess, "run", runner)

    post_comment(pr_number=5, body="review note")

    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "comment"]
    assert "5" in cmd and cmd[cmd.index("--body") + 1] == "review note"


def test_issue_comment_is_a_distinct_symbol():
    # issue_comment and post_comment are two distinct public functions (symmetrically asset/ PR exit).
    assert github.issue_comment is not github.post_comment


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
