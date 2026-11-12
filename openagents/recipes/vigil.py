"""Autonomous, level-triggered Vigil orchestration.

Spec-0089/T1: resume interrupted delivery and invalidate changed review candidates without
consuming the execution failure budget; merge only the published, reviewed candidate.
Spec-0090/T1: preserve completed merges and time-bound existing design/delivery recovery routes.

Each subject is classified from current forge facts, queued exactly once, and processed under
a process-liveness lock. Ordinary agent/backend/protocol failures are bounded and projected to
the signed ``automation-failed`` machine terminal; conflict recovery is explicitly retryable and
does not require a human handoff. A material fact change clears any projection and revives the
subject. Dynamic agent material is supplied once through the runtime context contract.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openagents.agents import curator, replier, tester
from openagents.backends.base import effective_max_wall
from openagents.observations.execution_contracts import ExecutionContractUnavailable
from openagents.recipes import stages
from openagents.runtime import context, engine, evidence, gates, preflight, research, timing
from openagents.runtime.state import STATUS_ITERATING, STATUS_PR_OPEN, RuntimeState
from openagents.utils import agent_config, git, identity, proc, streams

# Spec-0074/T1: Dispatch forge operations to the configured GitHub or Gitea driver.
from openagents.utils import forge as github

# Spec-0065/T2: Use one stable branch name per issue.
_BRANCH_PREFIX = "openagents/issue-"

# Spec-0065/T2: Keep the queue beside runtime-state.json in its own file.
_QUEUE_DB_FILENAME = "vigil-queue.db"

# Spec-0065/T2: The kernel releases a subject's flock when its holder exits. Do not guess liveness
# from a lease or a timestamp.
_CLAIMS_DIRNAME = "claims"

# Spec-0065/T2: Warn when a live claim exceeds this age. Never reclaim a held lock: doing so
# permits duplicate execution.
_INFLIGHT_ALARM_SECONDS = 7200

# Spec-0065/T2: Bound ordinary claim retries; conflicts have separate delayed recovery. A process
# crash can leave no forge event, so the queue records attempts.
_MAX_ATTEMPTS = 3

# Spec-0065/T2: A queued row can stay locked if a descendant inherited the descriptor. Allow a
# handoff window before treating it as stalled.
_STALE_LOCK_SECONDS = 300

# Spec-0065/T2: Poll idle workers at this interval and wake immediately on shutdown.
_WORKER_POLL_SECONDS = 1.0

# Spec-0082/T1: coding may fan out across issue worktrees, but all PRs advance one base branch.
# Serialize the irreversible forge merge inside one Vigil process; the forge still rejects a stale
# or conflicting head when multiple processes are accidentally present.
_MECHANICAL_MERGE_LOCK = threading.Lock()

# Spec-0065/T2: Bound waits for SQLite's single writer. Allow time for work done within the
# transaction; a timeout during finalization can leave a claim for recovery.
_BUSY_TIMEOUT_MS = 30000

# This is a per-claim yield limit. A loop requires repeated facts, not merely a long sequence of
# fresh states. The outer delivery limit still applies.
_MAX_RECONCILE_ROUNDS = 8

# Conflict recovery has a different failure shape from an ordinary agent turn.  A resolver
# can leave a perfectly valid PR untouched while the local worktree is stale or still carries
# an interrupted rebase.  Keep a bounded, diagnosable reason on the queue retry instead of
# collapsing that state into the generic "agent failed" message.
_CONFLICT_REASON_MAX_CHARS = 320
_CONFLICT_RESOLUTION_ATTEMPTS = 3
_CONFLICT_RETRY_PREFIX = "conflict-retryable:"
_CONFLICT_RETRY_DELAY_SECONDS = 60
_CONFLICT_RETRY_MAX_DELAY_SECONDS = 3600
_CONFLICT_EPISODE_LIMIT = 5
_CONFLICT_FP_RE = re.compile(r"\bconflict_fp=([0-9a-f]{16})\b")

# Spec-0065/T2: A single-cycle drain is a bounded synchronization point. Forge state remains
# authoritative if the drain times out.
_DRAIN_MAX_SECONDS = 3600

# Spec-0065/T2: A signed attempt stamp records the unchanged fingerprint and the agent's report.
_ATTEMPT_MARKER = "<!-- openagents:attempt"

# Spec-0065/T2: Bind e2e evidence to its full head SHA. A new head requires new evidence;
# gates.evidence_stamp_ok enforces the same rule.
_E2E_MARKER = "<!-- openagents:e2e head="

# Store decisions such as admission, terminal failure, and review in labels. Read CI and
# mergeability directly from the forge so facts never need reconciliation with copied labels.
#
# Vigil writes a signed diagnostic and the automation-failed label. A terminal state holds until
# relevant facts change.
_LABEL_AUTOMATION_FAILED = github.AUTOMATION_FAILED_LABEL
_FAILURE_MARKER = "<!-- openagents:automation-failed"
_LABEL_READY = "ready"  # Admission token

# Bind review labels to the reviewed SHA. An approval must become stale when an agent pushes a new
# head, even if CI is green.
_LABEL_REVIEW_APPROVED_PREFIX = "review-approved:"  # review-approved:<sha7>
_LABEL_REVIEW_CHANGES_PREFIX = "review-changes-requested:"  # review-changes-requested:<sha7>
_SHA_LABEL_LEN = 7  # Length of the head SHA in a review label.

_REVIEW_APPROVED = "APPROVED"
_REVIEW_CHANGES_REQUESTED = "CHANGES_REQUESTED"

# Check in-flight claims before other states so a live worker is not mistaken for a stalled
# subject.
_IN_FLIGHT = "in-flight"
# Merged, closed, or terminal automation failure. Reclassify if the failure label is removed.
_TERMINAL = "terminal"
# Wait without enqueuing. The watchdog checks the threshold for this reason.
_QUIET = "quiet"
# Enqueue with INSERT OR IGNORE.
_ACTIONABLE = "actionable"

# Quiet states have different expected durations and watchdog thresholds.
_AWAITING_BLOCKERS = "awaiting-blockers"  # Wait for blocking subjects to merge.
_AWAITING_MERGEABILITY = "awaiting-mergeability"  # Wait for GitHub to compute the merge ref.
_AWAITING_CI = "awaiting-ci"  # Pending CI or zero checks at the current head.
_AWAITING_EFFECT = "awaiting-effect"  # Wait for the action to change the observed state.

# Actions are produced by classification and dispatched by _act.
_ACT_REPLY = "reply"  # Reply to a new human comment.
_ACT_SOLVE = "solve"  # Open a PR for the issue.
_ACT_REBASE = "rebase"  # Resolve conflicts before evaluating CI.
_ACT_FIX_CI = "fix-ci"  # Fix failing CI for this head.
_ACT_E2E = "e2e"  # Run e2e for missing or stale evidence.
_ACT_REVIEW_OR_FIX = "review-or-fix"  # Review is missing, stale, or requests changes.
_ACT_READY = "ready"  # Promote a draft before evaluating merge eligibility.
_ACT_MERGE = "merge"  # Merge an approved non-draft head after checks pass.

# Spec-0066/T2: Record why a subject is terminal. Other phases use the wait reason, action, or
# in-flight state.
_PHASE_MERGED = "merged"  # Terminal: merged.
_PHASE_CLOSED = "closed"  # Terminal: closed.
_PHASE_AUTOMATION_FAILED = _LABEL_AUTOMATION_FAILED

# Normalized forge facts.
_MERGE_CLEAN = "clean"
_MERGE_DIRTY = "dirty"  # Update a conflicting, dirty, or behind branch before checking CI.
_MERGE_UNKNOWN = "unknown"  # Mergeability has not been computed.

_CI_SUCCESS = "success"
_CI_FAILURE = "failure"
_CI_PENDING = "pending"
_CI_NONE = "none"  # Zero checks mean the workflow is still unverified.

_KIND_ISSUE = "issue"
_KIND_PR = "pr"

_AGENT = agent_config.OWNER_AGENT
_SKIP = agent_config.OWNER_SKIP

# Spec-0065/T2: Prefer work already in progress over opening new issues. Human replies have
# highest priority; callers can override the ordering.
_PRIORITY_DEFAULTS = {
    _ACT_REPLY: 6,
    _ACT_MERGE: 5,
    _ACT_READY: 5,  # Spec-0017: Promote drafts at the same priority as merge.
    _ACT_REVIEW_OR_FIX: 4,
    _ACT_E2E: 3,
    _ACT_FIX_CI: 2,
    _ACT_REBASE: 2,
    _ACT_SOLVE: 1,
}

# Spec-0065/T2: Configure wait thresholds by reason. Give healthy work time to finish; a false
# terminal failure is more disruptive than a late diagnostic.
_WATCHDOG_DEFAULTS: dict[str, int | None] = {
    _AWAITING_BLOCKERS: None,
    _AWAITING_MERGEABILITY: 180,
    _AWAITING_CI: 3600,
    _AWAITING_EFFECT: 300,
}

# Spec-0065/T2: Keep exactly one queue row per subject.
#
# A row describes a subject, not an event. Recompute actions from forge facts; events for one
# subject cannot run in parallel.
#
# Use flock for liveness. The PID is diagnostic only; claim timestamps are used for in-flight
# warnings.
#
# A text subject distinguishes issue work from standalone PRs.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    subject          TEXT    NOT NULL UNIQUE,        -- "issue:5" | "pr:12"
                                                     -- Unique subject: deduplication and one claim at a time
    priority         INTEGER NOT NULL DEFAULT 0,     -- Higher values are claimed first
    action           TEXT    NOT NULL DEFAULT '',    -- Current action; distinguishes conflict recovery
    enqueued_at      TEXT    NOT NULL,               -- ISO; FIFO within the same priority
    available_at     TEXT    NOT NULL DEFAULT '',    -- ISO; empty means claimable now
    conflict_fp      TEXT    NOT NULL DEFAULT '',    -- Stable fingerprint for this conflict
    conflict_attempts INTEGER NOT NULL DEFAULT 0,     -- Recovery episodes for the fingerprint
    status           TEXT    NOT NULL DEFAULT 'queued',   -- queued | claimed
    worker           TEXT,                           -- Claim owner, for diagnostics
    worker_pid       INTEGER,                        -- PID for diagnostics, never liveness
    claimed_at       TEXT,                           -- Claim timestamp for warnings only
    attempts         INTEGER NOT NULL DEFAULT 0      -- Ordinary attempt count; conflicts use delayed recovery
);
CREATE INDEX IF NOT EXISTS ix_work_queue_claimable
    ON work_queue (status, priority DESC, enqueued_at ASC);
"""


@dataclass(frozen=True)
class _Facts:
    """Capture exactly the inputs used by classification and fingerprinting.

    Missing fields can hide a real change, such as an upstream merge changing
    deps_done or a base update causing conflicts. Including timestamps or the
    latest comment ID would make an attempt stamp change its own fingerprint
    and repeatedly dispatch an agent. Keep the latest comment's authorship
    flag, which still distinguishes a new human response.
    """

    subject: str  # "issue:5" | "pr:12"
    pr_number: int | None  # None means the issue has no PR yet.
    head_sha: str | None
    merged: bool  # Terminal if the PR has merged.
    closed: bool  # Terminal if the subject is closed.
    labels: frozenset[str]  # Admission, terminal failure, and SHA-bound review labels.
    deps_done: bool  # Whether all blockers have closed.
    mergeable_state: str | None  # Normalized forge mergeability.
    ci: str  # Check state for the current head.
    e2e_head_sha: str | None  # Head SHA stamped on the latest e2e evidence comment.
    review_state: str | None  # Review verdict extracted from labels.
    review_commit_id: str | None  # Short SHA bound to the review verdict.
    latest_comment_is_ours: bool  # Use authorship, never the comment ID, in the fingerprint.
    is_draft: bool = False  # Spec-0017/T2: Promote draft PRs before evaluating mergeability.
    material_digest: str = ""  # issue title/body + human comments; machine diagnostics are excluded
    # Draft promotion changes the fingerprint only when it actually changes the PR state.


@dataclass(frozen=True)
class _Clock:
    """Hold timestamps used only by the watchdog.

    Do not hash timestamps: starting a check can change a timestamp without
    changing the branch table's inputs. Read progress from forge timestamps so
    restarts do not reset the observed age. A new head starts a new clock.
    """

    last_progress_at: datetime | None  # Latest head push, check start, comment, or attempt stamp.


@dataclass(frozen=True)
class _Observed:
    """Group immutable forge facts and watchdog timestamps.

    Keep these separate so the fingerprint and branch table can share the
    complete set of facts without hashing elapsed time.
    """

    facts: _Facts
    clock: _Clock


@dataclass(frozen=True)
class _Verdict:
    """Represent one of four states; only QUIET has a reason and ACTIONABLE an action."""

    kind: str  # _IN_FLIGHT | _TERMINAL | _QUIET | _ACTIONABLE
    reason: str | None = None  # Reason selects the watchdog threshold.
    action: str | None = None  # Action selects the worker handler and priority.


class _ActTimeout(RuntimeError):
    """Spec-0046/0065: single-call budget exhausted; retain existing bounded retry handling."""


@dataclass(frozen=True)
class _LabelTargetSnapshot:
    """Capture current labels on a forge object an agent action could touch."""

    kind: str
    number: int
    labels: frozenset[str]
    terminal: bool = False


