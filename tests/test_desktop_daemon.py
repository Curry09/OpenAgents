"""# Spec-0073/T2: 本地 daemon 接口（HTTP+SSE）单测。

覆盖：`pending_category` 四级优先级；`read_work_queue` 读队列快照（DB 缺失→空）；`build_board` 合成 + 待看
类别；起真实 server GET /board 返 JSON、GET /stream/<subject>?follow=0 SSE 逐条推 ring buffer 行；未知
subject → 404 JSON；端口占用 → DaemonError。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from openagents.desktop import daemon
from openagents.utils import streams

# 直连本机 server，绕开环境里的 HTTP 代理（否则 localhost 请求被代理拦成 502）。
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture(autouse=True)
def _clean_streams():
    streams.reset()
    yield
    streams.reset()


def _seed_queue(*, db_path: Path, rows: list[tuple[str, str, int]]) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE work_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT UNIQUE, "
        "status TEXT, worker TEXT, worker_pid INTEGER, claimed_at TEXT, attempts INTEGER, "
        "priority INTEGER)"
    )
    for subject, status, attempts in rows:
        conn.execute(
            "INSERT INTO work_queue (subject, status, worker, attempts) VALUES (?, ?, ?, ?)",
            (subject, status, "w1", attempts),
        )
    conn.commit()
    conn.close()


def test_pending_category_priority_order():
    assert (
        daemon.pending_category(
            needs_human=True,
            pr_ready_to_merge=True,
            has_new_human_comment=True,
            just_changed=True,
        )
        == daemon.PENDING_NEEDS_HUMAN
    )
    assert (
        daemon.pending_category(
            needs_human=False,
            pr_ready_to_merge=True,
            has_new_human_comment=True,
            just_changed=True,
        )
        == daemon.PENDING_PR_TO_MERGE
    )
    assert (
        daemon.pending_category(
            needs_human=False,
            pr_ready_to_merge=False,
            has_new_human_comment=True,
            just_changed=True,
        )
        == daemon.PENDING_NEW_COMMENT
    )
    assert (
        daemon.pending_category(
            needs_human=False,
            pr_ready_to_merge=False,
            has_new_human_comment=False,
            just_changed=True,
        )
        == daemon.PENDING_JUST_CHANGED
    )
    assert (
        daemon.pending_category(
            needs_human=False,
            pr_ready_to_merge=False,
            has_new_human_comment=False,
            just_changed=False,
        )
        is None
    )


def test_read_work_queue_missing_db_is_empty(tmp_path):
    assert daemon.read_work_queue(db_path=tmp_path / "nope.db") == []


def test_read_work_queue_reads_rows(tmp_path):
    db = tmp_path / "vigil-queue.db"
    _seed_queue(db_path=db, rows=[("issue:1", "claimed", 1), ("pr:2", "queued", 0)])
    rows = daemon.read_work_queue(db_path=db)
    assert [r["subject"] for r in rows] == ["issue:1", "pr:2"]
    assert rows[0]["status"] == "claimed"
    assert rows[0]["attempts"] == 1


def test_build_board_offline_computes_no_pending():
    rows = [{"subject": "issue:1", "status": "claimed", "worker": "w1", "attempts": 1}]
    board = daemon.build_board(rows=rows, enrich=None)
    assert board[0]["subject"] == "issue:1"
    assert board[0]["pending"] is None


def test_build_board_enrich_sets_pending():
    rows = [{"subject": "issue:1", "status": "claimed", "worker": "w1", "attempts": 1}]

    def _enrich(subject: str) -> dict:
        return {"needs_human": True, "pr": 170}

    board = daemon.build_board(rows=rows, enrich=_enrich)
    assert board[0]["pr"] == 170
    assert board[0]["pending"] == daemon.PENDING_NEEDS_HUMAN


def _run_server(server) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def test_board_and_stream_over_http(tmp_path):
    streams.bind(subject="issue:1")
    streams.emit(line="第一行")
    streams.emit(line="第二行")
    streams.unbind()

    def _board_fn() -> list[dict]:
        return [{"subject": "issue:1", "status": "claimed", "pending": None}]

    server = daemon.serve(host="127.0.0.1", port=0, board_fn=_board_fn)
    port = server.server_address[1]
    thread = _run_server(server)
    try:
        with _NO_PROXY.open(f"http://127.0.0.1:{port}/board", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload == [{"subject": "issue:1", "status": "claimed", "pending": None}]

        url = f"http://127.0.0.1:{port}/stream/issue:1?follow=0"
        with _NO_PROXY.open(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "data: 第一行\n" in body
        assert "data: 第二行\n" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_stream_unknown_subject_returns_404_json(tmp_path):
    server = daemon.serve(host="127.0.0.1", port=0, board_fn=lambda: [])
    port = server.server_address[1]
    thread = _run_server(server)
    try:
        url = f"http://127.0.0.1:{port}/stream/pr:404?follow=0"
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _NO_PROXY.open(url, timeout=5)
        assert excinfo.value.code == 404
        payload = json.loads(excinfo.value.read().decode("utf-8"))
        assert "unknown subject" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_serve_on_busy_port_raises_daemon_error():
    first = daemon.serve(host="127.0.0.1", port=0, board_fn=lambda: [])
    port = first.server_address[1]
    try:
        with pytest.raises(daemon.DaemonError):
            daemon.serve(host="127.0.0.1", port=port, board_fn=lambda: [])
    finally:
        first.server_close()
