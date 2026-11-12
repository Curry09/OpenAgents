"""# Spec-0066/T2: vigil Targeted single bystander (false) backend/github seam  Don’t touch the truth   LLM/Network/The warehouse.

Overwrite: `_phase_of` to four values verdic x facts one by one (TERMINAL subdivision merged/closed/needs-human; QUIET taken
reason；ACTIONABLE Remove action；IN_FLIGHT→in-flight）；`_consider` Run one. tick Back timing.jsonl Generate, contain
dispatch(solve)/Wait(awaiting-*)/(a) Merge the paragraphs;record When you throw an anomaly `_consider` Return as usual (mistake to end);`_fingerprint`
The burial site is equal (fp not by side, self-destructing without touching the fence); the merged section awaiting-ci (CI-wait) can be distinguished from the review-or-fix (review-wait).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import (
    _ACT_FIX_CI,
    _ACT_MERGE,
    _ACT_SOLVE,
    _ACTIONABLE,
    _AWAITING_CI,
    _AWAITING_EFFECT,
    _IN_FLIGHT,
    _QUIET,
    _TERMINAL,
    _Clock,
    _connect,
    _consider,
    _Facts,
    _fingerprint,
    _init_db,
    _Observed,
    _phase_of,
    _Verdict,
)
from openagents.runtime import timing
from openagents.utils import agent_config, github

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_HEAD = "abc1234def5678901234567890123456789abcde"
_SHA7 = _HEAD[:7]


def _facts(**overrides) -> _Facts:
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


def _config(**overrides) -> agent_config.AgentConfig:
    defaults = {
        "version": 1,
        "agents": agent_config.AgentPolicy(backends={}),
        "stages": agent_config.StagePolicy(owners={}),
        "release": agent_config.ReleasePolicy(),
        "interval": 60,
        "base": "main",
        "labels": ["openagents"],
        "repos": [],
    }
    return agent_config.AgentConfig(**(defaults | overrides))


def _db(tmp_path: Path):
    db_path = tmp_path / ".openagents" / "vigil-queue.db"
    _init_db(db_path=db_path)
    return _connect(db_path=db_path)


def _stub_sense(monkeypatch, *, facts: _Facts, comments=()):
    monkeypatch.setattr(
        vigil_module,
        "_sense",
        lambda *, config, subject: _Observed(facts=facts, clock=_Clock(last_progress_at=_NOW)),
    )
    monkeypatch.setattr(vigil_module.github, "list_comments", lambda *, pr_number: list(comments))
    # The guard of the Solve section (pr_number =None) sideways the issue comment - also pegging, off the net.
    monkeypatch.setattr(
        vigil_module.github, "list_issue_comments", lambda *, number: list(comments)
    )


def _consider_once(conn, *, subject, work_dir, in_flight=None) -> int:
    return _consider(
        conn=conn,
        state=None,
        subject=subject,
        config=_config(),
        work_dir=work_dir,
        in_flight=in_flight or {},
        priority_fn=vigil_module._priority_default,
        thresholds=dict(vigil_module._WATCHDOG_DEFAULTS),
        quiet_counts={},
        now=_NOW,
        agent_id="vigil-1",
    )


def _timing_events(work_dir: Path):
    return timing.load_events(path=work_dir / ".openagents" / timing.TIMING_FILENAME)


# --------------------------------------------------------------------------------------------------
# _phase_of: Four values vedict x facts one by one.
# --------------------------------------------------------------------------------------------------


def test_phase_of_in_flight():
    assert _phase_of(verdict=_Verdict(kind=_IN_FLIGHT), facts=_facts()) == "in-flight"


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"merged": True}, "merged"),
        ({"closed": True}, "closed"),
        ({"labels": frozenset({"automation-failed"})}, "automation-failed"),
    ],
)
def test_phase_of_terminal_subdivides_by_facts(overrides, expected):
    """TERMINAL subdivided by facts merged/closed/automation-failed."""
    assert _phase_of(verdict=_Verdict(kind=_TERMINAL), facts=_facts(**overrides)) == expected


def test_phase_of_quiet_takes_reason():
    verdict = _Verdict(kind=_QUIET, reason=_AWAITING_CI)
    assert _phase_of(verdict=verdict, facts=_facts()) == "awaiting-ci"


def test_phase_of_actionable_takes_action():
    verdict = _Verdict(kind=_ACTIONABLE, action=_ACT_FIX_CI)
    assert _phase_of(verdict=verdict, facts=_facts()) == "fix-ci"


# --------------------------------------------------------------------------------------------------
# _consider By-pass:timing.jsonl Generate, contain dispatch(solve)/Wait/(a) Merge the paragraphs;issue/pr Attribution.
# --------------------------------------------------------------------------------------------------


def test_consider_stamps_dispatch_solve_phase(tmp_path, monkeypatch):
    """Not yet. PR → ACTIONABLE:solve → timing.jsonl - I’m down. solve Events (%1)dispatch paragraph), issue Attribution."""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts(pr_number=None))
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    events = _timing_events(tmp_path)
    assert len(events) == 1
    assert events[0]["phase"] == _ACT_SOLVE
    assert events[0]["subject"] == "issue:5"
    assert events[0]["issue"] == 5


def test_consider_stamps_merge_phase_with_pr_attribution(tmp_path, monkeypatch):
    """+APPROVED  → ACTIONABLE:merge; issue subject’s pr belongs to facts.pr_number."""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts())
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    (event,) = _timing_events(tmp_path)
    assert event["phase"] == _ACT_MERGE
    assert (event["issue"], event["pr"]) == (5, 12)


def test_consider_bare_pr_subject_has_null_issue(tmp_path, monkeypatch):
    """standalone PR subject (pr:12)  → issue belongs to nult, pr takes subject."""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts(subject="pr:12"))
    _consider_once(conn, subject="pr:12", work_dir=tmp_path)
    (event,) = _timing_events(tmp_path)
    assert event["issue"] is None
    assert event["pr"] == 12


def test_consider_merge_segment_distinguishes_ci_wait_from_review_wait(tmp_path, monkeypatch):
    """Combined throat: CI pending  →  ailing-ci (CI-wait); review old  →  review-or-fix (review-wait).
    The two are different phasies, and no longer a part of the old cork `open` -- this is the core of the value of this issue."""
    conn = _db(tmp_path)
    # 1 CI queue.
    _stub_sense(monkeypatch, facts=_facts(ci="pending"))
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    # 2 review old (sa) review-or-fix.
    stale = _facts(review_commit_id="0000000", labels=frozenset({"review-approved:0000000"}))
    _stub_sense(monkeypatch, facts=stale)
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    phases = [ev["phase"] for ev in _timing_events(tmp_path)]
    assert phases == [_AWAITING_CI, "review-or-fix"]
    assert _AWAITING_CI != "review-or-fix"  # CI-wait ≠ review-wait


def test_consider_guardrail_one_downgrade_records_awaiting_effect(tmp_path, monkeypatch):
    """Decline in the first column: with fp attempt jab ACTIONABLE down QUIET (awaiting-effict) remembers** the waiting face** after the downgrade."""
    conn = _db(tmp_path)
    stuck = _facts(ci="failure")
    fp = _fingerprint(facts=stuck)
    stamp = github.Comment(
        1, "bot", f"<!-- openagents:attempt fp={fp} -->\nIt hit the wall.", "2026-07-14T11:00:00Z"
    )
    _stub_sense(monkeypatch, facts=stuck, comments=[stamp])
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    (event,) = _timing_events(tmp_path)
    assert event["phase"] == _AWAITING_EFFECT


# --------------------------------------------------------------------------------------------------
# Allows the wrong end to the end + fp to remain unchanged (by-side not returning).
# --------------------------------------------------------------------------------------------------


def test_consider_survives_timing_record_raising(tmp_path, monkeypatch):
    """Record drops (injection) `_consider` returns as usual, without impact (with the wrong end to end)."""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts(pr_number=None))  #   Solve       Bang, bang, bang, bang

    def _boom(**kwargs):
        raise RuntimeError("timing backend down")

    monkeypatch.setattr(vigil_module.timing, "record", _boom)
    assert _consider_once(conn, subject="issue:5", work_dir=tmp_path) == 1  # As usual.


def test_fingerprint_unchanged_by_timing_stamp(tmp_path, monkeypatch):
    """timing.jsonl does not enter fp - equals `_fingerprint` before and after the burial site (I am not self-destructing)."""
    conn = _db(tmp_path)
    facts = _facts(ci="failure")
    fp_before = _fingerprint(facts=facts)
    _stub_sense(monkeypatch, facts=facts)
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    fp_after = _fingerprint(facts=facts)
    assert fp_before == fp_after
    # And it does.
    assert len(_timing_events(tmp_path)) == 1


def test_consider_timing_write_failure_does_not_block_enqueue(tmp_path, monkeypatch):
    """Even if the Timing catalogue was filed and the main process collapsed (the false assertion, the other injection path)."""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts(pr_number=None))
    # Jean. record Internal open Wrong. timing.record Your own. try Hold on.`_consider` No sense.
    monkeypatch.setattr(Path, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert _consider_once(conn, subject="issue:5", work_dir=tmp_path) == 1