def run_vigil(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    once: bool,
    concurrency: int = 1,
    agent_id: str = "",
    priority_fn: Callable[..., Any] | None = None,
    watchdog_thresholds: dict[str, int | None] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> None:
    """Run one or more cycles of graph-driven Vigil.
    Spec-0065/T2.

    The producer reconciles forge state on each tick, admits eligible issues,
    and enqueues actionable subjects without a matching attempt stamp.
    QUIET subjects go to the watchdog; IN_FLIGHT subjects can warn but cannot
    be reclaimed while their lock is held. Terminal subjects are skipped.
    Workers claim one subject atomically, hold its flock while reconciling,
    and delete its completed row before releasing the lock.

    SQLite serializes writes. Workers pull more work without waiting for a
    batch, so slow subjects do not hold idle slots. The default concurrency of
    one is serial. The queue lives in work_dir/.openagents/vigil-queue.db.

    With once=True, run one producer tick and drain the queue within the
    configured drain limit, including delayed conflict work that becomes
    available. Newly unblocked subjects that were not sensed this tick are
    left for the next invocation. In continuous mode, isolate tick errors and
    individual worker errors. Ctrl-C lets workers finish their current
    claims; queued rows persist. After a crash, reclaim abandoned claims
    when their flock becomes available, without relying on leases.

    Args:
        backend: Execution backend used by role invocations.
        state: Persistent progress and reconciliation state.
        work_dir: Repository containing the queue.
        config: Resolved stages, agents, base branch, labels, and poll interval.
        once: Run one tick and bounded drain instead of polling continuously.
        concurrency: Maximum number of resident workers.
        agent_id: Identity used for claims and signed comments.
        priority_fn: Override the default queue priority.
        watchdog_thresholds: Override QUIET watchdog limits by reason.
        now_fn: Clock override used by tests.

    Raises:
        Exception: A producer failure propagates in single-cycle mode.
    """
    resolved_priority = priority_fn or _priority_default
    resolved_now = now_fn or (lambda: datetime.now(UTC))
    thresholds = dict(_WATCHDOG_DEFAULTS) | (watchdog_thresholds or {})
    db_path = Path(work_dir) / ".openagents" / _QUEUE_DB_FILENAME
    _init_db(db_path=db_path)
    if config.coordination != "soft":
        preflight.cache_path(work_dir=Path(work_dir)).unlink(missing_ok=True)
    stop_event = threading.Event()

    workers = [
        threading.Thread(
            target=_worker_loop,
            kwargs={
                "db_path": db_path,
                "backend": backend,
                "state": state,
                "work_dir": Path(work_dir),
                "config": config,
                "agent_id": agent_id,
                "now_fn": resolved_now,
                "stop_event": stop_event,
                "worker_id": f"vigil-worker-{index}",
            },
            name=f"vigil-worker-{index}",
            daemon=True,
        )
        for index in range(max(1, concurrency))
    ]
    for worker in workers:
        worker.start()

    # Spec-0065/T2: Only the producer tracks continuously held locks. A restart can delay a
    # stalled-lock report by one threshold.
    seen_locked: dict[str, datetime] = {}
    try:
        while True:
            try:
                _producer_tick(
                    backend=backend,
                    state=state,
                    work_dir=Path(work_dir),
                    config=config,
                    agent_id=agent_id,
                    db_path=db_path,
                    priority_fn=resolved_priority,
                    thresholds=thresholds,
                    seen_locked=seen_locked,
                    now=resolved_now(),
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001 - Keep polling after a producer failure.
                if once:
                    raise
                _log(message=f"✗ Producer cycle failed; retrying in {config.interval}s: {exc}")
            if once:
                _drain_queue(  # Drain the queue so single-cycle callers can observe completion.
                    db_path=db_path,
                    work_dir=Path(work_dir),
                    seen_locked=seen_locked,
                    now_fn=resolved_now,
                    stop_event=stop_event,
                    agent_id=agent_id,
                )
                return
            _log(message=f"… Vigil will poll again in {config.interval}s (Ctrl-C to stop)")
            time.sleep(config.interval)
    except KeyboardInterrupt:
        _log(message="✓ Vigil stopped (Ctrl-C)")
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=_WORKER_POLL_SECONDS * 2)


def run_fleet(*, config: agent_config.AgentConfig, once: bool) -> None:
    """Run Vigil for each configured repository.

    Use separate processes for separate Git/forge working directories. Each
    repository may still use multiple subject workers within its own process.
    Run a single configured repository inline.
    """
    from openagents.utils import fleet as fleet_util

    if len(config.repos) == 1:
        repo = config.repos[0]
        _run_repo_inline(repo=repo, agents=config.agents, release=config.release, once=once)
        return
    fleet_util.Fleet(spawn=_default_spawn, queue_factory=fleet_util.default_queue).run(
        plans=config.repos, once=once
    )


# --------------------------------------------------------------------------------------------------
# Keep classification and fingerprinting pure over the same set of observed facts.
# --------------------------------------------------------------------------------------------------


def _sense(*, config: agent_config.AgentConfig, subject: str) -> _Observed:
    """Read the current forge state for one subject.

    Collect the facts used by classification and the timestamps used by the
    watchdog. Read checks for the current head only when mergeability is clean.
    An unknown or dirty merge state is not a CI wait, and zero checks are not
    success. Normalize configured skip stages here so the branch table does
    not need configuration. Resolve blockers from native dependency state.
    Keep this path free of policy judgments and avoid redundant forge reads.
    """
    kind, number = _split_subject(subject=subject)
    labels: set[str] = set()
    deps_done = True
    pr_number: int | None = None
    progress: list[str] = []
    material_parts: list[str] = []

    if kind == _KIND_ISSUE:
        issue = github.get_issue(number=number)
        material_parts.extend((str(issue.title), str(issue.body)))
        labels |= set(issue.labels)
        blockers = github.list_blocked_by(number=number)
        deps_done = all(blocker.state == "CLOSED" for blocker in blockers)
        # Read PRs in all states. Looking up only open PRs would redispatch work just after its PR
        # merges.
        pr = github.pr_for_branch(branch=f"{_BRANCH_PREFIX}{number}")
        pr_number = pr.number if pr is not None else None
    else:
        pr_number = number

    merged = False
    closed = False
    head_sha: str | None = None
    mergeable_state: str | None = None
    ci = _CI_NONE
    e2e_head_sha: str | None = None
    latest_comment_is_ours = True
    is_draft = False  # Spec-0017/T2: An issue without a PR is never a draft.

    if pr_number is not None:
        snapshot = github.pr_snapshot(pr_number=pr_number)
        labels |= set(snapshot.labels)
        merged = snapshot.state == "MERGED"
        closed = snapshot.state == "CLOSED"
        head_sha = snapshot.head_sha or None
        is_draft = (
            snapshot.is_draft
        )  # Read draft status in the same snapshot as head and mergeability.
        mergeable_state = _mergeable_state(snapshot=snapshot)
        progress.append(snapshot.head_pushed_at)
        if (
            mergeable_state == _MERGE_CLEAN
        ):  # Do not read checks while mergeability is unknown or dirty.
            checks = github.check_snapshot(pr_number=pr_number)
            ci = _ci_state(snapshot=checks)
            progress.append(checks.latest_started_at)
        comments = github.list_comments(pr_number=pr_number)
        material_parts.extend(
            comment.body
            for comment in comments
            if identity.parse_agent_id(body=comment.body) is None
        )
        e2e_head_sha = _latest_e2e_sha(comments=comments)
        latest_comment_is_ours = _latest_is_ours(comments=comments)
        progress.extend(comment.created_at for comment in comments)
    elif kind == _KIND_ISSUE:
        # Spec-0065/T2: Use issue comments for progress before a PR exists, including attempt
        # stamps. Without those timestamps the watchdog cannot detect an unchanged solve attempt.
        issue_comments = github.list_issue_comments(number=number)
        material_parts.extend(
            comment.body
            for comment in issue_comments
            if identity.parse_agent_id(body=comment.body) is None
        )
        progress.extend(comment.created_at for comment in issue_comments)
        # Spec-0016/T4: New human comments on admitted issues can be answered before a PR exists.
        # Unadmitted issues remain in triage.
        if _LABEL_READY in labels:
            latest_comment_is_ours = _latest_is_ours(comments=issue_comments)

    review_state, review_commit_id = _review_from_labels(labels=labels)

    owners = config.stages
    if owners.owner_of(stage=agent_config.STAGE_CI) == _SKIP:
        ci = _CI_SUCCESS
    if (
        config.flow in {agent_config.FLOW_MINIMAL, agent_config.FLOW_GENERATE_ONLY}
        or owners.owner_of(stage=agent_config.STAGE_E2E) == _SKIP
    ):
        e2e_head_sha = head_sha
    if owners.owner_of(stage=agent_config.STAGE_REVIEW) == _SKIP:
        review_state, review_commit_id = _REVIEW_APPROVED, _short(sha=head_sha)

    facts = _Facts(
        subject=subject,
        pr_number=pr_number,
        head_sha=head_sha,
        merged=merged,
        closed=closed,
        labels=frozenset(labels),
        deps_done=deps_done,
        mergeable_state=mergeable_state,
        ci=ci,
        e2e_head_sha=e2e_head_sha,
        review_state=review_state,
        review_commit_id=review_commit_id,
        latest_comment_is_ours=latest_comment_is_ours,
        is_draft=is_draft,
        material_digest=hashlib.sha256("\n\0\n".join(material_parts).encode()).hexdigest()[:16],
    )
    return _Observed(facts=facts, clock=_Clock(last_progress_at=_latest_ts(stamps=progress)))


def _classify(*, facts: _Facts, in_flight: bool) -> _Verdict:
    """Map facts to a reconciliation state or action.

    The producer first recognizes an active claim. Otherwise check terminal
    state, new human comments, blockers, and missing PRs, in that order.
    Promote draft PRs before checking mergeability: Gitea may report every
    draft as dirty, which would otherwise send it into conflict recovery.

    Resolve mergeability before reading CI. Check CI and evidence at the
    current head. Review labels only count for their recorded SHA; a changed
    head needs a new review. Merge only after these gates pass.

    Workers pass in_flight=False because they already hold the claim. A
    matching attempt stamp is applied by the producer outside this pure
    function, since finding it requires a forge read.
    """
    if in_flight:
        return _Verdict(kind=_IN_FLIGHT)
    if facts.merged or facts.closed or _LABEL_AUTOMATION_FAILED in facts.labels:
        return _Verdict(kind=_TERMINAL)
    if not facts.latest_comment_is_ours:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_REPLY)
    if not facts.deps_done:
        return _Verdict(kind=_QUIET, reason=_AWAITING_BLOCKERS)
    if facts.pr_number is None:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_SOLVE)
    # Promote drafts before checking mergeability. Gitea can report drafts as dirty, so conflict
    # handling first would prevent promotion.
    if facts.is_draft:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_READY)
    if facts.mergeable_state in (None, _MERGE_UNKNOWN):
        return _Verdict(kind=_QUIET, reason=_AWAITING_MERGEABILITY)
    if facts.mergeable_state == _MERGE_DIRTY:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_REBASE)
    if facts.ci in (_CI_PENDING, _CI_NONE):
        return _Verdict(kind=_QUIET, reason=_AWAITING_CI)
    if facts.ci == _CI_FAILURE:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_FIX_CI)
    if facts.e2e_head_sha != facts.head_sha:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_E2E)
    if facts.review_state != _REVIEW_APPROVED or facts.review_commit_id != _short(
        sha=facts.head_sha
    ):
        return _Verdict(kind=_ACTIONABLE, action=_ACT_REVIEW_OR_FIX)
    return _Verdict(kind=_ACTIONABLE, action=_ACT_MERGE)


def _implementation_pending(*, state: RuntimeState | None, facts: _Facts) -> bool:
    """Read the existing interrupted-development checkpoint (Spec-0089/T1)."""
    number = _issue_number_of(facts=facts)
    run = state.get_run(issue_number=number) if state is not None and number else None
    return bool(
        run
        and run.get("status") == STATUS_ITERATING
        and run.get("pr_number") == facts.pr_number
        and facts.pr_number is not None
    )


def _resume_verdict(*, state: RuntimeState | None, facts: _Facts, verdict: _Verdict) -> _Verdict:
    """Resume development before downstream checks, not before stop/reply/dependencies.

    Spec-0089/T1: reuse solve and run.status; no new stage, queue or forge label.
    """
    if (
        verdict.kind not in {_TERMINAL, _IN_FLIGHT}
        and verdict.action not in {_ACT_REPLY, _ACT_READY}
        and facts.deps_done
        and _implementation_pending(state=state, facts=facts)
    ):
        return _Verdict(kind=_ACTIONABLE, action=_ACT_SOLVE)
    return verdict


