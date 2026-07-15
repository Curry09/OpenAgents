"""# Spec-0073/T1: agent 输出按 subject 分流（stream tee）。

`vigil --parallel N` 下 K 个 worker 线程并行推进多个 subject，所有 agent 的 stream-json 事件原本都
`print` 到**同一条** stdout，交织成一段无法分辨的文本。本模块提供一个 **thread-local 的 subject 绑定** +
**per-subject 定长 ring buffer**：`backends/claude_code.py` 把 `print(...)` 换成 `emit(line=...)`——既照旧
打 stdout（行为逐字节不变），又把这一行追加进**当前线程绑定的 subject** 的 buffer；`recipes/vigil.py` 的
worker 认领 subject、进 `_reconcile` 前 `bind`，收工/异常时 `unbind`。

**为什么 thread-local 键得住。** 领取时的 `subject UNIQUE`（见 vigil `_worker_loop`）保证一个 worker 线程
同一时刻只处理一个 subject，故「当前线程 → 当前 subject」是一一映射，无需把 subject 参数一路透传穿过
`engine.run_agent`→`backend.run`（那会污染 `AgentBackend` 协议）。未绑定的线程（`oa solve` 单跑等）`emit`
只打 stdout、不进任何 buffer——行为完全不变。

**buffer 是模块级全局（非 thread-local）**：只有「当前线程发往哪个 subject」的**绑定**是 thread-local，
buffer 本身要被 daemon 线程（另一条线程）读走喂 SSE，故按 subject 索引挂在模块级、由锁护着。每行带一个单调
递增 `seq`，让 SSE 能「先补发已有、再增量续推」（`read_since`）。
"""

from __future__ import annotations

import collections
import os
import threading

# per-subject ring buffer 的默认定长（防长会话吃爆内存）；可用环境变量覆盖。
_DEFAULT_CAPACITY = 2000
_CAPACITY_ENV = "OPENAGENTS_STREAM_CAPACITY"


def _capacity() -> int:
    """ring buffer 定长：环境变量非法/缺失时回落默认，永不抛。"""
    raw = os.environ.get(_CAPACITY_ENV, "").strip()
    if not raw:
        return _DEFAULT_CAPACITY
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_CAPACITY
    return value if value > 0 else _DEFAULT_CAPACITY


class _RingBuffer:
    """定长环形缓冲：追加超容量自动丢最旧行；每行配单调 `seq`，供 SSE 增量补发。线程安全。"""

    def __init__(self, *, capacity: int) -> None:
        self._lines: collections.deque[tuple[int, str]] = collections.deque(maxlen=capacity)
        self._count = 0
        self._lock = threading.Lock()

    def append(self, *, line: str) -> None:
        with self._lock:
            self._count += 1
            self._lines.append((self._count, line))

    def read_since(self, *, after_seq: int) -> tuple[list[str], int]:
        """返回 seq > after_seq 的所有行 + 其中最大 seq（无新行则原样返回 after_seq）。"""
        with self._lock:
            fresh = [(seq, line) for seq, line in self._lines if seq > after_seq]
        if not fresh:
            return [], after_seq
        return [line for _, line in fresh], fresh[-1][0]


_BUFFERS: dict[str, _RingBuffer] = {}
_BUFFERS_LOCK = threading.Lock()
_CURRENT = threading.local()


def _buffer_for(*, subject: str, create: bool) -> _RingBuffer | None:
    with _BUFFERS_LOCK:
        buf = _BUFFERS.get(subject)
        if buf is None and create:
            buf = _RingBuffer(capacity=_capacity())
            _BUFFERS[subject] = buf
        return buf


def bind(*, subject: str) -> None:
    """把当前线程后续的 `emit` 绑定到 `subject`，并确保其 ring buffer 存在。"""
    _CURRENT.subject = subject
    _buffer_for(subject=subject, create=True)


def unbind() -> None:
    """解除当前线程的 subject 绑定；此后 `emit` 只打 stdout。"""
    _CURRENT.subject = None


def current_subject() -> str | None:
    """当前线程绑定的 subject（未绑定返回 None）。"""
    return getattr(_CURRENT, "subject", None)


def emit(*, line: str) -> None:
    """打印一行到 stdout（照旧、行为不变），并追加进当前线程绑定 subject 的 ring buffer。

    未绑定线程只打 stdout、不进任何 buffer。
    """
    print(line, flush=True)
    subject = getattr(_CURRENT, "subject", None)
    if subject is None:
        return
    buf = _buffer_for(subject=subject, create=True)
    if buf is not None:
        buf.append(line=line)


def subjects() -> list[str]:
    """当前有 ring buffer 的所有 subject（排序，稳定顺序）。"""
    with _BUFFERS_LOCK:
        return sorted(_BUFFERS)


def read_since(*, subject: str, after_seq: int) -> tuple[list[str], int] | None:
    """读某 subject 的 buffer 中 seq > after_seq 的行；subject 无 buffer 返回 None。

    SSE 首帧用 `after_seq=-1` 补发全部已有行；之后带上次的 max seq 增量续推。
    """
    buf = _buffer_for(subject=subject, create=False)
    if buf is None:
        return None
    return buf.read_since(after_seq=after_seq)


def reset() -> None:
    """清空所有 buffer 与当前线程绑定（仅供测试隔离用）。"""
    with _BUFFERS_LOCK:
        _BUFFERS.clear()
    _CURRENT.subject = None
