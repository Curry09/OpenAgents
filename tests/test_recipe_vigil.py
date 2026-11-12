"""Spec-0065/T2: recipes.vigil - level-triggered contract measurement for Vigil.

Nailed to five in the order of spec §14:
-** Perceptions**: `_classify` 4 values by branch + `in_flight` before everything; `_fingerprint` field set constant equals `_Facts` complete set,
  Without clocks,** without commment id** (fp must be equal before and after a capt - this direct nail to the guard is not self-destructive);
  `_sense` at the time of possible UNKNOWN** not read at all by CI**; `_watchdog` by reston slot.
- **Queue**：`_claim_next` exactly-once Not running double;`INSERT OR IGNORE` (a) Arguments, etc.;`_mark_done` yes DELETE(No, it’s not.
  `status='done'` - UNIQUE binding locks subproject permanently to death.
** Survivors’ Detection (Ben spec’s Core Claim, Zero Double)**: Holders Alive  →  EWOLDBLONK ** Lines remain the same** (even if they are beyond)**
  IN_FLIGHT alarm threshold, which is also only `_park`, which is never recycled; the holder is locked by `kill -9` kernel  →   →  ** immediately** returned
  Wait for any timeout; two fd each other with process (** failure with `lockf`** — crucifying must be doneflock); ** close after deletion (fd)**.
- **- Cut!**：`_act` Hard timeout → The killing process. + Throw → The Holder himself `_requeue_or_park`；`attempts` Top → needs-human。
-** Shutdown**: agent returns structured `needs-human`  →  Vigil
  `review-approved:<sha7>` must be ssha equal to the current head only mass, sha/ nud label always descend back into review-or-fix.

Full time off backend + - Prick. github/git/stages  Don’t touch the truth   LLM/Network/Warehouse.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import (
    _ACT_E2E,
    _ACT_FIX_CI,
    _ACT_MERGE,
    _ACT_READY,
    _ACT_REBASE,
    _ACT_REPLY,
    _ACT_REVIEW_OR_FIX,
    _ACT_SOLVE,
    _ACTIONABLE,
    _AWAITING_BLOCKERS,
    _AWAITING_CI,
    _AWAITING_EFFECT,
    _AWAITING_MERGEABILITY,
    _IN_FLIGHT,
    _MAX_ATTEMPTS,
    _QUIET,
    _TERMINAL,
    _ActTimeout,
    _claim_next,
    _classify,
    _Clock,
    _connect,
    _consider,
    _enqueue,
    _Facts,
    _fingerprint,
    _has_cycle,
    _init_db,
    _intake,
    _lock_path,
    _mark_done,
    _Observed,
    _proposed_edges,
    _reclaim_dead,
    _reconcile,
    _refresh_failure_projection,
    _requeue_or_park,
    _sense,
    _TimedBackend,
    _try_lock,
    _Verdict,
    _watchdog,
    route,
    run_vigil,
)
from openagents.runtime import engine
from openagents.utils import agent_config, github, identity

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_HEAD = "abc1234def5678901234567890123456789abcde"
_SHA7 = _HEAD[:7]


# --------------------------------------------------------------------------------------------------
# Plugin: acts model + put a gthub on.
# --------------------------------------------------------------------------------------------------


def _facts(**overrides) -> _Facts:
    """A ”all-in-all, all-in-all” fact sheet (subsection 11), with individual fields being changed as needed."""
    base = _Facts(
        subject="issue:5",
        pr_number=12,
        head_sha=_HEAD,
        merged=False,
        closed=False,
        labels=frozenset({f"review-approved:{_SHA7}"}),
        deps_done=True,
        mergeable_state="clean",
        ci="success",
        e2e_head_sha=_HEAD,
        review_state="APPROVED",
        review_commit_id=_SHA7,
        latest_comment_is_ours=True,
    )
    return replace(base, **overrides)


def _stages(**owners) -> agent_config.StagePolicy:
    return agent_config.StagePolicy(owners=owners)


def _config(**overrides) -> agent_config.AgentConfig:
    defaults = {
        "version": 1,
        "agents": agent_config.AgentPolicy(backends={}),
        "stages": _stages(),
        "release": agent_config.ReleasePolicy(),
        "interval": 1,
        "base": "main",
        "labels": ["openagents"],
        "repos": [],
    }
    return agent_config.AgentConfig(**(defaults | overrides))


def _db(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    db_path = tmp_path / ".openagents" / "vigil-queue.db"
    _init_db(db_path=db_path)
    return db_path, _connect(db_path=db_path)


# --------------------------------------------------------------------------------------------------
# Perception 1: _classify Quad-value list (order is correct).
# --------------------------------------------------------------------------------------------------


def test_classify_in_flight_precedes_machine_failure_terminal():
    facts = _facts(labels=frozenset({"automation-failed"}))
    assert _classify(facts=facts, in_flight=True).kind == _IN_FLIGHT
    assert _classify(facts=facts, in_flight=False).kind == _TERMINAL


@pytest.mark.parametrize(
    "overrides,kind,reason,action",
    [
        ({"merged": True}, _TERMINAL, None, None),
        ({"closed": True}, _TERMINAL, None, None),
        ({"labels": frozenset({"automation-failed"})}, _TERMINAL, None, None),
        ({"latest_comment_is_ours": False}, _ACTIONABLE, None, _ACT_REPLY),
        ({"deps_done": False}, _QUIET, _AWAITING_BLOCKERS, None),
        ({"pr_number": None}, _ACTIONABLE, None, _ACT_SOLVE),
        ({"mergeable_state": "unknown"}, _QUIET, _AWAITING_MERGEABILITY, None),
        ({"mergeable_state": None}, _QUIET, _AWAITING_MERGEABILITY, None),
        ({"mergeable_state": "dirty"}, _ACTIONABLE, None, _ACT_REBASE),
        ({"ci": "pending"}, _QUIET, _AWAITING_CI, None),
        (
            {"ci": "none"},
            _QUIET,
            _AWAITING_CI,
            None,
        ),  # No checks yet; wait for CI.
        ({"ci": "failure"}, _ACTIONABLE, None, _ACT_FIX_CI),
        ({"e2e_head_sha": None}, _ACTIONABLE, None, _ACT_E2E),
        ({"e2e_head_sha": "0" * 40}, _ACTIONABLE, None, _ACT_E2E),  # Evidence is old.
        (
            {"is_draft": True},
            _ACTIONABLE,
            None,
            _ACT_READY,
        ),  # Spec-0017: draft Zort
        (
            # Spec-0074 empirical return: Gitea vs. draft PR constant mediaable: false ( → DIRTY).
            # Unable to determine that otherwise the draft card rebase will never be corrected. draft is unconditionally placed before 56.
            {"is_draft": True, "mergeable_state": "dirty"},
            _ACTIONABLE,
            None,
            _ACT_READY,
        ),
        (
            {
                "is_draft": True,
                "mergeable_state": "unknown",
            },  # Same: not blocked by ailing-mergeability
            _ACTIONABLE,
            None,
            _ACT_READY,
        ),
        ({}, _ACTIONABLE, None, _ACT_MERGE),  # It's not datter that counts.
    ],
)
def test_classify_branch_table(overrides, kind, reason, action):
    verdict = _classify(facts=_facts(**overrides), in_flight=False)
    assert (verdict.kind, verdict.reason, verdict.action) == (kind, reason, action)


def test_classify_draft_promotion_precedes_whole_merge_pipeline():
    """Spec-0017 + Spec-0074 empirical: draft  →  ** must drop ready** and be before the whole ** mergeable/CI/review current line.

    #168：draft PR It doesn’t work.merge:human And so was the other. draft Wall.Spec-0074：Gitea Yeah. draft Report mergeable:false，
    The shift will be locked to death if it is scheduled after a decision is made - so the draft is unconditionally, physically, before 5678910112.
    """
    # All green – ready (in line with old behaviour).
    assert _classify(facts=_facts(is_draft=True), in_flight=False).action == _ACT_READY
    # draft superimposes any subsequent flow of water line state (dirty/CI red/unevaluated) and is still corrected - proof that the draft branch physics is pre-empted and unconditional.
    for pipeline_state in (
        {"mergeable_state": "dirty"},  # Gitea Draft's Real Report
        {"mergeable_state": "unknown"},
        {"ci": "failure"},
        {"review_state": "REWORK", "review_commit_id": None},
    ):
        verdict = _classify(facts=_facts(is_draft=True, **pipeline_state), in_flight=False)
        assert verdict.action == _ACT_READY, pipeline_state
        assert verdict.action != _ACT_MERGE
    # Non-draft same facts  → merge: certify that the transfer is triggered only by draft, and non draft normally reaches merge.
    assert _classify(facts=_facts(is_draft=False), in_flight=False).action == _ACT_MERGE


def test_classify_reply_precedes_merge_because_merge_is_irreversible():
    """People’s new comments are before merge -- ”Feed up, I have doubts” -- and must be taken.** Merger is irreversible.**"""
    facts = _facts(
        latest_comment_is_ours=False
    )  # The rest of the fields are green, should be merge
    assert _classify(facts=facts, in_flight=False).action == _ACT_REPLY


def test_classify_conflict_precedes_ci():
    """The conflict is ahead of the CI-the conflict PR can’t get merge ref, GitHub doesn’t check, read the CI and read ”Always wait.”"""
    facts = _facts(mergeable_state="dirty", ci="failure")
    assert _classify(facts=facts, in_flight=False).action == _ACT_REBASE


# --------------------------------------------------------------------------------------------------
# Sensory 2: Review decision binds a committee - ssha to a label or merges code that no one has ever examined.
# --------------------------------------------------------------------------------------------------


def test_review_approved_with_current_head_sha_merges():
    assert _classify(facts=_facts(), in_flight=False).action == _ACT_MERGE


def test_review_approved_with_stale_sha_never_merges():
    """After the trial, agent put a push on it: the ruling tied to the old committee had to be dropped back to 10,** never merge**."""
    stale = _facts(review_commit_id="0000000", labels=frozenset({"review-approved:0000000"}))
    verdict = _classify(facts=stale, in_flight=False)
    assert verdict.action == _ACT_REVIEW_OR_FIX
    assert verdict.action != _ACT_MERGE


def test_bare_review_approved_label_is_not_honored():
    """Naked `review-approved` (no ssha) is not recognized - it’s the bug that’s the ”merging unreviewed code”."""
    state, commit = vigil_module._review_from_labels(labels={"review-approved"})
    assert (state, commit) == (None, None)
    bare = _facts(review_state=None, review_commit_id=None, labels=frozenset({"review-approved"}))
    assert _classify(facts=bare, in_flight=False).action == _ACT_REVIEW_OR_FIX


def test_changes_requested_outranks_approved():
    """Two decisions (which were reviewed and returned) were also filed (CHANGES_REQUESTED priority)."""
    state, _ = vigil_module._review_from_labels(
        labels={f"review-approved:{_SHA7}", f"review-changes-requested:{_SHA7}"}
    )
    assert state == "CHANGES_REQUESTED"


# --------------------------------------------------------------------------------------------------
# Perception 3: _fingerprint - Field Set  → Facts Full; does not contain clock;** does not contain a contact id** (self-destruct switch for column I).
# --------------------------------------------------------------------------------------------------


def test_fingerprint_covers_exactly_every_facts_field():
    """fp , and then click the input set ≡ `dataclasses.fields(_Facts)` Full set: one field leak = The silent blinding of a whole kind of work."""
    baseline = _fingerprint(facts=_facts())
    mutations = {
        "subject": "issue:6",
        "pr_number": 99,
        "head_sha": "f" * 40,
        "merged": True,
        "closed": True,
        "labels": frozenset({"x"}),
        "deps_done": False,
        "mergeable_state": "dirty",
        "ci": "failure",
        "e2e_head_sha": None,
        "review_state": "CHANGES_REQUESTED",
        "review_commit_id": "0000000",
        "latest_comment_is_ours": False,
        "is_draft": True,  # Spec-0017/T2: Change True → False to fp and mark it as real progress.
        "material_digest": "changed-material",
    }
    assert set(mutations) == {field.name for field in fields(_Facts)}
    for name, value in mutations.items():
        assert _fingerprint(facts=_facts(**{name: value})) != baseline, f"{name} Not entered fp"


def test_fingerprint_ignores_clock():
    """`_Clock` does not enter fp:check brushes `started_at` as soon as it runs, mixing it with agent will be called repeatedly (the one that is not in the column)."""
    assert "last_progress_at" not in {field.name for field in fields(_Facts)}
    assert _fingerprint(facts=_facts()) == _fingerprint(
        facts=_facts()
    )  # Identical facts produce the same fingerprint.


def test_fingerprint_unchanged_by_our_own_comment(monkeypatch):
    """** Col. No Self-Default**: fp must be equal before and after the Guy Attempt jab (a new comment) - otherwise the jab will be scrapped on the spot and indefinitely called agent."""
    posted: list[str] = []
    monkeypatch.setattr(
        vigil_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(body),
    )
    before = _fingerprint(facts=_facts())
    vigil_module._post_attempt_stamp(facts=_facts(), fp=before, conclusion="flaky", agent_id="a")
    # The stamp adds only one comment: `latest_comment_is_ours` is still True and facts do not contain a comment id id  → fp.
    assert _fingerprint(facts=_facts()) == before
    assert posted and f"fp={before}" in posted[0]


# --------------------------------------------------------------------------------------------------
# Perception 4: _sense — universal UNKNOWN** not read by CI**; tri-state skip is divided into "passed gate"
# --------------------------------------------------------------------------------------------------


def _snapshot(**overrides) -> github.PRSnapshot:
    base = {
        "number": 12,
        "state": "OPEN",
        "head_sha": _HEAD,
        "labels": (),
        "mergeable": "MERGEABLE",
        "merge_state_status": "CLEAN",
        "head_pushed_at": "2026-07-14T10:00:00Z",
    }
    return github.PRSnapshot(**(base | overrides))


def _patch_sense(monkeypatch, *, snapshot, comments=(), blockers=(), on_checks=None):
    monkeypatch.setattr(
        vigil_module.github, "get_issue", lambda *, number: github.Issue(5, "T", "B", [])
    )
    monkeypatch.setattr(vigil_module.github, "list_blocked_by", lambda *, number: list(blockers))
    monkeypatch.setattr(vigil_module.github, "pr_for_branch", lambda *, branch: github.PR(12, "u"))
    monkeypatch.setattr(vigil_module.github, "pr_snapshot", lambda *, pr_number: snapshot)
    monkeypatch.setattr(vigil_module.github, "list_comments", lambda *, pr_number: list(comments))
    monkeypatch.setattr(
        vigil_module.github,
        "check_snapshot",
        on_checks or (lambda *, pr_number: github.CheckSnapshot("pass", 3, "2026-07-14T11:00:00Z")),
    )


def test_sense_does_not_read_ci_when_mergeability_unknown(monkeypatch):
    """The #CiClosed Symptoms will cover the cause of the conflict."""

    def _boom(*, pr_number):
        raise AssertionError("UnknowN is not allowed to read CI")

    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(mergeable="UNKNOWN", merge_state_status="UNKNOWN"),
        on_checks=_boom,
    )
    observed = _sense(config=_config(), subject="issue:5")
    assert observed.facts.mergeable_state == "unknown"
    assert _classify(facts=observed.facts, in_flight=False).reason == _AWAITING_MERGEABILITY


