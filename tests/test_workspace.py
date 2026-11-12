"""Unit testing for RFC-0005 T1: Workspace (worktree + guit wrap).

gint all monkeywatches (recording command, injecting back code by sub-order / stdout),
No real operation gig. Overwrite: prepare (fetch + Zipe etc. cleanup+ worktree add), ensure (reuse/rebuild),
assert_delivered (head-to-head move hard gate: fitch + rev-parse origin/<branch> compared to HEAD)
remote_branch_exists, Git failed to drop the error. (Spec-0056/T4: commit_and_push was removed with the delivery permission.)
Spec-0056 Supplement: 2026-09-09-delivery-review-snapshot-tests-design.md record version returns.
"""

import subprocess
from types import SimpleNamespace

import pytest

from openagents.utils import workspace as ws_module
from openagents.utils.workspace import Workspace, WorkspaceError


class _GitRecorder:
    """subprocess.run double: Record all git commands, return code by sub-order, and return stdout."""

    def __init__(self, *, fail=(), stdout=""):
        self.commands = []
        self._fail = set(fail)  # Revert non-zero git sub-command (args [3])
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


def test_prepare_resumes_existing_remote_issue_branch(tmp_path, monkeypatch):
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)
    monkeypatch.setattr(ws, "remote_branch_exists", lambda *, branch: True)

    ws.prepare(issue_number=3, branch="openagents/issue-3", base="main")

    joined = _joined(recorder)
    assert any("fetch origin openagents/issue-3" in command for command in joined)
    assert any(
        "worktree add -b openagents/issue-3" in command and "origin/openagents/issue-3" in command
        for command in joined
    )


def test_prepare_fetch_failure_raises(tmp_path, monkeypatch):
    # Fetch go check =True, failure should throw Workspace Error.
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
    # Reuse: Worktree add
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


def test_prepare_conflict_uses_detached_branch_specific_worktree(tmp_path, monkeypatch):
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    path = ws.prepare_conflict(branch="feature/pr-12", base="main")

    assert path.parent == tmp_path / ".openagents" / "conflict-worktrees"
    joined = _joined(recorder)
    assert any("fetch origin main feature/pr-12" in command for command in joined)
    assert any(
        "worktree add --detach" in command and "origin/feature/pr-12" in command
        for command in joined
    )


def test_prepare_conflict_preserves_an_interrupted_operation(tmp_path, monkeypatch):
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)
    path = ws.prepare_conflict(branch="feature/pr-12", base="main")
    path.mkdir(parents=True)
    recorder.commands.clear()
    monkeypatch.setattr(ws, "_operation_in_progress", lambda *, worktree: True)

    resumed = ws.prepare_conflict(branch="feature/pr-12", base="main")

    assert resumed == path
    joined = _joined(recorder)
    assert any("fetch origin main feature/pr-12" in command for command in joined)
    assert not any("worktree remove" in command for command in joined)
    assert not any("worktree add" in command for command in joined)


def test_remote_branch_exists_true_when_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GitRecorder(stdout="abc123\trefs/heads/x\n"))
    ws = Workspace(work_dir=tmp_path)
    assert ws.remote_branch_exists(branch="x") is True


def test_remote_branch_exists_false_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GitRecorder(stdout=""))
    ws = Workspace(work_dir=tmp_path)
    assert ws.remote_branch_exists(branch="x") is False


# --------------------------------------------------------------------------- #
# Spec-0035/T2: network guit timeout fail-open (fetch → WorkspaceError; go reprobate needle @True)
# --------------------------------------------------------------------------- #


def _timeout_run(argv, **kwargs):
    """subprocess.run double: always throw TimeoutExpired (simulation semi-open socket hanging)."""
    raise subprocess.TimeoutExpired(cmd=argv, timeout=30)


