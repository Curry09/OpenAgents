"""Spec-0079: privacy-minimal, append-only token usage ledger."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openagents.backends.base import TokenUsage
from openagents.runtime.tool_usage import _telemetry_root

TOKEN_USAGE_FILENAME = "token-usage.jsonl"
_STATUSES = frozenset({"success", "backend_error", "protocol_error"})


def record(
    *,
    work_dir: Path,
    role: str,
    backend: str,
    status: str,
    usage: TokenUsage | None,
) -> None:
    """Append exactly one privacy-minimal invocation event; telemetry is fail-open."""
    try:
        if status not in _STATUSES:
            raise ValueError(f"unknown invocation status: {status}")
        path = _telemetry_root(work_dir=Path(work_dir)) / ".openagents" / TOKEN_USAGE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "invocation_id": uuid.uuid4().hex,
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "role": str(role),
            "backend": str(backend),
            "status": status,
            "usage_source": "reported" if usage is not None else "unavailable",
            "model": usage.model if usage is not None else None,
            "input_tokens": usage.input_tokens if usage is not None else None,
            "output_tokens": usage.output_tokens if usage is not None else None,
            "cache_read_input_tokens": (
                usage.cache_read_input_tokens if usage is not None else None
            ),
            "cache_creation_input_tokens": (
                usage.cache_creation_input_tokens if usage is not None else None
            ),
            "reasoning_tokens": usage.reasoning_tokens if usage is not None else None,
            "total_tokens": usage.total_tokens if usage is not None else None,
            "total_source": usage.total_source if usage is not None else None,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 -- observability must never change workflow semantics
        return


def load_events(*, path: Path) -> list[dict[str, Any]]:
    """Load complete ledger rows and ignore missing, malformed, or unknown rows."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(event, dict)
            and event.get("role")
            and event.get("usage_source") in ("reported", "unavailable")
            and event.get("status") in _STATUSES
        ):
            events.append(event)
    return events


def aggregate(*, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate counts and coverage by role without treating unavailable as zero usage."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event["role"]), []).append(event)
    rows = []
    token_fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "reasoning_tokens",
        "total_tokens",
    )
    for role in sorted(grouped):
        role_events = grouped[role]
        reported = [event for event in role_events if event.get("usage_source") == "reported"]
        row = {
            "role": role,
            "invocations": len(role_events),
            "reported": len(reported),
            "unavailable": len(role_events) - len(reported),
            "reported_total_count": sum(
                event.get("total_source") == "reported" for event in reported
            ),
            "derived_total_count": sum(
                event.get("total_source") == "derived-components" for event in reported
            ),
        }
        row.update(
            {field: sum(int(event.get(field) or 0) for event in reported) for field in token_fields}
        )
        rows.append(row)
    return rows
