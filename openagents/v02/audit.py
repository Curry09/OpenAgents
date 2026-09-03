# Spec-0085/T1
"""Persist one immutable, machine-readable v0.2 batch terminal record."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from openagents.v02.model import BatchResult


def write_result(*, work_dir: Path, result: BatchResult) -> Path:
    """Atomically append a run record; prior runs are never overwritten."""
    root = Path(work_dir) / ".openagents" / "v02-runs"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    path = root / f"{stamp}-{uuid4().hex[:8]}.json"
    temporary = path.with_suffix(".tmp")
    payload = {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "result": asdict(result),
    }
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


__all__ = ["write_result"]
