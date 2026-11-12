# RFC-0005
"""Manage isolated worktrees and their Git lifecycle.

Never use a bare force push. An explicit --force-with-lease is limited to the
current openagents/issue- branch, never main or another issue branch.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import threading
from pathlib import Path

# RFC-0003 Decision 1: The isolated worktree root directory for each issue (.openagents/ has been ignored by.gitignore).
_WORKTREE_SUBDIR = Path(".openagents") / "worktrees"
_CONFLICT_WORKTREE_SUBDIR = Path(".openagents") / "conflict-worktrees"

# Spec-0068/T1: process level git-mutation serial lock - copy RuntimeState._LOCK
# (openagents/runtime/state.py). Watch K and send a pair of ** main warehouse. Git** run
# prepare/ensure（fetch + worktree remove/prune/add + branch -D）- Yes, it is. packed-refs.lock /
# Worktree management lock, and worktree rune is a cross-worker-wide side effect that can mistook a person 's half-finished product (P2).
# Share this second indent.get change the whole line: Draft +reconcile is a minute, and the line almost loses the parallel once
# Remove all three types of competition; preune is in the same lock and will no longer collide with the side-haired add. Use Lock instead of Rock -- Change
# Without a trap, a mutually exclusive approach is sufficient. The module level (non-example level) is not able to cross the worker because each call is new and a workspace.
# commit_and_push(each) worktree Private index）with assert_delivered(Pretty reading) Natural isolation, not locking.
_GIT_MUTATION_LOCK = threading.Lock()

# Spec-0035/T2: The number of hours of time-out seconds for the sub-process network (coordinate github._GH_TIMEOUT_SECONDS = 30; only triggered when the real card is stuck).
# Each of the three modules has one (git.py/workspace.py/release.py) and is replaced by zero import coupling (see spec Nationale Option 1).
_GIT_NET_TIMEOUT_SECONDS = 30

# 2026-06-24 spec-markdown-form: spec group = single file NNNN-slug.md (slug) starts with letters, and the ZVP is now in the middle of the day.
# Excludes the design document YYYY-MM-DD-*.md.
_SPEC_GROUP_FILE_RE = re.compile(r"^\d{4}-[A-Za-z].*\.md$")


def _short_sha(*, sha: str) -> str:
    """# Spec-0056/T1: Use the full SHA in short summary for hard-lock error reporting (empty-spectrum labels, easy to locate manually)."""
    return sha[:12] if sha else "(empty)"


class WorkspaceError(Exception):
    """guit / worktree when the operation failed to throw, carry the git stderr summary."""


