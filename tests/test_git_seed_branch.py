"""Spec-0074 实证修复：utils.git.seed_branch（rfc:skip 态开 PR 前置的确定性空提交+推送）单测。

hermetic：打桩 git._git 记录调用形状，不触真 git/网络（可在无 fcntl 的平台跑）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openagents.utils import git as git_mod
from openagents.utils.workspace import WorkspaceError


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


def test_seed_branch_commits_empty_then_pushes(monkeypatch):
    calls: list[list[str]] = []

    def _fake_git(*, args, cwd):
        calls.append(list(args))
        return _completed(0)

    monkeypatch.setattr(git_mod, "_git", _fake_git)
    git_mod.seed_branch(work_dir=Path("/wt"), branch="openagents/issue-7", message="m")

    assert "commit" in calls[0] and "--allow-empty" in calls[0]  # 空提交（不制造内容）
    assert "user.name=openagents" in calls[0]  # 显式身份，不依赖宿主全局 git 配置
    assert calls[1] == ["push", "-u", "origin", "openagents/issue-7"]  # 远端分支落地


def test_seed_branch_commit_failure_raises(monkeypatch):
    monkeypatch.setattr(git_mod, "_git", lambda *, args, cwd: _completed(1, "boom"))
    with pytest.raises(WorkspaceError, match="seed commit"):
        git_mod.seed_branch(work_dir=Path("/wt"), branch="b", message="m")


def test_seed_branch_push_failure_raises(monkeypatch):
    results = iter([_completed(0), _completed(1, "denied")])
    monkeypatch.setattr(git_mod, "_git", lambda *, args, cwd: next(results))
    with pytest.raises(WorkspaceError, match="推送"):
        git_mod.seed_branch(work_dir=Path("/wt"), branch="b", message="m")
