"""Spec-0074 Evidence rehabilitation:utils.git.seed_branch（rfc:skip Open PR Pre-established empty submission+(Pushed) Single.

Hermetic: Pile a git._git log call shape, untouchable git/net (runable on a platform without fcntl).
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

    assert (
        "commit" in calls[0] and "--allow-empty" in calls[0]
    )  # Empty submission (no content manufacturing)
    assert (
        "user.name=openagents" in calls[0]
    )  # Visible identity, not dependent on host-wide guit configuration
    assert calls[1] == ["push", "-u", "origin", "openagents/issue-7"]  # Remote branch landing


def test_seed_branch_commit_failure_raises(monkeypatch):
    monkeypatch.setattr(git_mod, "_git", lambda *, args, cwd: _completed(1, "boom"))
    with pytest.raises(WorkspaceError, match="Seed commit failed"):
        git_mod.seed_branch(work_dir=Path("/wt"), branch="b", message="m")


def test_seed_branch_push_failure_raises(monkeypatch):
    results = iter([_completed(0), _completed(1, "denied")])
    monkeypatch.setattr(git_mod, "_git", lambda *, args, cwd: next(results))
    with pytest.raises(WorkspaceError, match="Seed branch push failed"):
        git_mod.seed_branch(work_dir=Path("/wt"), branch="b", message="m")
