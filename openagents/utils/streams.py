# Spec-0073/T1
"""Route live backend output to the stream for the current subject."""

from __future__ import annotations

import collections
import os
import threading

# Per-subject ring buffer's silent determination (e.g., the blast memory for the long-dependant session); can be covered by environment variables.
_DEFAULT_CAPACITY = 2000
_CAPACITY_ENV = "OPENAGENTS_STREAM_CAPACITY"


def _capacity() -> int:
    """ring buffer fixed length: defaults to fall when the environment variable is illegal/missing, never drops."""
    raw = os.environ.get(_CAPACITY_ENV, "").strip()
    if not raw:
        return _DEFAULT_CAPACITY
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_CAPACITY
    return value if value > 0 else _DEFAULT_CAPACITY


class _RingBuffer:
    """A long ring buffer: Add an extra capacity to automatically throw the oldest line; a single `seq` for SSE incremental re-export. Thread is safe."""

    def __init__(self, *, capacity: int) -> None:
        self._lines: collections.deque[tuple[int, str]] = collections.deque(maxlen=capacity)
        self._count = 0
        self._lock = threading.Lock()

    def append(self, *, line: str) -> None:
        with self._lock:
            self._count += 1
            self._lines.append((self._count, line))

    def read_since(self, *, after_seq: int) -> tuple[list[str], int]:
        """returns all rows of seq > after_seq + with the largest seq (no new line returns after_seq as it is)."""
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
    """Ties the `emit` to `subject` for the current thread follow-up and ensures that it is ring buter."""
    _CURRENT.subject = subject
    _buffer_for(subject=subject, create=True)


def unbind() -> None:
    """Untie the object of the current thread; only stdout is played by `emit` thereafter."""
    _CURRENT.subject = None


def current_subject() -> str | None:
    """The current line bound subproject (noone returned without binding)."""
    return getattr(_CURRENT, "subject", None)


def emit(*, line: str) -> None:
    """Prints a line to stdout (business as usual, behaviour unchanged) and adds the ring butffer for the current line-bound object.

    The only way to get a wire is to hit the stdout, not into any buffer.
    """
    print(line, flush=True)
    subject = getattr(_CURRENT, "subject", None)
    if subject is None:
        return
    buf = _buffer_for(subject=subject, create=True)
    if buf is not None:
        buf.append(line=line)


def subjects() -> list[str]:
    """There are currently all sub-subjects ( sorting, stabilizing order) in the ring buffer."""
    with _BUFFERS_LOCK:
        return sorted(_BUFFERS)


def read_since(*, subject: str, after_seq: int) -> tuple[list[str], int] | None:
    """Reads the line of seq > after_seq for a subproject; subproject no buffer returns None.

    SSE frame resends all existing lines with `after_seq=-1`; followed by last max seq increment.
    """
    buf = _buffer_for(subject=subject, create=False)
    if buf is None:
        return None
    return buf.read_since(after_seq=after_seq)


def reset() -> None:
    """Empty all buffer bounds to the current thread (for testing isolation only)."""
    with _BUFFERS_LOCK:
        _BUFFERS.clear()
    _CURRENT.subject = None
