"""Track backend process ownership and terminate the associated process tree.

Backends register their process handles so a timeout can target the correct
invocation. A live child can inherit the claim lock to prevent duplicate work.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from typing import Any

# Spec-0065/T2: Thread ID # Subprocesses (PID  →  Popen handles, handles None). Only track() used
# The thread is only recorded so that the normal gh/git subprocess (from the producer's thread) does not contaminate any agent identification.
_TRACKED: dict[int, dict[int, Any]] = {}
# Spec-0065/T2: Thread ID # This thread is to pass** to fd of the son process to inherit** (for a round-of-life certificate, see hold_fd, used for the Vigil).
_INHERIT: dict[int, tuple[int, ...]] = {}
_TRACK_LOCK = threading.Lock()
_PROCESS_GROUP_ATTR = "_openagents_process_group"


def track() -> None:
    """Start tracking processes created by the current invocation thread."""
    with _TRACK_LOCK:
        _TRACKED[threading.get_ident()] = {}


def publish(*, pid: int, handle: Any = None) -> None:
    """Register a subprocess with the active invocation, if tracked.

    Keep the process handle so timeout cleanup can distinguish the original
    process from a reused PID. Untracked Git and forge calls are ignored.
    """
    with _TRACK_LOCK:
        bucket = _TRACKED.get(threading.get_ident())
        if bucket is not None:
            bucket[pid] = handle


def remember_process_group(*, handle: Any, pgid: int) -> None:
    """Bind a newly-created process handle to its independent process group.

    The group id must be captured immediately after ``Popen`` returns.  Looking it up only
    during timeout cleanup is racy: another thread may reap the leader first while a shell or
    MCP child keeps the group alive.  The handle is the identity anchor; a bare PID/PGID is
    never reconstructed after the leader has been reaped.
    """
    if pgid <= 0:
        return
    try:
        setattr(handle, _PROCESS_GROUP_ATTR, pgid)
    except Exception:
        pass


def process_group(*, handle: Any) -> int | None:
    """Return the process-group id captured for ``handle``, if any."""
    value = getattr(handle, _PROCESS_GROUP_ATTR, None)
    return value if isinstance(value, int) and value > 0 else None


def untrack(*, thread_id: int) -> dict[int, Any]:
    """Remove and return a thread’s tracked process handles."""
    with _TRACK_LOCK:
        return _TRACKED.pop(thread_id, {})


def hold_fd(*, fd: int) -> None:
    """Register a claim descriptor for inheritance by the backend subprocess.

    A surviving backend must keep the flock if its parent dies. Otherwise a
    new worker could reclaim the same subject while the backend is still
    pushing. A leaked descendant can also hold the lock, so the producer
    reports queued rows whose locks remain held. The backend passes the
    descriptor explicitly through Popen.
    """
    os.set_inheritable(fd, True)
    with _TRACK_LOCK:
        current = _INHERIT.get(threading.get_ident(), ())
        _INHERIT[threading.get_ident()] = (*current, fd)


def inherited_fds() -> tuple[int, ...]:
    """The current thread is to pass to the fd (backend from `Popen`); no `pass_fds` has been registered."""
    with _TRACK_LOCK:
        return _INHERIT.get(threading.get_ident(), ())


def release_fds(*, thread_id: int) -> None:
    """(fd) cancels a line registration (work-time adjustments; only registrations,** not** close-fd ownership is on the other side of the caller)."""
    with _TRACK_LOCK:
        _INHERIT.pop(thread_id, None)


def child_pids() -> set[int]:
    """The current **-direct** sub-process PID collection; no empty collection.

    `ps -eo pid=,ppid=` Filtered by `ps -P` (this is BSD/macOS special, GNU coreutils do not have this option,
    Semantics are also different) - A path covers both macOS and Linux.
    """
    return {pid for pid, ppid in _ps_table() if ppid == os.getpid()}


def kill_tree(*, pid: int, handle: Any = None) -> None:
    """SIGKILL A Subprocess** and All its descendants** (killing the offspring before killing themselves).

    And then, ant CLI often builds one more layer of its own, killing only the direct subprocess leaving a whole running tree --
    The ”still running” is the source of double running. Exited / Unauthorised / Unable to get the schedule silently ignored (does its best).

    # Spec-0065/T2: Give `handle` to identify a priori: `poll()` non-None = that process** has been withdrawn and is reap**, its PID**
    # Has returned the core, may have been taken over by another process — and at this point, by PD, killing is killing innocent people (most likely another worker of this process), and it is not the same thing that is happening in the country that is not being done.
    # So the line was recycled and re-dived. This layer of guards was much more important than ”involved”: the worst thing about the leak was the jamming of a door-dog-fucking.
    #
    ** Guards cover root PIDs, not offspring** (in honest accounting): Future generations are not our son processes, we never reap them, `ps` read tables and
    # `os.kill` can be withdrawn and re-enacted by real fathers, PID. The real block is the process group (`setsid`+)
    #`killpg`), which requires a new session from the back-up process - left for follow-up. The current window is millisecond-scale and needs PID to rewind and accept.
    """
    process_group_id = process_group(handle=handle) if handle is not None else None
    if handle is not None and handle.poll() is not None:
        # A reaped leader is normally a hard no-op because its PID may be reused.  If the
        # backend captured the independent process group at launch, it is still safe to close
        # the surviving shell/MCP descendants without consulting the dead PID again.
        if process_group_id is not None:
            _kill_group(pgid=process_group_id)
        return
    for pgid in _descendant_process_groups(pid=pid):
        _kill_group(pgid)
    if process_group_id is not None:
        _kill_group(pgid=process_group_id)
    for child in _descendants(pid=pid):
        _kill_one(pid=child)
    _kill_one(pid=pid)


def _descendant_process_groups(*, pid: int) -> set[int]:
    """Return escaped process groups observed among ``pid``'s descendants."""
    try:
        root_pgid = os.getpgid(pid)
        table = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,pgid="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return set()
    rows: list[tuple[int, int, int]] = []
    for line in table.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            rows.append(tuple(int(part) for part in parts))
    children: dict[int, list[tuple[int, int]]] = {}
    for child, parent, pgid in rows:
        children.setdefault(parent, []).append((child, pgid))
    groups: set[int] = set()
    frontier = [pid]
    seen = {pid}
    while frontier:
        parent = frontier.pop()
        for child, pgid in children.get(parent, ()):
            if child in seen:
                continue
            seen.add(child)
            frontier.append(child)
            if pgid != root_pgid and pgid > 0:
                groups.add(pgid)
    return groups


