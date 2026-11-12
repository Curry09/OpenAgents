"""Spec-0028/T1: overview_digest_for_group unit test.

Reads only spec group markdown (real model.dump_group drop-off file), without touch to git / GitHub.
Overwrite: 3 full rendering, overline cut-off and relay tips, missing passages, 3 full empty  →  None,
Non-file / Unread  → None (zero returns).
"""

from pathlib import Path

import pytest

from openagents.spec import model as spec_model
from openagents.spec.model import Group, Metadata, Overview, Task
from openagents.spec.signpost import (
    _DIGEST_MAX_LINES,
    _DIGEST_TRUNCATED_HINT,
    overview_digest_for_group,
)


def _dump(*, root, overview, number="0028", slug="pr-digest-and-conflict-agent"):
    group = Group(
        number=number,
        metadata=Metadata(title="Example:", issue=79, slug=slug, summary="TL;DR"),
        tasks=[Task(id="T1", title="t", status="pending", priority="P1")],
        overview=overview,
    )
    path = spec_model.group_path(specs_root=Path(root), number=number, slug=slug)
    spec_model.dump_group(group=group, path=path)
    return path


def test_digest_renders_three_sections(tmp_path):
    path = _dump(
        root=tmp_path,
        overview=Overview(
            summary="A summary of the sentence.",
            motivation="Why do you do that?",
            reference_level="How do technical programmes work?",
            # The following sections do not go into the digest.
            drawbacks="Shortcomings (not to be found in digest).",
        ),
    )
    digest = overview_digest_for_group(group_path=path)
    assert digest is not None
    assert digest.startswith(f"## Spec overview (docs/specs/{path.name})")
    assert "### Summary\nA summary of the sentence." in digest
    assert "### Motivation\nWhy do you do that?" in digest
    assert "### Reference-level explanation\nHow do technical programmes work?" in digest
    # Take only three paragraphs, excluding Drawbacks.
    assert "Drawbacks" not in digest
    assert "Disadvantages" not in digest


def test_digest_truncates_long_section(tmp_path):
    long_body = "\n".join(f"Line {i}" for i in range(_DIGEST_MAX_LINES + 5))
    path = _dump(root=tmp_path, overview=Overview(summary=long_body))
    digest = overview_digest_for_group(group_path=path)
    assert digest is not None
    # Keep the N-line + renewal hint, and the excess line is stopped.
    assert "Line 0" in digest
    assert f"Line {_DIGEST_MAX_LINES - 1}" in digest
    assert f"Line {_DIGEST_MAX_LINES}" not in digest
    assert _DIGEST_TRUNCATED_HINT in digest


def test_digest_skips_empty_sections(tmp_path):
    # Only summary, motivation/reference-level emptys only relish the Summary block.
    path = _dump(root=tmp_path, overview=Overview(summary="Only summary."))
    digest = overview_digest_for_group(group_path=path)
    assert digest is not None
    assert "### Summary" in digest
    assert "### Motivation" not in digest
    assert "### Reference-level explanation" not in digest


def test_digest_none_when_all_three_empty(tmp_path):
    # Three complete empty (e.g., unfilled overview) unfilled empty blocks returns None (back to no digest, no behavior change).
    path = _dump(root=tmp_path, overview=Overview(guide_level="Only figure-level."))
    assert overview_digest_for_group(group_path=path) is None


def test_digest_none_when_not_a_file(tmp_path):
    assert overview_digest_for_group(group_path=tmp_path / "missing.md") is None


def test_digest_none_when_unreadable(tmp_path, monkeypatch):
    path = _dump(root=tmp_path, overview=Overview(summary="x"))

    def _boom(*, path):
        raise ValueError("Bad spec.")

    monkeypatch.setattr(spec_model, "load_group", _boom)
    assert overview_digest_for_group(group_path=path) is None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
