# Spec-0073/T2
"""Serve the desktop dashboard over local HTTP and server-sent events.

Board entries combine the work queue with available forge data. Pending items
are ordered by automation failure, awaiting merge, new human comments, then
recent changes. The renderer shares that priority order.
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from openagents.utils import streams

# Four categories (high and low priority) to be observed.
PENDING_AUTOMATION_FAILED = "automation-failed"
PENDING_PR_TO_MERGE = "pr-to-merge"
PENDING_NEW_COMMENT = "new-comment"
PENDING_JUST_CHANGED = "just-changed"
PENDING_ORDER = [
    PENDING_AUTOMATION_FAILED,
    PENDING_PR_TO_MERGE,
    PENDING_NEW_COMMENT,
    PENDING_JUST_CHANGED,
]

# SSE continues the interrogation interval (sec): hibernation in the non-new line in the follow mode.
_POLL_INTERVAL = 0.5


class DaemonError(RuntimeError):
    """Daemon failed to get up (e.g. port occupation) - CLI thus made a clean mistake and did not quit."""


def pending_category(
    *,
    automation_failed: bool,
    pr_ready_to_merge: bool,
    has_new_human_comment: bool,
    just_changed: bool,
) -> str | None:
    """The status of a subproject is classified as a category to be watched in a 4th priority; neither returns None (not in the set to be read)."""
    if automation_failed:
        return PENDING_AUTOMATION_FAILED
    if pr_ready_to_merge:
        return PENDING_PR_TO_MERGE
    if has_new_human_comment:
        return PENDING_NEW_COMMENT
    if just_changed:
        return PENDING_JUST_CHANGED
    return None


def read_work_queue(*, db_path: Path) -> list[dict]:
    """Read a snapshot of `work_queue` for a line of subsubject; DB does not exist (vigil did not run) returns an empty list without dropping."""
    path = Path(db_path)
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT subject, status, worker, attempts, claimed_at FROM work_queue ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def build_board(*, rows: list[dict], enrich: Callable[[str], dict] | None) -> list[dict]:
    """work_queue Line + Optional GitHub eutrophication of the board entry and counting as a category to be looked at for each subproject. Pure function, easy to measure.

    `enrich(subject)` returns a dict that contains `pr`/ `labels`/ `automation_failed`/ `pr_ready_to_merge`/
    `has_new_human_comment` / `just_changed`, etc. frontend field; `None` = offline, all of which are not siphoned.
    """
    board: list[dict] = []
    for row in rows:
        subject = row["subject"]
        extra = enrich(subject) if enrich is not None else {}
        entry: dict = {
            "subject": subject,
            "status": row.get("status"),
            "worker": row.get("worker"),
            "attempts": row.get("attempts"),
        }
        entry.update(extra)
        entry["pending"] = pending_category(
            automation_failed=bool(extra.get("automation_failed")),
            pr_ready_to_merge=bool(extra.get("pr_ready_to_merge")),
            has_new_human_comment=bool(extra.get("has_new_human_comment")),
            just_changed=bool(extra.get("just_changed")),
        )
        board.append(entry)
    return board


def default_board_fn(
    *, db_path: Path, enrich: Callable[[str], dict] | None
) -> Callable[[], list[dict]]:
    """CLI provides a function by binding db_path (+ Emancipated Hook) to an unsqualid board for handler to read at request."""

    def _fn() -> list[dict]:
        rows = read_work_queue(db_path=db_path)
        return build_board(rows=rows, enrich=enrich)

    return _fn


def make_handler(*, board_fn: Callable[[], list[dict]]) -> type[BaseHTTPRequestHandler]:
    """Creates a request processing class for `board_fn` in a closed package. Only the GET, the rest of the path 404 JSON."""

    class _DesktopHandler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # noqa: A002 —_ Mute http.server Default stderr Access Log
            return

        def do_GET(self) -> None:  # noqa: N802 —— BaseHTTPRequesthandler
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path == "/board":
                self._send_json(status=200, payload=board_fn())
                return
            if path.startswith("/stream/"):
                subject = urllib.parse.unquote(path[len("/stream/") :])
                query = urllib.parse.parse_qs(parsed.query)
                follow = query.get("follow", ["1"])[0] not in ("0", "false", "")
                self._handle_stream(subject=subject, follow=follow)
                return
            self._send_json(status=404, payload={"error": f"not found: {path}"})

        def _send_json(self, *, status: int, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle_stream(self, *, subject: str, follow: bool) -> None:
            first = streams.read_since(subject=subject, after_seq=-1)
            if first is None:
                self._send_json(status=404, payload={"error": f"unknown subject: {subject}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            lines, last_seq = first
            if not self._emit_lines(lines=lines):
                return
            while follow:
                more = streams.read_since(subject=subject, after_seq=last_seq)
                if (
                    more is None
                ):  # The project's buffer is cleared (vigil is restored) and collected
                    return
                lines, last_seq = more
                if lines:
                    if not self._emit_lines(lines=lines):
                        return
                else:
                    time.sleep(_POLL_INTERVAL)

        def _emit_lines(self, *, lines: list[str]) -> bool:
            """Writes each line by the SSE `data:` frame; the client breakup (BrokenPipe) returns False to get the upper stream."""
            try:
                for line in lines:
                    for part in line.split("\n"):
                        self.wfile.write(f"data: {part}\n".encode())
                    self.wfile.write(b"\n")
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                return False

    return _DesktopHandler


def serve(*, host: str, port: int, board_fn: Callable[[], list[dict]]) -> ThreadingHTTPServer:
    """Start a linear HTTP server (without blocking) at host:port. Port occupation, etc. OSERrror `DaemonError`."""
    handler = make_handler(board_fn=board_fn)
    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise DaemonError(f"Could not start the desktop daemon at {host}:{port}: {exc}") from exc


def run(*, host: str, port: int, board_fn: Callable[[], list[dict]]) -> None:
    """Front desk permanent: `serve_forever`, Ctrl-C clean-out."""
    server = serve(host=host, port=port, board_fn=board_fn)
    bound_port = server.server_address[1]
    print(f"✓ desktop daemon: http://{host}:{bound_port}  (press Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ Desktop daemon stopped", flush=True)
    finally:
        server.shutdown()
        server.server_close()