def test_sense_zero_checks_is_awaiting_ci_not_green(monkeypatch):
    """The current zero check of the head `none` QuiET (awaiting-ci)** is not ”CI green”**."""
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(),
        on_checks=lambda *, pr_number: github.CheckSnapshot("pass", 0, ""),
    )
    facts = _sense(config=_config(), subject="issue:5").facts
    assert facts.ci == "none"
    assert _classify(facts=facts, in_flight=False).reason == _AWAITING_CI


def test_sense_reads_is_draft_from_snapshot(monkeypatch):
    """Spec-0017/T2: `_sense` read pr_snapshot.is_draft when `_classify` is green + programmed"""
    # e2e:skip pegs the evidence to a head (this test only concerns draft); review stays ant, with real review-approved label.
    config = _config(stages=_stages(e2e="skip"))
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(labels=(f"review-approved:{_SHA7}",), is_draft=True),
    )
    facts = _sense(config=config, subject="issue:5").facts
    assert facts.is_draft is True
    assert _classify(facts=facts, in_flight=False).action == _ACT_READY
    # Non-draft co-source  → merge (proves that is_draft is a first-class fact per tick check).
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(labels=(f"review-approved:{_SHA7}",), is_draft=False),
    )
    facts = _sense(config=config, subject="issue:5").facts
    assert facts.is_draft is False
    assert _classify(facts=facts, in_flight=False).action == _ACT_MERGE


def test_sense_normalizes_skip_gates_as_already_passed(monkeypatch):
    """The 3-State `skip` has been added to the ”de facto past the gate” in `_sense`, so that `_classify` remains purely mechanical and does not eat config."""
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(),
        on_checks=lambda *, pr_number: github.CheckSnapshot("fail", 2, "2026-07-14T11:00:00Z"),
    )
    config = _config(stages=_stages(ci="skip", e2e="skip", review="skip", merge="human"))
    facts = _sense(config=config, subject="issue:5").facts
    assert facts.ci == "success"
    assert facts.e2e_head_sha == _HEAD
    assert (facts.review_state, facts.review_commit_id) == ("APPROVED", _SHA7)
    assert _classify(facts=facts, in_flight=False).action == _ACT_MERGE


