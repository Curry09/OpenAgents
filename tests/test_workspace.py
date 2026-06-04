"""RFC-0005 T1: Workspace（worktree + git 封装）的单元测试。

git 子进程全部 monkeypatch（记录命令、可按子命令注入返回码 / stdout），
不真实操作 git。覆盖：prepare（fetch + 幂等清理 + worktree add）、ensure（复用/重建）、
commit_and_push（无改动跳过 commit 仍 push）、remote_branch_exists、git 失败抛错。
"""

import subprocess
from types import SimpleNamespace

import pytest

from openagents import workspace as ws_module
from openagents.workspace import Workspace, WorkspaceError


class _GitRecorder:
    """subprocess.run 替身：记录所有 git 命令，按子命令决定返回码，统一返回 stdout。"""

    def __init__(self, *, fail=(), stdout=""):
        self.commands = []
        self._fail = set(fail)  # 需要返回非零的 git 子命令（args[3]）
        self._stdout = stdout

    def __call__(self, args, **kwargs):
        self.commands.append(list(args))
        sub = args[3] if len(args) > 3 else ""
        returncode = 1 if sub in self._fail else 0
        return SimpleNamespace(returncode=returncode, stdout=self._stdout, stderr="boom")


def _joined(recorder):
    return [" ".join(c) for c in recorder.commands]


def test_prepare_fetches_cleans_and_adds_worktree(tmp_path, monkeypatch):
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    path = ws.prepare(issue_number=3, branch="openagents/issue-3", base="main")

    assert path == tmp_path / ".openagents" / "worktrees" / "issue-3"
    joined = _joined(recorder)
    assert any("fetch origin main" in c for c in joined)
    assert any("worktree remove --force" in c for c in joined)
    assert any("worktree prune" in c for c in joined)
    assert any("branch -D openagents/issue-3" in c for c in joined)
    assert any("worktree add -b openagents/issue-3" in c and "origin/main" in c for c in joined)


def test_prepare_uses_base_override(tmp_path, monkeypatch):
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    ws.prepare(issue_number=3, branch="openagents/issue-3", base="dev")

    joined = _joined(recorder)
    assert any("fetch origin dev" in c for c in joined)
    assert any("worktree add -b openagents/issue-3" in c and "origin/dev" in c for c in joined)


def test_prepare_fetch_failure_raises(tmp_path, monkeypatch):
    # fetch 走 check=True，失败应抛 WorkspaceError。
    monkeypatch.setattr(subprocess, "run", _GitRecorder(fail={"fetch"}))
    ws = Workspace(work_dir=tmp_path)
    with pytest.raises(WorkspaceError):
        ws.prepare(issue_number=3, branch="openagents/issue-3", base="main")


def test_ensure_reuses_existing_worktree(tmp_path, monkeypatch):
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)
    path = tmp_path / ".openagents" / "worktrees" / "issue-3"
    path.mkdir(parents=True)

    result = ws.ensure(issue_number=3, branch="openagents/issue-3")

    assert result == path
    # 复用：不应再 worktree add
    assert not any("worktree add" in c for c in _joined(recorder))


def test_ensure_rebuilds_when_missing(tmp_path, monkeypatch):
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    path = ws.ensure(issue_number=3, branch="openagents/issue-3")

    assert path == tmp_path / ".openagents" / "worktrees" / "issue-3"
    joined = _joined(recorder)
    assert any("fetch origin openagents/issue-3" in c for c in joined)
    assert any("worktree add" in c and "openagents/issue-3" in c for c in joined)


def test_commit_and_push_sequence(tmp_path, monkeypatch):
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    ws.commit_and_push(worktree=tmp_path, branch="openagents/issue-3", message="docs: x")

    joined = _joined(recorder)
    assert any("add -A" in c for c in joined)
    assert any("commit -m" in c for c in joined)
    assert any("push -u origin openagents/issue-3" in c for c in joined)
    # 决策 7：绝不 force-push
    assert not any("--force" in c or "-f" in c.split() for c in joined)


def test_commit_and_push_no_changes_still_pushes(tmp_path, monkeypatch):
    # commit 走 check=False：无改动（返回非零）也不抛，push 仍执行。
    recorder = _GitRecorder(fail={"commit"})
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    ws.commit_and_push(worktree=tmp_path, branch="openagents/issue-3", message="docs: x")

    assert any("push -u origin openagents/issue-3" in c for c in _joined(recorder))


def test_commit_and_push_add_failure_raises(tmp_path, monkeypatch):
    # add 走 check=True，失败应抛 WorkspaceError。
    monkeypatch.setattr(subprocess, "run", _GitRecorder(fail={"add"}))
    ws = Workspace(work_dir=tmp_path)
    with pytest.raises(WorkspaceError):
        ws.commit_and_push(worktree=tmp_path, branch="b", message="m")


def test_remote_branch_exists_true_when_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GitRecorder(stdout="abc123\trefs/heads/x\n"))
    ws = Workspace(work_dir=tmp_path)
    assert ws.remote_branch_exists(branch="x") is True


def test_remote_branch_exists_false_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GitRecorder(stdout=""))
    ws = Workspace(work_dir=tmp_path)
    assert ws.remote_branch_exists(branch="x") is False


def test_module_exposes_workspace_error():
    assert issubclass(ws_module.WorkspaceError, Exception)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
