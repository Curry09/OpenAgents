"""Spec-0043/T1：issue 级评论出口 github.issue_comment 单元测试。

所有 gh 子进程一律 mock（monkeypatch subprocess.run），不真实调用 gh。覆盖：
- issue_comment 走 `gh issue comment <number> --body <body>`、参数正确；
- gh 失败照抛 GithubError；
- 既有 post_comment 仍走 `gh pr comment`（零回归、两条路径互不干扰）。
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

    assert issue_comment(number=111, body="对齐一下") is None

    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "issue", "comment"]
    # number 作为定位参数、body 经 --body 传入。
    assert "111" in cmd
    assert cmd[cmd.index("--body") + 1] == "对齐一下"
    # 是 issue 级出口，绝不误走 pr comment。
    assert "pr" not in cmd


def test_issue_comment_reraises_gh_error(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401 must authenticate")
    )
    with pytest.raises(GithubError):
        issue_comment(number=9, body="x")


def test_post_comment_still_targets_pr(monkeypatch):
    # 零回归：既有 PR 级评论出口不受影响，仍走 `gh pr comment`。
    runner = _fake_run()
    monkeypatch.setattr(subprocess, "run", runner)

    post_comment(pr_number=5, body="review note")

    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "comment"]
    assert "5" in cmd and cmd[cmd.index("--body") + 1] == "review note"


def test_issue_comment_is_a_distinct_symbol():
    # issue_comment 与 post_comment 是两个不同的公开函数（对称的 issue / PR 出口）。
    assert github.issue_comment is not github.post_comment


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