def test_sense_still_sees_the_pr_after_it_is_merged(monkeypatch):
    """PR merges and disappears from the open list - `_sense` reads completed issue as ”P” if you use open-only.

    The result is not a missing field, but ** to redo the same issue as the whole** (subsection 4 Solve opens another PR). So here’s the nail:
    `_sense` Cha. PR Let’s go. `pr_for_branch`(open-ended),merged I can read it. → `_classify` Judgement TERMINAL。
    """
    monkeypatch.setattr(vigil_module.github, "find_pr_by_branch", lambda *, branch: None)  # open
    _patch_sense(monkeypatch, snapshot=_snapshot(state="MERGED"))
    facts = _sense(config=_config(), subject="issue:5").facts
    assert (facts.pr_number, facts.merged) == (12, True)
    assert _classify(facts=facts, in_flight=False).kind == _TERMINAL


def test_sense_reads_deps_from_native_blocked_by(monkeypatch):
    """Reliance on reading by-dot GitHub native `blocked_by`; responding to the autostate  →  call at a time to get both ”side” and ”sun-off”"""
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(),
        blockers=[github.Blocker(4, "OPEN"), github.Blocker(3, "CLOSED")],
    )
    facts = _sense(config=_config(), subject="issue:5").facts
    assert facts.deps_done is False
    assert _classify(facts=facts, in_flight=False).reason == _AWAITING_BLOCKERS


def test_sense_clock_uses_head_push_time_when_no_checks_no_comments(monkeypatch):
    """PR: `last_progress_at` must come from the head push time -- otherwise the watchdog never rings."""
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(),
        on_checks=lambda *, pr_number: github.CheckSnapshot("pass", 0, ""),
    )
    observed = _sense(config=_config(), subject="issue:5")
    assert observed.clock.last_progress_at == datetime(2026, 7, 14, 10, 0, tzinfo=UTC)


def test_sense_clock_reads_the_issue_comments_when_there_is_no_pr_yet(monkeypatch):
    """Not yet PR issue, progress clock must go from **issue’s own comment** - otherwise `last_progress_at` constant `None`,
    The second guard (QuiET door dog) permanently expires throughout `solve`**: an empty solve (agent running or pushing PR  → fp unchanged)
     →  Quixiet (awaiting-effect) will die silently and permanently, `_watchdog` will return directly because Noone
    False, Neds-human never triggers. Attempt falls on issue, reads it, and the watchdogs calculates the age."""
    monkeypatch.setattr(
        vigil_module.github, "get_issue", lambda *, number: github.Issue(7, "T", "B", [])
    )
    monkeypatch.setattr(vigil_module.github, "list_blocked_by", lambda *, number: [])
    monkeypatch.setattr(
        vigil_module.github, "pr_for_branch", lambda *, branch: None
    )  # Not yet, PR.
    stamp = github.Comment(
        id="IC_1",
        author="openagents-bot",
        body="<!-- openagents:attempt fp=abc -->",
        created_at="2026-07-14T12:00:00Z",
        author_association="OWNER",
    )
    monkeypatch.setattr(vigil_module.github, "list_issue_comments", lambda *, number: [stamp])

    observed = _sense(config=_config(), subject="issue:7")

    assert observed.facts.pr_number is None
    assert observed.clock.last_progress_at == datetime(2026, 7, 14, 12, 0, tzinfo=UTC), (
        "None-PR issue The clock didn't read. issue Comments → last_progress_at Constant None → The watchdog never rings. → Quiet and permanent death."
    )


def test_sense_reads_e2e_evidence_stamp(monkeypatch):
    """e2e The evidence is a comment with a head trace; head is moved and evidence automatically invalidates branch 9."""
    body = vigil_module.identity.sign(
        body=f"<!-- openagents:e2e head={_HEAD} -->\n → e2e Passed", agent_id="bot"
    )
    stamp = github.Comment(1, "bot", body, "2026-07-14T11:00:00Z")
    _patch_sense(monkeypatch, snapshot=_snapshot(), comments=[stamp])
    assert _sense(config=_config(), subject="issue:5").facts.e2e_head_sha == _HEAD

    _patch_sense(monkeypatch, snapshot=_snapshot(head_sha="f" * 40), comments=[stamp])
    facts = _sense(config=_config(), subject="issue:5").facts
    assert facts.e2e_head_sha != facts.head_sha  # Old evidence is not recognized.
    assert _classify(facts=facts, in_flight=False).action == _ACT_E2E


# --------------------------------------------------------------------------------------------------
# Perception 5: Watchdogs are in reason slots (Battle 2).
# --------------------------------------------------------------------------------------------------


def test_watchdog_fires_per_reason_threshold():
    clock = _Clock(last_progress_at=_NOW - timedelta(seconds=600))
    thresholds = {_AWAITING_CI: 3600, _AWAITING_EFFECT: 300, _AWAITING_BLOCKERS: None}
    assert not _watchdog(  # 10 min < 1 hour: CI is still running
        verdict=_Verdict(kind=_QUIET, reason=_AWAITING_CI),
        clock=clock,
        thresholds=thresholds,
        now=_NOW,
    )
    assert _watchdog(  # 10 minutes > 5 minutes: agent shot but hasn't moved yet, call for help.
        verdict=_Verdict(kind=_QUIET, reason=_AWAITING_EFFECT),
        clock=clock,
        thresholds=thresholds,
        now=_NOW,
    )
    assert not _watchdog(  # None = no doorkeeper (blocker has his own housekeeper dog upstream)
        verdict=_Verdict(kind=_QUIET, reason=_AWAITING_BLOCKERS),
        clock=clock,
        thresholds=thresholds,
        now=_NOW,
    )
    assert not _watchdog(  # QuiET, no doorkeeper.
        verdict=_Verdict(kind=_ACTIONABLE, action=_ACT_MERGE),
        clock=clock,
        thresholds=thresholds,
        now=_NOW,
    )


# --------------------------------------------------------------------------------------------------
# Queue: / Exactly-once collect / _mark_done is DelETE.
# --------------------------------------------------------------------------------------------------


def test_enqueue_is_idempotent_via_subject_unique(tmp_path):
    """`subject` UniQUE + `INSERT OR IGNORE`: No-op (level-triggered) per tick inbound."""
    _, conn = _db(tmp_path)
    assert _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW) is True
    assert _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW) is False
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 1


def test_claim_next_is_exactly_once(tmp_path):
    """Two times you get the same line of air space for the second time. This is exactly what GitHub label can’t do."""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    first = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w1", now=_NOW)
    assert first is not None
    row, fd = first
    assert (row["subject"], row["status"], row["attempts"]) == ("issue:5", "claimed", 1)
    assert _claim_next(conn=conn, work_dir=tmp_path, worker_id="w2", now=_NOW) is None
    os.close(fd)


def test_claim_next_orders_by_priority_then_fifo(tmp_path):
    """`ORDER BY priority DESC, enqueued_at ASC` is requested when ** is received (the priority of long waiting passes is not frozen at the time of entry)."""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:1", priority=1, now=_NOW)
    _enqueue(conn=conn, subject="pr:2", priority=6, now=_NOW + timedelta(seconds=10))
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    assert row["subject"] == "pr:2"  # Back in line, but first priority.
    os.close(fd)


def test_mark_done_deletes_the_row(tmp_path):
    """** Must be Delete**: Leave a `status='done'` row permanently locked to death (never in line) because of the UNIQUE constraint."""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    _mark_done(conn=conn, task_id=row["id"], fd=fd)
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0
    assert (
        _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW) is True
    )  # I can get in the line again.


def test_mark_done_deletes_row_before_closing_fd(tmp_path, monkeypatch):
    """** Delete first line, then close (fd)**: In turn, a window will be opened to get `_reclaim_dead` to grab the lock and hit back queued back and run."""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    seen: list[int] = []
    real_close = os.close

    def _spy_close(target_fd):
        seen.append(conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0])
        real_close(target_fd)

    monkeypatch.setattr(vigil_module.os, "close", _spy_close)
    _mark_done(conn=conn, task_id=row["id"], fd=fd)
    assert seen == [0], "The moment of the line must have been deleted."


# --------------------------------------------------------------------------------------------------
# Survivors (** Core assertion of this spec: zero doubles**): Flock is the reason for death, not the lease.
# --------------------------------------------------------------------------------------------------


def test_two_fds_in_same_process_are_mutually_exclusive(tmp_path):
    """** The lock that must be frozen, not locked**:lockf is per-process, and the two fds of the process do not rebuff each other and the k-lines are silent.

    This module is a ”K-K-worker thread” -- this assertion is the moat that was chosen. It will fail when `fcntl.lockf` is replaced.
    """
    path = tmp_path / "claims" / "issue-5.lock"
    first = _try_lock(path=path)
    assert first is not None
    assert _try_lock(path=path) is None, "The second fd of the process must be unlocked."
    os.close(first)
    second = _try_lock(path=path)
    assert second is not None  # Once released, you can rob again.
    os.close(second)


