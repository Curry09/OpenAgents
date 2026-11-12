"""RFC-0001 T6: The result viewer rendering and local start (decision 9) module testing.

# Spec-0063/T3: Consumption of diagram run record (issue_number/status/branch/pr_number/)
# closed_at, retired old cage column (summary/pr_url/rounds/fingerprint).
Overwrite: Render renders the dict log list to be recast as a single page HTML (with issue/ status/ PR in place),
And do HTML conversion injection; empty runs render ”No different records yet” empty lines; board generate files,
Call webbrowser.open (not really on a browser by a Monkeywatch) and return the file path.
"""

import openagents.utils.results as results
from openagents.runtime.state import RuntimeState


def _record(*, issue_number, status, pr_number=None):
    """Construct a Runtime State dict run record to render assertions."""
    return {
        "issue_number": issue_number,
        "status": status,
        "branch": f"openagents/issue-{issue_number}",
        "pr_number": pr_number if pr_number is not None else issue_number * 10,
        "closed_at": "",
    }


def test_render_returns_html_document():
    html = results.render(runs=[])
    assert "<html" in html.lower()
    assert "</html>" in html.lower()


def test_render_empty_runs_shows_placeholder_row():
    html = results.render(runs=[])
    assert "No delivery records yet" in html


def test_render_includes_issue_number_and_status_and_pr_number():
    record = _record(issue_number=3, status="pr-open", pr_number=30)
    html = results.render(runs=[record])

    assert "#3" in html
    assert "pr-open" in html
    assert "#30" in html  # Pr-hatting (Runtestate no pr_url, only pr_number)


def test_render_missing_pr_number_shows_dash():
    record = _record(issue_number=7, status="solving", pr_number=0)
    html = results.render(runs=[record])
    # pr_number Yes 0/None → PR "Stand in the table."—」No rendering #0（`>#0<` The precise match of cell contents,
    # Avoid #0f1117 equal colour from the CSS template.
    assert "#7" in html
    assert ">#0<" not in html


def test_render_escapes_html_in_status():
    record = _record(issue_number=2, status="<b>weird</b>", pr_number=20)
    html = results.render(runs=[record])
    assert "<b>weird</b>" not in html
    assert "&lt;b&gt;weird&lt;/b&gt;" in html


def test_render_multiple_runs_all_present():
    runs = [
        _record(issue_number=1, status="done", pr_number=10),
        _record(issue_number=2, status="pr-open", pr_number=20),
    ]
    html = results.render(runs=runs)
    assert "#1" in html
    assert "#2" in html
    assert "#10" in html
    assert "#20" in html


def test_board_writes_file_and_returns_path(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(results.webbrowser, "open", lambda url: opened.append(url))

    state = RuntimeState(path=tmp_path / ".openagents" / "runtime-state.json")
    state.set_run(
        issue_number=4,
        branch="openagents/issue-4",
        pr_number=40,
        status="pr-open",
    )

    monkeypatch.chdir(tmp_path)
    path = results.board(state=state)

    assert path.exists()
    assert path.read_text(encoding="utf-8").lower().count("<html") == 1
    assert len(opened) == 1


def test_board_does_not_open_real_browser(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(results.webbrowser, "open", lambda url: calls.append(url))

    state = RuntimeState(path=tmp_path / ".openagents" / "runtime-state.json")
    monkeypatch.chdir(tmp_path)
    path = results.board(state=state)

    # Open url should point to the board file just written.
    assert calls
    assert str(path) in calls[0]