def _fingerprint(*, facts: _Facts) -> str:
    """Hash all classification facts in a deterministic order.

    An unchanged fingerprint means the branch table still sees the same
    state. Do not include attempt comment IDs or watchdog timestamps; those
    can change without progress and defeat the no-progress guard. Derive the
    input set from the dataclass fields so new facts are never omitted.
    """
    payload = {field.name: _stable(value=getattr(facts, field.name)) for field in fields(_Facts)}
    # Failure projection is an output of this fingerprint, never an input. Otherwise applying the
    # terminal label would immediately make its own marker stale and revive the subject every tick.
    payload["labels"] = _stable(value=facts.labels - {_LABEL_AUTOMATION_FAILED})
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _conflict_fingerprint(*, facts: _Facts, base: str, branch: str, reason: str = "") -> str:
    """Stable identity for one conflict episode; diagnostics do not churn the identity."""
    payload = {
        "subject": facts.subject,
        "pr_number": facts.pr_number,
        "head_sha": facts.head_sha or "",
        "mergeable_state": facts.mergeable_state or "",
        "base": base,
        "branch": branch,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _conflict_fp_from_reason(*, reason: str) -> str:
    match = _CONFLICT_FP_RE.search(reason)
    return match.group(1) if match else ""


def _phase_of(*, verdict: _Verdict, facts: _Facts) -> str:
    """Map classification to a phase label without reading the forge.
    Spec-0066/T2.
    """
    if verdict.kind == _IN_FLIGHT:
        return _IN_FLIGHT
    if verdict.kind == _TERMINAL:
        if facts.merged:
            return _PHASE_MERGED
        if facts.closed:
            return _PHASE_CLOSED
        return _PHASE_AUTOMATION_FAILED
    if verdict.kind == _QUIET:
        return verdict.reason or _QUIET
    return verdict.action or _ACTIONABLE


def _record_timing(
    *, work_dir: Path, subject: str, facts: _Facts, verdict: _Verdict, now: datetime
) -> None:
    """Record an advisory phase transition.
    Spec-0066/T2.

    Derive issue and PR references from the subject. Timing failures must
    not affect reconciliation, fingerprints, or return values.
    """
    try:
        kind, number = _split_subject(subject=subject)
        issue = number if kind == _KIND_ISSUE else None
        pr = number if kind == _KIND_PR else facts.pr_number
        timing.record(
            work_dir=Path(work_dir),
            subject=subject,
            issue=issue,
            pr=pr,
            phase=_phase_of(verdict=verdict, facts=facts),
            now=now,
        )
    except Exception:  # noqa: BLE001 - Timing is advisory and must not interrupt reconciliation.
        return


def _watchdog(
    *, verdict: _Verdict, clock: _Clock, thresholds: dict[str, int | None], now: datetime
) -> bool:
    """Return whether a QUIET subject exceeded its reason-specific threshold.

    Measure age from the latest forge progress timestamp, not local polling
    history. A disabled threshold or missing timestamp does not park the
    subject. Active claims are handled separately and never reclaimed by age.
    """
    if verdict.kind != _QUIET:
        return False
    threshold = thresholds.get(verdict.reason or "")
    if threshold is None or clock.last_progress_at is None:
        return False
    return (now - clock.last_progress_at).total_seconds() > threshold


# --------------------------------------------------------------------------------------------------
# Pure normalization of forge facts, comments, and labels.
# --------------------------------------------------------------------------------------------------


def _split_subject(*, subject: str) -> tuple[str, int]:
    """Parse a subject such as issue:5 or pr:12 into its kind and number."""
    kind, _, raw = subject.partition(":")
    if kind not in (_KIND_ISSUE, _KIND_PR) or not raw.isdigit():
        raise ValueError(f"Invalid subject {subject!r}; expected issue:5 or pr:12")
    return kind, int(raw)


def _mergeable_state(*, snapshot: github.PRSnapshot) -> str:
    """Normalize forge mergeability.

    Treat BEHIND like a conflict: update the branch before checking CI for
    the resulting head. Keep uncomputed mergeability separate.
    """
    if snapshot.mergeable == "CONFLICTING" or snapshot.merge_state_status in ("DIRTY", "BEHIND"):
        return _MERGE_DIRTY
    if snapshot.mergeable == "MERGEABLE":
        return _MERGE_CLEAN
    return _MERGE_UNKNOWN


def _ci_state(*, snapshot: github.CheckSnapshot) -> str:
    """Normalize check results for the current head.

    Zero checks mean none, not success. This keeps unstarted workflows in
    the waiting state until checks appear or the watchdog reports the wait.
    """
    if snapshot.count == 0:
        return _CI_NONE
    if snapshot.state == "fail":
        return _CI_FAILURE
    if snapshot.state == "pending":
        return _CI_PENDING
    return _CI_SUCCESS


def _latest_e2e_sha(*, comments: list[github.Comment]) -> str | None:
    """Read the latest e2e evidence stamp, or return None if absent."""
    stamped = [comment for comment in comments if _E2E_MARKER in comment.body]
    if not stamped:
        return None
    latest = max(stamped, key=lambda comment: comment.created_at)
    tail = latest.body.split(_E2E_MARKER, 1)[1]
    return tail.split("-->", 1)[0].strip() or None


def _latest_is_ours(*, comments: list[github.Comment]) -> bool:
    """Return whether the latest comment is signed by this agent or absent."""
    if not comments:
        return True
    latest = max(comments, key=lambda comment: comment.created_at)
    return identity.parse_agent_id(body=latest.body) is not None


def _review_from_labels(*, labels: set[str]) -> tuple[str | None, str | None]:
    """Read a review decision bound to a specific head.

    Bare approval labels do not count. If both kinds of decision are present,
    a request for changes takes precedence.
    """
    changes = _label_sha(labels=labels, prefix=_LABEL_REVIEW_CHANGES_PREFIX)
    if changes is not None:
        return _REVIEW_CHANGES_REQUESTED, changes
    approved = _label_sha(labels=labels, prefix=_LABEL_REVIEW_APPROVED_PREFIX)
    if approved is not None:
        return _REVIEW_APPROVED, approved
    return None, None


def _label_sha(*, labels: set[str], prefix: str) -> str | None:
    """Read the short SHA from a matching label, rejecting an empty suffix."""
    for label in sorted(labels):
        if label.startswith(prefix):
            sha = label[len(prefix) :].strip()
            if sha:
                return sha
    return None


def _short(*, sha: str | None) -> str | None:
    """Shorten a head SHA to the label length, preserving None."""
    return None if sha is None else sha[:_SHA_LABEL_LEN]


def _stable(*, value: Any) -> Any:
    """Serialize fingerprint values deterministically by sorting sets."""
    if isinstance(value, frozenset):
        return sorted(value)
    return value


def _latest_ts(*, stamps: list[str]) -> datetime | None:
    """Return the latest valid forge timestamp, or None."""
    parsed = [moment for stamp in stamps if (moment := _parse_ts(stamp=stamp)) is not None]
    return max(parsed) if parsed else None


def _parse_ts(*, stamp: str) -> datetime | None:
    """Parse an aware ISO 8601 timestamp; return None for invalid input."""
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------------
# SQLite queue and flock ownership.
# --------------------------------------------------------------------------------------------------


def _init_db(*, db_path: Path) -> None:
    """Initialize the queue, enable WAL, and create the claim-lock directory.

    The queue lives beside runtime-state.json. WAL allows concurrent readers
    while a writer holds the transaction.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    (db_path.parent / _CLAIMS_DIRNAME).mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path=db_path)
    try:
        conn.executescript(_SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(work_queue)")}
        if "action" not in columns:
            conn.execute("ALTER TABLE work_queue ADD COLUMN action TEXT NOT NULL DEFAULT ''")
        if "available_at" not in columns:
            conn.execute("ALTER TABLE work_queue ADD COLUMN available_at TEXT NOT NULL DEFAULT ''")
        if "conflict_fp" not in columns:
            conn.execute("ALTER TABLE work_queue ADD COLUMN conflict_fp TEXT NOT NULL DEFAULT ''")
        if "conflict_attempts" not in columns:
            conn.execute(
                "ALTER TABLE work_queue ADD COLUMN conflict_attempts INTEGER NOT NULL DEFAULT 0"
            )
    finally:
        conn.close()


def _connect(*, db_path: Path) -> sqlite3.Connection:
    """Open a connection private to the current thread.

    The busy timeout bounds waits for SQLite's single writer. The producer and
    each worker use their own connections.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _enqueue(
    *,
    conn: sqlite3.Connection,
    subject: str,
    priority: int,
    now: datetime,
    action: str = "",
) -> bool:
    """Insert a subject unless a queue row already exists.

    The unique subject key makes repeat observations idempotent. Priority
    and availability are applied when a worker claims the entry.
    """
    existing = conn.execute(
        "SELECT id, status, priority, action, conflict_fp, conflict_attempts "
        "FROM work_queue WHERE subject=?",
        (subject,),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT OR IGNORE INTO work_queue "
            "(subject, priority, action, enqueued_at, available_at, conflict_fp, conflict_attempts, status) "
            "VALUES (?, ?, ?, ?, ?, '', 0, 'queued')",
            (subject, priority, action, now.isoformat(), ""),
        )
        return True
    if existing["status"] == "queued" and (
        existing["priority"] != priority or existing["action"] != action
    ):
        conn.execute(
            "UPDATE work_queue "
            "SET priority=?, action=?, "
            "    available_at=CASE WHEN action<>? THEN '' ELSE available_at END, "
            "    conflict_fp=CASE WHEN action<>? THEN '' ELSE conflict_fp END, "
            "    conflict_attempts=CASE WHEN action<>? THEN 0 ELSE conflict_attempts END "
            "WHERE id=? AND status='queued'",
            (priority, action, action, action, action, existing["id"]),
        )
    return False


def _claim_next(
    *,
    conn: sqlite3.Connection,
    work_dir: Path,
    worker_id: str,
    now: datetime,
) -> tuple[dict, int] | None:
    """Atomically claim the next eligible subject and hold its flock.

    Select a queued row by priority and enqueue time, skipping delayed work
    and locks still held by another process. Serialize row changes with
    BEGIN IMMEDIATE. Return the row and its open lock descriptor, or None.
    The caller must keep the descriptor open until the row is finished.
    """
    advice = preflight.hints(data=preflight.read(work_dir=work_dir))
    # Spec-0091: bounded soft selection stays inside the original claim/flock transaction.
    skipped: list[int] = []
    while True:
        placeholders = ",".join("?" * len(skipped))
        exclude = f" AND id NOT IN ({placeholders})" if skipped else ""
        conn.execute("BEGIN IMMEDIATE")
        fd: int | None = None
        try:
            eligible_rows = conn.execute(
                "SELECT id FROM work_queue "
                "WHERE status='queued' AND (available_at='' OR available_at<=?)"
                f"{exclude} ORDER BY priority DESC, enqueued_at ASC, id ASC "
                f"LIMIT {128 if advice else 1}",
                [now.isoformat(), *skipped],
            ).fetchall()
            selected = preflight.select(
                conn=conn,
                advice=advice,
                eligible=[int(row["id"]) for row in eligible_rows],
                now=now,
            )
            row = conn.execute(
                "UPDATE work_queue "
                "SET status='claimed', worker=?, worker_pid=?, claimed_at=?, attempts=attempts+1 "
                "WHERE id=? AND status='queued' RETURNING *",
                (worker_id, os.getpid(), now.isoformat(), selected),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            fd = _try_lock(path=_lock_path(work_dir=work_dir, subject=row["subject"]))
            if fd is None:
                # Skip a temporarily locked row rather than treating the entire queue as empty.
                # This avoids head-of-line blocking without duplicating work.
                conn.execute("ROLLBACK")
                skipped.append(int(row["id"]))
                continue
            conn.execute("COMMIT")
            return dict(row), fd
        except BaseException:
            # If the claim transaction does not commit, close the descriptor or it can permanently
            # block the queued row.
            if fd is not None:
                _close_quietly(fd=fd)
            conn.execute("ROLLBACK")
            raise


def _reclaim_dead(*, conn: sqlite3.Connection, work_dir: Path) -> int:
    """Return abandoned claims to the queue after acquiring their locks.

    An acquirable flock proves no live holder remains. Do not use age or PID
    as a liveness check. A live subprocess can inherit the lock and prevent
    duplicate delivery even when the parent has exited.
    """
    rows = conn.execute("SELECT id, subject FROM work_queue WHERE status='claimed'").fetchall()
    reclaimed = 0
    for row in rows:
        fd = _try_lock(path=_lock_path(work_dir=work_dir, subject=row["subject"]))
        if fd is None:
            continue  # A live owner may be slow. Leave its claim intact.
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE work_queue "
                "   SET status='queued', worker=NULL, worker_pid=NULL, claimed_at=NULL "
                " WHERE id=? AND status='claimed'",
                (row["id"],),
            )
            conn.execute("COMMIT")
            if cursor.rowcount:  # The owner may have completed and deleted the row after selection.
                reclaimed += 1
                _log(
                    message=f"♻ Reclaimed {row['subject']}: the former owner no longer holds the lock"
                )
        finally:
            os.close(fd)
    return reclaimed


def _sweep_stalled(
    *,
    conn: sqlite3.Connection,
    work_dir: Path,
    seen_locked: dict[str, datetime],
    now: datetime,
    agent_id: str,
    config: agent_config.AgentConfig | None = None,
) -> int:
    """Detect queued rows whose locks remain unexpectedly held.

    A queued row should be available. Track how long its lock stays held
    across observations; a short handoff is normal. A persistent lock can
    belong to a leaked descendant. Report it as an automation failure
    without stealing the lock or terminating an unverified process.
    """
    rows = conn.execute("SELECT id, subject FROM work_queue WHERE status='queued'").fetchall()
    parked = 0
    still_locked: set[str] = set()
    for row in rows:
        subject = row["subject"]
        path = _lock_path(work_dir=work_dir, subject=subject)
        fd = _try_lock(path=path)
        if fd is not None:
            os.close(fd)  # A free lock is a normal queued item waiting for a worker.
            continue
        still_locked.add(subject)
        first = seen_locked.setdefault(subject, now)
        held_seconds = (now - first).total_seconds()
        if held_seconds <= _STALE_LOCK_SECONDS:
            continue  # Allow the handoff window; check again next tick.
        try:
            parked += _park_stalled(
                conn=conn,
                task_id=int(row["id"]),
                subject=subject,
                path=path,
                held=held_seconds,
                agent_id=agent_id,
                config=config,
            )
        except Exception as exc:  # noqa: BLE001 - Isolate a failed stall report from the producer cycle.
            # Intake reconstructs the next attempt from the forge if row removal or reporting
            # fails.
            _log(
                message=f"✗ {subject}: Could not record the automation failure; intake will re-evaluate next cycle: {exc}"
            )
    for subject in set(seen_locked) - still_locked:
        seen_locked.pop(
            subject, None
        )  # Forget the timestamp once the lock is released or the row is gone.
    return parked


def _park_stalled(
    *,
    conn: sqlite3.Connection,
    task_id: int,
    subject: str,
    path: Path,
    held: float,
    agent_id: str,
    config: agent_config.AgentConfig | None = None,
) -> int:
    """Remove a stalled queued row before recording its failure.

    Delete only if it is still queued. If another worker claimed or removed
    it, do not post a competing failure report.
    """
    conn.execute("BEGIN IMMEDIATE")  # Serialize with worker claims; do not act on a stale SELECT.
    try:
        cur = conn.execute("DELETE FROM work_queue WHERE id=? AND status='queued'", (task_id,))
        won = cur.rowcount == 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    if not won:
        # A worker acquired the row before removal. Leave its claim alone.
        return 0
    _fail_automation(
        subject=subject,
        facts=_failure_facts(subject=subject, config=config),
        category="stale_lock",
        attempts=0,
        reason=(
            f"`{subject}`  is queued, but its claim lock `{path}` has been held for more than "
            f"{int(held)}s without an active worker. The entry cannot be claimed.\n\n"
            "A subprocess left by the last agent invocation may still hold the inherited lock (for example, an MCP or development server). "
            f"Check it with `lsof {path}`."
        ),
        agent_id=agent_id,
    )
    _log(message=f"⏸ {subject}: Queued item still has a held lock; recorded an automation failure")
    return 1


def _mark_done(*, conn: sqlite3.Connection, task_id: int, fd: int) -> None:
    """Delete a completed queue row before releasing its claim lock.

    Releasing first would let the producer reclaim a row whose worker was
    still finishing. The descriptor is closed by the finalization path.
    """
    try:
        conn.execute("DELETE FROM work_queue WHERE id=?", (task_id,))
    finally:
        os.close(fd)


def _requeue_or_park(
    *,
    conn: sqlite3.Connection,
    task_id: int,
    subject: str,
    fd: int,
    agent_id: str,
    config: agent_config.AgentConfig | None = None,
    reason: str = "",
) -> None:
    """Reschedule an unfinished claim or record a terminal failure.

    Ordinary failures are bounded by claim attempts. Conflict failures use
    their own fingerprint, episode counter, and delayed availability. Update
    the queue while the current claim is held.
    """
    try:
        row = conn.execute(
            "SELECT attempts, conflict_fp, conflict_attempts FROM work_queue WHERE id=?",
            (task_id,),
        ).fetchone()
        attempts = int(row["attempts"]) if row is not None else _MAX_ATTEMPTS
        if reason.startswith(_CONFLICT_RETRY_PREFIX) and attempts >= _MAX_ATTEMPTS:
            conflict_fp = _conflict_fp_from_reason(reason=reason) or (
                str(row["conflict_fp"]) if row is not None else ""
            )
            conflict_fp = conflict_fp or f"subject:{subject}"
            previous_fp = str(row["conflict_fp"]) if row is not None else ""
            previous_episodes = int(row["conflict_attempts"]) if row is not None else 0
            episodes = previous_episodes + 1 if conflict_fp == previous_fp else 1
            if episodes >= _CONFLICT_EPISODE_LIMIT:
                facts = _failure_facts(subject=subject, config=config)
                _fail_automation(
                    subject=subject,
                    facts=facts,
                    category="conflict_episode_exhausted",
                    attempts=episodes,
                    reason=(
                        f"Conflict {conflict_fp} did not resolve after {episodes} automatic recovery episodes. "
                        f"Last error: {reason}"
                    ),
                    agent_id=agent_id,
                    projection_fp=conflict_fp if config is not None else None,
                )
                conn.execute("DELETE FROM work_queue WHERE id=?", (task_id,))
                return
            delay = min(
                _CONFLICT_RETRY_MAX_DELAY_SECONDS,
                _CONFLICT_RETRY_DELAY_SECONDS * (2 ** (episodes - 1)),
            )
            retry_at = datetime.now(UTC) + timedelta(seconds=delay)
            conn.execute(
                "UPDATE work_queue "
                "   SET status='queued', worker=NULL, worker_pid=NULL, claimed_at=NULL, "
                "       attempts=0, available_at=?, conflict_fp=?, conflict_attempts=? WHERE id=?",
                (retry_at.isoformat(), conflict_fp, episodes, task_id),
            )
            _log(
                message=(
                    f"↻ {subject}: conflict recovery episode {episodes}/{_CONFLICT_EPISODE_LIMIT} incomplete; "
                    f"{delay}s before retrying without marking an automation failure ({reason}）"
                )
            )
            return
        if attempts < _MAX_ATTEMPTS:
            conn.execute(
                "UPDATE work_queue "
                "   SET status='queued', worker=NULL, worker_pid=NULL, claimed_at=NULL WHERE id=?",
                (task_id,),
            )
            _log(message=f"↻ {subject}: claim attempt {attempts} did not finish; requeued")
            return
        facts = _failure_facts(subject=subject, config=config)
        _fail_automation(
            subject=subject,
            facts=facts,
            category="retry_exhausted",
            attempts=attempts,
            reason=reason
            or "Claim attempts repeatedly failed to finish: the agent crashed, was killed, returned invalid output, or timed out",
            agent_id=agent_id,
        )
        conn.execute("DELETE FROM work_queue WHERE id=?", (task_id,))
    finally:
        os.close(fd)


def _drain_queue(
    *,
    db_path: Path,
    work_dir: Path,
    seen_locked: dict[str, datetime],
    now_fn: Callable[[], datetime],
    stop_event: threading.Event,
    agent_id: str,
) -> None:
    """Wait for queued and claimed rows in single-cycle mode.

    Honor delayed retries and the drain time limit. This is a bounded
    synchronization point, not the source of delivery truth.
    """
    conn = _connect(db_path=db_path)
    deadline = time.monotonic() + _DRAIN_MAX_SECONDS
    try:
        while not stop_event.is_set():
            now = now_fn()
            pending = conn.execute("SELECT COUNT(*) AS n FROM work_queue").fetchone()["n"]
            if not pending:
                return
            if time.monotonic() >= deadline:
                _log(
                    message=f"⏱ Drain timed out after {_DRAIN_MAX_SECONDS}s with {pending} entries still pending"
                )
                return
            due = conn.execute(
                "SELECT COUNT(*) AS n FROM work_queue "
                "WHERE status='claimed' OR (status='queued' "
                "AND (available_at='' OR available_at<=?))",
                (now.isoformat(),),
            ).fetchone()["n"]
            if not due:
                next_at = conn.execute(
                    "SELECT MIN(available_at) AS next_at FROM work_queue "
                    "WHERE status='queued' AND available_at<>'' AND available_at>?",
                    (now.isoformat(),),
                ).fetchone()["next_at"]
                try:
                    wait_seconds = max(0.0, (datetime.fromisoformat(next_at) - now).total_seconds())
                except (TypeError, ValueError):
                    wait_seconds = _WORKER_POLL_SECONDS
                stop_event.wait(min(_WORKER_POLL_SECONDS, wait_seconds))
                continue
            # Check for stalled queued locks while draining as well as on producer ticks. A failed
            # scan should not stop the drain from observing other work.
            try:
                _sweep_stalled(
                    conn=conn,
                    work_dir=Path(work_dir),
                    seen_locked=seen_locked,
                    now=now_fn(),
                    agent_id=agent_id,
                )
            except Exception as exc:  # noqa: BLE001
                _log(message=f"✗ Could not check for stale locks while draining; continuing: {exc}")
            stop_event.wait(_WORKER_POLL_SECONDS)
    finally:
        conn.close()


def _lock_path(*, work_dir: Path, subject: str) -> Path:
    """Build a filesystem-safe claim path; liveness belongs to the kernel lock."""
    return Path(work_dir) / ".openagents" / _CLAIMS_DIRNAME / f"{subject.replace(':', '-')}.lock"


def _try_lock(*, path: Path) -> int | None:
    """Try a nonblocking exclusive flock.

    Return the open descriptor on success. The caller closes it. A lock
    held by another owner returns None; other errors propagate.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        raise
    return fd


# --------------------------------------------------------------------------------------------------
# Producer: recover claims, admit issues, classify, enqueue, and check wait thresholds.
# --------------------------------------------------------------------------------------------------


def _producer_tick(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    agent_id: str,
    db_path: Path,
    priority_fn: Callable[..., Any],
    thresholds: dict[str, int | None],
    seen_locked: dict[str, datetime],
    now: datetime,
) -> int:
    """Run one producer cycle without claiming work.

    Reclaim abandoned rows, check stalled locks, admit issues, and read
    the current state of each subject. Enqueue actionable subjects, report
    quiet subjects through the watchdog, and return the new row count.
    """
    from openagents.observations.gaps import sweep_async

    sweep_async(work_dir=Path(work_dir))
    conn = _connect(db_path=db_path)
    try:
        _reclaim_dead(conn=conn, work_dir=Path(work_dir))
        _sweep_stalled(
            conn=conn,
            work_dir=Path(work_dir),
            seen_locked=seen_locked,
            now=now,
            agent_id=agent_id,
            config=config,
        )
        _intake(
            backend=backend,
            work_dir=Path(work_dir),
            config=config,
            agent_id=agent_id,
            now=now,
        )

        in_flight = {
            row["subject"]: row["claimed_at"]
            for row in conn.execute(
                "SELECT subject, claimed_at FROM work_queue WHERE status='claimed'"
            ).fetchall()
        }
        enqueued = 0
        quiet_counts: dict[str, int] = {}
        subjects = _subjects(config=config)
        if config.coordination == "soft":
            subjects = preflight.discovery_order(work_dir=Path(work_dir), subjects=subjects)
        for subject in subjects:
            try:
                enqueued += _consider(
                    conn=conn,
                    state=state,
                    subject=subject,
                    config=config,
                    work_dir=Path(work_dir),
                    in_flight=in_flight,
                    priority_fn=priority_fn,
                    thresholds=thresholds,
                    quiet_counts=quiet_counts,
                    now=now,
                    agent_id=agent_id,
                )
            except Exception as exc:  # noqa: BLE001 - Isolate one subject's observation failure.
                _log(
                    message=f"✗ {subject}: Could not read current state; skipped this cycle: {exc}"
                )
        if enqueued == 0:
            _hang(
                quiet_counts=quiet_counts,
                in_flight_count=len(in_flight),
                interval=config.interval,
            )
        return enqueued
    finally:
        conn.close()


def _refresh_failure_projection(
    *, observed: _Observed, subject: str, base: str | None = None
) -> _Observed:
    """Revive only on proven fact changes on the failure's own object (Spec-0088/T2)."""
    facts = observed.facts
    if _LABEL_AUTOMATION_FAILED not in facts.labels:
        return observed
    current_fp = _fingerprint(facts=facts)
    recorded = None
    category = ""
    for comment in reversed(_failure_comments(subject=subject)):
        if (
            _FAILURE_MARKER in comment.body
            and identity.parse_agent_id(body=comment.body) is not None
        ):
            match = re.search(
                r"<!-- openagents:automation-failed fp=([0-9a-f]{16}) category=([^\s<>]+) -->",
                comment.body,
            )
            recorded = match.group(1) if match else None
            category = match.group(2) if match else ""
            # Spec-0088/T2: a broken latest marker cannot fall back to an obsolete failure.
            break
    if category == "conflict_episode_exhausted" and base is not None:
        try:
            branch = github.pr_head_branch(pr_number=facts.pr_number or 0)
            current_fp = _conflict_fingerprint(facts=facts, base=base, branch=branch)
        except Exception as exc:  # noqa: BLE001 - failure projection is fail-closed
            _log(
                message=f"⚠ {subject}: Could not reread the conflict branch; keeping the terminal failure: {exc}"
            )
            return observed
    if recorded == current_fp:
        return observed
    if recorded is None:
        _log(
            message=f"⚠ {subject}: Failure marker missing or invalid; keeping the terminal failure without a retry"
        )
        return observed
    _remove_automation_failed(subject=subject)
    _log(message=f"⟳ {subject}: State fingerprint changed ({recorded} → {current_fp}); resuming")
    return replace(
        observed,
        facts=replace(facts, labels=facts.labels - {_LABEL_AUTOMATION_FAILED}),
    )


def _remove_automation_failed(*, subject: str) -> None:
    """Idempotently clear the stale machine-failure projection from its forge object."""
    kind, number = _split_subject(subject=subject)
    if kind == _KIND_ISSUE:
        github.issue_remove_label(number=number, name=_LABEL_AUTOMATION_FAILED)
    else:
        github.remove_label(pr_number=number, name=_LABEL_AUTOMATION_FAILED)


def _failure_facts(*, subject: str, config: agent_config.AgentConfig | None = None) -> _Facts:
    """Read the same canonical facts used by classification before persisting a failure marker."""
    return _sense(config=config or agent_config.default_config(), subject=subject).facts


def _consider(
    *,
    conn: sqlite3.Connection,
    state: RuntimeState | None,
    subject: str,
    config: agent_config.AgentConfig,
    work_dir: Path,
    in_flight: dict[str, Any],
    priority_fn: Callable[..., Any],
    thresholds: dict[str, int | None],
    quiet_counts: dict[str, int],
    now: datetime,
    agent_id: str,
) -> int:
    """Observe and classify one subject, then enqueue, park, or skip it.

    A matching attempt stamp suppresses another call for unchanged facts.
    Return one only when a new queue row is inserted.
    """
    observed = _sense(config=config, subject=subject)
    # Clear a stale failure after observing facts and before classification. Remove it from the
    # same tick's facts so an eligible action can resume immediately.
    observed = _refresh_failure_projection(observed=observed, subject=subject, base=config.base)
    verdict = _classify(facts=observed.facts, in_flight=subject in in_flight)
    verdict = _resume_verdict(state=state, facts=observed.facts, verdict=verdict)
    fp = _fingerprint(facts=observed.facts)

    if (
        verdict.kind == _ACTIONABLE
        and not _implementation_pending(state=state, facts=observed.facts)
        and _has_attempt_stamp(facts=observed.facts, fp=fp)
    ):
        # A matching attempt stamp suppresses another agent call for unchanged facts.
        verdict = _Verdict(kind=_QUIET, reason=_AWAITING_EFFECT)

    # Spec-0066/T2: Record producer phases without changing control flow or fingerprints.
    _record_timing(
        work_dir=work_dir, subject=subject, facts=observed.facts, verdict=verdict, now=now
    )

    if verdict.kind == _IN_FLIGHT:
        # A live holder is telemetry only: terminal projection here could race a healthy worker.
        claimed_at = _parse_ts(stamp=str(in_flight.get(subject) or ""))
        if claimed_at is not None and (now - claimed_at).total_seconds() > _INFLIGHT_ALARM_SECONDS:
            _log(
                message=f"⚠ {subject}: Claim exceeded its warning threshold but still holds the lock; leaving it active"
            )
        return 0
    if verdict.kind == _TERMINAL:
        return 0

    if verdict.kind == _ACTIONABLE:
        # Spec-0093/T2: persist required independently before publishing queue work.
        number = _issue_number_of(facts=observed.facts)
        if number and isinstance(state, RuntimeState):
            state.execution_requirement(
                issue_number=number, required=config.execution_evidence_required
            )
        if _enqueue(
            conn=conn,
            subject=subject,
            priority=priority_fn(verdict=verdict),
            now=now,
            action=verdict.action or "",
        ):
            _log(message=f"⊕ {subject}: queued {verdict.action}")
            return 1
        return 0

    quiet_counts[verdict.reason or ""] = quiet_counts.get(verdict.reason or "", 0) + 1
    if _watchdog(verdict=verdict, clock=observed.clock, thresholds=thresholds, now=now):
        # Check ownership again before parking. A worker may claim the subject during the forge
        # reads after the initial snapshot.
        if _is_claimed(conn=conn, subject=subject):
            return 0
        _park(
            facts=observed.facts,
            verdict=verdict,
            clock=observed.clock,
            now=now,
            agent_id=agent_id,
        )
    return 0


def _is_claimed(*, conn: sqlite3.Connection, subject: str) -> bool:
    """Read whether a worker currently owns the subject."""
    row = conn.execute(
        "SELECT 1 FROM work_queue WHERE subject=? AND status='claimed'", (subject,)
    ).fetchone()
    return row is not None


def _subjects(*, config: agent_config.AgentConfig) -> list[str]:
    """List ready open issues and standalone open PRs.

    Avoid scheduling the same PR through both its issue and a standalone
    subject.
    """
    subjects: list[str] = []
    for issue in github.list_issues(labels=[_LABEL_READY]):
        subjects.append(f"{_KIND_ISSUE}:{issue.number}")
    for pr in github.list_open_prs():
        branch = github.pr_head_branch(pr_number=pr.number)
        if branch.startswith(_BRANCH_PREFIX):
            continue  # The linked issue already owns this PR's lifecycle.
        subjects.append(f"{_KIND_PR}:{pr.number}")
    return subjects


def _intake(
    *,
    backend: Any,
    work_dir: Path,
    config: agent_config.AgentConfig,
    agent_id: str,
    now: datetime,
) -> None:
    """Admit new issues and coordinate their dependencies.

    Apply the configured admission gate and readiness label first. Depending
    on the coordination mode, ask the Curator for hard dependencies, collect
    advisory ordering, or use only existing forge facts.
    """
    github.ensure_label(name=_LABEL_READY, description="OpenAgents Vigil: issue admitted")
    owner = config.stages.owner_of(stage=agent_config.STAGE_TRIAGE)
    # Spec-0065/T2: Bound triage and Curator calls in the producer thread. A stalled producer
    # would stop recovery and prevent single-cycle draining.
    timed = _TimedBackend(inner=backend, timeout_seconds=effective_max_wall(), lock_fd=None)
    admitted = 0
    # Spec-0035/T4: Report discovery before the potentially slow forge request.
    _log(message="▶ Discovering issues with the configured labels…")
    for issue in github.list_issues(labels=config.labels):
        if _LABEL_READY in issue.labels or _LABEL_AUTOMATION_FAILED in issue.labels:
            continue
        try:
            admitted += _admit(
                owner=owner,
                config=config,
                backend=timed,
                work_dir=Path(work_dir),
                issue=issue,
                agent_id=agent_id,
                discovery_labels=tuple(config.labels),
            )
        except Exception as exc:  # noqa: BLE001 - One failed admission must not stop the cycle.
            _log(message=f"✗ issue #{issue.number} admission failed; skipped: {exc}")
    if config.coordination == "soft":
        # Spec-0091: revisit changed snapshots after cooldown even with no new admissions.
        try:
            ready = [
                issue
                for issue in github.list_issues(labels=[_LABEL_READY])
                if _LABEL_AUTOMATION_FAILED not in issue.labels
            ]
            status = preflight.refresh(
                work_dir=Path(work_dir),
                issues=ready,
                backend=_TimedBackend(
                    inner=backend.for_advisory() if hasattr(backend, "for_advisory") else backend,
                    timeout_seconds=preflight.WALL_SECONDS,
                    lock_fd=None,
                ),
                now=time.time(),
            )
            _log(message=f"⇢ advisory preflight: {status}")
        except Exception as exc:
            _log(message=f"↷ advisory preflight unavailable: {type(exc).__name__}; using queue")
    elif admitted and config.coordination != "off":
        _order_edges(backend=timed, work_dir=Path(work_dir), config=config, agent_id=agent_id)


def _admit(
    *,
    owner: str,
    config: agent_config.AgentConfig,
    backend: Any,
    work_dir: Path,
    issue: Any,
    agent_id: str,
    discovery_labels: tuple[str, ...],
) -> int:
    """Admit an issue by configuration or triage, or record a terminal refusal."""

    def _on_agent() -> int:
        # Spec-0035/T4: Report triage before the model call.
        _log(message=f"… issue #{issue.number} triaging with the model…")
        verdict = stages.triage(backend=backend, work_dir=work_dir, issue=issue)
        if verdict["actionable"]:
            return _grant_ready(issue=issue, discovery_labels=discovery_labels)
        facts = _sense(config=config, subject=f"{_KIND_ISSUE}:{issue.number}").facts
        _fail_automation(
            subject=f"{_KIND_ISSUE}:{issue.number}",
            facts=facts,
            category="triage_rejected",
            attempts=1,
            reason=verdict["reason"],
            agent_id=agent_id,
        )
        return 0

    return route(
        owner=owner,
        on_agent=_on_agent,
        on_skip=lambda: _grant_ready(issue=issue, discovery_labels=discovery_labels),
    )


def _grant_ready(*, issue: Any, discovery_labels: tuple[str, ...]) -> int:
    """Reread discovery labels immediately before granting readiness.
    Spec-0074/T1.

    This closes the race where an operator removes the discovery label
    after enumeration but before admission.
    """
    latest = github.get_issue(number=issue.number)
    if _LABEL_READY in latest.labels or _LABEL_AUTOMATION_FAILED in latest.labels:
        return 0
    if discovery_labels and set(discovery_labels).isdisjoint(latest.labels):
        _log(message=f"↷ issue #{issue.number}：discovery label was removed; admission canceled")
        return 0
    github.issue_add_label(number=latest.number, name=_LABEL_READY)
    _log(message=f"✓ issue #{issue.number}：admitted and labeled {_LABEL_READY}")
    return 1


def _order_edges(
    *, backend: Any, work_dir: Path, config: agent_config.AgentConfig, agent_id: str
) -> None:
    """Propose and validate only new blocking edges.

    Preserve existing dependencies as anchors. Reject cycles or unknown
    issues before posting any edges.
    """
    ready = github.list_issues(labels=[_LABEL_READY])
    if len(ready) < 2:
        return  # Fewer than two nodes cannot have a dependency edge.
    known = {issue.number for issue in ready}
    existing = {issue.number: _blocker_numbers(number=issue.number) for issue in ready}

    snapshot = "\n".join(f"- #{issue.number}「{issue.title}」：{issue.body}" for issue in ready)
    anchors = json.dumps(
        [
            {"issue": number, "blocked_by": blockers}
            for number, blockers in sorted(existing.items())
            if blockers
        ],
        ensure_ascii=False,
    )
    payload = engine.run_agent(
        curator,
        backend=backend,
        work_dir=Path(work_dir),
        context=context.sections(("ready issues", snapshot), ("existing edges", anchors)),
    )
    proposed = _proposed_edges(
        edges=payload["edges"],
        known=known,
        existing=existing,
        config=config,
        agent_id=agent_id,
    )
    if proposed is None:
        return
    for issue_number, blocker in proposed:
        github.add_blocked_by(number=issue_number, blocker_number=blocker)
        _log(message=f"⇢ Dependency: #{issue_number} blocked_by #{blocker}")


def _blocker_numbers(*, number: int) -> list[int]:
    """Read existing blocker issue numbers as read-only anchors."""
    return [blocker.number for blocker in github.list_blocked_by(number=number)]


def _proposed_edges(
    *,
    edges: list,
    known: set[int],
    existing: dict[int, list[int]],
    agent_id: str,
    config: agent_config.AgentConfig | None = None,
) -> list[tuple[int, int]] | None:
    """Validate Curator output and return only new edges, or None on invalid input."""
    graph = {number: set(blockers) for number, blockers in existing.items()}
    fresh: list[tuple[int, int]] = []
    bad: set[int] = set()
    hallucinated = False  # Reject an unknown issue number without trying to modify it.
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        issue_number = edge.get("issue")
        blockers = edge.get("blocked_by") or []
        if issue_number not in known or not isinstance(blockers, list):
            # Reject the graph without assigning a failure to issue zero or an unrelated object.
            if isinstance(issue_number, int) and issue_number in known:
                bad.add(issue_number)
            else:
                hallucinated = True
            continue
        for blocker in blockers:
            if blocker not in known or blocker == issue_number:
                bad.add(issue_number)
                continue
            graph.setdefault(issue_number, set()).add(blocker)
            if blocker not in existing.get(issue_number, []):
                fresh.append((issue_number, blocker))
    cyclic = _cycle_members(graph=graph)
    if bad or cyclic or hallucinated:
        # Record failures only for issues implicated by invalid edges or cycles.
        for number in sorted(bad | cyclic):
            subject = f"{_KIND_ISSUE}:{number}"
            _fail_automation(
                subject=subject,
                facts=_failure_facts(subject=subject, config=config),
                category="dependency_validation",
                attempts=1,
                reason="The Curator graph contains a cycle or references an unknown issue; no edges were written",
                agent_id=agent_id,
            )
        _log(
            message="✗ Invalid Curator graph (cycle or unknown issue); no edges were written this cycle"
        )
        return None
    return fresh


def _cycle_members(*, graph: dict[int, set[int]]) -> set[int]:
    """Return nodes left after Kahn ordering, including nodes blocked by a cycle."""
    pending = {node: set(blockers) for node, blockers in graph.items()}
    for blockers in graph.values():
        for blocker in blockers:
            pending.setdefault(blocker, set())
    while True:
        free = [node for node, blockers in pending.items() if not blockers]
        if not free:
            return set(pending)
        for node in free:
            pending.pop(node)
        for blockers in pending.values():
            blockers.difference_update(free)


def _has_cycle(*, graph: dict[int, set[int]]) -> bool:
    """Report whether the dependency graph contains a cycle."""
    return bool(_cycle_members(graph=graph))


def route(
    *,
    owner: str,
    on_agent: Callable[[], Any],
    on_skip: Callable[[], Any],
) -> Any:
    """Two-state policy router: execute the agent or the explicit skip behavior."""
    if owner == _AGENT:
        return on_agent()
    if owner == _SKIP:
        return on_skip()
    raise ValueError(f"Unknown stage owner: {owner!r}")


def _park(*, facts: _Facts, verdict: _Verdict, clock: _Clock, now: datetime, agent_id: str) -> None:
    """Record a watchdog failure bound to observed facts without calling a model.

    Only a subject that is still eligible to park should receive a failure
    projection. A changed fingerprint lets reconciliation reopen it.
    """
    age = (
        int((now - clock.last_progress_at).total_seconds())
        if clock.last_progress_at is not None
        else -1
    )
    _fail_automation(
        subject=facts.subject,
        facts=facts,
        category="watchdog",
        attempts=0,
        reason=(
            f"OpenAgents Vigil watchdog: `{facts.subject}` has been waiting on **{verdict.reason or verdict.kind}** "
            f"for {age}s (head `{_short(sha=facts.head_sha) or '—'}`).\n\n"
            f"{_diagnosis(reason=verdict.reason or verdict.kind)}"
        ),
        agent_id=agent_id,
    )


def _diagnosis(*, reason: str) -> str:
    """Return deterministic diagnostic suggestions for the wait reason."""
    return {
        _AWAITING_CI: (
            "Check whether Actions is enabled and the base branch matches the workflow trigger. "
            "Also check whether the workflow excludes draft PRs."
        ),
        _AWAITING_MERGEABILITY: "GitHub has not produced a merge ref. Check whether both branches still exist and whether repository migration is in progress.",
        _AWAITING_EFFECT: (
            "The agent ran, but the observed state did not change. "
            "See its report in the attempt comment for details."
        ),
        _AWAITING_BLOCKERS: "A blocking issue is still open. Check the dependency graph for incorrect edges or cycles, and inspect the upstream issue.",
        _IN_FLIGHT: (
            "The claim exceeded the in-flight warning threshold. Its owner still holds the lock and may be blocked in a call. "
            "The queue row was kept to prevent duplicate execution."
        ),
    }.get(reason, "Unknown cause; inspect manually.")


def _priority_default(*, verdict: _Verdict) -> int:
    """Prioritize finishing active deliveries over starting new issues."""
    return _PRIORITY_DEFAULTS.get(verdict.action or "", 0)


def _hang(*, quiet_counts: dict[str, int], in_flight_count: int, interval: int) -> None:
    """Report why no subjects were queued so idle polling is visible."""
    parts = [
        f"{count} waiting: {reason}" for reason, count in sorted(quiet_counts.items()) if count
    ]
    if in_flight_count:
        parts.insert(0, f"{in_flight_count} in flight")
    detail = "、".join(parts) if parts else "No ready issues or open PRs"
    _log(message=f"… Nothing actionable: {detail}. Polling again in {interval}s")


# --------------------------------------------------------------------------------------------------
# Workers hold the claim lock through reconciliation and finalization.
# --------------------------------------------------------------------------------------------------


def _worker_loop(
    *,
    db_path: Path,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    agent_id: str,
    now_fn: Callable[[], datetime],
    stop_event: threading.Event,
    worker_id: str,
) -> None:
    """Claim and reconcile subjects until shutdown.

    A worker keeps its flock across the full claim. Failures in one subject
    or claim do not stop the worker pool. When no entry is available, wait on
    the stop event before polling again.
    """
    conn = _connect(db_path=db_path)
    try:
        while not stop_event.is_set():
            try:
                claimed = _claim_next(
                    conn=conn, work_dir=Path(work_dir), worker_id=worker_id, now=now_fn()
                )
            except Exception as exc:  # noqa: BLE001 - Retry claims after a transient SQLite failure.
                _log(message=f"✗ {worker_id}: Claim failed; will retry: {exc}")
                stop_event.wait(_WORKER_POLL_SECONDS)
                continue
            if claimed is None:
                stop_event.wait(_WORKER_POLL_SECONDS)
                continue
            row, fd = claimed
            _run_claimed(
                conn=conn,
                row=row,
                fd=fd,
                backend=backend,
                state=state,
                work_dir=Path(work_dir),
                config=config,
                agent_id=agent_id,
                now_fn=now_fn,
            )
    finally:
        conn.close()


def _run_claimed(
    *,
    conn: sqlite3.Connection,
    row: dict,
    fd: int,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    agent_id: str,
    now_fn: Callable[[], datetime],
) -> None:
    """Reconcile one claim and finalize it on all paths.

    Complete, requeue, or park the row according to the outcome. Handle
    exceptions within the worker and always release the claim descriptor.
    """
    subject = row["subject"]
    if int(row["attempts"]) > _MAX_ATTEMPTS:
        if row.get("action", "") == _ACT_REBASE:
            _log(
                message=(
                    f"↻ {subject}: Conflict resolver did not finish before claim {row['attempts']}; "
                    "leaving it queued for automatic recovery"
                )
            )
            _finish(
                conn=conn,
                task_id=row["id"],
                fd=fd,
                park=False,
                subject=subject,
                reason=(
                    f"{_CONFLICT_RETRY_PREFIX} resolver was interrupted or Vigil restarted; "
                    "no complete result was recorded. Resume from the isolated worktree."
                ),
                agent_id=agent_id,
                config=config,
            )
            return
        _log(
            message=f"⏸ {subject}: claim {row['attempts']} did not finish; marking automation failure without another agent call"
        )
        _finish(
            conn=conn,
            task_id=row["id"],
            fd=fd,
            park=True,
            subject=subject,
            reason=(
                f"This entry was claimed {row['attempts']} times without finishing (limit: {_MAX_ATTEMPTS}). "
                "The agent may have crashed, Vigil may have restarted, or the previous attempt to record the failure on the forge did not complete."
            ),
            agent_id=agent_id,
            config=config,
        )
        return
    # Spec-0073/T1: Bind output to the claimed subject's stream. The unique claim allows only this
    # worker to hold the binding.
    streams.bind(subject=subject)
    try:
        # Spec-0093/T2: carry the trusted project policy through every role/retry.
        with context.execution_dispatch(state=state, required=config.execution_evidence_required):
            _reconcile(
                backend=backend,
                state=state,
                work_dir=Path(work_dir),
                config=config,
                subject=subject,
                agent_id=agent_id,
                now_fn=now_fn,
                lock_fd=fd,
            )
    except ExecutionContractUnavailable:
        # Spec-0093/T2: this is missing infrastructure, not a model/candidate verdict.
        # Release the claim without spending retry attempts; the next poll can read repaired evidence.
        _log(
            message=f"⏳ {subject}: Execution contract evidence unavailable; still required. Will retry reading next cycle."
        )
        _finish(
            conn=conn,
            task_id=row["id"],
            fd=fd,
            park=None,
            subject=subject,
            reason="execution_contract_unavailable",
            agent_id=agent_id,
            config=config,
        )
        return
    except _ActTimeout as exc:
        _log(
            message=f"⏱ {subject}: Agent invocation exhausted its time budget ({exc}); retrying within the retry limit"
        )
        _finish(
            conn=conn,
            task_id=row["id"],
            fd=fd,
            park=False,
            subject=subject,
            reason=f"Agent invocation exhausted its time budget ({exc})",
            agent_id=agent_id,
            config=config,
        )
        return
    except gates.MergeNotReady as exc:
        # Pending CI is a wait, not a failure. Finish without charging a retry so the producer can
        # reconsider once checks finish.
        # Spec-0017 recovery: candidate changes use this path too, without failed attempts.
        _log(
            message=f"⏳ {subject}：{exc}; releasing the worker to reread the candidate and gates next cycle"
        )
        _finish(
            conn=conn,
            task_id=row["id"],
            fd=fd,
            park=None,
            subject=subject,
            reason="",
            agent_id=agent_id,
            config=config,
        )
        return
    except Exception as exc:  # noqa: BLE001 - Keep the worker alive after a subject failure.
        _log(message=f"✗ {subject}: Claim failed: {exc}")
        _finish(
            conn=conn,
            task_id=row["id"],
            fd=fd,
            park=False,
            subject=subject,
            reason=str(exc),
            agent_id=agent_id,
            config=config,
        )
        return
    finally:
        # Spec-0073/T1: Always clear the stream binding before reusing the worker.
        streams.unbind()
    _finish(
        conn=conn,
        task_id=row["id"],
        fd=fd,
        park=None,
        subject=subject,
        reason="",
        agent_id=agent_id,
        config=config,
    )


def _finish(
    *,
    conn: sqlite3.Connection,
    task_id: int,
    fd: int,
    park: bool | None,
    subject: str,
    reason: str,
    agent_id: str,
    config: agent_config.AgentConfig | None = None,
) -> None:
    """Finalize a claim and always close its lock descriptor.

    A None park value finishes the row; False retries within budget; True
    records a terminal failure. Finalization errors leave the row eligible
    for later reclaim after the descriptor closes.
    """
    closed = False
    try:
        if park is True:
            facts = _failure_facts(subject=subject, config=config)
            _fail_automation(
                subject=subject,
                facts=facts,
                category="deterministic_failure",
                attempts=_MAX_ATTEMPTS,
                reason=reason,
                agent_id=agent_id,
            )
            conn.execute(
                "DELETE FROM work_queue WHERE id=?", (task_id,)
            )  # Autocommit; see _connect.
            closed = True  # Mark closed before closing so an error cannot close the same descriptor twice.
            os.close(fd)
            return
        if park is False:
            closed = True  # Transfer descriptor ownership to the finalizer.
            _requeue_or_park(
                conn=conn,
                task_id=task_id,
                subject=subject,
                fd=fd,
                agent_id=agent_id,
                config=config,
                reason=reason,
            )
            return
        closed = True  # Transfer descriptor ownership to _mark_done.
        _mark_done(conn=conn, task_id=task_id, fd=fd)
    except Exception as exc:  # noqa: BLE001 - Keep the worker alive if finalization fails.
        _log(
            message=f"✗ {subject}: Could not finish the claim; a remaining row will be reclaimed after the owner exits: {exc}"
        )
    finally:
        if not closed:
            _close_quietly(fd=fd)


def _close_quietly(*, fd: int) -> None:
    """Release the claim descriptor, tolerating an already closed descriptor."""
    try:
        os.close(fd)
    except OSError:
        pass


def _refresh_design_approval(
    *, backend: Any, state: RuntimeState, work_dir: Path, facts: _Facts
) -> None:
    """Spec-0090/T1: re-run the existing architecture route after a candidate Spec changed."""
    issue_number = _issue_number_of(facts=facts)
    if not issue_number or facts.pr_number is None:
        raise gates.GateError("Design digest mismatch with no issue or PR available for recovery")
    worktree = _pr_worktree(work_dir=work_dir, facts=facts)
    evidence_pack = _evidence_pack(state=state, facts=facts)
    run = state.get_run(issue_number=issue_number) or {}
    review_context = context.sections(
        ("runtime context", _AUTONOMOUS_CONTRACT),
        (
            "design change review",
            f"Approved design digest: {run.get('design_digest', '')}; raw digest: "
            f"{run.get('design_raw_digest', '')}. Compare the original issue, approved design in Git history, current base, "
            "and candidate diff. Verify that objectives, constraints, and acceptance criteria have not been weakened. Reuse of the base implementation must preserve acceptance coverage. "
            "Return REWORK if the original design or required evidence is unavailable. Do not assume approval.",
        ),
    )
    verdict = stages.architecture(
        backend=backend,
        work_dir=worktree,
        issue_number=issue_number,
        context_text=review_context,
        evidence_pack=evidence_pack,
    )
    _verify_candidate(worktree=worktree, facts=facts)
    if verdict.get("verdict") != "PASS":
        stages.rfc(
            backend=backend,
            worktree=worktree,
            mode="refine",
            target=str(verdict["spec_path"]),
            branch=_work_branch(facts=facts),
            detail=str(verdict.get("reason", "Architecture review did not pass")),
            context_text=review_context,
            require_delivered=True,
            evidence_pack=evidence_pack,
        )
        # Spec-0090/T1: validation is not approval. Review the delivered refinement again;
        # never replace the old digest merely because the new Spec parses successfully.
        facts = replace(facts, head_sha=gates.snapshot_head(workspace=worktree))
        _verify_candidate(worktree=worktree, facts=facts)
        verdict = stages.architecture(
            backend=backend,
            work_dir=worktree,
            issue_number=issue_number,
            context_text=review_context,
            evidence_pack=evidence_pack,
        )
        _verify_candidate(worktree=worktree, facts=facts)
        if verdict.get("verdict") != "PASS":
            raise gates.GateError(
                f"Design remains unapproved after revision: {verdict.get('reason', '')}"
            )
    state.set_run(
        issue_number=issue_number,
        status=STATUS_PR_OPEN,
        branch=_work_branch(facts=facts),
        pr_number=facts.pr_number,
        design_digest=str(verdict["design_digest"]),
        design_raw_digest=str(verdict.get("design_raw_digest", "")),
    )
    _log(message=f"↻ issue #{issue_number}：Design digest refreshed; returning to code review")


def _repair_repository_integrity(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    facts: _Facts,
    reason: str,
) -> None:
    """Spec-0090/T1: send a generated-view mismatch through existing delivery repair."""
    issue_number = _issue_number_of(facts=facts)
    if not issue_number or facts.pr_number is None:
        raise gates.GateError(
            "Repository integrity mismatch with no issue or PR available for recovery"
        )
    _implement_and_deliver(
        backend=backend,
        state=state,
        worktree=_pr_worktree(work_dir=work_dir, facts=facts),
        facts=facts,
        config=config,
        resuming=True,
        feedback=(
            f"Deterministic delivery check failed: {reason}\nFix the Spec validation errors and regenerate "
            "OVERVIEW.md, run the relevant checks, commit, and push. Preserve the original objectives and acceptance criteria; keep unrelated changes out."
        ),
        context_text=_AUTONOMOUS_CONTRACT,
    )
    gates.assert_repository_integrity(workspace=_pr_worktree(work_dir=work_dir, facts=facts))


def _reconcile_progress(*, facts: _Facts, state: RuntimeState | None) -> tuple[str, ...]:
    """Compare forge facts AND durable local gates, excluding timestamps and comments.

    Refreshing design approval intentionally removes the code review label. When
    review passes again, the forge facts recur but the approved design has advanced.
    That is forward progress, not a cycle. Keep the public fact fingerprint stable
    for attempt/failure stamps; only reconciliation needs this local checkpoint.
    """
    issue_number = _issue_number_of(facts=facts)
    run = (state.get_run(issue_number=issue_number) or {}) if state and issue_number else {}
    return (
        _fingerprint(facts=facts),
        str(run.get("status", "")),
        str(run.get("design_digest", "")),
        str(run.get("design_raw_digest", "")),
    )


def _reconcile(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    subject: str,
    agent_id: str,
    now_fn: Callable[[], datetime],
    lock_fd: int | None,
) -> None:
    """Advance one claimed subject until it waits, finishes, or yields.

    Reread forge facts after each action, and classify from the worker's
    perspective. Stop and stamp an action that makes no progress. Detect
    cycles using observed facts and local gate checkpoints. Yield the slot
    after the per-claim limit if progress continues; the producer can resume
    from observed state. Keep the claim lock for this entire sequence.
    """
    last_fp: str | None = None
    last_summary = ""
    seen_progress: set[tuple[str, ...]] = set()
    last_progress: tuple[str, ...] | None = None
    for round_index in range(_MAX_RECONCILE_ROUNDS):
        observed = _sense(config=config, subject=subject)
        fp = _fingerprint(facts=observed.facts)
        verdict = _classify(
            facts=observed.facts, in_flight=False
        )  # This worker owns the in-flight claim.
        verdict = _resume_verdict(state=state, facts=observed.facts, verdict=verdict)
        resuming = verdict.action == _ACT_SOLVE and observed.facts.pr_number is not None

        if verdict.kind != _ACTIONABLE:
            _log(
                message=f"⏹ {subject}：{verdict.kind} ({verdict.reason or '—'}); releasing the worker"
            )
            return

        progress = _reconcile_progress(facts=observed.facts, state=state)
        if (
            fp == last_fp and progress == last_progress
        ):  # An action already ran against these unchanged facts.
            _post_attempt_stamp(
                facts=observed.facts, fp=fp, conclusion=last_summary, agent_id=agent_id
            )
            return

        seen_progress.add(progress)
        last_progress = progress
        last_fp = fp
        # Spec-0066/T2: Record the worker's actual action phase, independently of the producer's
        # generic in-flight phase.
        _record_timing(
            work_dir=Path(work_dir),
            subject=subject,
            facts=observed.facts,
            verdict=verdict,
            now=now_fn(),
        )
        label_baseline = _capture_label_targets(facts=observed.facts)
        allowed_removals = _allowed_label_removals(facts=observed.facts, verdict=verdict)
        try:
            last_summary = _act(
                backend=backend,
                state=state,
                work_dir=Path(work_dir),
                config=config,
                observed=observed,
                verdict=verdict,
                agent_id=agent_id,
                now=now_fn(),
                lock_fd=lock_fd,
            )
        except gates.DesignApprovalStale:
            # Spec-0090/T1: a changed Spec is a design lifecycle event, not an execution
            # failure. Re-run the existing architecture gate and invalidate the old code vote.
            _refresh_design_approval(
                backend=_TimedBackend(
                    inner=backend, timeout_seconds=effective_max_wall(), lock_fd=lock_fd
                ),
                state=state,
                work_dir=Path(work_dir),
                facts=observed.facts,
            )
            _clear_review_labels(
                pr_number=observed.facts.pr_number or 0, labels=observed.facts.labels
            )
            allowed_removals = _allowed_label_removals(
                facts=observed.facts, verdict=replace(verdict, action=_ACT_REVIEW_OR_FIX)
            )
            last_summary = "design approval refreshed"
            # A changed candidate yields a new fp on the next read; an unchanged repair is
            # stopped by the existing zero-progress guard instead of looping to round_cap.
            last_fp = fp
        except gates.RepositoryIntegrityStale as exc:
            # Spec-0090/T1: repair the generated repository view through the existing
            # implement→deliver path; do not spend the claim retry budget on a deterministic
            # source/generated-view mismatch.
            _repair_repository_integrity(
                backend=_TimedBackend(
                    inner=backend, timeout_seconds=effective_max_wall(), lock_fd=lock_fd
                ),
                state=state,
                work_dir=Path(work_dir),
                config=config,
                facts=observed.facts,
                reason=str(exc),
            )
            last_summary = "repository integrity repaired"
            last_fp = fp
        # Spec-0090/T1: `_do_merge` only returns after the forge reports success. Treat that
        # result as terminal even if the next remote snapshot is briefly stale.
        if verdict.action == _ACT_MERGE and last_summary == "merged":
            return
        if resuming and not _implementation_pending(state=state, facts=observed.facts):
            # Spec-0056 recovery: checking a completed interrupted turn need not create a commit.
            # The existing run checkpoint advanced; let the normal review path run once.
            last_fp = None

        integrity_body = _restore_label_integrity(
            baseline=label_baseline,
            allowed_removals=allowed_removals,
        )
        if integrity_body is not None:
            _fail_automation(
                subject=subject,
                facts=observed.facts,
                category="label_integrity",
                attempts=round_index + 1,
                reason=integrity_body,
                agent_id=agent_id,
            )
            return
        _log(
            message=f"↻ {subject}: Reconciliation step {round_index + 1}/{_MAX_RECONCILE_ROUNDS} completed"
        )

    # Spec-0090/T1: one last level-triggered read closes the action/cap boundary. A successful
    # merge may become visible one read later; never overwrite that terminal fact with round_cap.
    final = _sense(config=config, subject=subject)
    final_verdict = _classify(facts=final.facts, in_flight=False)
    if final_verdict.kind != _ACTIONABLE:
        return

    final_fp = _fingerprint(facts=final.facts)
    final_progress = _reconcile_progress(facts=final.facts, state=state)
    if final_fp == last_fp and final_progress == last_progress:
        _post_attempt_stamp(
            facts=final.facts, fp=final_fp, conclusion=last_summary, agent_id=agent_id
        )
        return
    if final_progress in seen_progress:
        _fail_automation(
            subject=subject,
            facts=final.facts,
            category="fact_cycle",
            attempts=_MAX_RECONCILE_ROUNDS,
            reason="Repeated forge facts and local gate checkpoints within one claim; state cycle detected",
            agent_id=agent_id,
        )
        return
    _log(
        message=f"↪ {subject}: New state after {_MAX_RECONCILE_ROUNDS} steps; releasing the worker for later reconciliation"
    )


def _capture_label_targets(*, facts: _Facts) -> dict[tuple[str, int], _LabelTargetSnapshot]:
    """Snapshot each distinct forge object that an agent action could affect."""
    kind, number = _split_subject(subject=facts.subject)
    keys = [(kind, number)]
    if kind == _KIND_ISSUE and facts.pr_number is not None:
        keys.append((_KIND_PR, facts.pr_number))
    return {key: _read_label_target(kind=key[0], number=key[1]) for key in keys}


def _read_label_target(*, kind: str, number: int) -> _LabelTargetSnapshot:
    """Read labels and terminal status for one issue or pull request."""
    if kind == _KIND_ISSUE:
        issue = github.get_issue(number=number)
        return _LabelTargetSnapshot(
            kind=kind, number=number, labels=frozenset(issue.labels), terminal=False
        )
    snapshot = github.pr_snapshot(pr_number=number)
    return _LabelTargetSnapshot(
        kind=kind,
        number=number,
        labels=frozenset(snapshot.labels),
        terminal=snapshot.state in {"MERGED", "CLOSED"},
    )


def _allowed_label_removals(
    *, facts: _Facts, verdict: _Verdict
) -> dict[tuple[str, int], frozenset[str]]:
    """Return the exact labels that the host may remove for this action."""
    if verdict.action != _ACT_REVIEW_OR_FIX or facts.pr_number is None:
        return {}
    fixing_current_review = (
        facts.review_state == _REVIEW_CHANGES_REQUESTED
        and facts.review_commit_id == _short(sha=facts.head_sha)
    )
    if fixing_current_review:
        return {}
    stale = frozenset(
        label
        for label in facts.labels
        if label.startswith((_LABEL_REVIEW_APPROVED_PREFIX, _LABEL_REVIEW_CHANGES_PREFIX))
    )
    return {(_KIND_PR, facts.pr_number): stale} if stale else {}


def _restore_label_integrity(
    *,
    baseline: dict[tuple[str, int], _LabelTargetSnapshot],
    allowed_removals: dict[tuple[str, int], frozenset[str]],
) -> str | None:
    """Detect unexpected label removal and restore only labels still missing.

    Reread the specific forge object before an additive update to avoid
    undoing concurrent changes or writing to the wrong issue or PR.
    """
    violations: dict[tuple[str, int], frozenset[str]] = {}
    for key, before in baseline.items():
        after = _read_label_target(kind=before.kind, number=before.number)
        if after.terminal:
            continue
        missing = before.labels - after.labels - allowed_removals.get(key, frozenset())
        if missing:
            violations[key] = frozenset(missing)
    if not violations:
        return None

    restored: dict[tuple[str, int], list[str]] = {}
    for key, originally_missing in violations.items():
        latest = _read_label_target(kind=key[0], number=key[1])
        if latest.terminal:
            continue
        still_missing = sorted(originally_missing - latest.labels)
        for label in still_missing:
            if key[0] == _KIND_ISSUE:
                github.issue_add_label(number=key[1], name=label)
            else:
                github.add_label(pr_number=key[1], name=label)
        restored[key] = still_missing

    details = []
    for key, missing in sorted(violations.items()):
        target = f"{key[0]}:{key[1]}"
        restored_labels = restored.get(key, [])
        details.append(
            f"- `{target}` Unexpectedly removed: {', '.join(f'`{label}`' for label in sorted(missing))}; "
            f"Restored missing labels: {', '.join(f'`{label}`' for label in restored_labels) or 'none (already restored or terminal)'}"
        )
    body = (
        "An agent action removed required labels. "
        "OpenAgents reread the forge and restored only missing labels to preserve source, priority, round, and workflow metadata. Reconciliation is paused.\n\n"
        + "\n".join(details)
    )
    _log(
        message="⚠ Agent unexpectedly removed labels; restored missing labels and recorded an automation failure"
    )
    return body


def _act(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    observed: _Observed,
    verdict: _Verdict,
    agent_id: str,
    now: datetime,
    lock_fd: int | None,
) -> str:
    """Dispatch the selected action and return its report.

    Use deterministic helpers for readiness and other forge facts. Roles
    perform semantic work under the invocation budget. Compare labels around
    agent work and stop when integrity has been lost. Keep the report for a
    no-progress attempt stamp.
    """
    facts = observed.facts
    timed = _TimedBackend(inner=backend, timeout_seconds=effective_max_wall(), lock_fd=lock_fd)
    action = _resume_verdict(state=state, facts=facts, verdict=verdict).action
    stage_owner = config.stages.owner_of

    # Spec-0017 recovery: developers may edit; readers certify a delivered candidate only.
    fixing_review = (
        config.flow == agent_config.FLOW_STANDARD
        and facts.review_state == _REVIEW_CHANGES_REQUESTED
        and facts.review_commit_id == _short(sha=facts.head_sha)
    )
    candidate_stage = {
        _ACT_E2E: agent_config.STAGE_E2E,
        _ACT_MERGE: agent_config.STAGE_MERGE,
        _ACT_REVIEW_OR_FIX: agent_config.STAGE_REVIEW,
    }.get(action)
    if (
        candidate_stage is not None
        and stage_owner(stage=candidate_stage) == _AGENT
        and not (action == _ACT_REVIEW_OR_FIX and fixing_review)
    ):
        _prepare_candidate(
            backend=timed, state=state, work_dir=work_dir, facts=facts, config=config
        )

    if action == _ACT_REPLY:
        return _do_reply(
            backend=timed, state=state, work_dir=work_dir, facts=facts, agent_id=agent_id
        )
    if action == _ACT_SOLVE:
        return _do_solve(
            backend=timed,
            state=state,
            work_dir=work_dir,
            config=config,
            facts=facts,
            agent_id=agent_id,
        )
    if action == _ACT_REBASE:
        return route(
            owner=stage_owner(stage=agent_config.STAGE_CONFLICT),
            on_agent=lambda: _do_rebase(
                backend=timed,
                work_dir=work_dir,
                base=config.base,
                facts=facts,
                refresh_facts=lambda: _refresh_conflict_facts(facts=facts),
            ),
            on_skip=lambda: "conflict skipped",
        )
    if action == _ACT_FIX_CI:
        if config.flow in {agent_config.FLOW_MINIMAL, agent_config.FLOW_GENERATE_ONLY}:
            logs = "\n".join(github.check_logs(pr_number=facts.pr_number or 0))
            _fail_automation(
                subject=facts.subject,
                facts=facts,
                category="minimal_ci_failed",
                attempts=1,
                reason=logs
                or "CI failed for the current head. The minimal flow does not automatically revise the implementation.",
                agent_id=agent_id,
            )
            return "minimal flow stopped on CI failure"
        return route(
            owner=stage_owner(stage=agent_config.STAGE_CI),
            on_agent=lambda: _do_fix_ci(
                backend=timed, state=state, work_dir=work_dir, facts=facts, config=config
            ),
            on_skip=lambda: "ci skipped",
        )
    if action == _ACT_E2E:
        return route(
            owner=stage_owner(stage=agent_config.STAGE_E2E),
            on_agent=lambda: _do_e2e(
                backend=timed, state=state, work_dir=work_dir, facts=facts, agent_id=agent_id
            ),
            on_skip=lambda: "e2e skipped",
        )
    if action == _ACT_REVIEW_OR_FIX:
        return route(
            owner=stage_owner(stage=agent_config.STAGE_REVIEW),
            on_agent=lambda: _do_review_or_fix(
                backend=timed,
                state=state,
                work_dir=work_dir,
                facts=facts,
                config=config,
                agent_id=agent_id,
            ),
            on_skip=lambda: "review skipped",
        )
    if action == _ACT_READY:
        # Promote drafts through the forge driver. The decision is mechanical and does not require
        # a model or configurable stage owner.
        return _do_ready(facts=facts)
    if action == _ACT_MERGE:
        return route(
            owner=stage_owner(stage=agent_config.STAGE_MERGE),
            on_agent=lambda: _do_merge(
                backend=timed,
                state=state,
                work_dir=work_dir,
                facts=facts,
                flow=config.flow,
                require_ci=stage_owner(stage=agent_config.STAGE_CI) != _SKIP,
            ),
            on_skip=lambda: "merge skipped",
        )
    raise ValueError(f"Unknown action: {action!r}")


# Spec-0065/T2: Give every dispatched role a clear failure exit rather than relying on a later
# watchdog diagnosis.
_AUTONOMOUS_CONTRACT = (
    "\n\n---\n"
    "If you cannot finish, do not keep retrying, claim success, or change forge labels. Return a clear failure and verified facts in this role’s JSON schema. "
    "Orchestration handles bounded retries and records terminal automation failures."
)

_MINIMAL_FLOW_CONTRACT = (
    "\n\n--- minimal flow objective contract ---\n"
    "The original issue title and body define the objective. The Spec chooses a path without weakening it. Make one implementation attempt and replay the original failure when possible. "
    "Avoid repository-wide audits and unrelated verification. Commit and push the current branch during this invocation. Report partial work honestly. "
    "Read and write only in the isolated worktree where the backend started. "
    "Do not switch to /work/harness or access the parent checkout or another workspace."
)


def _do_reply(
    *, backend: Any, state: RuntimeState, work_dir: Path, facts: _Facts, agent_id: str
) -> str:
    """Answer the latest human PR comment and post a signed reply."""
    pr_number = facts.pr_number
    if pr_number is None:
        return _do_reply_issue(
            backend=backend, state=state, work_dir=work_dir, facts=facts, agent_id=agent_id
        )
    news = identity.new_human_comments(
        pr_number=pr_number, since=state.get_cursor(pr_number=pr_number) or ""
    )
    if not news:
        return ""
    latest = news[-1]
    placeholders = context.for_reply(
        work_dir=work_dir,
        pr_number=pr_number,
        branch=github.pr_head_branch(pr_number=pr_number),
        comment=latest,
    )
    placeholders["context"] = f"{placeholders['context']}{_AUTONOMOUS_CONTRACT}"
    verdict = engine.run_agent(replier, backend=backend, **placeholders)
    identity.post_signed_comment(pr_number=pr_number, body=verdict["reply"], agent_id=agent_id)
    state.set_cursor(pr_number=pr_number, comment_id=latest.created_at)
    _log(message=f"↩ PR #{pr_number}：Replied to a human comment")
    return verdict["reply"]


# Spec-0016/T4: Use the issue reply prompt with the shared reply schema. An issue reply does not
# authorize implementation.
_ISSUE_REPLIER = SimpleNamespace(PROMPT=replier.ISSUE_PROMPT, OUTPUT_SCHEMA=replier.OUTPUT_SCHEMA)


def _do_reply_issue(
    *, backend: Any, state: RuntimeState, work_dir: Path, facts: _Facts, agent_id: str
) -> str:
    """Answer the latest human issue comment without implementing changes.
    Spec-0016/T4.
    """
    kind, number = _split_subject(subject=facts.subject)
    if kind != _KIND_ISSUE:
        return ""  # Defensive check: a standalone PR subject must have a PR.
    news = identity.new_human_comments_on_issue(
        number=number, since=state.get_issue_cursor(number=number) or ""
    )
    if not news:
        return ""
    latest = news[-1]
    placeholders = context.for_issue_reply(work_dir=work_dir, issue_number=number, comment=latest)
    placeholders["context"] = f"{placeholders['context']}{_AUTONOMOUS_CONTRACT}"
    verdict = engine.run_agent(_ISSUE_REPLIER, backend=backend, **placeholders)
    identity.post_signed_comment_on_issue(number=number, body=verdict["reply"], agent_id=agent_id)
    state.set_issue_cursor(number=number, comment_id=latest.created_at)
    _log(message=f"↩ issue #{number}：Replied to a human comment")
    return verdict["reply"]


def _do_solve(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    facts: _Facts,
    agent_id: str,
) -> str:
    """Prepare an issue worktree, open a draft PR, implement, and deliver as configured."""
    kind, number = _split_subject(subject=facts.subject)
    if kind != _KIND_ISSUE:
        return ""  # A standalone PR cannot enter the issue solve stage.
    issue = github.get_issue(number=number)
    advisory = (
        preflight.advice_for(work_dir=work_dir, issue=issue)
        if config.coordination == "soft"
        else ""
    )
    runtime_context = _AUTONOMOUS_CONTRACT + advisory
    branch = f"{_BRANCH_PREFIX}{number}"
    if facts.pr_number is not None:
        # Spec-0056 recovery: an existing PR is a delivery container, not a completion signal.
        report = _implement_and_deliver(
            backend=backend,
            state=state,
            worktree=_pr_worktree(work_dir=work_dir, facts=facts),
            facts=facts,
            config=config,
            resuming=True,
            feedback="The previous implementation was interrupted. Keep existing changes, check the original task and relevant tests, and finish implementation and delivery. Do not repeat finished work or create an empty commit.",
            context_text=context.sections(
                ("original issue", issue.body), ("runtime context", runtime_context)
            ),
        )
        return str(report.get("summary", ""))
    worktree = git.Workspace(work_dir=work_dir).prepare(
        issue_number=number, branch=branch, base=config.base
    )

    if config.flow in {agent_config.FLOW_MINIMAL, agent_config.FLOW_GENERATE_ONLY}:
        spec_report = stages.minimal_spec(
            backend=backend,
            worktree=worktree,
            issue_number=number,
            issue_title=issue.title,
            issue_body=issue.body,
            branch=branch,
            context_text=f"{runtime_context}{_MINIMAL_FLOW_CONTRACT}",
        )
        if spec_report["status"] in {"PARTIAL", "BLOCKED"}:
            reason = str(spec_report.get("blocker") or spec_report.get("summary") or "blocked")
            _fail_automation(
                subject=facts.subject,
                facts=facts,
                category=f"minimal_spec_{str(spec_report['status']).lower()}",
                attempts=1,
                reason=reason,
                agent_id=agent_id,
            )
            return reason

        evidence_pack = research.normalize(spec_report.get("evidence_pack", []))
        design_snapshot = stages.minimal_design_snapshot(work_dir=worktree, issue_number=number)
        approved_design_digest = design_snapshot["design_digest"]
        pr = github.create_pr(
            branch=branch,
            base=config.base,
            title=f"feat: issue #{issue.number} {issue.title}".strip(),
            body=(
                f"Closes #{issue.number}\n\nopenagents "
                f"{'generate-only' if config.flow == agent_config.FLOW_GENERATE_ONLY else 'minimal'} flow。"
            ),
            draft=True,
        )
        state.set_run(
            issue_number=number,
            status=STATUS_ITERATING,
            branch=branch,
            pr_number=pr.number,
            design_digest=approved_design_digest,
            evidence_pack=evidence_pack,
        )
        compact_path = Path(design_snapshot["spec_path"])
        compact_text = (
            compact_path.read_text(encoding="utf-8")
            if compact_path.is_file()
            else f"validated compact spec: {compact_path}"
        )
        implementation_context = context.sections(
            ("compact objective spec", compact_text),
            ("original issue", f"# {issue.number} {issue.title}\n\n{issue.body}"),
            ("runtime context", f"{runtime_context}{_MINIMAL_FLOW_CONTRACT}"),
        )
        if config.flow == agent_config.FLOW_GENERATE_ONLY:
            report = _implement_and_deliver(
                backend=backend,
                state=state,
                worktree=worktree,
                facts=replace(facts, pr_number=pr.number),
                config=config,
                resuming=False,
                feedback="",
                context_text=implementation_context,
            )
        else:
            implementation_before = gates.snapshot_head(workspace=worktree)
            report = _implement_and_deliver(
                backend=backend,
                state=state,
                worktree=worktree,
                facts=replace(facts, pr_number=pr.number),
                config=config,
                resuming=False,
                feedback="",
                context_text=implementation_context,
            )
            implementation_after = gates.snapshot_head(workspace=worktree)
            if implementation_after == implementation_before:
                _fail_automation(
                    subject=facts.subject,
                    facts=facts,
                    category="minimal_implementation_no_delivery",
                    attempts=1,
                    reason=str(report.get("summary", "Implementer did not deliver a new head")),
                    agent_id=agent_id,
                )
                return str(report.get("summary", "minimal implementation did not advance HEAD"))
        git.Workspace(work_dir=work_dir).assert_delivered(worktree=worktree, branch=branch)
        _log(
            message=f"✓ issue #{number}：{config.flow} opened PR #{pr.number} and completed one implementation attempt"
        )
        return str(report.get("summary", ""))

    def _draft() -> dict:
        return stages.rfc(
            backend=backend,
            worktree=worktree,
            mode=stages.MODE_DRAFT,
            # Spec-0081: target is a routing scalar, never a dynamic issue title.
            target=f"issue #{issue.number}",
            branch=branch,
            detail=context.sections(("issue title", issue.title), ("issue body", issue.body)),
            context_text=runtime_context,
            require_delivered=False,
        )

    draft_report = route(
        owner=config.stages.owner_of(stage=agent_config.STAGE_RFC),
        on_agent=_draft,
        # When drafting is skipped there may be no remote branch. Seed and publish it
        # deterministically before creating the PR.
        on_skip=lambda: git.seed_branch(
            work_dir=worktree,
            branch=branch,
            message=f"chore: open delivery branch for issue #{number} (rfc skipped)",
        ),
    )
    evidence_pack = draft_report.get("evidence_pack", []) if isinstance(draft_report, dict) else []

    approved_design_digest = ""
    approved_raw_digest = ""
    architecture_owner = config.stages.owner_of(stage=agent_config.STAGE_ARCHITECTURE)
    if architecture_owner not in {_AGENT, _SKIP}:
        raise ValueError(f"Unknown stage owner: {architecture_owner!r}")
    if architecture_owner == _AGENT:
        architecture_verdict = stages.architecture(
            backend=backend,
            work_dir=worktree,
            issue_number=number,
            context_text=runtime_context,
            evidence_pack=evidence_pack,
        )
        if architecture_verdict["verdict"] == "PASS":
            approved_design_digest = architecture_verdict["design_digest"]
            approved_raw_digest = architecture_verdict.get("design_raw_digest", "")
        else:
            refine_report = stages.rfc(
                backend=backend,
                worktree=worktree,
                mode="refine",
                target=architecture_verdict["spec_path"],
                branch=branch,
                detail=architecture_verdict["reason"],
                context_text=runtime_context,
                require_delivered=False,
                evidence_pack=evidence_pack,
            )
            if isinstance(refine_report, dict):
                evidence_pack = research.merge(
                    evidence_pack, refine_report.get("evidence_pack", [])
                )
            # Allow one independent architecture review and one focused revision. Validate and
            # bind the revised digest without repeatedly calling reviewers.
            snapshot = stages.design_snapshot(work_dir=worktree, issue_number=number)
            approved_design_digest = snapshot["design_digest"]
            approved_raw_digest = snapshot.get("design_raw_digest", "")
    pr = github.create_pr(
        branch=branch,
        base=config.base,
        title=f"feat: issue #{issue.number} {issue.title}".strip(),
        body=f"Closes #{issue.number}\n\nImplemented by OpenAgents Vigil. Awaiting review.",
        draft=True,
    )
    state.set_run(
        issue_number=number,
        status=STATUS_ITERATING,
        branch=branch,
        pr_number=pr.number,
        design_digest=approved_design_digest,
        design_raw_digest=approved_raw_digest,
        evidence_pack=evidence_pack,
    )
    report = _implement_and_deliver(
        backend=backend,
        state=state,
        worktree=worktree,
        facts=replace(facts, pr_number=pr.number),
        config=config,
        resuming=False,
        feedback="",
        context_text=(
            context.sections(("original issue", issue.body), ("runtime context", runtime_context))
            if config.coordination == "soft"
            else runtime_context
        ),
    )
    # Use the level-triggered readiness branch for promotion on either forge; the delivery role
    # does not run a platform command.
    _log(message=f"✓ issue #{number}：Opened PR #{pr.number}")
    return str(report.get("summary", ""))


def _work_branch(*, facts: _Facts) -> str:
    """Locate the existing delivery branch (Spec-0089/T1)."""
    number = _issue_number_of(facts=facts)
    return (
        f"{_BRANCH_PREFIX}{number}"
        if number
        else github.pr_head_branch(pr_number=facts.pr_number or 0)
    )


def _implement_and_deliver(
    *,
    backend: Any,
    state: RuntimeState,
    worktree: Path,
    facts: _Facts,
    config: agent_config.AgentConfig,
    feedback: str,
    context_text: str,
    resuming: bool,
) -> dict:
    """Finish an existing development turn and its delivery (Spec-0089/T1)."""
    number = _issue_number_of(facts=facts)
    branch = _work_branch(facts=facts)
    if resuming and config.flow in {
        agent_config.FLOW_MINIMAL,
        agent_config.FLOW_GENERATE_ONLY,
    }:
        snapshot = stages.minimal_design_snapshot(work_dir=worktree, issue_number=number)
        context_text = context.sections(
            ("compact objective spec", Path(snapshot["spec_path"]).read_text(encoding="utf-8")),
            ("recovery context", context_text),
            ("flow contract", _MINIMAL_FLOW_CONTRACT),
        )
    if number:
        state.set_run(
            issue_number=number, status=STATUS_ITERATING, branch=branch, pr_number=facts.pr_number
        )
    if config.flow == agent_config.FLOW_GENERATE_ONLY:
        report = stages.execute_compact_spec(
            backend=backend,
            work_dir=worktree,
            issue_number=number,
            pr_number=facts.pr_number or 0,
            context_text=context_text + "\n" + feedback,
            resume_branch=branch if resuming else None,
        )
    else:
        report = stages.implement(
            backend=backend,
            work_dir=worktree,
            issue_number=number,
            pr_number=facts.pr_number or 0,
            feedback=feedback,
            context_text=context_text,
            evidence_pack=_evidence_pack(state=state, facts=facts),
        )
    workspace = git.Workspace(work_dir=worktree)
    if not workspace.sync_delivered(worktree=worktree, branch=branch):
        stages.deliver(
            backend=backend,
            worktree=worktree,
            branch=branch,
            pr_number=facts.pr_number or 0,
            issue_number=number,
            rebase_onto=config.base,
            context_text=context_text,
        )
    workspace.assert_delivered(worktree=worktree, branch=branch)
    if number:
        state.set_run(
            issue_number=number, status=STATUS_PR_OPEN, branch=branch, pr_number=facts.pr_number
        )
    return report


def _prepare_candidate(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    facts: _Facts,
    config: agent_config.AgentConfig,
) -> None:
    """Recover unpublished work or align a behind-only reader (Spec-0089/T1)."""
    worktree = _pr_worktree(work_dir=work_dir, facts=facts)
    workspace = git.Workspace(work_dir=worktree)
    if not workspace.sync_delivered(worktree=worktree, branch=_work_branch(facts=facts)):
        _implement_and_deliver(
            backend=backend,
            state=state,
            worktree=worktree,
            facts=facts,
            config=config,
            resuming=True,
            feedback="Undelivered local work was found before review or testing. Keep all existing changes, check the original task, and complete implementation, verification, commit, and push. Do not report unfinished code as delivered.",
            context_text=context.sections(
                ("original issue", _issue_body_of(facts=facts)),
                ("runtime context", _AUTONOMOUS_CONTRACT),
            ),
        )
    _verify_candidate(worktree=worktree, facts=facts)


def _verify_candidate(*, worktree: Path, facts: _Facts) -> None:
    """Bind checks to exactly the sensed, local and remote candidate (Spec-0089/T1)."""
    local, published = git.Workspace(work_dir=worktree).delivery_heads(
        worktree=worktree, branch=_work_branch(facts=facts)
    )
    # Spec-0017: remote churn invalidates a verdict, not the execution failure budget.
    # A reader's new, unpublished commit is still a delivery error, not remote churn.
    if local != facts.head_sha and local != published:
        raise git.WorkspaceError(
            f"PR #{facts.pr_number} review candidate contains unpushed local commits"
        )
    remote = github.pr_snapshot(pr_number=facts.pr_number or 0).head_sha
    if not remote:
        raise git.WorkspaceError(f"PR #{facts.pr_number} could not read the remote candidate HEAD")
    if local != facts.head_sha or published != local or remote != local:
        raise gates.MergeNotReady(
            f"PR #{facts.pr_number} candidate revision changed; reread and verify it"
        )


def _conflict_worktree(*, work_dir: Path, base: str, facts: _Facts, branch: str) -> Path:
    """Return a worktree that is bound to the actual PR branch.

    ``Workspace.ensure`` intentionally reuses an existing path.  That is correct for normal
    implementation work, but unsafe for conflict recovery: a previous timed-out rebase may
    have left an in-progress index, and an issue worktree may be bound to the conventional
    issue branch while the PR head branch has been renamed.  Rebuild only a clean, published
    worktree; preserve dirty/diverged work so unpublished commits are never discarded.
    """
    workspace = git.Workspace(work_dir=Path(work_dir))
    prepare_conflict = getattr(workspace, "prepare_conflict", None)
    if callable(prepare_conflict):
        return prepare_conflict(branch=branch, base=base)

    # Compatibility seam for older injected/fake Workspace implementations.  Production
    # always uses the detached conflict worktree above.
    _, number = _split_subject(subject=facts.subject)
    worktree = workspace.ensure(issue_number=number, branch=branch)
    if not workspace.sync_delivered(worktree=worktree, branch=branch):
        _log(
            message=(
                f"… {facts.subject}: Conflict worktree has unpublished changes or an unfinished rebase; preserving it for the resolver "
                f"(branch={branch})"
            )
        )
        return worktree
    rebuilt = workspace.prepare(issue_number=number, branch=branch, base=base)
    _log(
        message=f"↻ {facts.subject}: Rebuilding the conflict worktree from origin/{base} and origin/{branch}"
    )
    return rebuilt


def _conflict_context(*, facts: _Facts, base: str, branch: str, reason: str = "") -> str:
    """Context contract for a repeatable, fully automated conflict attempt."""
    fp = _conflict_fingerprint(facts=facts, base=base, branch=branch, reason=reason)
    bounded_reason = " ".join(reason.split())[:_CONFLICT_REASON_MAX_CHARS]
    snapshot = json.dumps(
        {
            "subject": facts.subject,
            "pr_number": facts.pr_number,
            "head_sha": facts.head_sha or "",
            "mergeable_state": facts.mergeable_state or "",
            "base": base,
            "branch": branch,
            "conflict_fingerprint": fp,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return context.sections(
        ("runtime context", _AUTONOMOUS_CONTRACT),
        ("conflict snapshot", snapshot),
        (
            "conflict recovery protocol",
            "Check git status for an unfinished rebase and resume it first. Do not create a new commit with an unmerged index. "
            "Otherwise record the remote head before fetching the latest base and working branch, and rebase only the working branch. "
            "Resolve conflicts according to both sides’ intent, then run the project’s spec validate/render/graph and relevant tests. "
            "If a Spec number collides, reserve a new number on the shared remote with spec reserve-number --issue <N> --slug <slug>; never guess it. For other shared resources, follow ownership on the latest base. "
            "Return delivered=true only after verification passes, the worktree is clean, and a force-with-lease push to the same branch succeeds. "
            "If the attempt fails, report why. The next attempt will resume from the preserved state or rebuild a clean isolated worktree. "
            f"Previous failure: {bounded_reason or 'none'}. "
            f"Conflict fingerprint: {fp}",
        ),
    )


def _refresh_conflict_facts(*, facts: _Facts) -> _Facts:
    """Refresh the forge facts that define a conflict episode before each resolver attempt."""
    if facts.pr_number is None:
        return facts
    snapshot = github.pr_snapshot(pr_number=facts.pr_number)
    return replace(
        facts,
        head_sha=snapshot.head_sha or facts.head_sha,
        merged=snapshot.state == "MERGED",
        closed=snapshot.state == "CLOSED",
        mergeable_state=_mergeable_state(snapshot=snapshot),
    )


def _do_rebase(
    *,
    backend: Any,
    work_dir: Path,
    base: str,
    facts: _Facts,
    refresh_facts: Callable[[], _Facts] | None = None,
) -> str:
    """Try a deterministic branch update before delegating conflict resolution."""
    pr_number = facts.pr_number or 0
    mechanical_reason = ""
    try:
        if github.update_branch(pr_number=pr_number, rebase=True):
            _log(
                message=f"↻ PR #{pr_number}：Base branch integrated with update-branch; no agent call"
            )
            return "Base branch integrated with update-branch"
    except github.GithubError as exc:
        mechanical_reason = str(exc)
        _log(
            message=f"… PR #{pr_number}：update-branch failed ({exc}); delegating conflict resolution"
        )
    _, number = _split_subject(subject=facts.subject)
    branch = ""
    last_reason = mechanical_reason
    last_facts = facts
    for attempt in range(1, _CONFLICT_RESOLUTION_ATTEMPTS + 1):
        try:
            if refresh_facts is not None:
                last_facts = refresh_facts()
                pr_number = last_facts.pr_number or pr_number
            # The forge can rename a head branch while a previous attempt is running; never
            # continue a retry against the branch name from an obsolete snapshot.
            branch = github.pr_head_branch(pr_number=pr_number)
            worktree = _conflict_worktree(
                work_dir=work_dir,
                base=base,
                facts=last_facts,
                branch=branch,
            )
            conflict_fp = _conflict_fingerprint(
                facts=last_facts, base=base, branch=branch, reason=last_reason
            )
            result = stages.conflict(
                backend=backend,
                work_dir=worktree,
                pr_number=pr_number,
                issue_number=number if last_facts.subject.startswith(_KIND_ISSUE) else 0,
                branch=branch,
                base=base,
                context_text=_conflict_context(
                    facts=last_facts, base=base, branch=branch, reason=last_reason
                ),
            )
            if isinstance(result, dict) and result.get("delivered"):
                return f"{result.get('summary', 'Conflicts resolved and delivered')} (conflict_fp={conflict_fp})"
            last_reason = (
                str(result.get("reason", "Resolver did not deliver"))
                if isinstance(result, dict)
                else str(result)
            )
        except Exception as exc:  # noqa: BLE001 - each attempt is isolated and retriable
            last_reason = str(exc)
        _log(
            message=(
                f"… PR #{pr_number}：Conflict recovery attempt {attempt}/{_CONFLICT_RESOLUTION_ATTEMPTS} incomplete; "
                f"the next attempt will reuse or rebuild an isolated worktree: {last_reason}"
            )
        )
    conflict_fp = _conflict_fingerprint(
        facts=last_facts, base=base, branch=branch, reason=last_reason
    )
    raise git.WorkspaceError(
        f"{_CONFLICT_RETRY_PREFIX} PR #{pr_number} conflict recovery pending "
        f"（conflict_fp={conflict_fp}): {last_reason}"
    )


def _do_fix_ci(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    facts: _Facts,
    config: agent_config.AgentConfig,
) -> str:
    """Pass failures for the current head to the implementer."""
    pr_number = facts.pr_number or 0
    logs = "\n".join(github.check_logs(pr_number=pr_number))
    report = _implement_and_deliver(
        backend=backend,
        state=state,
        worktree=_pr_worktree(work_dir=work_dir, facts=facts),
        facts=facts,
        config=config,
        resuming=False,
        feedback=f"[ci] CI failed. Fix the errors reported below:\n{logs}",
        context_text=_AUTONOMOUS_CONTRACT,
    )
    return str(report.get("summary", ""))


def _do_e2e(
    *, backend: Any, state: RuntimeState, work_dir: Path, facts: _Facts, agent_id: str
) -> str:
    """Run independent verification when current-head evidence is missing.

    Post a SHA-bound evidence stamp only after a passing verdict. A later head
    must obtain its own evidence.
    """
    pr_number = facts.pr_number or 0
    verdict = engine.run_agent(
        tester,
        backend=backend,
        work_dir=_pr_worktree(work_dir=work_dir, facts=facts),
        context=context.sections(
            ("issue", _issue_body_of(facts=facts)),
            (
                "runtime context",
                f"{_AUTONOMOUS_CONTRACT}{_evidence_context(state=state, facts=facts)}",
            ),
        ),
        pr_number=pr_number,
    )
    evidence.validate_manifest(
        verdict=verdict["verdict"], evidence=verdict["evidence"], require_behavior=True
    )
    if verdict["verdict"] != "PASS":
        _log(
            message=f"✗ PR #{pr_number}：e2e failed ({verdict['reason']}); no evidence stamp posted"
        )
        return str(verdict["reason"])
    _verify_candidate(worktree=_pr_worktree(work_dir=work_dir, facts=facts), facts=facts)
    identity.post_signed_comment(
        pr_number=pr_number,
        body=(
            f"{_E2E_MARKER}{facts.head_sha} -->\n"
            f"✅ e2e passed (head `{_short(sha=facts.head_sha)}`）。\n\n{verdict['reason']}"
        ),
        agent_id=agent_id,
    )
    _log(
        message=f"✓ PR #{pr_number}：e2e passed; evidence stamp posted (head {_short(sha=facts.head_sha)}）"
    )
    return str(verdict["reason"])


def _do_review_or_fix(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    facts: _Facts,
    config: agent_config.AgentConfig,
    agent_id: str,
) -> str:
    """Review an unapproved head or send current-head findings for implementation."""
    pr_number = facts.pr_number or 0
    evidence_pack = _evidence_pack(state=state, facts=facts)
    if config.flow == agent_config.FLOW_GENERATE_ONLY:
        _clear_review_labels(pr_number=pr_number, labels=facts.labels)
        label = f"{_LABEL_REVIEW_APPROVED_PREFIX}{_short(sha=facts.head_sha)}"
        github.ensure_label(
            name=label, description="openagents generate-only: structural delivery complete"
        )
        github.add_label(pr_number=pr_number, name=label)
        _log(message=f"✓ PR #{pr_number}：generate-only structural gate passed: {label}")
        return "generate-only mechanical approval"
    if config.flow == agent_config.FLOW_MINIMAL:
        issue_number = _issue_number_of(facts=facts)
        issue = github.get_issue(number=issue_number)
        verdict = stages.acceptance(
            backend=backend,
            work_dir=_pr_worktree(work_dir=work_dir, facts=facts),
            issue_number=issue_number,
            pr_number=pr_number,
            issue_title=issue.title,
            issue_body=issue.body,
            context_text=(
                f"{_AUTONOMOUS_CONTRACT}{_MINIMAL_FLOW_CONTRACT}{_render_evidence(evidence_pack)}"
            ),
        )
        _verify_candidate(worktree=_pr_worktree(work_dir=work_dir, facts=facts), facts=facts)
        _clear_review_labels(pr_number=pr_number, labels=facts.labels)
        if verdict["verdict"] == "PASS":
            label = f"{_LABEL_REVIEW_APPROVED_PREFIX}{_short(sha=facts.head_sha)}"
            github.ensure_label(
                name=label,
                description="openagents minimal: original issue acceptance bound to head",
            )
            github.add_label(pr_number=pr_number, name=label)
            _log(message=f"✓ PR #{pr_number}：minimal acceptance {label}")
            return str(verdict["reason"])
        category = f"minimal_acceptance_{str(verdict['verdict']).lower()}"
        _fail_automation(
            subject=facts.subject,
            facts=facts,
            category=category,
            attempts=1,
            reason=str(verdict["reason"]),
            agent_id=agent_id,
        )
        _log(message=f"✗ PR #{pr_number}：minimal acceptance {verdict['verdict']}")
        return str(verdict["reason"])
    if facts.review_state == _REVIEW_CHANGES_REQUESTED and facts.review_commit_id == _short(
        sha=facts.head_sha
    ):
        issue_number = _issue_number_of(facts=facts)
        detailed_feedback = state.get_review_feedback(
            issue_number=issue_number, head_sha=facts.head_sha
        )
        report = _implement_and_deliver(
            backend=backend,
            state=state,
            worktree=_pr_worktree(work_dir=work_dir, facts=facts),
            facts=facts,
            config=config,
            resuming=False,
            feedback=(
                f"[review] Address and verify each review finding for the current head:\n"
                f"{detailed_feedback}"
                if detailed_feedback
                else "[review] Review requested changes without details. Recheck the implementation against the acceptance criteria."
            ),
            context_text=_AUTONOMOUS_CONTRACT,
        )
        return str(report.get("summary", ""))

    verdict = stages.review(
        backend=backend,
        work_dir=_pr_worktree(work_dir=work_dir, facts=facts),
        pr_number=pr_number,
        issue_number=_issue_number_of(facts=facts),
        issue_body=_issue_body_of(facts=facts),
        context_text=f"{_AUTONOMOUS_CONTRACT}{_render_evidence(evidence_pack)}",
    )
    _verify_candidate(worktree=_pr_worktree(work_dir=work_dir, facts=facts), facts=facts)
    _clear_review_labels(pr_number=pr_number, labels=facts.labels)
    prefix = (
        _LABEL_REVIEW_APPROVED_PREFIX
        if verdict["verdict"] == "PASS"
        else _LABEL_REVIEW_CHANGES_PREFIX
    )
    label = f"{prefix}{_short(sha=facts.head_sha)}"
    github.ensure_label(
        name=label, description="OpenAgents Vigil: review verdict bound to head SHA"
    )
    github.add_label(pr_number=pr_number, name=label)
    if verdict["verdict"] != "PASS":
        state.set_review_feedback(
            issue_number=_issue_number_of(facts=facts),
            head_sha=facts.head_sha,
            reason=str(verdict["reason"]),
        )
    _log(message=f"✓ PR #{pr_number}：Review verdict: {label}")
    return str(verdict["reason"])


def _evidence_pack(*, state: RuntimeState, facts: _Facts) -> list[dict[str, str]]:
    issue_number = _issue_number_of(facts=facts)
    if not issue_number:
        return []
    run = state.get_run(issue_number=issue_number) or {}
    return research.normalize(run.get("evidence_pack", []))


def _render_evidence(evidence_pack: list | None) -> str:
    rendered = research.render(evidence_pack)
    if rendered == "[]":
        return ""
    return f"\n\n--- repository evidence_pack (objective facts only) ---\n{rendered}"


def _evidence_context(*, state: RuntimeState, facts: _Facts) -> str:
    return _render_evidence(_evidence_pack(state=state, facts=facts))


def _do_ready(*, facts: _Facts) -> str:
    """Promote a draft before the remaining delivery gates are checked."""
    pr_number = facts.pr_number or 0
    github.mark_ready(pr_number=pr_number)
    _log(
        message=f"✓ PR #{pr_number}：Marked ready for review; merge eligibility will be checked next cycle"
    )
    return "Marked ready for review"


def _do_merge(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    facts: _Facts,
    flow: str = agent_config.FLOW_STANDARD,
    require_ci: bool = True,
) -> str:
    """Merge the approved non-draft candidate at its verified head.

    Recheck the irreversible merge gate before dispatch. Only close the issue
    and mark delivery done when the forge confirms the merge.
    """
    pr_number = facts.pr_number or 0
    candidate_worktree = _pr_worktree(work_dir=work_dir, facts=facts)
    # Spec-0082 generate-only deliberately has no repository-wide quality or generated-index
    # validation.  Its design artifact lives under docs/objectives (outside the standard
    # docs/specs DAG), so applying the standard OVERVIEW integrity gate makes a frozen seed with
    # a stale/missing generated index impossible to deliver even when this issue never touched
    # that tree.  Minimal still keeps the repository integrity gate because it is the
    # acceptance-bearing flow; generate-only re-reads only its compact objective digest below.
    if flow != agent_config.FLOW_GENERATE_ONLY:
        gates.assert_repository_integrity(workspace=candidate_worktree)
    issue_number = _issue_number_of(facts=facts)
    run = state.get_run(issue_number=issue_number) if issue_number else None
    approved_digest = str((run or {}).get("design_digest", ""))
    if approved_digest:
        if flow in {agent_config.FLOW_MINIMAL, agent_config.FLOW_GENERATE_ONLY}:
            stages.assert_minimal_design_approved(
                work_dir=candidate_worktree,
                issue_number=issue_number,
                approved_digest=approved_digest,
            )
        else:
            gates.assert_design_approved(
                workspace=candidate_worktree,
                issue_number=issue_number,
                approved_digest=approved_digest,
            )
    if flow in {agent_config.FLOW_MINIMAL, agent_config.FLOW_GENERATE_ONLY}:
        with _MECHANICAL_MERGE_LOCK:
            report = stages.merge_mechanical(
                pr_number=pr_number,
                head_sha=facts.head_sha or "",
                require_ci=require_ci,
            )
    else:
        report = stages.merge(
            backend=backend,
            pr_number=pr_number,
            head_sha=facts.head_sha or "",
            work_dir=candidate_worktree,
            context_text=_AUTONOMOUS_CONTRACT,
            require_ci=require_ci,
        )
    if not report["merged"]:
        raise gates.MergeNotReady(f"PR #{pr_number} not yet merged: {report.get('summary', '')}")
    number = issue_number
    if number:
        state.set_run(
            issue_number=number,
            status="done",
            branch=f"{_BRANCH_PREFIX}{number}",
            pr_number=pr_number,
        )
        github.close_issue(number=number)
    _log(message=f"✓ PR #{pr_number}：Merged")
    return "merged"


def _clear_review_labels(*, pr_number: int, labels: frozenset[str]) -> None:
    """Remove old SHA-bound review labels before posting a new decision."""
    for label in sorted(labels):
        if label.startswith((_LABEL_REVIEW_APPROVED_PREFIX, _LABEL_REVIEW_CHANGES_PREFIX)):
            github.remove_label(pr_number=pr_number, name=label)


def _pr_worktree(*, work_dir: Path, facts: _Facts) -> Path:
    """Prepare the PR branch worktree for an agent.

    Keep undelivered work and an unfinished rebase when recovering. Rebuild
    only when an isolated candidate can be prepared without losing work.
    """
    kind, number = _split_subject(subject=facts.subject)
    if kind == _KIND_ISSUE:
        return git.Workspace(work_dir=Path(work_dir)).ensure(
            issue_number=number, branch=f"{_BRANCH_PREFIX}{number}"
        )
    return git.Workspace(work_dir=Path(work_dir)).ensure(
        issue_number=number, branch=github.pr_head_branch(pr_number=facts.pr_number or number)
    )


def _issue_number_of(*, facts: _Facts) -> int:
    """Return the linked issue number, or zero for a standalone PR."""
    kind, number = _split_subject(subject=facts.subject)
    return number if kind == _KIND_ISSUE else 0


def _issue_body_of(*, facts: _Facts) -> str:
    """Return the issue acceptance context, or empty text for a standalone PR."""
    number = _issue_number_of(facts=facts)
    return github.get_issue(number=number).body if number else ""


def _has_attempt_stamp(*, facts: _Facts, fp: str) -> bool:
    """Check signed comments for an attempt stamp matching this fingerprint."""
    return any(
        f"{_ATTEMPT_MARKER} fp={fp} -->" in comment.body for comment in _comments(facts=facts)
    )


def _post_attempt_stamp(*, facts: _Facts, fp: str, conclusion: str, agent_id: str) -> None:
    """Post a signed report when an action did not change the observed facts."""
    body = (
        f"{_ATTEMPT_MARKER} fp={fp} -->\n"
        f"🔁 OpenAgents Vigil: the action did not change the observed state. No further agent call will be made for this fingerprint.\n\n"
        f"Agent report: {conclusion or '(none)'}"
    )
    if facts.pr_number is not None:
        identity.post_signed_comment(pr_number=facts.pr_number, body=body, agent_id=agent_id)
    else:
        github.issue_comment(
            number=_issue_number_of(facts=facts), body=identity.sign(body=body, agent_id=agent_id)
        )
    _log(message=f"🔁 {facts.subject}: No progress; posted attempt stamp (fp={fp}）")


def _comments(*, facts: _Facts) -> list[github.Comment]:
    """Read the PR comment stream if available, otherwise read the issue stream."""
    if facts.pr_number is not None:
        return github.list_comments(pr_number=facts.pr_number)
    return github.list_issue_comments(number=_issue_number_of(facts=facts))


def _failure_comments(*, subject: str) -> list[github.Comment]:
    """Read failure markers from the same object as the writer (Spec-0088/T2)."""
    kind, number = _split_subject(subject=subject)
    if kind == _KIND_ISSUE:
        return github.list_issue_comments(number=number)
    return github.list_comments(pr_number=number)


def _fail_automation(
    *,
    subject: str,
    facts: _Facts,
    category: str,
    attempts: int,
    reason: str,
    agent_id: str,
    projection_fp: str | None = None,
) -> None:
    """Persist an idempotent, self-reviving machine-failure terminal projection."""
    fp = projection_fp or _fingerprint(facts=facts)
    marker = f"{_FAILURE_MARKER} fp={fp} category={category} -->"
    body = (
        f"{marker}\n"
        f"⚠️ OpenAgents automation failure\n\n"
        f"- category: `{category}`\n"
        f"- attempts: `{attempts}`\n"
        f"- projection fingerprint: `{fp}`\n"
        f"- at: `{datetime.now(UTC).isoformat()}`\n\n"
        f"Last error: {reason}\n\n"
        "Vigil will not call the model again for the same observed state. When relevant facts change, it clears the failure state and re-evaluates."
    )
    kind, number = _split_subject(subject=subject)
    signed = identity.sign(body=body, agent_id=agent_id)
    if kind == _KIND_ISSUE:
        github.issue_add_label(number=number, name=_LABEL_AUTOMATION_FAILED)
        if not any(marker in comment.body for comment in github.list_issue_comments(number=number)):
            github.issue_comment(number=number, body=signed)
    else:
        github.add_label(pr_number=number, name=_LABEL_AUTOMATION_FAILED)
        if not any(marker in comment.body for comment in github.list_comments(pr_number=number)):
            github.post_comment(pr_number=number, body=signed)
    _log(message=f"⚠ {subject}: Recorded {_LABEL_AUTOMATION_FAILED}（{category}, fp={fp}）")


def _already_said(*, comments: list[github.Comment], body: str) -> bool:
    """Deduplicate comments by unsigned body so changing agent IDs do not matter."""
    return any(
        identity.parse_agent_id(body=comment.body) is not None and body.strip() in comment.body
        for comment in comments
    )


# --------------------------------------------------------------------------------------------------
# Share the backend wall-clock budget. Exhaustion does not imply a dead worker.
# --------------------------------------------------------------------------------------------------


class _TimedBackend:
    """Bound the wall-clock duration of a single backend invocation.

    Track the process tree started by this invocation, not unrelated workers.
    On timeout, request termination and raise _ActTimeout. The worker decides
    whether to retry or record failure.
    """

    def __init__(self, *, inner: Any, timeout_seconds: float, lock_fd: int | None) -> None:
        self._inner = inner
        self._timeout_seconds = timeout_seconds
        self._lock_fd = lock_fd

    def run(self, *, work_dir: Path, task: str, context: str) -> Any:
        """Run a backend invocation or raise after its wall-clock budget expires."""
        box: dict[str, Any] = {}
        thread = threading.Thread(
            target=self._call,
            kwargs={"box": box, "work_dir": work_dir, "task": task, "context": context},
            daemon=True,
        )
        thread.start()
        thread.join(timeout=self._timeout_seconds if self._timeout_seconds > 0 else None)
        spawned = proc.untrack(thread_id=thread.ident or 0)
        proc.release_fds(thread_id=thread.ident or 0)
        if thread.is_alive():
            for pid, handle in sorted(spawned.items()):
                proc.kill_tree(
                    pid=pid, handle=handle
                )  # Check the process handle to avoid killing a reused PID.
            raise _ActTimeout(
                f"Agent invocation exceeded its wall-clock limit of {self._timeout_seconds:g}s. "
                f"Requested termination of process tree {sorted(spawned)}"
            )
        if "error" in box:
            raise box["error"]
        return box["result"]

    def _call(self, *, box: dict[str, Any], work_dir: Path, task: str, context: str) -> None:
        """Run the underlying backend in a thread and relay its result or exception."""
        # Register the descriptor inside the try block so errors such as EBADF are returned to the
        # caller, not lost in the worker thread.
        try:
            proc.track()
            if self._lock_fd is not None:
                proc.hold_fd(fd=self._lock_fd)
            box["result"] = self._inner.run(work_dir=work_dir, task=task, context=context)
        except BaseException as exc:  # noqa: BLE001 - Relay the original error to the caller.
            box["error"] = exc


# --------------------------------------------------------------------------------------------------
# Run each repository in a process with its own Git and forge working directory.
# --------------------------------------------------------------------------------------------------


def _run_repo_inline(
    *,
    repo: agent_config.RepoPlan,
    agents: agent_config.AgentPolicy,
    release: agent_config.ReleasePolicy,
    once: bool,
) -> None:
    """Run Vigil in the current process for one repository."""
    from openagents import cli
    from openagents.utils import config as config_mod

    ctx = config_mod.resolve_project()
    if ctx is None:
        raise RuntimeError(f"{repo.path} is not a Git repository; Vigil cannot watch it")
    backend, state, agent_id = cli._vigil_deps_for(ctx=ctx)
    from openagents.runtime import legacy

    legacy.assert_migrated(state=state)
    run_vigil(
        backend=backend,
        state=state,
        work_dir=ctx.repo_root,
        config=_repo_as_config(repo=repo, agents=agents, release=release),
        once=once,
        agent_id=agent_id,
    )


def _repo_as_config(
    *,
    repo: agent_config.RepoPlan,
    agents: agent_config.AgentPolicy,
    release: agent_config.ReleasePolicy,
) -> agent_config.AgentConfig:
    """Resolve a single-repository configuration from a fleet plan."""
    return agent_config.AgentConfig(
        version=1,
        agents=agents,
        stages=repo.stages,
        release=release,
        interval=repo.interval,
        base=repo.base,
        labels=repo.labels,
        repos=[repo],
        flow=repo.flow,
        coordination=repo.coordination,
        execution_evidence_required=repo.execution_evidence_required,
    )


def _run_repo_entry(*, plan: agent_config.RepoPlan, log_queue: Any, once: bool) -> None:
    """Set the child working directory, then run Vigil and report failures."""
    from openagents.utils import fleet as fleet_util

    os.chdir(plan.path)
    writer = fleet_util._QueueWriter(name=plan.name, log_queue=log_queue)
    original_stderr = sys.stderr
    sys.stderr = writer
    try:
        _run_repo_inline(
            repo=plan,
            agents=agent_config.AgentPolicy(backends={}),
            release=agent_config.ReleasePolicy(),
            once=once,
        )
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 - Report child process errors to the caller.
        log_queue.put((plan.name, f"✗ Vigil failed: {exc}"))
        raise SystemExit(1) from exc
    finally:
        writer.flush()
        sys.stderr = original_stderr


def _default_spawn(*, plan: agent_config.RepoPlan, log_queue: Any, once: bool) -> Any:
    """Start an isolated process for a repository plan."""
    import multiprocessing

    process = multiprocessing.Process(
        target=_run_repo_entry,
        kwargs={"plan": plan, "log_queue": log_queue, "once": once},
        name=plan.name,
        daemon=True,
    )
    process.start()
    return process


def _log(*, message: str) -> None:
    """Write Vigil progress to stderr."""
    print(message, file=sys.stderr, flush=True)
