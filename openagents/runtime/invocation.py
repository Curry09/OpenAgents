"""Fail-open, redacted audit records for delivery-side agent invocations."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_SECRET_ENV_NAMES = (
    "GITEA_TOKEN",
    "VIGIL_REPO_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "HARNESS_LLM_API_KEY",
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "OPENAGENTS_NEXAU_API_KEY",
)


def redact_text(text: str) -> str:
    """Replace every configured secret value before text crosses an audit boundary."""
    redacted = str(text)
    for name in _SECRET_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            redacted = redacted.replace(value, f"${{{name}}}")
    return redacted


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def _subject(placeholders: dict[str, Any]) -> dict[str, str]:
    if placeholders.get("pr_number") is not None:
        return {"kind": "pull_request", "id": str(placeholders["pr_number"])}
    if placeholders.get("issue_number") is not None:
        return {"kind": "issue", "id": str(placeholders["issue_number"])}
    return {"kind": "agent", "id": ""}


def _optional_round() -> int | None:
    raw = os.environ.get("AUTO_DESIGNER_ROUND", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def record(
    *,
    role: str,
    backend: str,
    prompt: str,
    context: str,
    placeholders: dict[str, Any],
    structured: Any,
    status: str,
    error: str | None,
) -> None:
    """Write one v1 invocation JSON plus an index row; never affect delivery."""
    root_raw = os.environ.get("ROLE_RUNS_DIR", "").strip()
    if not root_raw:
        return
    try:
        root = Path(root_raw)
        root.mkdir(parents=True, exist_ok=True)
        invocation_id = uuid.uuid4().hex
        captured_at = datetime.now(UTC).isoformat()
        payload = {
            "schema_version": 1,
            "invocation_id": invocation_id,
            "run_id": os.environ.get("AUTO_DESIGNER_RUN_ID"),
            "round": _optional_round(),
            "side": "delivery",
            "role": role,
            "subject": _subject(placeholders),
            "replayable": False,
            "input": {
                "prompt": redact_text(prompt),
                "context": redact_text(context),
                "placeholders": _redact(placeholders),
            },
            "output": {
                "structured": _redact(structured),
                "status": status,
                "error": redact_text(error) if error else None,
            },
            "env": {
                "model": os.environ.get("ANTHROPIC_MODEL"),
                "agent_def_pin": None,
                "backend": backend,
                "captured_at": captured_at,
            },
        }
        stamp = captured_at.replace(":", "").replace("-", "")[:15]
        relative = f"{stamp}_{role}_{invocation_id[:8]}.json"
        path = root / relative
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        row = json.dumps(
            {
                "invocation_id": invocation_id,
                "side": "delivery",
                "role": role,
                "status": status,
                "path": relative,
            },
            ensure_ascii=False,
        )
        with _LOCK, (root / "index.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(row + "\n")
    except Exception:
        return
