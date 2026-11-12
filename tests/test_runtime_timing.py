"""# Spec-0066/T1: runtime.timing Target Single Measure (Pretty Standard Bank, Network/Storage)

Overwrite: recod append valid JSON 5 + UTC ISO8601; record writing failed (no raise); load_events jump corrupted
Line; Timelines multi-wheel recreate each phase furisation (including phase recurrences, end time of triminal 0); phase_stats every
Case p50/p90+ Maximum end subject + limit field.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openagents.runtime import timing


def _at(minute: int, second: int = 0) -> datetime:
    return datetime(2026, 7, 9, 12, minute, second, tzinfo=UTC)


def _events_path(tmp_path: Path) -> Path:
    return tmp_path / ".openagents" / timing.TIMING_FILENAME


# --------------------------------------------------------------------------------------------------
# record:append is valid JSON five keys + UTC ISO8601; tolerance for misadventure abnormalities.
# --------------------------------------------------------------------------------------------------


def test_record_appends_one_legal_json_event_with_five_keys(tmp_path):
    timing.record(
        work_dir=tmp_path, subject="issue:145", issue=145, pr=154, phase="solving", now=_at(0)
    )
    lines = _events_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event == {
        "subject": "issue:145",
        "issue": 145,
        "pr": 154,
        "phase": "solving",
        "at": "2026-07-09T12:00:00Z",
    }


def test_record_appends_and_bare_pr_issue_may_be_null(tmp_path):
    timing.record(
        work_dir=tmp_path, subject="issue:145", issue=145, pr=None, phase="solving", now=_at(0)
    )
    timing.record(work_dir=tmp_path, subject="pr:9", issue=None, pr=9, phase="merged", now=_at(3))
    lines = _events_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["issue"] is None


def test_record_at_is_utc_iso8601_with_z_suffix_from_aware_and_naive(tmp_path):
    aware = datetime(2026, 7, 9, 4, 0, 0, tzinfo=UTC)  # UTC already
    naive = datetime(2026, 7, 9, 5, 0, 0)  # Consider UTC as a naive
    timing.record(work_dir=tmp_path, subject="issue:1", issue=1, pr=None, phase="a", now=aware)
    timing.record(work_dir=tmp_path, subject="issue:1", issue=1, pr=None, phase="b", now=naive)
    lines = _events_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["at"] == "2026-07-09T04:00:00Z"
    assert json.loads(lines[1])["at"] == "2026-07-09T05:00:00Z"


def test_record_swallows_write_failure_and_does_not_raise(tmp_path, monkeypatch):
    """The core claim of error: injection of open drops  →  record swallows silently, no raise (shows only one time for writing failure)."""

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", _boom)
    # Pass or pass (the main Vigil process is moving on).
    timing.record(
        work_dir=tmp_path, subject="issue:1", issue=1, pr=None, phase="solving", now=_at(0)
    )


# --------------------------------------------------------------------------------------------------
# load_events: Jumping corrupt line; missing file empty.
# --------------------------------------------------------------------------------------------------


def test_load_events_skips_corrupt_lines_keeps_legal(tmp_path):
    path = _events_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                json.dumps({"subject": "issue:1", "issue": 1, "pr": None, "phase": "a", "at": "x"}),
                "{ not json",  # Damage Line
                "",  # Empty Line
                json.dumps({"pr": 2}),  # subject/phase/at Jump
                json.dumps({"subject": "issue:1", "issue": 1, "pr": None, "phase": "b", "at": "y"}),
            ]
        ),
        encoding="utf-8",
    )
    events = timing.load_events(path=path)
    assert [ev["phase"] for ev in events] == ["a", "b"]


def test_load_events_missing_file_is_empty(tmp_path):
    assert timing.load_events(path=_events_path(tmp_path)) == []


# --------------------------------------------------------------------------------------------------
# Timelines: Multi-cycle reconstruction of each case situation; re-emergence of the case in two parts; end of the terminal 0.
# --------------------------------------------------------------------------------------------------


def _seq(subject, phases_at):
    return [
        {"subject": subject, "issue": 145, "pr": 154, "phase": phase, "at": at}
        for phase, at in phases_at
    ]


def test_timelines_reconstructs_durations_across_ticks(tmp_path):
    events = _seq(
        "issue:145",
        [
            ("solving", "2026-07-09T12:00:00Z"),
            ("awaiting-ci", "2026-07-09T12:03:00Z"),  # SOLVING STAY 3min
            ("review-or-fix", "2026-07-09T12:10:00Z"),  # Waiting-ci Stay 7min
            ("merged", "2026-07-09T12:12:00Z"),  # 2min
        ],
    )
    (line,) = timing.timelines(events=events)
    assert line.durations["solving"] == 180.0
    assert line.durations["awaiting-ci"] == 420.0
    assert line.durations["review-or-fix"] == 120.0
    assert line.durations["merged"] == 0.0  # Last Article Term0
    assert line.total == 720.0
    assert (line.issue, line.pr) == (145, 154)


def test_timelines_phase_recurrence_accumulates_two_segments(tmp_path):
    """PH Case Revert: review-or-fix  → fix-ci  → review-or-fix, review-or-fix"""
    events = _seq(
        "issue:7",
        [
            ("review-or-fix", "2026-07-09T12:00:00Z"),  # 2min
            ("fix-ci", "2026-07-09T12:02:00Z"),  # 5min
            ("review-or-fix", "2026-07-09T12:07:00Z"),  # 3min
            ("merged", "2026-07-09T12:10:00Z"),  # 0
        ],
    )
    (line,) = timing.timelines(events=events)
    assert line.durations["review-or-fix"] == 300.0  # 120 + 180 2-part addition
    assert line.durations["fix-ci"] == 300.0
    # Split into four paragraphs (without the two paragraphs correctly review-or-fix).
    assert [seg.phase for seg in line.segments] == [
        "review-or-fix",
        "fix-ci",
        "review-or-fix",
        "merged",
    ]


def test_timelines_merges_consecutive_same_phase(tmp_path):
    """The following is a list of the links to the video that you can use to create a new video that is used in the video."""
    events = _seq(
        "issue:9",
        [
            ("awaiting-ci", "2026-07-09T12:00:00Z"),
            ("awaiting-ci", "2026-07-09T12:01:00Z"),
            ("awaiting-ci", "2026-07-09T12:02:00Z"),
            ("merged", "2026-07-09T12:03:00Z"),
        ],
    )
    (line,) = timing.timelines(events=events)
    assert [seg.phase for seg in line.segments] == ["awaiting-ci", "merged"]
    assert line.durations["awaiting-ci"] == 180.0


def test_timelines_sorts_events_by_at_regardless_of_input_order(tmp_path):
    events = _seq(
        "issue:3",
        [
            ("merged", "2026-07-09T12:05:00Z"),
            ("solving", "2026-07-09T12:00:00Z"),
        ],
    )
    (line,) = timing.timelines(events=events)
    assert [seg.phase for seg in line.segments] == ["solving", "merged"]
    assert line.durations["solving"] == 300.0


# --------------------------------------------------------------------------------------------------
# phase_stats: limit field for crossing subsubject p50/p90+end subproject + intelval precision.
# --------------------------------------------------------------------------------------------------


def test_phase_stats_p50_p90_and_longest_tail_subject():
    events = []
    # Three sub-projects stopped at 100/ 200/ 900 seconds at ailing-ci.
    for subject, dwell in [("issue:1", 100), ("issue:2", 200), ("issue:3", 900)]:
        events += [
            {"subject": subject, "issue": None, "pr": None, "phase": "awaiting-ci", "at": _iso(0)},
            {
                "subject": subject,
                "issue": None,
                "pr": None,
                "phase": "merged",
                "at": _iso(dwell),
            },
        ]
    stats = timing.phase_stats(events=events, interval=60)
    assert stats.interval == 60
    ci = next(ps for ps in stats.phases if ps.phase == "awaiting-ci")
    assert ci.count == 3
    assert ci.p50 == 200.0  # Medium
    assert ci.p90 == pytest.approx(760.0)  # Linear plug 90 fraction (100 200 900)
    assert ci.max_subject == "issue:3"
    assert ci.max_seconds == 900.0


def _iso(offset_seconds: int) -> str:
    base = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)
    return timing._iso(now=base.replace(second=0) + _delta(offset_seconds))


def _delta(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)
