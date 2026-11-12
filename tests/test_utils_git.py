"""Spec-0060/T1: utils.git stability monometry - telemetry workspace + read only head_sha/porcelain.

Without touching the real warehouse: subprocess.run stakes, head_sha/porcelain adamant to git sub-command, strip stdout;
Workspace/WorkspaceError is asserted to be the same object (sand export, behavioral equivalent) of workspace.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from openagents.utils import git
from openagents.utils import workspace as workspace_module


class _FakeProc:
    def __init__(self, *, stdout):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def test_workspace_reexport_is_same_object():
    # Thin re-export: utils.git.Workspace / WorkspaceError must be the same object (zero copy) as workspace.py.
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


# --- Spec-0035/T1: network guit timeout fail-open + ls-remote progress bread crumbs ---------------------


def test_git_helper_passes_net_timeout(monkeypatch):
    # _git must pass subprocess.run timeout = _GIT_NET_TIMEOUT_SECONDS (conduce to the only helper).
    captured = {}

    def _fake_run(argv, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return _FakeProc(stdout="")

    monkeypatch.setattr(git.subprocess, "run", _fake_run)
    git.head_sha(work_dir=Path("/tmp/wt"))
    assert captured["timeout"] == git._GIT_NET_TIMEOUT_SECONDS


def test_remote_branch_exists_true_on_output(monkeypatch):
    # Normal path by bytes: ls-remote has output True.
    monkeypatch.setattr(
        git.subprocess, "run", lambda argv, **kw: _FakeProc(stdout="abc123\trefs/heads/x\n")
    )
    assert git.remote_branch_exists(work_dir=Path("/tmp/wt"), branch="x") is True


def test_remote_branch_exists_false_on_empty(monkeypatch):
    # Normal path by bytes unchanged: ls-remote does not output  →  False (near end does not have that branch).
    monkeypatch.setattr(git.subprocess, "run", lambda argv, **kw: _FakeProc(stdout="\n"))
    assert git.remote_branch_exists(work_dir=Path("/tmp/wt"), branch="x") is False


def test_remote_branch_exists_fail_open_true_on_timeout(monkeypatch):
    # Fail-open: ls-remote timeout  →  conservatively returns True ( "possibly" ) This round skips, does not repeat the pie sheets.
    def _boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=30)

    monkeypatch.setattr(git.subprocess, "run", _boom)
    assert git.remote_branch_exists(work_dir=Path("/tmp/wt"), branch="x") is True


def test_remote_branch_exists_logs_breadcrumb_before_ls_remote(monkeypatch, capsys):
    # Runs the ls-remote front line of stderr bread crumbs (the output stops in this line when stuck).
    monkeypatch.setattr(git.subprocess, "run", lambda argv, **kw: _FakeProc(stdout=""))
    git.remote_branch_exists(work_dir=Path("/tmp/wt"), branch="openagents/issue-9")
    err = capsys.readouterr().err
    assert "Checking whether the remote branch exists" in err
    assert "openagents/issue-9" in err