def test_reclaim_leaves_row_alone_while_holder_is_alive(tmp_path):
    """The holder** lives** EWOLDBLONK** stays the same.** Recycles a live holder’s walk, by definition, double-drive."""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w1", now=_NOW)
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 0
    after = conn.execute(
        "SELECT status, worker FROM work_queue WHERE id=?", (row["id"],)
    ).fetchone()
    assert (after["status"], after["worker"]) == ("claimed", "w1")
    assert (
        _claim_next(conn=conn, work_dir=tmp_path, worker_id="w2", now=_NOW) is None
    )  # I can't take it.
    os.close(fd)


def test_reclaim_leaves_row_alone_even_past_inflight_alarm_age(tmp_path):
    """Even if `claimed_at` is above the IN_FLIGHT threshold:  →  ** Only `_park` is still alive, never recycle**."""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    ancient = _NOW - timedelta(seconds=vigil_module._INFLIGHT_ALARM_SECONDS * 3)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w1", now=ancient)
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 0
    after = conn.execute(
        "SELECT status, worker FROM work_queue WHERE id=?", (row["id"],)
    ).fetchone()
    assert (after["status"], after["worker"]) == ("claimed", "w1")
    os.close(fd)


def test_reclaim_requeues_immediately_when_holder_was_killed(tmp_path):
    """Holders are locked by `kill -9` kernel ** immediately ** returned (** without any timeout**: no lease at all etc.)"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    lock_file = _lock_path(work_dir=tmp_path, subject="issue:5")
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    # The real process is locked and killed-9 -- only internal nuclear power proves the nature of "flock automatically released with process death".
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(f"""
                import fcntl, os, sys, time
                fd = os.open({str(lock_file)!r}, os.O_CREAT | os.O_RDWR, 0o644)
                fcntl.flock(fd, fcntl.LOCK_EX)
                sys.stdout.write("locked\\n"); sys.stdout.flush()
                time.sleep(300)
            """),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout.readline().strip() == "locked"
    conn.execute(
        "UPDATE work_queue SET status='claimed', worker='dead', worker_pid=?, claimed_at=?",
        (holder.pid, _NOW.isoformat()),
    )
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 0, (
        "The owner is not to be recovered while alive."
    )

    holder.kill()
    holder.wait(timeout=5)
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 1, "Holder dead."
    row = conn.execute("SELECT status, worker, claimed_at FROM work_queue").fetchone()
    assert (row["status"], row["worker"], row["claimed_at"]) == ("queued", None, None)
    reclaimed = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w2", now=_NOW)
    assert reclaimed is not None  # Reunified
    os.close(reclaimed[1])


# --------------------------------------------------------------------------------------------------
# Card dead: _act hard timeout + upper limit (only one bar that must be counted).
# --------------------------------------------------------------------------------------------------


def test_requeue_returns_row_to_queue_below_max_attempts(tmp_path):
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    _requeue_or_park(conn=conn, task_id=row["id"], subject="issue:5", fd=fd, agent_id="vigil-1")
    after = conn.execute("SELECT status, attempts FROM work_queue").fetchone()
    assert (after["status"], after["attempts"]) == ("queued", 1)
    freed = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert freed is not None, "When we get back, we’ll have to release the locks together."
    os.close(freed)


def test_requeue_marks_automation_failed_at_max_attempts(tmp_path, monkeypatch):
    _, conn = _db(tmp_path)
    parked: list[tuple[int, str]] = []
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: parked.append((number, name)),
    )
    monkeypatch.setattr(vigil_module.github, "issue_comment", lambda *, number, body: None)
    monkeypatch.setattr(vigil_module.github, "list_issue_comments", lambda *, number: [])
    monkeypatch.setattr(vigil_module, "_failure_facts", lambda **kwargs: _facts(pr_number=None))
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    for _ in range(_MAX_ATTEMPTS):
        row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
        _requeue_or_park(conn=conn, task_id=row["id"], subject="issue:5", fd=fd, agent_id="vigil-1")
    assert (
        conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0
    )  # We're done. We don't take the chute.
    assert parked == [(5, "automation-failed")]


class _HangingBackend:
    """The backend - a simulation of ”process alive but hung up on a call that doesn’t return” (flock can’t rule out this death)."""

    name = "hanging"

    def run(self, *, work_dir, task, context):
        time.sleep(300)


def test_timed_backend_raises_on_agent_hang():
    """`_act` Hard timeout → Throw! `_ActTimeout` → `_worker_loop` Capture → The Holder himself `_requeue_or_park`Or not."""
    with pytest.raises(_ActTimeout):
        _TimedBackend(inner=_HangingBackend(), timeout_seconds=1, lock_fd=None).run(
            work_dir=Path("."), task="t", context="c"
        )


def test_timed_backend_passes_through_normal_result():
    class _Fast:
        name = "fast"

        def run(self, *, work_dir, task, context):
            return "ok"

    result = _TimedBackend(inner=_Fast(), timeout_seconds=30, lock_fd=None).run(
        work_dir=Path("."), task="t", context="c"
    )
    assert result == "ok"


@pytest.mark.parametrize("budget", ["5400.5", "0"])
def test_intake_runs_its_producer_thread_agent_calls_through_a_timed_backend(
    monkeypatch, tmp_path, budget
):
    """# Spec-0065/T2: Two agent calls on the access ** must ** be `_TimedBackend`, not naked back.

    They run on the **Producer’s ** -- that’s the whole Vigil cycle. Any hang-up, no swinging.
    A sub-project is a system**: no more ticks, no more `_reclaim_dead` (no more dead holders being recovered),
    `--once` cannot even get in, and K-worker is waiting for the producer to resupply. ** This death penalty is not visible **:
    The watchdog and IN_FLIGHT report themselves live in that stopped loop. Hard time is the only living thing here.

    There was no claim on this road (access is not yet on the team), so `lock_fd=None` - no fd, no proof of survival.
    """
    monkeypatch.setenv("OPENAGENTS_CLAUDE_MAX_WALL", budget)
    raw = object()  # Naked: It must not be missing in any of the stages.
    seen: list[object] = []
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)
    monkeypatch.setattr(
        vigil_module.github,
        "list_issues",
        lambda *, labels: [github.Issue(number=5, title="Title", body="Text", labels=())],
    )
    monkeypatch.setattr(
        vigil_module.github,
        "get_issue",
        lambda *, number: github.Issue(
            number=number, title="Title", body="Text", labels=("openagents",)
        ),
    )
    monkeypatch.setattr(vigil_module.github, "issue_add_label", lambda *, number, name: None)
    monkeypatch.setattr(
        vigil_module.stages,
        "triage",
        lambda *, backend, work_dir, issue: (
            seen.append(backend) or {"actionable": True, "reason": ""}
        ),
    )
    monkeypatch.setattr(
        vigil_module,
        "_order_edges",
        lambda *, backend, work_dir, config, agent_id: seen.append(backend),
    )

    _intake(
        backend=raw,
        work_dir=tmp_path,
        config=_config(stages=_stages(triage="agent")),
        agent_id="vigil-1",
        now=_NOW,
    )

    assert len(seen) == 2, "Tread with curator both times through hard time."
    for backend in seen:
        assert isinstance(backend, _TimedBackend), (
            "  Naked backend hanged     The whole Vigil was out and nobody could see  "
        )
        assert backend._inner is raw  # It's just one floor.
        assert backend._lock_fd is None, "No access, no access, no proof of survival, fd."
        assert backend._timeout_seconds == float(budget)


# --------------------------------------------------------------------------------------------------
# Recincile: worker constant in_flight = False _classify (or every workr gets a job); zero progress  →  stamped off.
# --------------------------------------------------------------------------------------------------


def _stub_reconcile(monkeypatch, *, facts_seq: list[_Facts]) -> list[str]:
    """- Put it on. `_sense` I’ll put it in a line of presets. facts(one at a time, and one after the last after the last time) and recorded `_act` is the sequence of actions."""
    seen: list[str] = []
    box = {"index": 0}

    def _fake_sense(*, config, subject):
        index = min(box["index"], len(facts_seq) - 1)
        box["index"] += 1
        return _Observed(facts=facts_seq[index], clock=_Clock(last_progress_at=_NOW))

    def _fake_act(*, backend, state, work_dir, config, observed, verdict, agent_id, now, lock_fd):
        seen.append(verdict.action)
        return "Conclusions"

    monkeypatch.setattr(vigil_module, "_sense", _fake_sense)
    monkeypatch.setattr(vigil_module, "_act", _fake_act)
    monkeypatch.setattr(vigil_module, "_capture_label_targets", lambda *, facts: {})
    return seen


def _reconcile_once(tmp_path):
    # Spec-0065/T2: `lock_fd` = recognized flock fd (successive to agent subprocess); this group only detects perceptions/routings, and no approval.
    _reconcile(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        subject="issue:5",
        agent_id="a",
        now_fn=lambda: _NOW,
        lock_fd=None,
    )


def test_reconcile_never_idles_on_its_own_claim(monkeypatch, tmp_path):
    """worker **Yeah.**That. in-flight Holders → I have to. `in_flight=False` Tranquility `_classify`Otherwise it’s going to be empty."""
    seen = _stub_reconcile(monkeypatch, facts_seq=[_facts(), _facts(merged=True)])
    _reconcile_once(tmp_path)
    assert seen == [_ACT_MERGE], "worker You must be real. in_flight=True   Will make it empty  "


def test_reconcile_drives_to_a_stop_not_one_step(monkeypatch, tmp_path):
    """One claim** pushed to the point where it was stuck**: e2e  → review  →  merge should have gone after the trip, instead of burning three ticks (one per tick)."""
    seen = _stub_reconcile(
        monkeypatch,
        facts_seq=[
            _facts(e2e_head_sha=None, review_state=None, review_commit_id=None, labels=frozenset()),
            _facts(review_state=None, review_commit_id=None, labels=frozenset()),
            _facts(),
            _facts(merged=True),
        ],
    )
    _reconcile_once(tmp_path)
    assert seen == [_ACT_E2E, _ACT_REVIEW_OR_FIX, _ACT_MERGE]


def test_reconcile_accepts_merge_result_before_remote_snapshot_changes(monkeypatch, tmp_path):
    """Spec-0090/T1: a successful merge must not be rewritten as round_cap by a stale read."""
    _stub_reconcile(monkeypatch, facts_seq=[_facts()])
    calls: list[str] = []
    monkeypatch.setattr(
        vigil_module, "_act", lambda **kwargs: calls.append(kwargs["verdict"].action) or "merged"
    )
    failed: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda **kwargs: failed.append(kwargs["category"]),
    )
    _reconcile_once(tmp_path)
    assert calls == [_ACT_MERGE]
    assert failed == []


@pytest.mark.parametrize(
    ("error", "helper"),
    [
        (vigil_module.gates.DesignApprovalStale("stale"), "_refresh_design_approval"),
        (vigil_module.gates.RepositoryIntegrityStale("stale"), "_repair_repository_integrity"),
    ],
)
def test_reconcile_routes_repairable_gate_errors_without_retry_budget(
    monkeypatch, tmp_path, error, helper
):
    """Spec-0090/T1: repairable gates are routed once, not converted into claim retries."""
    _stub_reconcile(monkeypatch, facts_seq=[_facts()])
    calls: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_act",
        lambda **kwargs: (_ for _ in ()).throw(error),
    )

    def recover(**kwargs):
        assert isinstance(kwargs["backend"], _TimedBackend)
        assert kwargs["backend"]._lock_fd is None
        calls.append(helper)

    monkeypatch.setattr(vigil_module, helper, recover)
    monkeypatch.setattr(vigil_module, "_clear_review_labels", lambda **kwargs: None)
    monkeypatch.setattr(vigil_module, "_post_attempt_stamp", lambda **kwargs: None)
    failed: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda **kwargs: failed.append(kwargs["category"]),
    )
    _reconcile_once(tmp_path)
    assert calls == [helper]
    assert failed == []


@pytest.mark.parametrize("ending", ["merged", "waiting", "progress", "cycle"])
def test_reconcile_checks_actual_final_state_before_round_cap(monkeypatch, tmp_path, ending):
    """Recheck terminal state; a new fact at the claim boundary yields instead of failing."""
    facts = [_facts(head_sha=f"head-{i}") for i in range(8)]
    final = {
        "merged": _facts(merged=True),
        "waiting": _facts(ci="pending"),
        "progress": _facts(head_sha="head-8"),
        "cycle": facts[0],
    }[ending]
    seen = _stub_reconcile(monkeypatch, facts_seq=[*facts, final])
    failed = []
    monkeypatch.setattr(vigil_module, "_fail_automation", lambda **kw: failed.append(kw))
    _reconcile_once(tmp_path)
    assert len(seen) == 8
    assert len(failed) == (1 if ending == "cycle" else 0)
    if failed:
        assert failed[0]["facts"] == final


def test_implementer_summary_cannot_claim_merge_success(monkeypatch, tmp_path):
    """Spec-0090/T1: only the merge action owns the authoritative merged result."""
    _stub_reconcile(monkeypatch, facts_seq=[_facts(ci="failure"), _facts()])
    calls = []
    monkeypatch.setattr(
        vigil_module, "_act", lambda **kw: calls.append(kw["verdict"].action) or "merged"
    )
    _reconcile_once(tmp_path)
    assert calls == [_ACT_FIX_CI, _ACT_MERGE]


def test_reconcile_returns_the_slot_when_stuck_on_something_external(monkeypatch, tmp_path):
    """The cartons are stuck outside (QUIET: Waiting for CI) immediately return the slot, without the worker empty, etc."""
    seen = _stub_reconcile(monkeypatch, facts_seq=[_facts(ci="pending")])
    _reconcile_once(tmp_path)
    assert seen == []


def test_reconcile_stamps_and_stops_when_agent_made_zero_progress(monkeypatch, tmp_path):
    """Column 1: fp** a byte remains unchanged after agent’s hand is taken (it does not know, it does not need-human)."""
    stuck = _facts(ci="failure")
    seen = _stub_reconcile(monkeypatch, facts_seq=[stuck, stuck, stuck])
    stamps: list[tuple[str, str]] = []
    monkeypatch.setattr(
        vigil_module,
        "_post_attempt_stamp",
        lambda *, facts, fp, conclusion, agent_id: stamps.append((fp, conclusion)),
    )
    _reconcile_once(tmp_path)
    assert seen == [_ACT_FIX_CI], "The same fp only once."
    assert stamps == [(_fingerprint(facts=stuck), "Conclusions")]


def test_reconcile_propagates_protocol_error_to_bounded_queue_retry(monkeypatch, tmp_path):
    _stub_reconcile(monkeypatch, facts_seq=[_facts(ci="failure")])
    monkeypatch.setattr(
        vigil_module,
        "_act",
        lambda **kwargs: (_ for _ in ()).throw(engine.AgentOutputError("Old Control")),
    )
    with pytest.raises(engine.AgentOutputError, match="Old Control"):
        _reconcile_once(tmp_path)


def test_reconcile_restores_deleted_labels_then_parks(monkeypatch, tmp_path):
    """The raw PUT type replacement is detected at the action boundary: read twice, restore item by item, and turn over."""
    _stub_reconcile(monkeypatch, facts_seq=[_facts(ci="failure")])
    baseline = vigil_module._LabelTargetSnapshot(
        kind="issue",
        number=5,
        labels=frozenset({"ready", "from-synthesize", "P1", "round-1"}),
    )
    monkeypatch.setattr(
        vigil_module, "_capture_label_targets", lambda *, facts: {("issue", 5): baseline}
    )
    reads = iter(
        [
            vigil_module._LabelTargetSnapshot(
                kind="issue", number=5, labels=frozenset({"automation-failed"})
            ),
            vigil_module._LabelTargetSnapshot(
                kind="issue", number=5, labels=frozenset({"automation-failed", "P1"})
            ),
        ]
    )
    monkeypatch.setattr(vigil_module, "_read_label_target", lambda *, kind, number: next(reads))
    restored: list[str] = []
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: restored.append(name),
    )
    failed: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda *, subject, facts, category, attempts, reason, agent_id: failed.append(reason),
    )

    _reconcile_once(tmp_path)

    assert restored == ["from-synthesize", "ready", "round-1"]
    assert len(failed) == 1
    assert "removed required labels" in failed[0]
    assert "`P1`" in failed[0], (
        "The labels that the co-dispersor has returned should still appear in the accident diagnosis."
    )


def test_review_refresh_allows_only_framework_owned_stale_verdict_removal():
    facts = _facts(
        labels=frozenset({"ready", "review-approved:oldsha1"}),
        review_state=None,
        review_commit_id=None,
    )

    allowed = vigil_module._allowed_label_removals(
        facts=facts,
        verdict=_Verdict(kind=_ACTIONABLE, action=_ACT_REVIEW_OR_FIX),
    )

    assert allowed == {("pr", 12): frozenset({"review-approved:oldsha1"})}


# --------------------------------------------------------------------------------------------------
# Producer: First reading of the guard (with fp poking); four-value diversion; single subject error segregation.
# --------------------------------------------------------------------------------------------------


def _consider_once(conn, *, work_dir, in_flight=None, quiet_counts=None) -> int:
    # Spec-0066/T2: `_consider` Add additive keyword `work_dir` (Word clock timedown path); this Seam faxed tmp_path.
    return _consider(
        conn=conn,
        state=None,
        subject="issue:5",
        config=_config(),
        work_dir=work_dir,
        in_flight=in_flight or {},
        priority_fn=vigil_module._priority_default,
        thresholds=dict(vigil_module._WATCHDOG_DEFAULTS),
        quiet_counts=quiet_counts if quiet_counts is not None else {},
        now=_NOW,
        agent_id="vigil-1",
    )


def _stub_consider(monkeypatch, *, facts: _Facts, comments=()):
    monkeypatch.setattr(
        vigil_module,
        "_sense",
        lambda *, config, subject: _Observed(facts=facts, clock=_Clock(last_progress_at=_NOW)),
    )
    monkeypatch.setattr(vigil_module.github, "list_comments", lambda *, pr_number: list(comments))


def test_producer_skips_enqueue_when_same_fp_attempt_stamp_exists(tmp_path, monkeypatch):
    """The first reading side of the guard: ** has been stamped attempt with fp** downgraded QUIEET (awaiting-effect), ** is not in line (nil LLM)."""
    _, conn = _db(tmp_path)
    stuck = _facts(ci="failure")
    fp = _fingerprint(facts=stuck)
    stamp = github.Comment(
        1, "bot", f"<!-- openagents:attempt fp={fp} -->\nIt hit the wall.", "2026-07-14T11:00:00Z"
    )
    _stub_consider(monkeypatch, facts=stuck, comments=[stamp])
    quiet: dict[str, int] = {}
    assert _consider_once(conn, work_dir=tmp_path, quiet_counts=quiet) == 0
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0
    assert quiet == {_AWAITING_EFFECT: 1}


def test_producer_enqueues_again_once_fingerprint_changes(tmp_path, monkeypatch):
    """fp One change (real progress/new)  →  Old jab automatically lost  →  normal re-entry (column I does not nail subproject permanently)."""
    _, conn = _db(tmp_path)
    old_fp = _fingerprint(facts=_facts(ci="failure"))
    stale = github.Comment(
        1,
        "bot",
        f"<!-- openagents:attempt fp={old_fp} -->\nIt hit the wall.",
        "2026-07-14T11:00:00Z",
    )
    _stub_consider(monkeypatch, facts=_facts(ci="failure", head_sha="f" * 40), comments=[stale])
    assert _consider_once(conn, work_dir=tmp_path) == 1


def test_producer_marks_machine_failure_on_watchdog_timeout(tmp_path, monkeypatch):
    _, conn = _db(tmp_path)
    monkeypatch.setattr(
        vigil_module,
        "_sense",
        lambda *, config, subject: _Observed(
            facts=_facts(ci="none"),
            clock=_Clock(last_progress_at=_NOW - timedelta(seconds=7200)),
        ),
    )
    failed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda *, subject, facts, category, attempts, reason, agent_id: failed.append(
            (subject, reason)
        ),
    )
    _consider_once(conn, work_dir=tmp_path)
    assert failed and failed[0][0] == "issue:5"
    assert _AWAITING_CI in failed[0][1]


def test_producer_does_not_park_a_live_in_flight_holder(tmp_path, monkeypatch):
    """IN_FLIGHT does nothing until it is overage (** never** mistook the enpute of the code writing as ”state is still moving” needs-human)."""
    _, conn = _db(tmp_path)
    _stub_consider(monkeypatch, facts=_facts(ci="failure"))
    failed: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda **kwargs: failed.append(kwargs["subject"]),
    )
    assert _consider_once(conn, work_dir=tmp_path, in_flight={"issue:5": _NOW.isoformat()}) == 0
    assert failed == []
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0


def test_producer_only_logs_overdue_live_holder_without_terminal_projection(tmp_path, monkeypatch):
    _, conn = _db(tmp_path)
    _stub_consider(monkeypatch, facts=_facts(ci="failure"))
    failed: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda **kwargs: failed.append(kwargs["subject"]),
    )
    ancient = (_NOW - timedelta(seconds=vigil_module._INFLIGHT_ALARM_SECONDS * 2)).isoformat()
    assert _consider_once(conn, work_dir=tmp_path, in_flight={"issue:5": ancient}) == 0
    assert failed == []


def test_producer_isolates_a_failing_subject(tmp_path, monkeypatch):
    """Single subject perception failure  →  log skips,** does not slow down the whole production round** (the first priority of the watch is to go on the next round alive)."""
    db_path, conn = _db(tmp_path)

    def _flaky_sense(*, config, subject):
        if subject == "issue:5":
            raise RuntimeError("gh, wind.")
        return _Observed(facts=_facts(subject=subject), clock=_Clock(last_progress_at=_NOW))

    monkeypatch.setattr(vigil_module, "_sense", _flaky_sense)
    monkeypatch.setattr(vigil_module, "_intake", lambda **kw: None)
    monkeypatch.setattr(vigil_module, "_has_attempt_stamp", lambda *, facts, fp: False)
    monkeypatch.setattr(vigil_module, "_subjects", lambda *, config: ["issue:5", "issue:6"])
    enqueued = vigil_module._producer_tick(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        agent_id="a",
        db_path=db_path,
        priority_fn=vigil_module._priority_default,
        thresholds=dict(vigil_module._WATCHDOG_DEFAULTS),
        seen_locked={},
        now=_NOW,
    )
    assert enqueued == 1
    assert [row["subject"] for row in conn.execute("SELECT subject FROM work_queue")] == ["issue:6"]


# --------------------------------------------------------------------------------------------------
# Spec-0081: machine failure is sticky for the same facts and self-revives on fact changes.
# --------------------------------------------------------------------------------------------------


def _observed(**overrides) -> _Observed:
    return _Observed(facts=_facts(**overrides), clock=_Clock(last_progress_at=_NOW))


def _spy_remove_labels(monkeypatch) -> tuple[list[tuple[str, str]], list[tuple[int, str]]]:
    """Play two drop-labels, return (PR call record, issue call record) for unfixing the assertion."""
    pr_calls: list[tuple[str, str]] = []
    issue_calls: list[tuple[int, str]] = []
    monkeypatch.setattr(
        vigil_module.github,
        "remove_label",
        lambda *, pr_number, name: pr_calls.append((str(pr_number), name)),
    )
    monkeypatch.setattr(
        vigil_module.github,
        "issue_remove_label",
        lambda *, number, name: issue_calls.append((number, name)),
    )
    return pr_calls, issue_calls


def _failure_comment(*, facts: _Facts) -> github.Comment:
    fp = _fingerprint(facts=facts)
    body = identity.sign(
        body=f"<!-- openagents:automation-failed fp={fp} category=test -->",
        agent_id="vigil-1",
    )
    return github.Comment(1, "bot", body, "2026-07-14T11:00:00Z")


def test_failure_projection_revives_when_material_facts_change(monkeypatch):
    pr_calls, _ = _spy_remove_labels(monkeypatch)
    old = _facts(labels=frozenset({"automation-failed"}), material_digest="old")
    current = replace(old, material_digest="new")
    monkeypatch.setattr(
        vigil_module.github, "list_comments", lambda *, pr_number: [_failure_comment(facts=old)]
    )
    out = _refresh_failure_projection(
        observed=_Observed(current, _Clock(last_progress_at=_NOW)), subject="pr:12"
    )
    assert pr_calls == [("12", "automation-failed")]
    assert "automation-failed" not in out.facts.labels
    verdict = _classify(facts=out.facts, in_flight=False)
    assert verdict.kind != _TERMINAL


def test_failure_projection_stays_terminal_for_same_fingerprint(monkeypatch):
    pr_calls, issue_calls = _spy_remove_labels(monkeypatch)
    facts = _facts(labels=frozenset({"automation-failed"}))
    observed = _Observed(facts, _Clock(last_progress_at=_NOW))
    monkeypatch.setattr(
        vigil_module.github, "list_comments", lambda *, pr_number: [_failure_comment(facts=facts)]
    )
    out = _refresh_failure_projection(observed=observed, subject="pr:12")
    assert pr_calls == [] and issue_calls == []
    assert out is observed
    assert _classify(facts=out.facts, in_flight=False).kind == _TERMINAL


def test_failure_refresh_passthrough_without_failure_label(monkeypatch):
    pr_calls, issue_calls = _spy_remove_labels(monkeypatch)
    observed = _observed(labels=frozenset(), latest_comment_is_ours=False)
    out = _refresh_failure_projection(observed=observed, subject="pr:12")
    assert pr_calls == [] and issue_calls == []
    assert out is observed


def test_failure_refresh_issue_subject_uses_issue_remove_label(monkeypatch):
    pr_calls, issue_calls = _spy_remove_labels(monkeypatch)
    facts = _facts(subject="issue:5", pr_number=None, labels=frozenset({"automation-failed"}))
    old = replace(facts, material_digest="old")
    monkeypatch.setattr(
        vigil_module.github, "list_issue_comments", lambda *, number: [_failure_comment(facts=old)]
    )
    out = _refresh_failure_projection(
        observed=_Observed(facts, _Clock(last_progress_at=_NOW)), subject="issue:5"
    )
    assert issue_calls == [(5, "automation-failed")] and pr_calls == []
    assert "automation-failed" not in out.facts.labels


def test_consider_reenqueues_after_failure_fingerprint_changes(tmp_path, monkeypatch):
    _, conn = _db(tmp_path)
    _spy_remove_labels(monkeypatch)
    old = _facts(labels=frozenset({"automation-failed"}), material_digest="old")
    current = replace(old, material_digest="new", ci="failure")
    _stub_consider(monkeypatch, facts=current)
    monkeypatch.setattr(
        vigil_module.github, "list_issue_comments", lambda *, number: [_failure_comment(facts=old)]
    )
    assert _consider_once(conn, work_dir=tmp_path) == 1
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 1


def test_consider_stays_terminal_for_unchanged_failure_fingerprint(tmp_path, monkeypatch):
    _, conn = _db(tmp_path)
    pr_calls, issue_calls = _spy_remove_labels(monkeypatch)
    facts = _facts(labels=frozenset({"automation-failed"}))
    _stub_consider(monkeypatch, facts=facts)
    monkeypatch.setattr(
        vigil_module.github,
        "list_issue_comments",
        lambda *, number: [_failure_comment(facts=facts)],
    )
    assert _consider_once(conn, work_dir=tmp_path) == 0
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0
    assert pr_calls == [] and issue_calls == []


@pytest.mark.parametrize("pr_number", [None, 12])
def test_issue_failure_write_read_round_trip_with_linked_pr(monkeypatch, pr_number):
    """Spec-0088/T2: the real writer and reader must share the issue comment stream."""
    pr_calls, issue_calls = _spy_remove_labels(monkeypatch)
    facts = _facts(subject="issue:5", pr_number=pr_number)
    comments: list[github.Comment] = []
    added: list[tuple] = []
    reads: list[int] = []

    def list_issue_comments(*, number):
        reads.append(number)
        return comments

    def issue_comment(*, number, body):
        assert number == 5
        comments.append(github.Comment(1, "bot", body, "2026-07-14T11:00:00Z"))

    monkeypatch.setattr(vigil_module.github, "list_issue_comments", list_issue_comments)
    monkeypatch.setattr(vigil_module.github, "issue_comment", issue_comment)
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: added.append((number, name)),
    )
    # A conflicting PR marker is deliberately present: issue-owned failure must ignore it.
    foreign = _failure_comment(facts=replace(facts, material_digest="foreign"))
    monkeypatch.setattr(vigil_module.github, "list_comments", lambda *, pr_number: [foreign])
    for _ in range(2):
        vigil_module._fail_automation(
            subject="issue:5",
            facts=facts,
            category="gate",
            attempts=3,
            reason="approved design not found",
            agent_id="vigil-1",
        )
    assert len(comments) == 1
    assert added == [(5, "automation-failed"), (5, "automation-failed")]
    observed = _Observed(
        replace(facts, labels=facts.labels | {"automation-failed"}), _Clock(last_progress_at=_NOW)
    )
    for _ in range(4):
        assert _refresh_failure_projection(observed=observed, subject="issue:5") is observed
    assert not pr_calls and not issue_calls
    assert reads == [5] * 6

    changed = replace(observed, facts=replace(observed.facts, head_sha="new-head"))
    revived = _refresh_failure_projection(observed=changed, subject="issue:5")
    assert "automation-failed" not in revived.facts.labels
    assert _refresh_failure_projection(observed=revived, subject="issue:5") is revived
    assert issue_calls == [(5, "automation-failed")]


@pytest.mark.parametrize("subject", ["issue:5", "pr:12"])
@pytest.mark.parametrize("marker_kind", ["missing", "unsigned", "malformed", "stale-before-bad"])
def test_failure_missing_or_invalid_marker_is_not_new_evidence(monkeypatch, subject, marker_kind):
    """Spec-0088/T2: missing evidence must not remove an explicit terminal failure."""
    pr_calls, issue_calls = _spy_remove_labels(monkeypatch)
    facts = _facts(subject=subject, labels=frozenset({"automation-failed"}))
    old = _failure_comment(facts=replace(facts, material_digest="old"))
    body = {
        "missing": "unrelated comment",
        "unsigned": "<!-- openagents:automation-failed fp=0123456789abcdef category=test -->",
        "malformed": old.body.replace("fp=", "invalid="),
        "stale-before-bad": old.body.replace("fp=", "invalid="),
    }[marker_kind]
    comment = github.Comment(2, "someone", body, "2026-07-14T12:00:00Z")
    comments = [old, comment] if marker_kind == "stale-before-bad" else [comment]
    monkeypatch.setattr(vigil_module.github, "list_comments", lambda *, pr_number: comments)
    monkeypatch.setattr(vigil_module.github, "list_issue_comments", lambda *, number: comments)
    observed = _Observed(facts, _Clock(last_progress_at=_NOW))
    for _ in range(3):
        assert _refresh_failure_projection(observed=observed, subject=subject) is observed
    assert not pr_calls and not issue_calls


def test_producer_tick_survives_a_park_that_never_lands(tmp_path, monkeypatch):
    """# Spec-0065/T2: `_sweep_stalled` line park (`gh` 429) ** whole round of production **

    `gh` throws `_producer_tick`, and this `_intake` of tick stops with ** all ** perception/incoming team -
    A leaked line dragged the whole line to death, which was far worse than it was stuck itself (and it was only ”the next round of the park”).
    """
    db_path, conn = _db(tmp_path)
    intake_calls: list[int] = []
    monkeypatch.setattr(vigil_module, "_intake", lambda **kw: intake_calls.append(1))
    monkeypatch.setattr(vigil_module, "_has_attempt_stamp", lambda *, facts, fp: False)
    monkeypatch.setattr(vigil_module, "_subjects", lambda *, config: ["issue:6"])
    monkeypatch.setattr(
        vigil_module,
        "_sense",
        lambda *, config, subject: _Observed(
            facts=_facts(subject=subject, ci="failure"), clock=_Clock(last_progress_at=_NOW)
        ),
    )
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("gh restricted flow 429.")),
    )
    monkeypatch.setattr(vigil_module, "_failure_facts", lambda **kwargs: _facts(pr_number=None))
    # A queued line of "survival certificate leak": the lock is held and ** the last tick has ** seen it locked.
    # `_sweep_stalled` of tick will go to park it, and `gh` of park will throw it.
    vigil_module._enqueue(conn=conn, subject="issue:9", priority=1, now=_NOW)
    leaked = vigil_module._try_lock(
        path=vigil_module._lock_path(work_dir=tmp_path, subject="issue:9")
    )
    assert leaked is not None
    seen_locked = {"issue:9": _NOW - timedelta(seconds=vigil_module._STALE_LOCK_SECONDS + 60)}

    enqueued = vigil_module._producer_tick(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        agent_id="a",
        db_path=db_path,
        priority_fn=vigil_module._priority_default,
        thresholds=dict(vigil_module._WATCHDOG_DEFAULTS),
        seen_locked=seen_locked,
        now=_NOW,
    )

    assert intake_calls == [1], "Park, throw no `_intake`."
    assert enqueued == 1, "Park, throw no food for this round of perception/into the team."
    assert vigil_module._is_claimed(conn=conn, subject="issue:9") is False
    # Okay.**Before you start talking,**Use DELETE - It's stolen.`_park_stalled`:Deleting an appointment) `gh` Throw it and don't come back.
    # Restore `_intake` from GitHub current re-guide (the lock also holds the re-calculation  →  Park: no throttle, no LLM).
    assert conn.execute("SELECT 1 FROM work_queue WHERE subject='issue:9'").fetchone() is None
    assert vigil_module._enqueue(conn=conn, subject="issue:9", priority=1, now=_NOW) is True, (
        "The subject must still recover (UNIQUE’s pit was not killed by this failed park)"
    )
    os.close(leaked)


def test_priority_finishes_work_in_progress_before_starting_new():
    """Finish the product first, start new work; people wait for the highest rate."""
    order = [_ACT_REPLY, _ACT_MERGE, _ACT_REVIEW_OR_FIX, _ACT_E2E, _ACT_FIX_CI, _ACT_SOLVE]
    priorities = [
        vigil_module._priority_default(verdict=_Verdict(kind=_ACTIONABLE, action=action))
        for action in order
    ]
    assert priorities == sorted(priorities, reverse=True)


# --------------------------------------------------------------------------------------------------
# Access: Tri-state route / dependent on validate (Little + real issue; half of the wrong graph is worse than no graph).
# --------------------------------------------------------------------------------------------------


def test_route_dispatches_agent_and_skip_and_rejects_retired_owner():
    calls: dict[str, int] = {"agent": 0, "skip": 0}

    def _bump(key):
        def _run():
            calls[key] += 1
            return key

        return _run

    for owner in ("agent", "skip"):
        assert (
            route(
                owner=owner,
                on_agent=_bump("agent"),
                on_skip=_bump("skip"),
            )
            == owner
        )
    assert calls == {"agent": 1, "skip": 1}
    with pytest.raises(ValueError, match="Unknown"):
        route(owner="hu" + "man", on_agent=_bump("agent"), on_skip=_bump("skip"))


def test_has_cycle_detects_cycles():
    assert _has_cycle(graph={5: {6}, 6: {5}}) is True
    assert _has_cycle(graph={5: {6}, 6: set()}) is False


def test_proposed_edges_returns_only_new_edges_and_keeps_anchors():
    """The edge is the anchor (a person may be set by UI) - a new POST, never re-numbered, undeleted."""
    fresh = _proposed_edges(
        edges=[{"issue": 6, "blocked_by": [5]}, {"issue": 7, "blocked_by": [5]}],
        known={5, 6, 7},
        existing={5: [], 6: [5], 7: []},
        agent_id="vigil-1",
    )
    assert fresh == [(7, 5)]  # 6  → 5 Exists (Olmb) with 7  → 5


def test_proposed_edges_rejects_the_whole_batch_on_cycle(monkeypatch):
    """Ring ** without any edge** + Park-to-man (the wrong side will freeze for long periods of time in parallel, half a wrong picture is worse than no picture)."""
    monkeypatch.setattr(vigil_module, "_failure_facts", lambda **kwargs: _facts(pr_number=None))
    monkeypatch.setattr(vigil_module, "_fail_automation", lambda **kwargs: None)
    assert (
        _proposed_edges(
            edges=[{"issue": 5, "blocked_by": [6]}, {"issue": 6, "blocked_by": [5]}],
            known={5, 6},
            existing={5: [], 6: []},
            agent_id="vigil-1",
        )
        is None
    )


def test_proposed_edges_rejects_hallucinated_issue_numbers(monkeypatch):
    monkeypatch.setattr(vigil_module, "_failure_facts", lambda **kwargs: _facts(pr_number=None))
    monkeypatch.setattr(vigil_module, "_fail_automation", lambda **kwargs: None)
    assert (
        _proposed_edges(
            edges=[{"issue": 5, "blocked_by": [999]}],
            known={5, 6},
            existing={5: [], 6: []},
            agent_id="vigil-1",
        )
        is None
    )


# --------------------------------------------------------------------------------------------------
# Life cycle: once go _drain_queue empty; K=1 is the same as K=2; Keyboard Interrupt is a stop_event collection.
# --------------------------------------------------------------------------------------------------


def _run_once(tmp_path, *, concurrency, subjects) -> list[str]:
    """Runs to `run_vigil(once=True)`: Plugs `_sense`/ `_act`, returns the real advance of the subject sequence."""
    acted: list[str] = []
    lock = threading.Lock()
    done: set[str] = set()

    def _fake_sense(*, config, subject):
        with lock:
            finished = subject in done
        return _Observed(
            facts=_facts(subject=subject, merged=finished), clock=_Clock(last_progress_at=_NOW)
        )

    def _fake_act(*, backend, state, work_dir, config, observed, verdict, agent_id, now, lock_fd):
        with lock:
            acted.append(observed.facts.subject)
            done.add(observed.facts.subject)
        return "done"

    import openagents.recipes.vigil as mod

    saved = (
        mod._sense,
        mod._act,
        mod._intake,
        mod._subjects,
        mod._has_attempt_stamp,
        mod._capture_label_targets,
    )
    mod._sense, mod._act = _fake_sense, _fake_act
    mod._intake = lambda **kw: None
    mod._subjects = lambda *, config: list(subjects)
    mod._has_attempt_stamp = lambda *, facts, fp: False
    mod._capture_label_targets = lambda *, facts: {}
    try:
        run_vigil(
            backend=None,
            state=None,
            work_dir=tmp_path,
            config=_config(),
            once=True,
            concurrency=concurrency,
            agent_id="a",
        )
    finally:
        (
            mod._sense,
            mod._act,
            mod._intake,
            mod._subjects,
            mod._has_attempt_stamp,
            mod._capture_label_targets,
        ) = saved
    return acted


def test_run_vigil_once_drains_the_queue(tmp_path):
    """`once=True`: A producer tick + `_drain_queue` emptied (the queue must return to the bottom to test the definitive sync syntax)."""
    acted = _run_once(tmp_path, concurrency=1, subjects=["issue:5", "issue:6"])
    assert sorted(acted) == ["issue:5", "issue:6"]
    conn = _connect(db_path=tmp_path / ".openagents" / "vigil-queue.db")
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0


def test_k1_serial_and_k2_parallel_reach_the_same_end_state(tmp_path):
    """**K=1 is not another model, but a single cap of 1** - the last two must be consistent."""
    subjects = ["issue:5", "issue:6", "issue:7"]
    serial = _run_once(tmp_path / "a", concurrency=1, subjects=subjects)
    parallel = _run_once(tmp_path / "b", concurrency=2, subjects=subjects)
    assert sorted(serial) == sorted(parallel) == subjects


def test_run_vigil_survives_keyboard_interrupt(tmp_path, monkeypatch):
    """Ctrl-C → `stop_event` Place → worker (b) Exiting the pool;queued Stay DB(scoffs) + Hold on, start running again."""

    def _boom(**kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(vigil_module, "_producer_tick", _boom)
    run_vigil(  # Keyboard Interrupt is not allowed to leak out.
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        once=False,
        concurrency=2,
        agent_id="a",
    )
    assert not [
        t for t in threading.enumerate() if t.name.startswith("vigil-worker") and t.is_alive()
    ]


def test_producer_error_does_not_kill_the_daemon(tmp_path, monkeypatch):
    """`once=False` single-wheel producers abnormally log, continuing (** no producers killed**); second round confirmed to be alive and then closed."""
    ticks = {"n": 0}

    def _flaky(**kwargs):
        ticks["n"] += 1
        if ticks["n"] == 1:
            raise RuntimeError("gh, wind.")
        raise KeyboardInterrupt

    monkeypatch.setattr(vigil_module, "_producer_tick", _flaky)
    monkeypatch.setattr(vigil_module.time, "sleep", lambda _: None)
    run_vigil(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        once=False,
        concurrency=1,
        agent_id="a",
    )
    assert ticks["n"] == 2, (
        "After the first round of anomalies, producers must live to go through the second round."
    )


@pytest.mark.parametrize("refresh_design", [True, False])
def test_review_after_design_refresh_is_progress_not_fact_cycle(
    monkeypatch, tmp_path, refresh_design
):
    """N16 #107: review PASS -> refreshed design approval -> same-head review PASS."""
    from types import SimpleNamespace

    pending = _facts(review_state=None, review_commit_id=None, labels=frozenset())
    approved = _facts()
    _stub_reconcile(monkeypatch, facts_seq=[pending, approved, pending, approved])
    monkeypatch.setattr(vigil_module, "_MAX_RECONCILE_ROUNDS", 3)
    run = {
        "status": vigil_module.STATUS_PR_OPEN,
        "design_digest": "old",
        "design_raw_digest": "old-raw",
    }
    state = SimpleNamespace(get_run=lambda **kw: run)
    calls = []

    def act(**kw):
        calls.append(kw["verdict"].action)
        if kw["verdict"].action == _ACT_MERGE:
            raise vigil_module.gates.DesignApprovalStale("design changed by rebase")
        return "review passed"

    def refresh(**kw):
        if refresh_design:
            run.update(design_digest="new", design_raw_digest="new-raw")

    monkeypatch.setattr(vigil_module, "_act", act)
    monkeypatch.setattr(vigil_module, "_refresh_design_approval", refresh)
    monkeypatch.setattr(vigil_module, "_clear_review_labels", lambda **kw: None)
    failed = []
    monkeypatch.setattr(vigil_module, "_fail_automation", lambda **kw: failed.append(kw))
    vigil_module._reconcile(
        backend=None,
        state=state,
        work_dir=tmp_path,
        config=_config(),
        subject="issue:5",
        agent_id="a",
        now_fn=lambda: _NOW,
        lock_fd=None,
    )
    assert calls == [_ACT_REVIEW_OR_FIX, _ACT_MERGE, _ACT_REVIEW_OR_FIX]
    assert [x["category"] for x in failed] == ([] if refresh_design else ["fact_cycle"])
