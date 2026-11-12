# Spec-0060/T3
"""Verify objective repository facts before delivery or merge.

These gates check head advancement, SHA-bound approval and evidence, file
ownership, and other deterministic invariants. They leave review judgments
and conflict resolution to roles and obtain repository facts through helpers.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openagents.spec import model as spec_model
from openagents.spec import ownership
from openagents.spec.model import Group
from openagents.spec.render import render as render_specs
from openagents.spec.validate import validate as validate_specs

# Spec-0074/T1: arias-import switch - Platform operations are configured by github/gitea driver to call zero changes.
from openagents.utils import forge as github
from openagents.utils import git

# Spec-0060/T3: The default limit for the evaluation cycle - above which PASS is still not considered dead, go to the bottom raise (which can be covered by the caller).
DEFAULT_MAX_ROUNDS = 10


def assert_repository_integrity(*, workspace: Path) -> None:
    """Reject a merge candidate whose complete Spec snapshot is inconsistent."""
    specs_root = Path(workspace) / "docs" / "specs"
    report = validate_specs(specs_root=specs_root)
    errors = [f"{item.where}: {item.message}" for item in report.issues if item.level == "error"]
    if errors:
        raise RepositoryIntegrityStale(
            "Repository level Spec integrity failed:" + "; ".join(errors)
        )
    overview = specs_root / "OVERVIEW.md"
    actual = overview.read_text(encoding="utf-8") if overview.exists() else ""
    if actual != render_specs(specs_root=specs_root):
        raise RepositoryIntegrityStale(
            "Repository level Spec integrity failed: OVERVIEW.md does not match the tree candidate"
        )


def assert_design_approved(*, workspace: Path, issue_number: int, approved_digest: str) -> None:
    """Reject changed semantics; retain exact legacy approvals (Spec-0088/T1)."""
    # Never migrate a legacy approval by blessing the current candidate's new digest.
    digest_of = spec_model.design_digest
    if re.fullmatch(r"[0-9a-f]{64}", approved_digest):
        digest_of = spec_model.legacy_design_digest
    issue_groups = [
        group
        for group in spec_model.load_all(specs_root=Path(workspace) / "docs" / "specs")
        if group.metadata.issue == issue_number
    ]
    approved_groups = [group for group in issue_groups if digest_of(group=group) == approved_digest]
    if len(approved_groups) == 1:
        return
    if not approved_groups:
        current = ",".join(digest_of(group=group)[:12] for group in issue_groups) or "none"
        raise DesignApprovalStale(
            f"issue #{issue_number} The approved design does not exist:"
            f"approved={approved_digest[:12]} current={current}"
        )
    raise DesignApprovalStale(
        f"issue #{issue_number} has multiple Specs matching the approved design digest"
    )


# Spec-0062/T2: The definitive interpretation of the original language of the combined waterline (recipes.merge_pr) - ** reading only the classification of objective facts** and not "can we fit?"
# Default threshold for the Easter Window: Aligning old messages.REOPEN_REVIVE_WINDOW_SECONDS (7 days) -closed run beyond this to harden the eventuality.
REVIVE_WINDOW_SECONDS = 7 * 24 * 3600

# Spec-0062/T2: white list of skip gates; unknown lock name GateError (defunct-proof-flip).
_SKIP_GATES = ("ci", "code", "evidence", "spec")

# Spec-0017/T3: Two objective criteria for combining the hardlock - CI All Green + `review-approved:<head sha7>` label and ssha match the current head.
# Label prefix with recipes.vigil `_LABEL_REVIEW_APPROVED_PREFIX` (single agreement on the location of the award), Sha7 length and guit short
# Shas. Gates does not report vigil (avoid recipe → runtime inverse) and is therefore standing here.
_REVIEW_APPROVED_LABEL_PREFIX = "review-approved:"
_SHA_LABEL_LEN = 7


class GateError(Exception):
    """# Spec-0060/T3: Throw out the smallest hard-barrel when it determines that the objective fact is not valid (undelivered / dead cycle / PR does not exist/ jabs do not match)."""


class DesignApprovalStale(GateError):
    """Spec-0090/T1: Approved design no longer corresponds to Spec, and needs to return to the existing architecture review."""


class RepositoryIntegrityStale(GateError):
    """Spec-0090/T1: The generation of the view is not compatible with the source data and needs to be repaired along the established delivery path."""


