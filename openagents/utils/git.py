# Spec-0060/T1
"""Provide deterministic Git operations shared by the runtime and recipes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Spec-0060/T1: Thin reexports the original language of the worktree life cycle (without changing any line of workspace.py).
from openagents.utils.workspace import Workspace, WorkspaceError

# Spec-0035/T1: The number of hours of time-out seconds for the sub-process network (coordinate github._GH_TIMEOUT_SECONDS = 30; only triggered when the real card is stuck).
# No three module sharing constants: git.py has import workspace.py, and Import is revolving dependent (see spec Rationale option 1).
_GIT_NET_TIMEOUT_SECONDS = 30

__all__ = [
    "Workspace",
    "WorkspaceError",
    "head_sha",
    "porcelain",
    "remote_branch_exists",
    "seed_branch",
]


def head_sha(*, work_dir: Path) -> str:
    """Current full SHA (`git rev-parse HEAD`); no submitted/ failed to return empty string.

    The new gate `gates.assert_head_advanced` and the evidence trace to the objective fact that the head is the one that is coming together, and the evidence is coming back to us.
    It is the only source of objective judgement, such as ”if there is a real delivery”, and does not contain any operational judgement.
    """
    result = _git(args=["rev-parse", "HEAD"], cwd=Path(work_dir))
    return result.stdout.strip()


def porcelain(*, work_dir: Path) -> str:
    """PV: Porcelain digest (`git status --porcelain`) of the change of the workspace; clean workspace returns empty string.

    The same guit face as the backend (claude_code) determines whether the ”conformity of this round” is to be found; read in context/diagnostic.
    """
    result = _git(args=["status", "--porcelain"], cwd=Path(work_dir))
    return result.stdout.strip()


# Spec-0061/T1: Existence probe for remote-only branches - Sinoval vigil recide certainty to the heavy gate (subsection already exists = already in flight)
# Required, the same name method for the old workspace.py is tied to the case of Workspace, where free functions are provided in the thinest envelope.
def remote_branch_exists(*, work_dir: Path, branch: str) -> bool:
    """Whether the branch (`git ls-remote --heads origin <branch>` has output exists at a remote end).

    The main reason for the delay is that the remote branch already exists, indicating that the issue has been claimed by a back end in flight, and that the issue of the identity is not being considered by the authorities.
    Recide skips, does not repeat, accordingly. Read objective facts (ref) purely, excluding business judgement.

    # Spec-0035/T1: ls-remote walks the network and is likely to be half-open socket. Play a line of stderr bread crumbs before running. Output stops when stuck
    # This line, one-stop-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go-go--go-go-go-go-go-go-go-go--------go-go-go-go-go--go---------------------------go-go-go-----go-------------------------------
    # Misjudgement of ”no branch” and repetition of the list (for two miscalculations, see spec fail-open matrix).
    """
    print(f"...Checking whether the remote branch exists: {branch}…", file=sys.stderr, flush=True)
    try:
        result = _git(args=["ls-remote", "--heads", "origin", branch], cwd=Path(work_dir))
    except subprocess.TimeoutExpired:
        return True
    return bool(result.stdout.strip())


def seed_branch(*, work_dir: Path, branch: str, message: str) -> None:
    """Spec-0074 empirical restoration: a empty lid committee and a prefix to a PR when `rfc: skip` is pushed.

    `rfc: agent` ”First group + Push Branch” was completed by Draffer; no one in Sskip did either of these things.
    Not at the far end. head branch → `create_pr` 404(Property of production) Here**Uncertainty empty submission**Filling (%2)`--allow-empty`：
    Do not manufacture content, only have branches and pr anchors at the far end; visible `-c` identity, not dependent on host-wide guit configurations. By-band gain:
    The re-entry of the remote branch after landing can also be re-awakened by `pr_for_branch` (level-triggered self-rehabilitation).
    This is the organization of the guit (framework action, non-agent judgement), the sub-set of certainty; failure to throw the WorkspaceError caller digests.
    """
    commit = _git(
        args=[
            "-c",
            "user.name=openagents",
            "-c",
            "user.email=openagents@local",
            "commit",
            "--allow-empty",
            "-m",
            message,
        ],
        cwd=Path(work_dir),
    )
    if commit.returncode != 0:
        raise WorkspaceError(f"Seed commit failed: {(commit.stderr or '').strip()[:200]}")
    push = _git(args=["push", "-u", "origin", branch], cwd=Path(work_dir))
    if push.returncode != 0:
        raise WorkspaceError(f"Seed branch push failed: {(push.stderr or '').strip()[:200]}")


def _git(*, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Runs a read-only guit command and captures the output (in the same workspace._git mode as the ).

    # Spec-0035/T1: Pass = _GIT_NET_TIMEOUT_SECONDS — Network git (ls-remote) full is aborted
    # TimeoutExpired, never limit to the pol; local git (rev-parse/status) gets one unstarted by the same helper
    # No harm in time limit. Consume to the only helper (issue) that requests ”avoid a break-up”
    """
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_NET_TIMEOUT_SECONDS,
    )