class Workspace:
    """RFC-0005 T1: Worktree Workspace Manager (constructed by work_dir) with only guit."""

    def __init__(self, *, work_dir: Path) -> None:
        self._work_dir = Path(work_dir)

    def prepare(self, *, issue_number: int, branch: str, base: str) -> Path:
        """Prepares issue worktree; restores the branch when results are available at the remote end, otherwise created from the latest baseline."""
        path = self._worktree_path(issue_number=issue_number)
        # Spec-0068/T1: Share the whole .get change (fetch → remove → prene → brancy_Dzaadd) with a chained line,
        # Eliminated Kworker and released packed-refs / worktree management lock competition with prune half-finished (P2).
        with _GIT_MUTATION_LOCK:
            # Decision 2: Draw up the latest base before drafting (fetch does not touch current user check).
            self._git(args=["fetch", "origin", base], cwd=self._work_dir, check=True)
            # Retry must continue the already sent issue branch. If you are still rebuilt from base, you will be called for the first successful delivery.
            # Spec/codes are discarded, and follow-up models can only be drafted over and eventually become competitively achieved.
            resume_remote = self.remote_branch_exists(branch=branch)
            if resume_remote:
                self._git(args=["fetch", "origin", branch], cwd=self._work_dir, check=True)
            # Decision 4: The equivalent of the possible worktree left by the issue and local branch (failed to ignore).
            self._git(
                args=["worktree", "remove", "--force", str(path)], cwd=self._work_dir, check=False
            )
            self._git(args=["worktree", "prune"], cwd=self._work_dir, check=False)
            self._git(args=["branch", "-D", branch], cwd=self._work_dir, check=False)
            start_point = f"origin/{branch}" if resume_remote else f"origin/{base}"
            self._git(
                args=["worktree", "add", "-b", branch, str(path), start_point],
                cwd=self._work_dir,
                check=True,
            )
        return path

    def ensure(self, *, issue_number: int, branch: str) -> Path:
        """RFC-0003 Decision 5: Reuse existing worktree; the missing is rebuilt from a remote branch."""
        path = self._worktree_path(issue_number=issue_number)
        if path.exists():
            return path
        # Spec-0068/T1: Continue path is also setch + worktree add shared.git, whole locked line (same as prepare).
        with _GIT_MUTATION_LOCK:
            self._git(args=["fetch", "origin", branch], cwd=self._work_dir, check=False)
            self._git(args=["worktree", "add", str(path), branch], cwd=self._work_dir, check=True)
        return path

    def prepare_conflict(self, *, branch: str, base: str) -> Path:
        """Prepare a detached, branch-specific worktree for conflict recovery.

        Conflict repair must not reuse the normal issue worktree: that path may be checked
        out on a conventional issue branch, may be owned by an interrupted implementation,
        or may still contain an in-progress rebase.  A detached worktree is safe because the
        deliver protocol publishes ``HEAD:<branch>`` explicitly.  Clean instances are rebuilt
        from the current remote head; dirty instances are preserved for the resolver to resume.
        """
        key = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:16]
        path = self._work_dir / _CONFLICT_WORKTREE_SUBDIR / key
        with _GIT_MUTATION_LOCK:
            self._git(args=["fetch", "origin", base, branch], cwd=self._work_dir, check=True)
            if path.exists():
                inside = self._git(
                    args=["rev-parse", "--is-inside-work-tree"], cwd=path, check=False
                )
                if inside.returncode != 0:
                    # A killed `worktree add` can leave the destination directory behind
                    # without a registered worktree. It contains no valid resolver state;
                    # remove only this managed conflict-worktree so the next add can proceed.
                    shutil.rmtree(path)
                elif self._operation_in_progress(worktree=path):
                    return path
                else:
                    status = self._git(
                        args=["status", "--porcelain", "--untracked-files=all"],
                        cwd=path,
                        check=True,
                    )
                    if status.stdout.strip():
                        return path
                    self._git(
                        args=["worktree", "remove", "--force", str(path)],
                        cwd=self._work_dir,
                        check=False,
                    )
                    self._git(args=["worktree", "prune"], cwd=self._work_dir, check=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._git(
                args=["worktree", "add", "--detach", str(path), f"origin/{branch}"],
                cwd=self._work_dir,
                check=True,
            )
        return path

    def _operation_in_progress(self, *, worktree: Path) -> bool:
        """Detect rebase/merge/cherry-pick state even when porcelain is currently empty."""
        git_dir_result = self._git(args=["rev-parse", "--git-dir"], cwd=worktree, check=False)
        raw_git_dir = git_dir_result.stdout.strip()
        if not raw_git_dir:
            return False
        git_dir = Path(raw_git_dir)
        if not git_dir.is_absolute():
            git_dir = (worktree / git_dir).resolve()
        for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"):
            if (git_dir / marker).exists():
                return True
        return False

    def assert_delivered(self, *, worktree: Path, branch: str) -> None:
        """#Spec-0056/T1: It is asserted that no results were submitted and local HEAD has been pushed to a remote <branch>.

        After delivery (committee  →  setch  →  rebase resolve conflict  →  push --force-with-lease) by
        Harness Call: Checking Workspace (allowing Git’s ignored cache), successful `git fetch origin <branch>`
        `git rev-parse origin/<branch>` vs. `git rev-parse HEAD` - Same = released;
        = agent self-determination completed without pushing it up and throwing Workspace Error.
        SHA Summary. Far from the branch (rev-parse failed) is considered as ”undelivered” throw (agent should have push-built branch).

        Ref only updated tracking, unremarked GitHub/backend (watching RFC-0005 ”Only GIT” borders); Harness never acts
        The gate is only ”unattendable” (offerment decision 7) and is left in order.

        Version assumption (PR #141 review minor): Reliance on `git fetch origin <branch>` will refresh local
        `origin/<branch>` Track ref, and then `rev-parse origin/<branch>` I read the latest far end. head——Requirement of the act
        glit gi (1.8.4 (early version of the setch does not update single branch tracking ref). The development/CI environment guit is much higher than this version and therefore does not run-time detection.
        """
        head_sha, remote_sha = self.delivery_heads(worktree=worktree, branch=branch)
        if remote_sha != head_sha:
            raise WorkspaceError(
                f"branch {branch} not delivered: remote and local heads differ; "
                f"origin/{branch}={_short_sha(sha=remote_sha)} and local HEAD={_short_sha(sha=head_sha)}"
            )

    def delivery_heads(self, *, worktree: Path, branch: str) -> tuple[str, str]:
        """Read clean local/remote heads without deciding why they differ (Spec-0089/T1).

        Delivery requires equality; a reader may instead have an outdated candidate. Keep
        that classification with the caller, but never turn dirty work or Git IO failure
        into an ordinary candidate change. Fetch refreshes refs, never the reviewed files.
        """
        # Spec-0056 recovery: a matching HEAD alone does not include staged/untracked source.
        status = self._git(
            args=["status", "--porcelain", "--untracked-files=all"], cwd=worktree, check=True
        )
        if status.stdout.strip():
            raise WorkspaceError(f"branch {branch} not delivered: worktree has uncommitted changes")
        self._git(args=["fetch", "origin", branch], cwd=worktree, check=True)
        remote = self._git(args=["rev-parse", f"origin/{branch}"], cwd=worktree, check=False)
        head = self._git(args=["rev-parse", "HEAD"], cwd=worktree, check=True)
        head_sha = head.stdout.strip()
        remote_sha = remote.stdout.strip()
        if remote.returncode != 0 or not remote_sha:
            raise WorkspaceError(
                f"branch {branch} not delivered: missing remote branch origin/{branch}"
                f"(local HEAD=){_short_sha(sha=head_sha)}- I don’t think so."
            )
        if not head_sha:
            raise WorkspaceError(f"branch {branch} Unable to read local HEAD")
        # Spec-0017: fetching may take time; reject source dirt introduced during IO too.
        status = self._git(
            args=["status", "--porcelain", "--untracked-files=all"], cwd=worktree, check=True
        )
        if status.stdout.strip():
            raise WorkspaceError(f"branch {branch} not delivered: worktree has uncommitted changes")
        return head_sha, remote_sha

    def sync_delivered(self, *, worktree: Path, branch: str) -> bool:
        """Align a clean, behind-only worktree without discarding local work.

        Spec-0089/T1: False means existing development/delivery must continue. Git IO
        failures raise instead of being interpreted as unfinished source or successful delivery.
        """
        status = self._git(
            args=["status", "--porcelain", "--untracked-files=all"], cwd=worktree, check=True
        )
        if status.stdout.strip():
            return False
        self._git(args=["fetch", "origin", branch], cwd=worktree, check=True)
        head = self._git(args=["rev-parse", "HEAD"], cwd=worktree, check=True).stdout.strip()
        remote = self._git(
            args=["rev-parse", f"origin/{branch}"], cwd=worktree, check=True
        ).stdout.strip()
        if not head or not remote:
            raise WorkspaceError(f"branch {branch} Unable to read local or remote HEAD")
        if head == remote:
            return True
        ancestor = self._git(
            args=["merge-base", "--is-ancestor", head, remote], cwd=worktree, check=False
        )
        if ancestor.returncode == 1:
            return False  # Ahead/diverged: preserve every local commit for the delivery agent.
        if ancestor.returncode != 0:
            raise WorkspaceError(
                f"branch {branch} I can’t judge the relationship:{ancestor.stderr.strip()}"
            )
        self._git(args=["merge", "--ff-only", f"origin/{branch}"], cwd=worktree, check=True)
        return True

    def changed_spec_groups(self, *, worktree: Path, base: str) -> list[Path]:
        """Locate every spec group markdown file this branch touches, via git diff vs base.

        2026-06-24 spec-markdown-form: spec group is now a single file docs/specs/NNNN-slug.md.
        `git diff --name-only origin/<base>...HEAD -- docs/specs/` Group File to Fetch Changes to this Branch
        (Excludes OVERVIEW.md / ARCHITECTURE.md / README.md / designed document) returns it in worktree
        list of absolute paths. Read only guit, do not drop business errors.
        """
        # 1. Lists docs/specs/ files (three points diff: changes to the side of this branch only) that have been changed by this branch relative to base.
        result = self._git(
            args=["diff", "--name-only", f"origin/{base}...HEAD", "--", "docs/specs/"],
            cwd=worktree,
            check=False,
        )
        # 2. Take all NNNN-slug.md group files (third segment of the path; exclusion of the generator /README/dated document).
        paths = []
        for line in result.stdout.splitlines():
            rel = line.strip()
            if not rel:
                continue
            parts = Path(rel).parts
            if len(parts) == 3 and parts[0] == "docs" and parts[1] == "specs":
                if _SPEC_GROUP_FILE_RE.match(parts[2]):
                    paths.append(worktree / "docs" / "specs" / parts[2])
        return paths

    def changed_spec_group(self, *, worktree: Path, base: str) -> Path | None:
        """Return the first changed spec group for callers expecting the original API."""
        paths = self.changed_spec_groups(worktree=worktree, base=base)
        return paths[0] if paths else None

    def remote_branch_exists(self, *, branch: str) -> bool:
        """Whether the branch (`git ls-remote --heads`) exists at a remote end.

        # Spec-0035/T2: ls-remote go network. check=WorkspaceError under `_git`** sole source**
        # (normal non-zero exit normally returns Completed Process under check = False) so this level of catch exact equivalents ”overtime”
        #Do not misapprove the true failure # — conservative judgment ”may be on the way” — skips this round, retries the next round, never repeats the ”no branch” by misjudgement (fail-open)
        """
        try:
            result = self._git(
                args=["ls-remote", "--heads", "origin", branch],
                cwd=self._work_dir,
                check=False,
            )
        except WorkspaceError:
            return True
        return bool(result.stdout.strip())

    def _worktree_path(self, *, issue_number: int) -> Path:
        """RFC-0003 Decision 1: The defined worktree path for each issue (not durable)."""
        return self._work_dir / _WORKTREE_SUBDIR / f"issue-{issue_number}"

    def _git(self, *, args: list[str], cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        """Runs a guit sub-command in cwd; check =True does not exit at zero for workspaceError.

        #Spec-0035/T2: Pass = _GIT_NET_TIMEOUT_SECONDS — Internet git (fetch/ls-remote) is blocked and the #system is broken.
        # WorksspaceError (overcovering prepare/ensure/assert_delivered three setch callers)
        # per-issue/per-round quarantine, without lifting the wheel; local git (worktree/rev-parse/diff/branch) is only up to the limit of no harm.
        """
        try:
            result = subprocess.run(
                ["git", "-C", str(cwd), *args],
                capture_output=True,
                text=True,
                timeout=_GIT_NET_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise WorkspaceError(
                f"git {' '.join(args)} Timeout (Performance){_GIT_NET_TIMEOUT_SECONDS}s）"
            ) from None
        if check and result.returncode != 0:
            reason = (
                result.stderr.strip() or f"git {' '.join(args)} Return Code {result.returncode}"
            )
            raise WorkspaceError(reason)
        return result