@dataclass(frozen=True)
class IntegrationStamp:
    """The exact repository/design versions covered by an integration check."""

    base_sha: str
    head_sha: str
    design_digest: str


def assert_integration_stamp(*, approved: IntegrationStamp, current: IntegrationStamp) -> None:
    """Reject reuse of an integration result after any observed input changed."""
    if not all((current.base_sha, current.head_sha, current.design_digest)):
        raise GateError("Integrated validation stamp incomplete")
    if current != approved:
        raise GateError(
            "Integrated validation is invalid: base, head or standard certificate changes after the test is performed"
        )


class MergeNotReady(Exception):
    """Indicate that the candidate is not ready to merge.

    Pending CI is temporary. Release the worker without charging a failure
    attempt so the producer can reconsider the candidate when checks finish.
    """


def snapshot_head(*, workspace: Path) -> str:
    """Read the current worktree HEAD before dispatching a delivery role."""
    return git.head_sha(work_dir=Path(workspace))


def assert_head_advanced(*, before: str, workspace: Path) -> str:
    """Require the candidate HEAD to advance beyond the host-recorded baseline.

    The role report cannot establish the before or after commit. Read both
    from Git and reject a missing or unchanged head.
    """
    after = git.head_sha(work_dir=Path(workspace))
    if not after:
        raise GateError(
            f"Not delivered: Workspace {workspace} Not read HEAD (suspect empty/not submitted)"
        )
    if after == before:
        raise GateError(
            f"HEAD did not advance after delivery:  {after[:12]} (no new commit was delivered)"
        )
    return after


def assert_merge_allowed(*, pr_number: int, head_sha: str, require_ci: bool = True) -> None:
    """Recheck the objective merge conditions immediately before dispatch.
    Spec-0017/T3.

    Verify CI and approval for the live head. A changed or unready candidate
    must return to reconciliation rather than merging on stale evidence.
    """
    if require_ci:
        checks = github.check_snapshot(pr_number=pr_number)
        # Zero check = did not run the CI Zen hard-bar (never match the code of the CI); the order is before the pending.
        if checks.count == 0:
            raise GateError(
                f"Merged hardlock not released: PR #{pr_number} Current head zero check -- Never merge uncharted CI codes"
            )
        if checks.state == "pending":
            raise MergeNotReady(
                f"PR #{pr_number} Currently head CI is running - non-red line, waiting for the next tick to get the"
            )
        if checks.state != "pass":
            raise GateError(
                f"Merged hardlock not released: PR #{pr_number} Current head CI is not green"
                f"（state={checks.state},Check Number ={checks.count}) - Never merge an unCI code"
            )
    snapshot = github.pr_snapshot(pr_number=pr_number)
    # Spec-0017 recovery: old labels remain after a push; they cannot certify a new PR head.
    if snapshot.head_sha != head_sha:
        raise MergeNotReady(f"PR #{pr_number} HEAD has changed, read and evaluated again")
    labels = snapshot.labels
    expected = f"{_REVIEW_APPROVED_LABEL_PREFIX}{head_sha[:_SHA_LABEL_LEN]}"
    if expected not in labels:
        raise GateError(
            f"Merged hardlock not released: PR #{pr_number} No match for current head {expected!r} label"
            f"(existing) {sorted(labels)}) - never merge unheard codes or awards are invalidated before they are read"
        )


def round_cap(*, max_rounds: int | None = None) -> Iterator[int]:
    """Yield numbered review rounds and raise after the configured limit."""
    limit = DEFAULT_MAX_ROUNDS if max_rounds is None else max_rounds
    yield from range(
        1, limit + 1
    )  # Round by round yield wheel (1.limit); break discards, never rises.
    raise GateError(
        f"Review cycle exceeding {limit} The ceiling of the wheel remains undeterred, and appears to be a dead end cycle (reviewer constant REWORK)"
    )


def assert_pr_exists(*, pr_number: int) -> None:
    """PR Existence hardlock: Detection PR is the real PR, does not exist or does not throw.

    Through utils.github.pr_head_branch (`gh pr view`) probe - PR - github throws GithubError when it does not exist.
    Here you can turn to GateError (with PR). Only the PR point to a true PR, and not to state/content.
    """
    try:
        github.pr_head_branch(pr_number=pr_number)
    except github.GithubError as exc:
        raise GateError(
            f"PR #{pr_number} Cannot initialise Evolution’s mail component.{exc}"
        ) from exc


