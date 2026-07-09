"""Spec-0060/T1: utils.git 稳定面单测——透传 workspace 原语 + 只读 head_sha/porcelain。

不触真实仓库：subprocess.run 打桩，断言 head_sha/porcelain 拼对 git 子命令、strip stdout；
断言 Workspace/WorkspaceError 就是 workspace.py 的同一对象（薄再导出、行为等价）。
"""

from __future__ import annotations

from pathlib import Path

from openagents import workspace as workspace_module
from openagents.utils import git


class _FakeProc:
    def __init__(self, *, stdout):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def test_workspace_reexport_is_same_object():
    # 薄再导出：utils.git.Workspace / WorkspaceError 必须就是 workspace.py 的同一对象（零复制）。
    assert git.Workspace is workspace_module.Workspace
    assert git.WorkspaceError is workspace_module.WorkspaceError


def test_head_sha_runs_rev_parse_head_and_strips(monkeypatch):
    captured = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        return _FakeProc(stdout="deadbeefcafe1234\n")

    monkeypatch.setattr(git.subprocess, "run", _fake_run)
    sha = git.head_sha(work_dir=Path("/tmp/wt"))
    assert sha == "deadbeefcafe1234"
    assert captured["argv"] == ["git", "-C", "/tmp/wt", "rev-parse", "HEAD"]


def test_porcelain_runs_status_porcelain_and_strips(monkeypatch):
    captured = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        return _FakeProc(stdout=" M openagents/cli.py\n?? new.py\n")

    monkeypatch.setattr(git.subprocess, "run", _fake_run)
    out = git.porcelain(work_dir=Path("/tmp/wt"))
    assert out == "M openagents/cli.py\n?? new.py"
    assert captured["argv"] == ["git", "-C", "/tmp/wt", "status", "--porcelain"]


def test_head_sha_empty_when_no_output(monkeypatch):
    monkeypatch.setattr(git.subprocess, "run", lambda argv, **kw: _FakeProc(stdout="\n"))
    assert git.head_sha(work_dir=Path(".")) == ""