def _descendants(*, pid: int) -> list[int]:
    """All offspring of the pid (extended the whole subtree from the ppid table, without the pid itself).

    Return order** does not guarantee** bottom up (brothers staggered) - caller `kill_tree` sends SIGKILL, not to be caught, not to clean up at a time,
    The sequence of the killings is not related to the outcome; only one guarantee is here.
    """
    children: dict[int, list[int]] = {}
    for child, parent in _ps_table():
        children.setdefault(parent, []).append(child)
    found: list[int] = []
    frontier = list(children.get(pid, []))
    while frontier:
        current = frontier.pop()
        found.append(current)
        frontier.extend(children.get(current, []))
    found.reverse()
    return found


def _ps_table() -> list[tuple[int, int]]:
    """Full process table `[(pid, ppid), …]`; empty table not available."""
    try:
        table = subprocess.run(
            ["ps", "-eo", "pid=,ppid="], capture_output=True, text=True, check=False
        )
    except OSError:
        return []
    rows: list[tuple[int, int]] = []
    for line in table.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1])))
    return rows


def _kill_one(*, pid: int) -> None:
    """SIGKILL single process (exited/ unauthorized silent ignore)."""
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _kill_group(pgid: int) -> None:
    """SIGKILL one descendant process group (already gone → no-op)."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass
