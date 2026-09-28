"""Multi-repository process supervision shared by the autonomous Vigil stack."""

from __future__ import annotations

import queue as _queue
import sys
from collections.abc import Callable
from typing import Any

from openagents.utils.agent_config import RepoPlan

_DRAIN_TIMEOUT = 0.2


class _QueueWriter:
    """Line-buffered stderr adapter used by repository worker processes."""

    def __init__(self, *, name: str, log_queue: Any) -> None:
        self._name = name
        self._queue = log_queue
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._queue.put((self._name, line))
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._queue.put((self._name, self._buffer))
            self._buffer = ""


def default_queue() -> Any:
    """Return the real cross-process logging queue."""
    import multiprocessing

    return multiprocessing.Queue()


class Fleet:
    """Spawn one isolated Vigil process per repository and aggregate its logs."""

    def __init__(self, *, spawn: Callable[..., Any], queue_factory: Callable[[], Any]) -> None:
        self._spawn = spawn
        self._queue_factory = queue_factory

    def run(self, *, plans: list[RepoPlan], once: bool) -> None:
        log_queue = self._queue_factory()
        handles = {
            plan.name: self._spawn(plan=plan, log_queue=log_queue, once=once) for plan in plans
        }
        try:
            self._supervise(handles=handles, log_queue=log_queue)
        except KeyboardInterrupt:
            self._emit(message="✓ 多仓库守夜已停止（Ctrl-C）")
            for handle in handles.values():
                handle.terminate()
        finally:
            for handle in handles.values():
                handle.join()

    def _supervise(self, *, handles: dict[str, Any], log_queue: Any) -> None:
        while True:
            try:
                name, line = log_queue.get(timeout=_DRAIN_TIMEOUT)
                self._emit(message=f"[{name}] {line}")
                continue
            except _queue.Empty:
                pass
            if all(not handle.is_alive() for handle in handles.values()):
                self._report_exits(handles=handles)
                return

    def _report_exits(self, *, handles: dict[str, Any]) -> None:
        for name, handle in handles.items():
            code = handle.exitcode
            if code:
                self._emit(message=f"[{name}] ✗ 守夜进程退出（code {code}）")

    def _emit(self, *, message: str) -> None:
        print(message, file=sys.stderr, flush=True)


__all__ = ["Fleet", "_QueueWriter", "default_queue"]
