"""# Spec-0073/T2: 本地 daemon 接口（HTTP + SSE），只听 127.0.0.1。

两个端点：
- `GET /board` → 读 `vigil-queue.db` 的 `work_queue`（subject/status/worker/attempts）+ 可选 GitHub 富化 +
  每个 subject 的**待看类别**（见 `pending_category`），返回 JSON 数组。前端轮询它渲染 N 个小窗看板。
- `GET /stream/<subject>` → **SSE**（`text/event-stream`）：先把该 subject 的 ring buffer 已有行补发，
  再按 `?follow=1`（默认）持续增量续推。大窗订它看实时 agent 会话流。

**奥卡姆（理念 1）**：用 stdlib `http.server`，不引 web 框架。请求处理里的**纯逻辑**（`read_work_queue` /
`build_board` / `pending_category`）与 socket 解耦，可脱离 HTTP 直接单测；HTTP 层只做路由与序列化。

**待看优先级（与前端 `nav/pending.ts` 同序）**：① `automation-failed` 挂起 > ② PR 等合并 > ③ 人类新评论待回 >
④ 刚变状态。无类别 → 不在待看集（`pending=None`）。GitHub 富化是**可选钩子**：离线（`enrich=None`）时
只凭 work_queue 出 board，富化字段缺省即各 pending 判据为假——退化为「只呈现队列状态」，行为明确不静默。
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

# 待看四类（高→低优先级）。
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

# SSE 续推轮询间隔（秒）：follow 模式下无新行时的休眠。
_POLL_INTERVAL = 0.5


class DaemonError(RuntimeError):
    """daemon 起服务失败（如端口占用）——CLI 据此打一行干净错误、非零退出。"""


def pending_category(
    *,
    automation_failed: bool,
    pr_ready_to_merge: bool,
    has_new_human_comment: bool,
    just_changed: bool,
) -> str | None:
    """按四级优先级把一个 subject 的状态归到一个待看类别；都不满足返回 None（不在待看集）。"""
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
    """读 `work_queue` 一行一 subject 的快照；DB 不存在（vigil 没跑过）返回空列表，不抛。"""
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
    """把 work_queue 行 + 可选 GitHub 富化合成 board 条目，并算每 subject 的待看类别。纯函数、易测。

    `enrich(subject)` 返回一个 dict，可含 `pr` / `labels` / `automation_failed` / `pr_ready_to_merge` /
    `has_new_human_comment` / `just_changed` 等前端字段；`None` = 离线，全部缺省为假。
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
    """CLI 用：绑定 db_path（+可选富化钩子）成一个无参 board 提供函数，供 handler 每次请求现读。"""

    def _fn() -> list[dict]:
        rows = read_work_queue(db_path=db_path)
        return build_board(rows=rows, enrich=enrich)

    return _fn


def make_handler(*, board_fn: Callable[[], list[dict]]) -> type[BaseHTTPRequestHandler]:
    """造一个闭包住 `board_fn` 的请求处理类。只认 GET，其余路径 404 JSON。"""

    class _DesktopHandler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # noqa: A002 —— 静音 http.server 默认 stderr 访问日志
            return

        def do_GET(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 约定方法名
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
                if more is None:  # subject 的 buffer 被清（vigil 复位）→ 收流
                    return
                lines, last_seq = more
                if lines:
                    if not self._emit_lines(lines=lines):
                        return
                else:
                    time.sleep(_POLL_INTERVAL)

        def _emit_lines(self, *, lines: list[str]) -> bool:
            """把每行按 SSE `data:` 帧写出；客户端断开（BrokenPipe）返回 False 让上层收流。"""
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
    """在 host:port 起一个线程化 HTTP server（不阻塞）。端口占用等 OSError → `DaemonError`。"""
    handler = make_handler(board_fn=board_fn)
    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise DaemonError(f"无法在 {host}:{port} 起 desktop daemon（端口占用？）：{exc}") from exc


def run(*, host: str, port: int, board_fn: Callable[[], list[dict]]) -> None:
    """前台常驻：起服务并 `serve_forever`，Ctrl-C 干净收尾。"""
    server = serve(host=host, port=port, board_fn=board_fn)
    bound_port = server.server_address[1]
    print(f"✓ desktop daemon: http://{host}:{bound_port}  (Ctrl-C 停止)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ desktop daemon 已停止", flush=True)
    finally:
        server.shutdown()
        server.server_close()
