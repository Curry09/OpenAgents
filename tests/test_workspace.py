"""RFC-0005 T1: Workspace（worktree + git 封装）的单元测试。

git 子进程全部 monkeypatch（记录命令、可按子命令注入返回码 / stdout），
不真实操作 git。覆盖：prepare（fetch + 幂等清理 + worktree add）、ensure（复用/重建）、
assert_delivered（head 前移硬闸：fetch + rev-parse origin/<branch> 与 HEAD 对比）、
remote_branch_exists、git 失败抛错。（Spec-0056/T4：commit_and_push 随交付下放 agent 删除。）
"""

import subprocess
from types import SimpleNamespace

import pytest

from openagents.utils import workspace as ws_module
from openagents.utils.workspace import Workspace, WorkspaceError


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


def test_remote_branch_exists_true_when_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GitRecorder(stdout="abc123\trefs/heads/x\n"))
    ws = Workspace(work_dir=tmp_path)
    assert ws.remote_branch_exists(branch="x") is True


def test_remote_branch_exists_false_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GitRecorder(stdout=""))
    ws = Workspace(work_dir=tmp_path)
    assert ws.remote_branch_exists(branch="x") is False


# --------------------------------------------------------------------------- #
# issue #53: changed_spec_group（取代 RFC-0008 changed_rfc_path）
# --------------------------------------------------------------------------- #


def test_changed_spec_group_returns_group_dir(tmp_path, monkeypatch):
    # git diff 列出本分支改动的 spec 组文件，方法返回该 NNNN-slug.md 的绝对路径。
    recorder = _GitRecorder(stdout="docs/specs/0008-pr-e2e-signpost.md\n")
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    path = ws.changed_spec_group(worktree=tmp_path, base="main")

    assert path == tmp_path / "docs/specs/0008-pr-e2e-signpost.md"
    joined = _joined(recorder)
    assert any("diff --name-only origin/main...HEAD -- docs/specs/" in c for c in joined)


def test_changed_spec_group_none_when_no_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GitRecorder(stdout=""))
    ws = Workspace(work_dir=tmp_path)
    assert ws.changed_spec_group(worktree=tmp_path, base="main") is None


def test_changed_spec_group_excludes_top_level_files(tmp_path, monkeypatch):
    # 顶层 OVERVIEW.md / README.md 改动不属于任何组，不应被误判。
    recorder = _GitRecorder(stdout="docs/specs/OVERVIEW.md\ndocs/specs/README.md\n")
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)
    assert ws.changed_spec_group(worktree=tmp_path, base="main") is None


def test_changed_spec_group_picks_group_over_overview(tmp_path, monkeypatch):
    # 同时改了 OVERVIEW 与组文件时，挑出组文件（排除 dated 设计文档）。
    recorder = _GitRecorder(
        stdout="docs/specs/OVERVIEW.md\ndocs/specs/2026-06-24-d.md\ndocs/specs/0008-x.md\n"
    )
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)
    assert (
        ws.changed_spec_group(worktree=tmp_path, base="main") == tmp_path / "docs/specs/0008-x.md"
    )


# --------------------------------------------------------------------------- #
# Spec-0056/T1: assert_delivered（head 前移硬闸）+ 决策 7 修订
# --------------------------------------------------------------------------- #


class _RevParseRecorder:
    """subprocess.run 替身：按 rev-parse 目标（origin/<branch> vs HEAD）返回不同 SHA。

    remote_fail=True 时让 `rev-parse origin/<branch>` 返回非零（模拟远端无分支）。
    """

    def __init__(self, *, remote_sha, head_sha, remote_fail=False):
        self.commands = []
        self._remote_sha = remote_sha
        self._head_sha = head_sha
        self._remote_fail = remote_fail

    def __call__(self, args, **kwargs):
        self.commands.append(list(args))
        sub = args[3] if len(args) > 3 else ""
        if sub == "rev-parse":
            target = args[4]
            if target == "HEAD":
                return SimpleNamespace(returncode=0, stdout=self._head_sha + "\n", stderr="")
            # origin/<branch>
            if self._remote_fail:
                return SimpleNamespace(returncode=128, stdout="", stderr="unknown revision")
            return SimpleNamespace(returncode=0, stdout=self._remote_sha + "\n", stderr="")
        # fetch 等其它子命令：无条件成功、空输出。
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_assert_delivered_passes_when_remote_equals_head(tmp_path, monkeypatch):
    # origin/<branch> == HEAD → 已交付，放行（不抛）。
    recorder = _RevParseRecorder(remote_sha="a" * 40, head_sha="a" * 40)
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    ws.assert_delivered(worktree=tmp_path, branch="openagents/issue-140")

    joined = _joined(recorder)
    # fetch 先行（远端无分支不报错），再 rev-parse 两侧对比。
    assert any("fetch origin openagents/issue-140" in c for c in joined)
    assert any("rev-parse origin/openagents/issue-140" in c for c in joined)
    assert any("rev-parse HEAD" in c for c in joined)
    # 硬闸只读、绝不代 agent force-push（决策 7）。
    assert not any("push" in c or "--force" in c for c in joined)


def test_assert_delivered_raises_on_mismatch_with_both_shas(tmp_path, monkeypatch):
    # origin/<branch> != HEAD → 未交付，抛 WorkspaceError，报错携双 SHA 摘要。
    recorder = _RevParseRecorder(remote_sha="b" * 40, head_sha="c" * 40)
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    with pytest.raises(WorkspaceError) as excinfo:
        ws.assert_delivered(worktree=tmp_path, branch="openagents/issue-140")
    msg = str(excinfo.value)
    assert "b" * 12 in msg  # 远端短 SHA
    assert "c" * 12 in msg  # 本地 HEAD 短 SHA


def test_assert_delivered_raises_when_remote_branch_missing(tmp_path, monkeypatch):
    # 远端无该分支（rev-parse origin/<branch> 失败）→ 视作未交付，抛。
    recorder = _RevParseRecorder(remote_sha="", head_sha="d" * 40, remote_fail=True)
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    with pytest.raises(WorkspaceError):
        ws.assert_delivered(worktree=tmp_path, branch="openagents/issue-140")


def test_decision_7_docstring_allows_force_with_lease_on_own_branch():
    # 决策 7 修订：绝不*裸* force、允许 --force-with-lease 仅限本 issue 分支。
    doc = ws_module.__doc__ or ""
    assert "绝不裸 force-push" in doc
    assert "--force-with-lease" in doc
    assert "openagents/issue-" in doc


def test_module_exposes_workspace_error():
    assert issubclass(ws_module.WorkspaceError, Exception)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
