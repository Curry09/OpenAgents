"""Spec-0068/T2: The N thread and the ZZlock Retrace Test for the same main warehouse.git construction workstream.

threading.Thread vs. ** same temporary get warehouse** and Workspace.prepare (differently)
issue_number/branch, base=main) and join later asserted:
  - Return all active worktree paths, directories are actually built;
  - Zero Workspace Error;
  - Got ’cannot lock ref’/ ’could not lock working tree’.

Walk local file://www.un.org/gitub_prepare
Far. _GIT_MUTATION_LOCK locked in openagents/utils/workspace.py: share the whole prepare. Git changes
Serialization, eliminating packed-refs / workstream management lock competition and prune half-finished product (P2).

Contrast (documentation, no long run): N is more and more easily re-emergence after removing _GIT_MUTATION_LOCK (remove two `with` segments)
`cannot lock ref … File exists` / `could not lock working tree`, this test turns to flaky/failed - exactly what this lock is about to be removed.
"""

import subprocess
import threading
from pathlib import Path

import pytest

from openagents.utils.workspace import Workspace

_N_WORKERS = (
    6  #  → 4: Larger co-opt windows to stabilize exposure lock competition (flaky if unlocked)
)


def _run_git(*, cwd: Path, args: list[str]) -> None:
    """Run a guit command (testing kit, failure or throw, with stderr easily positioned)."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} Failed:{proc.stderr}")


def _make_origin_and_work(*, tmp_path: Path) -> Path:
    """Build a bare origin+ with a moin branch, and return to the workspace path with it as a workspace."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _run_git(cwd=tmp_path, args=["init", "--bare", "-b", "main", str(origin)])
    _run_git(cwd=tmp_path, args=["clone", str(origin), str(work)])
    _run_git(cwd=work, args=["config", "user.email", "t@t.io"])
    _run_git(cwd=work, args=["config", "user.name", "t"])
    (work / "README.md").write_text("seed\n")
    _run_git(cwd=work, args=["add", "README.md"])
    _run_git(cwd=work, args=["commit", "-m", "seed"])
    _run_git(cwd=work, args=["push", "origin", "main"])
    return work


class _StderrCapturingWorkspace(Workspace):
    """Workspace subcategory: record the stderr of each guit sub-order for the adjoining assertion of unlocked competition.

    Check = False ’s guit command (worktree remove/prune, lanch-D) **/ Locked in error **, therefore must
    The arrest of the stderr - a single look at ”zero workspace Error” would have missed such silent locks.
    """

    def __init__(self, *, work_dir: Path, sink: list) -> None:
        super().__init__(work_dir=work_dir)
        self._sink = sink

    def _git(self, *, args, cwd, check):
        result = super()._git(args=args, cwd=cwd, check=check)
        if result.stderr:
            self._sink.append(result.stderr)
        return result


def test_concurrent_prepare_same_repo_no_git_lock_contention(tmp_path):
    work = _make_origin_and_work(tmp_path=tmp_path)

    stderr_sink: list[str] = []
    errors: list[BaseException] = []
    paths: dict[int, Path] = {}
    barrier = threading.Barrier(
        _N_WORKERS
    )  # Lets the N-line run as much as possible in the .git change

    def _worker(n: int) -> None:
        ws = _StderrCapturingWorkspace(work_dir=work, sink=stderr_sink)
        try:
            barrier.wait(timeout=30)
            path = ws.prepare(issue_number=n, branch=f"openagents/issue-{n}", base="main")
            paths[n] = path
        except BaseException as exc:  # noqa: BLE001 —- Collecting any arbitrary abnormally uniform claims
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(n,)) for n in range(_N_WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    # 1. WorkspaceError / Any anomalies.
    assert not errors, f"Concurrent prepare error (lock competition?{[repr(e) for e in errors]}"
    # 2. All worktrees are built, catalogues are real and they differ from one another.
    assert len(paths) == _N_WORKERS
    for n, path in paths.items():
        assert path.exists(), f"issue-{n} The worktree is not built:{path}"
    assert len({str(p) for p in paths.values()}) == _N_WORKERS
    # 3. The catch of girder does not contain the kernel lock competition.
    joined = "\n".join(stderr_sink)
    assert "cannot lock ref" not in joined, f"ref lock competition:{joined}"
    assert "could not lock working tree" not in joined, (
        f"There is a worktree management lock competition:{joined}"
    )


def test_concurrent_prepare_lock_serializes_git_mutation_segment(tmp_path):
    # Direct validation of retort: The probe asserts in a locked segment that at most one line range is in .git (and the maximum combined length observed = 1).
    work = _make_origin_and_work(tmp_path=tmp_path)
    from openagents.utils import workspace as ws_module

    active = {"n": 0, "max": 0}
    guard = threading.Lock()
    errors: list[BaseException] = []
    barrier = threading.Barrier(_N_WORKERS)

    real_git = Workspace._git

    def _observing_git(self, *, args, cwd, check):
        # Only sample and hair (fetch/worktree/branch) on the .git change sub-command.
        sub = args[0] if args else ""
        sample = sub in {"fetch", "worktree", "branch"}
        if sample:
            with guard:
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
        try:
            return real_git(self, args=args, cwd=cwd, check=check)
        finally:
            if sample:
                with guard:
                    active["n"] -= 1

    def _worker(n: int) -> None:
        ws = Workspace(work_dir=work)
        try:
            barrier.wait(timeout=30)
            ws.prepare(issue_number=n, branch=f"openagents/issue-{n}", base="main")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    import unittest.mock as _mock

    with _mock.patch.object(ws_module.Workspace, "_git", _observing_git):
        threads = [threading.Thread(target=_worker, args=(n,)) for n in range(_N_WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

    assert not errors, f"_Other Organiser{[repr(e) for e in errors]}"
    # The lock links the change in a line at any given time to a line at least one course within the .get change sub-command.
    assert active["max"] == 1, (
        f"Lock unstrung .git change segment, maximum co-length ={active['max']}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