def test_git_helper_passes_net_timeout(tmp_path, monkeypatch):
    # _git must pass subprocess.run timeout = _GIT_NET_TIMEOUT_SECONDS (conduce to the only helper).
    captured = {}

    def _fake_run(argv, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    Workspace(work_dir=tmp_path).remote_branch_exists(branch="x")
    assert captured["timeout"] == ws_module._GIT_NET_TIMEOUT_SECONDS


def test_prepare_fetch_timeout_raises_workspace_error(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _timeout_run)
    with pytest.raises(WorkspaceError):
        Workspace(work_dir=tmp_path).prepare(
            issue_number=3, branch="openagents/issue-3", base="main"
        )


def test_ensure_fetch_timeout_raises_workspace_error(tmp_path, monkeypatch):
    # The test is checked = False, but _git universal overtime: WorkspaceError (not normal non-zero exit).
    monkeypatch.setattr(subprocess, "run", _timeout_run)
    with pytest.raises(WorkspaceError):
        Workspace(work_dir=tmp_path).ensure(issue_number=3, branch="openagents/issue-3")


def test_assert_delivered_fetch_timeout_raises_workspace_error(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _timeout_run)
    with pytest.raises(WorkspaceError):
        Workspace(work_dir=tmp_path).assert_delivered(
            worktree=tmp_path, branch="openagents/issue-3"
        )


def test_remote_branch_exists_fail_open_true_on_timeout(tmp_path, monkeypatch):
    # To reprobate the needle timeout and to return the True to the conservative ( "possibly" skip the wheel, not repeat the pie list), without the error of swallowing the real failure.
    monkeypatch.setattr(subprocess, "run", _timeout_run)
    assert Workspace(work_dir=tmp_path).remote_branch_exists(branch="x") is True


def test_remote_branch_exists_false_on_nonzero_not_timeout(tmp_path, monkeypatch):
    # Check = normal non-zero exit under False still goes bol (stdout) =''''  →  False (both path unchanged and not overtime as True).
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    assert Workspace(work_dir=tmp_path).remote_branch_exists(branch="x") is False


# --------------------------------------------------------------------------- #
# changed_spec_group (replaces RFC-0008 changed_rfc_path)
# --------------------------------------------------------------------------- #


def test_changed_spec_group_returns_group_dir(tmp_path, monkeypatch):
    # git diff lists the spec group files that are changed by this branch, and the method is to return the NNNN-slug.md absolute path.
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
    # OVERVIEW.md/README.md changes do not belong to any group and should not be misjudged.
    recorder = _GitRecorder(stdout="docs/specs/OVERVIEW.md\ndocs/specs/README.md\n")
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)
    assert ws.changed_spec_group(worktree=tmp_path, base="main") is None


def test_changed_spec_group_picks_group_over_overview(tmp_path, monkeypatch):
    # Select the group file (excluding the deded design document) when the Overview and group files are changed.
    recorder = _GitRecorder(
        stdout="docs/specs/OVERVIEW.md\ndocs/specs/2026-06-24-d.md\ndocs/specs/0008-x.md\n"
    )
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)
    assert (
        ws.changed_spec_group(worktree=tmp_path, base="main") == tmp_path / "docs/specs/0008-x.md"
    )


def test_changed_spec_groups_returns_all_changed_groups(tmp_path, monkeypatch):
    recorder = _GitRecorder(
        stdout="docs/specs/0004-foreign.md\ndocs/specs/0006-candidate.md\ndocs/specs/OVERVIEW.md\n"
    )
    monkeypatch.setattr(subprocess, "run", recorder)

    assert Workspace(work_dir=tmp_path).changed_spec_groups(worktree=tmp_path, base="main") == [
        tmp_path / "docs/specs/0004-foreign.md",
        tmp_path / "docs/specs/0006-candidate.md",
    ]


# --------------------------------------------------------------------------- #
# Spec-0056/T1: assert_delivered (head forward to hardlock)+ Decision 7 Revision
# --------------------------------------------------------------------------- #


