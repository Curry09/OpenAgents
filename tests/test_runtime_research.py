"""Tests for bounded cross-role repository evidence."""

import json

from openagents.runtime import research


def test_normalize_keeps_only_bounded_objective_fields() -> None:
    items = [
        {
            "fact": "timeout is polled",
            "path": "entry.py",
            "symbol": "_run_supervised",
            "verification": "read function body",
            "decision": "use this layer",
        },
        {"fact": "missing path"},
    ]
    assert research.normalize(items) == [
        {
            "fact": "timeout is polled",
            "path": "entry.py",
            "symbol": "_run_supervised",
            "verification": "read function body",
        }
    ]


def test_render_is_compact_and_caps_item_count() -> None:
    rendered = research.render(
        [{"fact": f"事实{i}" + "x" * 500, "path": "入口.py"} for i in range(research.MAX_ITEMS + 5)]
    )
    decoded = json.loads(rendered)
    assert len(decoded) == research.MAX_ITEMS
    assert len(decoded[0]["fact"]) == 400
    assert "事实" in rendered
    assert "\\u4e8b" not in rendered
    assert " " not in rendered


def test_merge_preserves_old_facts_and_refreshes_matching_identity() -> None:
    initial = [
        {
            "fact": "old interface",
            "path": "entry.py",
            "symbol": "_run_supervised",
            "verification": "read body",
            "source_revision": "a1",
            "interface": "old signature",
            "tasks": "T1",
        },
        {"fact": "tool schema is closed", "path": "tools/tool.yaml", "symbol": "schema"},
    ]
    refined = [
        {
            "fact": "current interface",
            "path": "entry.py",
            "symbol": "_run_supervised",
            "verification": "read revised body",
            "source_revision": "b2",
            "interface": "new signature",
            "tasks": "T1",
            "decision": "must not cross role boundary",
        }
    ]
    merged = research.merge(initial, refined)
    assert len(merged) == 2
    assert merged[0]["fact"] == "current interface"
    assert merged[0]["source_revision"] == "b2"
    assert merged[0]["interface"] == "new signature"
    assert "decision" not in merged[0]
    assert merged[1]["fact"] == "tool schema is closed"
