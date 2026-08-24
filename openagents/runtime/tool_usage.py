"""Privacy-preserving, append-only tool-usage telemetry for agent invocations."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TOOL_USAGE_FILENAME = "tool-usage.jsonl"
DEFAULT_LOOKUP_BUDGET = 6
_EDIT_TOOLS = frozenset({"edit", "write", "multiedit", "notebookedit"})
_LOOKUP_TOOLS = frozenset({"read", "bash", "grep", "glob", "search", "find"})


def _telemetry_root(*, work_dir: Path) -> Path:
    """Return the main worktree root so per-issue worktrees share one report stream."""
    root = Path(work_dir)
    dot_git = root / ".git"
    if not dot_git.is_file():
        return root
    try:
        marker = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return root
    prefix = "gitdir:"
    if not marker.casefold().startswith(prefix):
        return root
    git_dir = Path(marker[len(prefix) :].strip())
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()
    # Linked worktree gitdir: <main>/.git/worktrees/<name>.
    if git_dir.parent.name == "worktrees" and git_dir.parent.parent.name == ".git":
        return git_dir.parent.parent.parent
    return root


def summarize(*, tool_names: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Summarize ordered tool names, including lookup count before the first edit."""
    names = [str(name) for name in tool_names]
    lowered = [name.casefold() for name in names]
    first_edit = next((index for index, name in enumerate(lowered) if name in _EDIT_TOOLS), None)
    prefix = lowered if first_edit is None else lowered[:first_edit]
    lookup_count = sum(name in _LOOKUP_TOOLS for name in prefix)
    return {
        "tool_count": len(names),
        "tool_names": names,
        "first_edit_index": first_edit,
        "lookup_before_first_edit": lookup_count,
        "lookup_budget": DEFAULT_LOOKUP_BUDGET,
        "lookup_budget_exceeded": lookup_count > DEFAULT_LOOKUP_BUDGET,
    }


def record(
    *,
    work_dir: Path,
    role: str,
    tool_names: tuple[str, ...] | list[str],
    lookup_exception_reason: str = "",
) -> None:
    """Append one invocation metric; failures never affect the agent workflow."""
    try:
        path = _telemetry_root(work_dir=Path(work_dir)) / ".openagents" / TOOL_USAGE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        usage = summarize(tool_names=tool_names)
        event = {
            "invocation_id": uuid.uuid4().hex,
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "role": role,
            **usage,
        }
        if usage["lookup_budget_exceeded"] and lookup_exception_reason.strip():
            event["lookup_exception_reason"] = lookup_exception_reason.strip()[:400]
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 -- telemetry is non-critical
        return


def load_events(*, path: Path) -> list[dict[str, Any]]:
    """Load valid telemetry rows, skipping missing, malformed, or incomplete lines."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("role") and "tool_count" in event:
            events.append(event)
    return events


def aggregate(*, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate invocation and lookup-budget metrics by role."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event["role"]), []).append(event)
    rows: list[dict[str, Any]] = []
    for role in sorted(grouped):
        role_events = grouped[role]
        lookups = [int(event.get("lookup_before_first_edit", 0)) for event in role_events]
        rows.append(
            {
                "role": role,
                "invocations": len(role_events),
                "average_lookup_before_edit": sum(lookups) / len(lookups),
                "max_lookup_before_edit": max(lookups),
                "budget_exceeded": sum(
                    bool(event.get("lookup_budget_exceeded")) for event in role_events
                ),
                "exceeded_without_reason": sum(
                    bool(event.get("lookup_budget_exceeded"))
                    and not str(event.get("lookup_exception_reason", "")).strip()
                    for event in role_events
                ),
            }
        )
    return rows