class _RevParseRecorder:
    """subprocess.run double: press rev-parse target (origin/ <branch> vs HEAD) to return different SHA.

    remote_fail =True returns `rev-parse origin/<branch>` to non-zero (simulation of a remote non-division).
    """

    def __init__(self, *, remote_sha, head_sha, remote_fail=False, status=""):
        self.commands = []
        self._remote_sha = remote_sha
        self._head_sha = head_sha
        self._remote_fail = remote_fail
        self.status = status  # Spec-0056 Supplement: HEAD may have the same source code as it has not been delivered.

    def __call__(self, args, **kwargs):
        self.commands.append(list(args))
        sub = args[3] if len(args) > 3 else ""
        if sub == "status":
            return SimpleNamespace(returncode=0, stdout=self.status, stderr="")
        if sub == "rev-parse":
            target = args[4]
            if target == "HEAD":
                return SimpleNamespace(returncode=0, stdout=self._head_sha + "\n", stderr="")
            # origin/<branch>
            if self._remote_fail:
                return SimpleNamespace(returncode=128, stdout="", stderr="unknown revision")
            return SimpleNamespace(returncode=0, stdout=self._remote_sha + "\n", stderr="")
        # Fetch et al. command: Unconditional success, empty output.
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_assert_delivered_passes_when_remote_equals_head(tmp_path, monkeypatch):
    # Origin/<branch> ==HEAD  →  delivered, released (none dropped).
    recorder = _RevParseRecorder(remote_sha="a" * 40, head_sha="a" * 40)
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    ws.assert_delivered(worktree=tmp_path, branch="openagents/issue-140")

    joined = _joined(recorder)
    # Fetch first (unspecified and unspecified) and rev-parse.
    assert any("fetch origin openagents/issue-140" in c for c in joined)
    assert any("rev-parse origin/openagents/issue-140" in c for c in joined)
    assert any("rev-parse HEAD" in c for c in joined)
    # The hard-line is read-only and never-present (decision 7).
    assert not any("push" in c or "--force" in c for c in joined)


def test_assert_delivered_raises_on_mismatch_with_both_shas(tmp_path, monkeypatch):
    # = HEAD = undelivered, threw WorkspaceError, misdirected with double SHA summary.
    recorder = _RevParseRecorder(remote_sha="b" * 40, head_sha="c" * 40)
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    with pytest.raises(WorkspaceError) as excinfo:
        ws.assert_delivered(worktree=tmp_path, branch="openagents/issue-140")
    msg = str(excinfo.value)
    assert "b" * 12 in msg  # Shorter Far SHA
    assert "c" * 12 in msg  # Local HEAD Short SHA


def test_assert_delivered_raises_when_remote_branch_missing(tmp_path, monkeypatch):
    # No branch (rev-parse origin/<branch> failed) is considered undelivered, thrown.
    recorder = _RevParseRecorder(remote_sha="", head_sha="d" * 40, remote_fail=True)
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)

    with pytest.raises(WorkspaceError):
        ws.assert_delivered(worktree=tmp_path, branch="openagents/issue-140")


@pytest.mark.parametrize(
    "status",
    [" M entry.py\n", "M  entry.py\n", "?? tests/test_new.py\n", " D entry.py\n", "UU entry.py\n"],
    ids=["unstaged", "staged", "new-source", "deleted-source", "unmerged"],
)
def test_delivery_snapshot_rejects_source_outside_the_pushed_commit(tmp_path, monkeypatch, status):
    """Spec-0056 supplements: The rejection is an omission, not a clean-up, submission or push-over for the developer."""
    recorder = _RevParseRecorder(remote_sha="a" * 40, head_sha="a" * 40, status=status)
    monkeypatch.setattr(subprocess, "run", recorder)
    ws = Workspace(work_dir=tmp_path)
    rejected = False
    try:
        ws.assert_delivered(worktree=tmp_path, branch="openagents/issue-140")
    except WorkspaceError:
        rejected = True

    assert all(
        command[3] in {"fetch", "rev-parse", "status", "diff"} for command in recorder.commands
    )
    assert rejected, "HEAD is the same as far-reaching, not representing delivery in the workspace"

    # The development role is normally submitted, pushed back and must be accessible in the same workspace.
    recorder.status = ""
    recorder._head_sha = recorder._remote_sha = "b" * 40
    ws.assert_delivered(worktree=tmp_path, branch="openagents/issue-140")


def test_delivery_snapshot_ensure_preserves_uncommitted_implementation(tmp_path, monkeypatch):
    """RFC-0005: The restoration of unclean working areas cannot be repeated in the prepare language of forced reconstruction."""
    recorder = _RevParseRecorder(remote_sha="a" * 40, head_sha="a" * 40, status=" M entry.py\n")
    monkeypatch.setattr(subprocess, "run", recorder)
    worktree = tmp_path / ".openagents" / "worktrees" / "issue-140"
    worktree.mkdir(parents=True)
    source = worktree / "entry.py"
    source.write_text("implementation surviving a timeout\n")

    assert (
        Workspace(work_dir=tmp_path).ensure(issue_number=140, branch="openagents/issue-140")
        == worktree
    )
    assert source.read_text() == "implementation surviving a timeout\n"
    assert recorder.commands == [], (
        "Relay existing workspaces without reconstruction, reset or clean"
    )


