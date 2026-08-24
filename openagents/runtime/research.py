"""Normalize and render bounded, objective repository evidence for role reuse."""

from __future__ import annotations

import json
from typing import Any

MAX_ITEMS = 24
_FIELDS = (
    "fact",
    "path",
    "symbol",
    "verification",
    "source_revision",
    "line_range",
    "interface",
    "tasks",
)
_LIMITS = {
    "fact": 400,
    "path": 240,
    "symbol": 160,
    "verification": 400,
    "source_revision": 120,
    "line_range": 80,
    "interface": 600,
    "tasks": 120,
}


def normalize(items: Any) -> list[dict[str, str]]:
    """Return a bounded evidence pack containing only objective string fields."""
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in items[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        record = {
            field: str(item.get(field, "")).strip()[: _LIMITS[field]] for field in _FIELDS[:4]
        }
        record.update(
            {
                field: value
                for field in _FIELDS[4:]
                if (value := str(item.get(field, "")).strip()[: _LIMITS[field]])
            }
        )
        if record["fact"] and record["path"]:
            normalized.append(record)
    return normalized


def render(items: Any) -> str:
    """Render normalized evidence as compact JSON for an agent prompt."""
    return json.dumps(normalize(items), ensure_ascii=False, separators=(",", ":"))


def merge(*packs: Any) -> list[dict[str, str]]:
    """Merge evidence packs, letting later records refresh the same path and symbol."""
    merged: dict[tuple[str, str], dict[str, str]] = {}
    for pack in packs:
        for item in normalize(pack):
            identity = (item["path"], item["symbol"] or item["fact"])
            if identity in merged:
                merged[identity] = merged[identity] | {
                    key: value for key, value in item.items() if value
                }
            elif len(merged) < MAX_ITEMS:
                merged[identity] = item
    return list(merged.values())
