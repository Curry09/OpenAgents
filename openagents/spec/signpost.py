"""Extract declared end-to-end verification scripts and render a PR signpost."""

from __future__ import annotations

import re
from pathlib import Path

from openagents.spec import model

# Integrated Test Script Relative Path: scripts/....sh, first (same as old rfc.py).
_SCRIPT_RE = re.compile(r"scripts/[^\s`)」]+\.sh")

# Spec-0028/T1: Summary of the embedded summary of the PR body - only three segments with the highest information density (what/ why/ what to do)
# Breaks each section above the maximum number of lines, avoiding the body inflating and flooding of Closes/Guidemarks (Reference-level / Drawbacks mitigation).
_DIGEST_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Summary", "summary"),
    ("Motivation", "motivation"),
    ("Reference-level explanation", "reference_level"),
)
# The maximum number of lines per paragraph (Unresolved questions: initial conservative value, followed by PR senses)
_DIGEST_MAX_LINES = 12
# A follow-up reminder of the break-up - a clear message to the reviewers to read the full text in the spec file.
_DIGEST_TRUNCATED_HINT = "... (see spec for full)"


def script_path_for_group(*, group_path: Path) -> str | None:
    """Scan a spec group’s Overview 9 for the first `scripts/*.sh`.

    issue #69: Script threads are taken from group overview (in _OVERVIEW_SECTIONS order, usually falling on Reference-level)
    Extracts. Group is now a single file NNNN-slug.md; Group is not read/ script-free Noone.
    """
    if not group_path.is_file():
        return None
    try:
        group = model.load_group(path=group_path)
    except (OSError, ValueError):
        return None
    for _, attr in model._OVERVIEW_SECTIONS:
        match = _SCRIPT_RE.search(getattr(group.overview, attr) or "")
        if match:
            return match.group(0)
    return None


def overview_digest_for_group(*, group_path: Path) -> str | None:
    """Render the Summary, Motivation, and Reference-level sections for the PR body.
    Spec-0028/T1.
    """
    if not group_path.is_file():
        return None
    try:
        group = model.load_group(path=group_path)
    except (OSError, ValueError):
        return None

    blocks: list[str] = []
    for heading, attr in _DIGEST_SECTIONS:
        body = _truncate_section(text=getattr(group.overview, attr) or "")
        if body:
            blocks.append(f"### {heading}\n{body}")
    if not blocks:
        # Three complete empty (unique, e.g., overview not completed): unfilled empty chunks, back to no digest (no behavior change).
        return None

    header = f"## Spec overview (docs/specs/{group_path.name})"
    return "\n\n".join([header, *blocks])


def _truncate_section(*, text: str) -> str:
    """Limit a digest section to the configured line count and add a truncation hint."""
    stripped = text.strip("\n")
    if not stripped.strip():
        return ""
    lines = stripped.split("\n")
    if len(lines) <= _DIGEST_MAX_LINES:
        return stripped
    return "\n".join([*lines[:_DIGEST_MAX_LINES], _DIGEST_TRUNCATED_HINT])


def signpost_for_group(*, group_path: Path) -> str | None:
    """Render a verification command and link to the Spec acceptance criteria."""
    if not group_path.is_file():
        return None
    number = group_path.name[:4]
    spec_id = f"Spec-{number}"
    script = script_path_for_group(group_path=group_path)

    run_line = (
        f"- Run: `bash {script}`"
        if script
        else f"- Run: see the Reference-level explanation in {spec_id}"
    )
    detail_line = f"- See docs/specs/{group_path.name} and each task’s `acceptance` criteria"
    return "\n".join(["## End-to-end verification", run_line, detail_line])