def test_decision_7_docstring_allows_force_with_lease_on_own_branch():
    # Decision 7 Revision: Never* naked* force, allow --force-with-lease only for the branch of the issue.
    doc = ws_module.__doc__ or ""
    assert "Never use a bare force push" in doc
    assert "--force-with-lease" in doc
    assert "openagents/issue-" in doc


def test_module_exposes_workspace_error():
    assert issubclass(ws_module.WorkspaceError, Exception)


# --------------------------------------------------------------------------- #
# Spec-0068/T1: Process Level git-mutation Serial Lock (Lock)prepare/ensure (a) Locked;commit/assert No locks)
# --------------------------------------------------------------------------- #


class _LockProbeRecorder:
    """subprocess.run double: detect if _GIT_MUTATION_LOCK is currently held while each guit command is being executed.

    Record (sub-order, lock occupied when entering). `acquire(blocking=False)` detect: Can get = current
    No one holds a lock (returns to False ”unlocked” and is released immediately); cannot get = locks with a segment (True).
    """

    def __init__(self, *, stdout=""):
        self.observations = []  # list[tuple[str, bool]]
        self._stdout = stdout

    def __call__(self, args, **kwargs):
        sub = args[3] if len(args) > 3 else ""
        got = ws_module._GIT_MUTATION_LOCK.acquire(blocking=False)
        held_by_caller = not got
        if got:
            ws_module._GIT_MUTATION_LOCK.release()
        self.observations.append((sub, held_by_caller))
        return SimpleNamespace(
            returncode=0, stdout="" if sub == "status" else self._stdout, stderr=""
        )


def test_prepare_git_mutations_run_under_lock(tmp_path, monkeypatch):
    # The whole of prepare shares.git changes (fetch/remove/prune/branch/add) should be executed under a lock.
    probe = _LockProbeRecorder()
    monkeypatch.setattr(subprocess, "run", probe)
    Workspace(work_dir=tmp_path).prepare(issue_number=3, branch="openagents/issue-3", base="main")

    mutating = {"fetch", "worktree", "branch"}
    seen = [(sub, held) for sub, held in probe.observations if sub in mutating]
    assert seen, "Prepare should run at least one guit change order"
    assert all(held for _, held in seen), (
        f"The git change in prepare is to be executed with a lock.{seen}"
    )


def test_ensure_git_mutations_run_under_lock(tmp_path, monkeypatch):
    # The setch + worktree add of the ensure (missing path for reconstruction) should also be executed under a lock.
    probe = _LockProbeRecorder()
    monkeypatch.setattr(subprocess, "run", probe)
    Workspace(work_dir=tmp_path).ensure(issue_number=3, branch="openagents/issue-3")

    seen = [(sub, held) for sub, held in probe.observations if sub in {"fetch", "worktree"}]
    assert seen, "Esure re-build path should run"
    assert all(held for _, held in seen), (
        f"The guit change in the grate of the giraffe is to be executed with a lock.{seen}"
    )


def test_assert_delivered_does_not_take_lock(tmp_path, monkeypatch):
    # assert_delivered is read-only, without changing the share ref, should not get the guit-mutation lock.
    probe = _LockProbeRecorder(stdout="a" * 40 + "\n")
    monkeypatch.setattr(subprocess, "run", probe)
    Workspace(work_dir=tmp_path).assert_delivered(worktree=tmp_path, branch="openagents/issue-3")

    assert probe.observations, "assert_delivered Run"
    assert all(not held for _, held in probe.observations), (
        f"assert_delivered should not hold a grate-mutuation lock.{probe.observations}"
    )


def test_lock_is_module_level_threading_lock():
    # The lock must be a modular threading.Lock (repeated, non-renewable; example lock cannot be used to cross-worker call).
    lock = ws_module._GIT_MUTATION_LOCK
    assert lock.acquire(blocking=False) is True
    lock.release()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
