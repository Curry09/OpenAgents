"""# Spec-0066/T1: runtime.timing 针对性单测（纯标准库、不触网络/仓库）。

覆盖：record append 合法 JSON 五键 + UTC ISO8601；record 写失败被容错吞掉（不 raise）；load_events 跳损坏
行；timelines 跨轮重建各 phase duration（含 phase 复现分段累加、末条 terminal 时长 0）；phase_stats 出每
phase p50/p90 + 最长尾 subject + interval 精度下限字段。
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
# record：append 合法 JSON 五键 + UTC ISO8601；容错吞异常。
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
    aware = datetime(2026, 7, 9, 4, 0, 0, tzinfo=UTC)  # 已是 UTC
    naive = datetime(2026, 7, 9, 5, 0, 0)  # naive 视为 UTC
    timing.record(work_dir=tmp_path, subject="issue:1", issue=1, pr=None, phase="a", now=aware)
    timing.record(work_dir=tmp_path, subject="issue:1", issue=1, pr=None, phase="b", now=naive)
    lines = _events_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["at"] == "2026-07-09T04:00:00Z"
    assert json.loads(lines[1])["at"] == "2026-07-09T05:00:00Z"


def test_record_swallows_write_failure_and_does_not_raise(tmp_path, monkeypatch):
    """容错核心断言：注入 open 抛异常 → record 静默吞掉、不 raise（写失败只丢一条计时）。"""

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", _boom)
    # 不抛即通过（守夜主流程照常推进）。
    timing.record(
        work_dir=tmp_path, subject="issue:1", issue=1, pr=None, phase="solving", now=_at(0)
    )


# --------------------------------------------------------------------------------------------------
# load_events：跳损坏行；缺文件 → 空。
# --------------------------------------------------------------------------------------------------


def test_load_events_skips_corrupt_lines_keeps_legal(tmp_path):
    path = _events_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                json.dumps({"subject": "issue:1", "issue": 1, "pr": None, "phase": "a", "at": "x"}),
                "{ not json",  # 损坏行
                "",  # 空行
                json.dumps({"pr": 2}),  # 缺 subject/phase/at → 跳
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
# timelines：跨轮重建各 phase duration；phase 复现分两段累加；末条 terminal 时长 0。
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
            ("awaiting-ci", "2026-07-09T12:03:00Z"),  # solving 停留 3min
            ("review-or-fix", "2026-07-09T12:10:00Z"),  # awaiting-ci 停留 7min
            ("merged", "2026-07-09T12:12:00Z"),  # review-or-fix 停留 2min
        ],
    )
    (line,) = timing.timelines(events=events)
    assert line.durations["solving"] == 180.0
    assert line.durations["awaiting-ci"] == 420.0
    assert line.durations["review-or-fix"] == 120.0
    assert line.durations["merged"] == 0.0  # 末条 terminal 时长 0
    assert line.total == 720.0
    assert (line.issue, line.pr) == (145, 154)


def test_timelines_phase_recurrence_accumulates_two_segments(tmp_path):
    """phase 复现：review-or-fix → fix-ci → review-or-fix，review-or-fix 两段累加。"""
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
    assert line.durations["review-or-fix"] == 300.0  # 120 + 180 两段累加
    assert line.durations["fix-ci"] == 300.0
    # 分成四段（不把两段 review-or-fix 误并成一段）。
    assert [seg.phase for seg in line.segments] == [
        "review-or-fix",
        "fix-ci",
        "review-or-fix",
        "merged",
    ]


def test_timelines_merges_consecutive_same_phase(tmp_path):
    """连续同 phase（跨多 tick 仍 awaiting-ci）合并成一段、区间累加。"""
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
# phase_stats：跨 subject p50/p90 + 最长尾 subject + interval 精度下限字段。
# --------------------------------------------------------------------------------------------------


def test_phase_stats_p50_p90_and_longest_tail_subject():
    events = []
    # 三个 subject 在 awaiting-ci 分别停留 100 / 200 / 900 秒。
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
    assert ci.p50 == 200.0  # 中位数
    assert ci.p90 == pytest.approx(760.0)  # 线性插值 90 分位（100,200,900）
    assert ci.max_subject == "issue:3"
    assert ci.max_seconds == 900.0


def _iso(offset_seconds: int) -> str:
    base = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)
    return timing._iso(now=base.replace(second=0) + _delta(offset_seconds))


def _delta(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)
