# RFC-0001
"""Render and open the local delivery dashboard from recorded run state."""

from __future__ import annotations

import html
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Spec-0063/T3: Reconnect the new warehouse Runtestate -- its list_runs() returns the dict record (non-old house RunRecord).
    from openagents.runtime.state import RuntimeState

# Template and default output position (decision 9: Render static HTML+ local view).
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "board.html"
_OUTPUT_PATH = Path(".openagents") / "board.html"


def render(*, runs: list[dict]) -> str:
    """RFC-0001 T6: Render the Runte State Run Record List into a single page viewer HTML (decision 9).

    # Spec-0063/T3: Consumption of dict records (issue_number/status/branch/) for RuntimeState.list_runs()
    #pr_number/closed_at, retired old warehouse exclusive column (rounds/fingerprint/summary/pr_url - none of the new records).
    Each displays the issue, state, PR; all texts are transposed by `html.escape`.
    """
    template = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    rows = "\n".join(_render_row(record=record) for record in runs)
    if not rows:
        rows = '      <tr><td colspan="4" class="empty">No delivery records yet</td></tr>'
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return template.substitute(rows=rows, generated_at=html.escape(generated_at))


def board(*, state: RuntimeState) -> Path:
    """RFC-0001 T6: Rendering panel writing and opening with local browser to return file path (decision 9)."""
    output = _OUTPUT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    # Spec-0063/T3: all_runs((RunRecord) list_runs((dict record)).
    output.write_text(render(runs=state.list_runs()), encoding="utf-8")
    resolved = output.resolve()
    webbrowser.open(resolved.as_uri())
    return resolved


def _render_row(*, record: dict) -> str:
    """Renders the single Runtestate Dict record as a line <tr> and all fields as HTML transposes.

    # Spec-0063/T3: Number of columns (%1)4）with board.html Header (%1)Issue/status/PR/Summary)——No new record summary，
    # The column renders the bits # —; the PR column shows only pr_number (Runtestate without pr_url, minimum change without derivative link)
    # pr_number Yes None/0 ”and it’s the same place.”—」。dict All values are equal. .get Mistake.
    """
    issue = html.escape(str(record.get("issue_number", "")))
    status = html.escape(str(record.get("status", "")))
    pr_number = record.get("pr_number")
    pr_cell = html.escape(f"#{pr_number}") if pr_number else "—"
    return (
        "      <tr>"
        f"<td>#{issue}</td>"
        f'<td><span class="status">{status}</span></td>'
        f"<td>{pr_cell}</td>"
        "<td>—</td>"
        "</tr>"
    )
