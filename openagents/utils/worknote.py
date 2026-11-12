# Spec-0051/T3
"""Render implementation and iteration receipts for pull request comments.

These formatters perform no I/O. Signing and posting are the caller’s job.
"""

from __future__ import annotations

# Two types of backlash are on the rise (render_* 's first anchor). The traverse itself embeds culture in the headline of the reason, making ci/review
# Natural sub-breaves (go grouping by heading line and insulated from the different reasson traverse; Spec-0051/T5_report_already_posted).
_IMPLEMENT_HEADER = "## Implementation report"
_ITERATE_HEADER = "## Iteration report"

# Override two sources of feedback that _process_coding will import;
# Unknown return to original text (never drop, same style as blocknote._GATE_REASONS).
_REASON_LABELS = {
    "ci": "CI feedback",
    "review": "Code review feedback",
}

# Summary is the place where time is empty (same as the empty orchestrator._REFINE_COMMENT summary is returned).
_EMPTY_SUMMARY = "(No summary)"


def render_implement(*, summary: str) -> str:
    """Render an implementation report with a stable heading and summary.
    Spec-0051/T3.
    """
    return f"{_IMPLEMENT_HEADER}\n\n{_summary_body(summary=summary)}"


def render_iterate(*, reason: str, summary: str) -> str:
    """Render an iteration report with a heading that distinguishes the feedback source.
    Spec-0051/T3.
    """
    label = _REASON_LABELS.get(reason, reason or _EMPTY_SUMMARY)
    return f"{_ITERATE_HEADER} ({label})\n\n{_summary_body(summary=summary)}"


def _summary_body(*, summary: str) -> str:
    """Use a placeholder when no summary was supplied."""
    return summary.strip() if summary.strip() else _EMPTY_SUMMARY