def assert_evidence_stamp(*, head_sha: str, claimed: str) -> None:
    """Require the e2e evidence stamp to match the current candidate head."""
    if head_sha != claimed:
        raise GateError(
            f"Evidence tracer mismatch: actual head={head_sha[:12] or '(empty)'} ≠ "
            f"Evidence says he’s dead.{claimed[:12] or '(empty)'}”The evidence is old or Zhang Li”"
        )


def assert_writes_owned(
    *,
    group: Group,
    changed_paths: list[str],
    specs_root: Path = Path("docs/specs"),
) -> None:
    """Reject changed paths that are neither owned nor generated for this Spec.
    Spec-0071/T3.
    """
    offenders = ownership.unowned_writes(
        group=group, changed_paths=changed_paths, specs_root=specs_root
    )
    if offenders:
        raise GateError(
            f"Overstepped: change of group (in %){group.number}) Any document of Task that is not declared and is not generated "
            f"{offenders}– The idea is that 6 ”Each Task is a set of faces” must be written in a spec before it is written."
        )


# --------------------------------------------------------------------------------------------------
# Spec-0062/T2: Merge current line interpretation gate - Scratch the "Read GitHub Objective Fact to Categorize" scattered in the old messages.poll to a pure function.
# Read objective facts, return to the `Berble/Class'** and never judge "the fit of the "reviewer agent" or "the conflict."
# recipes.merge_pr says these are the routings. They're pure logic, zero IO, hermetic.
# (The reference is the caller who read the Mergeability / CheckStatus snapshot from utils.github, no more net touch on the floor).
# --------------------------------------------------------------------------------------------------


def is_conflicting(*, mergeability: github.Mergeability) -> bool:
    """Read whether the forge reports a dirty or conflicting PR."""
    return mergeability.merge_state_status == "DIRTY" or mergeability.mergeable == "CONFLICTING"


def is_mergeable_unknown(*, mergeability: github.Mergeability) -> bool:
    """GitHub is not yet counted (just push common) - UNKNOWN is a legal middle: this round does not advance and next round is rechecked."""
    return mergeability.mergeable == "UNKNOWN"


def is_behind(*, mergeability: github.Mergeability) -> bool:
    """Backward base but no text conflict - BEHIND: Need to pull the latest base in to trigger CI rerun in integrated state (RaySync)."""
    return mergeability.merge_state_status == "BEHIND"


def ci_failed(*, check_status: github.CheckStatus) -> bool:
    """CI Conclusion Interpretation: Any check failed (`status.state == "fail"` for Old Poll)."""
    return check_status.state == "fail"


def ci_pending(*, check_status: github.CheckStatus) -> bool:
    """CI Conclusion interpretation: Check still in progress (not reviewed in current cycle, recheck next round)."""
    return check_status.state == "pending"


def evidence_stamp_ok(*, head_sha: str, claimed: str) -> bool:
    """e2e Trace-of-source interpretation of evidence - `assert_evidence_stamp`** Boll version** (no raise, for merge_pr route).

    `assert_evidence_stamp` caliber: claimed non-empty and = actual head = current head, release;
    Otherwise (unprevented / old / Zhang Li) is not ready. The difference is that the evidence in solve_issue does not fit ”agent lies”
    Hard raise, while merge_pr only indicates that ”the current round should be filled with e2e” (return to ”e2e” event, not hard failure), so read in Boolean.
    """
    return bool(claimed) and claimed == head_sha


def revive_eligible(*, closed_at: str, now: datetime, window_seconds: int | None = None) -> bool:
    """Check whether a recently closed run is eligible to be reconsidered."""
    if not closed_at:
        return False
    try:
        closed = datetime.fromisoformat(closed_at)
    except ValueError:
        return False
    window = REVIVE_WINDOW_SECONDS if window_seconds is None else window_seconds
    return (now - closed).total_seconds() <= window


def skip_hits(*, skip: object, gate: str) -> bool:
    """Whether the `gate` gate was released by `--skip` as PASS. Gate _SKIP_GATES."""
    if gate not in _SKIP_GATES:
        raise GateError(f"Unknown skip gate {gate!r}; valid gates: {_SKIP_GATES}")
    return bool(getattr(skip, f"at_{gate}"))
