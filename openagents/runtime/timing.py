"""# Spec-0066/T1: runtime.timing —— 墙钟阶段计时的旁路事件流 + 跨轮重建聚合器。

守夜是**轮询式** reconcile：每 tick 把每个 subject 往前推一步、`sleep(interval)` 后再来一轮，**没有任何
一处阻塞等 CI/review**。所以「某阶段耗时」不是一次函数调用的墙钟，而是**该 subject 反复被判成同一个阶段
的那段连续 tick 覆盖的日历时间**——必须**跨轮重建**（见 spec Motivation / Kubernetes level-triggered）。

本模块只做三件事，且**仅依赖标准库**、与 `runtime-state.json` / `vigil-queue.db` **文件级零耦合**
（理念 10）、对 `recipes.vigil` **零依赖**（phase 是纯字符串，归一逻辑留在 vigil、见 `_phase_of`），杜绝
循环 import：

1. `record(...)` —— append-only 事件写入器，落到 `work_dir/.openagents/timing.jsonl`（每行一个 JSON
   事件）。**容错**：捕获全部异常、绝不向调用方抛（写失败只丢一条计时，绝不掀翻守夜主流程）。
2. `load_events(...)` —— 读 jsonl，逐行容错跳过损坏行。
3. `timelines(...)` / `phase_stats(...)` —— 纯函数聚合，hermetic 可测：
   - `timelines`：按 subject 分组、按 `at` 排序，**每条事件占据「到该 subject 下一条事件为止」的墙钟
     区间**（末条事件为终点、区间 0），连续同 phase 合并为一段，聚合出各 phase 总 dwell。天然支持 phase
     复现（`review-or-fix → fix-ci → review-or-fix` 分两段累加）且每区间≈一个 interval（精度下限来源）。
   - `phase_stats`：跨 subject 对「各 subject 在该 phase 的总 dwell」求 p50/p90（尾延迟看百分位，见
     Google SRE）+ 最长尾 subject；报告结构携带 `interval` 作为墙钟精度下限标注。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Spec-0066/T1: 独立事件流文件名——与 runtime-state.json / vigil-queue.db 文件级零耦合（理念 10）。
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
    """# Spec-0066/T1: append 一条阶段信号事件到 `work_dir/.openagents/timing.jsonl`（旁路、容错）。

    **绝不向调用方抛任何异常**——计时是旁路富化，写失败只丢一条计时；守夜第一要务是「活着进下一轮」，
    一条 append IO 崩掉绝不能掀翻主流程（对齐既有「只富化不回归」）。schema 见模块 docstring 的样例。
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
    except Exception:  # noqa: BLE001 —— 旁路容错：写失败只丢一条计时，绝不掀翻守夜主流程
        return


def load_events(*, path: Path) -> list[dict[str, Any]]:
    """# Spec-0066/T1: 读 jsonl 事件流，逐行容错跳过损坏行/缺字段行；文件缺失 → 空列表。"""
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
            continue  # 损坏行：跳过、只保留合法事件
        if isinstance(obj, dict) and "subject" in obj and "phase" in obj and "at" in obj:
            events.append(obj)
    return events


@dataclass(frozen=True)
class Segment:
    """时间线上的一段：连续同 phase 区间合并后的墙钟停留（秒）。"""

    phase: str
    seconds: float


@dataclass(frozen=True)
class Timeline:
    """单 subject 的跨轮重建时间线：有序 segments（含 phase 复现分段）+ 各 phase 总 dwell。"""

    subject: str
    issue: int | None
    pr: int | None
    segments: tuple[Segment, ...]  # 按时间序、连续同 phase 已合并
    durations: dict[str, float]  # phase → 该 subject 在此 phase 的总 dwell（秒，跨复现累加）
    total: float  # 首戳到末戳的墙钟总长（秒）


@dataclass(frozen=True)
class PhaseStat:
    """某 phase 跨 subject 的分位统计 + 最长尾 subject。"""

    phase: str
    p50: float
    p90: float
    count: int  # 有该 phase 的 subject 数
    max_subject: str  # 最长尾（在该 phase 停留最久）的 subject
    max_seconds: float


@dataclass(frozen=True)
class PhaseStats:
    """`phase_stats` 的报告结构：各 phase 分位 + **墙钟精度下限 = interval**（秒）。"""

    interval: int  # 墙钟精度下限：各段时延有 ±interval 粒度误差，勿当精确值
    phases: tuple[PhaseStat, ...]


def timelines(*, events: list[dict[str, Any]]) -> list[Timeline]:
    """# Spec-0066/T1: 跨轮重建——把事件流按 subject 折叠成各自的阶段时间线。

    **每条事件占据「到该 subject 下一条事件为止」的墙钟区间**（末条为终点、区间 0）；连续同 phase 的区间
    合并成一段 Segment，同 phase 的所有区间累加进 `durations`（故 `review→fix→review` 的两段自然累加）。
    subject 按名排序、返回顺序稳定（可 hermetic 断言）。
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
                span = 0.0  # 末条事件是终点，区间 0（terminal 时长 0）
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
    """# Spec-0066/T1: 跨 subject 汇总每 phase 的 p50/p90 + 最长尾 subject，携 interval 精度下限。

    对每个 phase，收「各**有该 phase** 的 subject 在此 phase 的总 dwell」求分位（p90 看尾延迟，见
    Google SRE）；`max_subject` 为该 phase 停留最久的 subject。phase 按名排序、返回稳定。
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
# 纯辅助（时间解析 / 分位 / subject 归属）。
# --------------------------------------------------------------------------------------------------


def _iso(*, now: datetime) -> str:
    """datetime → UTC ISO8601（`...Z` 后缀）；naive 视为已是 UTC。"""
    moment = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_at(*, at: str) -> datetime:
    """ISO8601（含 `Z` 后缀）→ UTC-aware datetime；容错回落到纪元零点（不让一条坏 `at` 掀翻聚合）。"""
    try:
        parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _percentile(*, values: list[float], q: float) -> float:
    """线性插值分位（stdlib、确定性）。空 → 0.0；单值 → 该值。q ∈ [0,100]。"""
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
    """从该 subject 的事件里取 issue/pr 号（取首个非空值；裸 PR 无 issue → None）。"""
    issue: int | None = None
    pr: int | None = None
    for event in events:
        if issue is None and isinstance(event.get("issue"), int):
            issue = event["issue"]
        if pr is None and isinstance(event.get("pr"), int):
            pr = event["pr"]
    return issue, pr
