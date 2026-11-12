# Spec-0066/T1
"""Record phase transitions and reconstruct wall-clock timelines across polls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Spec-0066/T1: Independent Event Stream File Name - 0-Current-Sync with runtime-state.json/ vigil-queue.db File Level (Preception 10).
TIMING_FILENAME = "timing.jsonl"


def record(
    *,
    work_dir: Path,
    subject: str,
    issue: int | None,
    pr: int | None,
    phase: str,
    now: datetime,
) -> None:
    """Append a phase transition to the project timing log.

    Recording is advisory: an I/O failure must not interrupt reconciliation.
    """
    try:
        path = Path(work_dir) / ".openagents" / TIMING_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "subject": subject,
            "issue": issue,
            "pr": pr,
            "phase": phase,
            "at": _iso(now=now),
        }
        line = json.dumps(event, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:  # noqa: BLE001 —- Wrong side: one time for a failure, never turn the Vigil.
        return


def load_events(*, path: Path) -> list[dict[str, Any]]:
    """# Spec-0066/T1: Read jsonl event stream, skip the corrupted/missed field line by line error; file missing empty list."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue  # Damage line: Skip, keep only legitimate events
        if isinstance(obj, dict) and "subject" in obj and "phase" in obj and "at" in obj:
            events.append(obj)
    return events


@dataclass(frozen=True)
class Segment:
    """A segment of the time line: a wall clock stops in seconds after it has been merged with a phase area."""

    phase: str
    seconds: float


@dataclass(frozen=True)
class Timeline:
    """Single subject ’s time line for inter-cycle reconstruction: orderly segments (with replicated lines)+ individual face total dwell."""

    subject: str
    issue: int | None
    pr: int | None
    segments: tuple[Segment, ...]  # Timelined, continuous and consistent with case merged
    durations: dict[str, float]  # PHase  →  Total dwell in this verse
    total: float  # Wall clock length (sec) for initial to final post


@dataclass(frozen=True)
class PhaseStat:
    """A verse-cross-subject split + the longest end of the object."""

    phase: str
    p50: float
    p90: float
    count: int  # Number of subprojects with the face
    max_subject: str  # longest end (most long spent in the verse) subject
    max_seconds: float


@dataclass(frozen=True)
class PhaseStats:
    """Report structure for `phase_stats`: each verse fraction + ** lower limit for wall clock accuracy = intelval** (sec)."""

    interval: int  # Wall clock precision lower limit:  → interval particle error for each segment, not to be used as an exact value
    phases: tuple[PhaseStat, ...]


def timelines(*, events: list[dict[str, Any]]) -> list[Timeline]:
    """# Spec-0066/T1: Rebuild over the wheel - Flow events by subsubject and fold them into their respective time lines.

    ** Each event occupies the wall clock slot ”until the next event of the subject”** (end note 0; continuous area with phaase)
    Merges into a single section of Segment, which adds up to all the `durations` (so two parts of `review→fix→review` naturally add up).
    The subproject is sorted by name and returned in a stable order (which may be asserted by hermetic).
    """
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_subject.setdefault(str(event["subject"]), []).append(event)

    result: list[Timeline] = []
    for subject in sorted(by_subject):
        ordered = sorted(by_subject[subject], key=lambda ev: _parse_at(at=str(ev["at"])))
        durations: dict[str, float] = {}
        segments: list[Segment] = []
        total = 0.0
        for index, event in enumerate(ordered):
            phase = str(event["phase"])
            if index + 1 < len(ordered):
                span = (
                    _parse_at(at=str(ordered[index + 1]["at"])) - _parse_at(at=str(event["at"]))
                ).total_seconds()
            else:
                span = 0.0  # The last event is the end, the zone 0 (terminal 0)
            span = max(span, 0.0)
            total += span
            durations[phase] = durations.get(phase, 0.0) + span
            if segments and segments[-1].phase == phase:
                merged = segments[-1]
                segments[-1] = Segment(phase=phase, seconds=merged.seconds + span)
            else:
                segments.append(Segment(phase=phase, seconds=span))
        issue, pr = _subject_ids(subject=subject, events=ordered)
        result.append(
            Timeline(
                subject=subject,
                issue=issue,
                pr=pr,
                segments=tuple(segments),
                durations=durations,
                total=total,
            )
        )
    return result


def phase_stats(*, events: list[dict[str, Any]], interval: int) -> PhaseStats:
    """# Spec-0066/T1: Summarize p50/p90 + Maximum End Subject per verse with minimum interval accuracy.

    For each phase, get a split for ”the total dwell of the subject** with the phose** in this phase” (p90, see
    Google SRE; `max_subject` is the longest-stayed subject for the verse. PHase sorts by name and returns stable.
    """
    lines = timelines(events=events)
    dwell_by_phase: dict[str, list[tuple[str, float]]] = {}
    for line in lines:
        for phase, seconds in line.durations.items():
            dwell_by_phase.setdefault(phase, []).append((line.subject, seconds))

    stats: list[PhaseStat] = []
    for phase in sorted(dwell_by_phase):
        pairs = dwell_by_phase[phase]
        values = [seconds for _, seconds in pairs]
        max_subject, max_seconds = max(pairs, key=lambda pair: pair[1])
        stats.append(
            PhaseStat(
                phase=phase,
                p50=_percentile(values=values, q=50.0),
                p90=_percentile(values=values, q=90.0),
                count=len(values),
                max_subject=max_subject,
                max_seconds=max_seconds,
            )
        )
    return PhaseStats(interval=interval, phases=tuple(stats))


# --------------------------------------------------------------------------------------------------
# Purely assistive (time resolution/ split/ subject attribution).
# --------------------------------------------------------------------------------------------------


def _iso(*, now: datetime) -> str:
    """Datetime  → UTC ISO8601 (`...Z` suffix); naive is considered to be UTC."""
    moment = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_at(*, at: str) -> datetime:
    """ISO8601 (with `Z` suffix) UTC-aware datetime; allow error back to Zero in the age (not to allow a bad `at` to flip a fusion)."""
    try:
        parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _percentile(*, values: list[float], q: float) -> float:
    """Linear interpolation fraction (stdlib, certainty). Empty 0.0; single value  →  that value. q  →  [0,100]."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = q / 100.0 * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


def _subject_ids(*, subject: str, events: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """Take issue/pr from the subproject event (first empty; nud n n. no issue  →  None)."""
    issue: int | None = None
    pr: int | None = None
    for event in events:
        if issue is None and isinstance(event.get("issue"), int):
            issue = event["issue"]
        if pr is None and isinstance(event.get("pr"), int):
            pr = event["pr"]
    return issue, pr
