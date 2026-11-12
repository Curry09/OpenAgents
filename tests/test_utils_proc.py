"""Spec-0065/T2: `openagents/utils/proc.py` contract test - **PID identification drum per thread** + ** process tree SIGKILL**.

The four unchanging forms are all the reasons for the existence of this module and are therefore verified with real things (without a stick):

** When claiming self-reported, linear sub-bunk**: K works and runs ant, A threaded `publish()` can never fall into B ’s barrel
   ”Or else, time will be out of time.” SIGKILL The process of someone else.——It’s the same module that’s going to be eradicated. PID Misconfirmation. The barrel is ’(PID: Popen Snack)’。
** Kills the whole tree**: agent CLI often builds another layer (shell / node wrapper) on its own, killing only the next generation that will survive the direct process.
   So, `subprocess.Popen` (the grandchild process `sleep`) **, `kill_tree`, later asserted that neither father nor grandson was running.
3. **Screen positive **: `kill_tree(handle=…)` and `handle.poll()` non-None  →  process** has been withdrawn and is reap**,
   PID has returned the core, which may have been occupied by others ** No one can kill a process ** (killing an agent that is probably another working party of this process).
4. ** Survivors ’ certificates follow the work process**: `hold_fd` / `inherited_fds` / `release_fds`LLLENDS OF THE PROJECT
   fd (the fd of the flock) is not visible on both lines.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from openagents.utils import proc

# Spec-0065/T2: The limit for genuine process to use for a simple question (secs). SIGKILL is synchronized delivery, reap is a step, just a short window.
# Neither slow nor shiver on the load-high CI.
_DEADLINE = 5.0


# --------------------------------------------------------------------------- #
# Caller: Track / public / untrack
# --------------------------------------------------------------------------- #


def test_track_opens_empty_bucket_for_calling_thread():
    """Spec-0065/T2：`track()` (b) Drums,`untrack()` Take it away. The bucket is... ’(PID: Snack)’ It’s... dict。"""
    proc.track()
    assert proc.untrack(thread_id=threading.get_ident()) == {}


def test_publish_adds_pid_to_calling_thread_bucket():
    """Spec-0065/T2：`publish()` Fall in.**Call Thread**(a) His own bucket;`untrack()` Back ’(PID: Snack)’ And shut the bucket."""
    proc.track()
    proc.publish(pid=4242)
    proc.publish(pid=4243)

    me = threading.get_ident()
    assert proc.untrack(thread_id=me) == {4242: None, 4243: None}  # No one.
    # The drums have been removed: take them again  →  empty barrels (not residues).
    assert proc.untrack(thread_id=me) == {}


def test_publish_records_the_popen_handle_alongside_the_pid():
    """Spec-0065/T2: The handle is the only **-reliable basis for ”this PID or not the process of the year” (PID will be reissued by kernel).

    So `publish(handle=…)` has to put `Popen` in the original barrel for `kill_tree` to verify the body -- lose it, and the time is only left.
    Naked PID can kill, and the most likely victim is another worker of the process, agent (the line is recycled and retraced and run together).
    """
    handle = object()  # Just keep it as it is, not real, Popen.
    proc.track()
    proc.publish(pid=4244, handle=handle)

    bucket = proc.untrack(thread_id=threading.get_ident())
    assert bucket == {4244: handle}
    assert bucket[4244] is handle  # It's the **--the **-word handle, not the copy/substitute.


def test_track_twice_resets_bucket():
    """Spec-0065/T2: Repeat `track()`, or rerun emptied (same thread runs second round agent, cannot carry a round of residual PID)."""
    proc.track()
    proc.publish(pid=111)
    proc.track()
    assert proc.untrack(thread_id=threading.get_ident()) == {}


def test_untrack_unknown_thread_returns_empty_bucket():
    """Spec-0065/T2: The thread id id id id id id id id id id id & & & not KeyError (do as far as you can, never crash the Vigil owner’s loop)."""
    assert proc.untrack(thread_id=-12345) == {}


def test_publish_without_track_is_noop():
    """Spec-0065/T2: The common gh/git subprocess in the producer line also has `publish`, but it does not open a barrel of no-op.

    The contract consists of two parts: (a) no anomaly; (b) no empty barrel - `untrack` remains empty after the event, i.e. the PID** is not ** recognized by anyone.
    """
    me = threading.get_ident()
    proc.untrack(thread_id=me)  # Make sure there's no buckets at the current thread.

    proc.publish(pid=999_001)  # Don't throw it away.

    assert proc.untrack(thread_id=me) == {}


def test_concurrent_threads_do_not_see_each_other_pids():
    """Spec-0065/T2:** The full meaning of this module** - Two threads at the same time publish, each of them, zero.

    Use Barrier to push both sides to the same moment (show, not sequentially) and untrack their own buckets.
    """
    ready = threading.Barrier(2)
    buckets: dict[str, set[int]] = {}

    def worker(*, name: str, pids: set[int]) -> None:
        proc.track()
        ready.wait(timeout=_DEADLINE)  # Open the buckets and join us, publish.
        for pid in pids:
            proc.publish(pid=pid)
            time.sleep(0)  # Get out of the Gil, maximize the interspersion.
        buckets[name] = set(proc.untrack(thread_id=threading.get_ident()))  # Only PID Set

    a_pids = {10, 11, 12}
    b_pids = {20, 21, 22}
    threads = [
        threading.Thread(target=worker, kwargs={"name": "a", "pids": a_pids}),
        threading.Thread(target=worker, kwargs={"name": "b", "pids": b_pids}),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=_DEADLINE)

    assert buckets["a"] == a_pids
    assert buckets["b"] == b_pids
    assert (
        not buckets["a"] & buckets["b"]
    )  # Intersection is empty: no one has received a PID from anyone else.


def test_untrack_from_another_thread_gets_worker_bucket():
    """Spec-0065/T2: The time-out is `thread_id` (the same path when the woker hangs) in ** other ** threads."""
    worker_id: dict[str, int] = {}
    published = threading.Event()
    handle = object()

    def worker() -> None:
        proc.track()
        worker_id["id"] = threading.get_ident()
        proc.publish(pid=777, handle=handle)
        published.set()
        time.sleep(
            0.05
        )  # Simulation "still hanging in agent call" -- buckets removed from the outside line

    t = threading.Thread(target=worker)
    t.start()
    assert published.wait(timeout=_DEADLINE)

    assert proc.untrack(thread_id=worker_id["id"]) == {777: handle}  # PID and handle to timeout
    t.join(timeout=_DEADLINE)


# --------------------------------------------------------------------------- #
# Inheritance fd Registration: hold_fd / inherited_fds / release_fds (survival certificate following the work process)
# --------------------------------------------------------------------------- #


def test_hold_fd_round_trips_per_thread_and_marks_the_fd_inheritable(tmp_path):
    """Spec-0065/T2: `hold_fd` registers fd, which is to be inherited by the sub-procedure, at ** thread**, both are invisible; the fd is treated as inheritability.

    ** Registration itself**: Vigil fd registered here,backend from
    `Popen(pass_fds=proc.inherited_fds())` hands it over to agent subprocess - locked into ”Vigil process** or ** its agent
    One is alive.” If two worker threads see each other’s fd, A’s agent will inherit the B lock: B’s lock is still A’s when it’s finished
    The orphan process holds the B-line and never dies. So **wire segregation** is a hard-line requirement and the main assertion of the example.

    True Jean. fd Through it alive. `exec` Yes. `pass_fds` Self:CPython It’s... `_posixsubprocess` Yes. fork And then,exec Before,
    In the ** sub-process** the `pass_fds` has been removed from each fd of the CLOEXEC (PEP 446 only provides for ”a new fd default non-inheritability”).
    This `os.set_inheritable(fd, True)` process is not a mechanism, it’s just a state-of-the-art **: let this fd inheritable place with us
    The intention is consistent (it does pass on to the child process). It is still asserted that it is a paradoxical state - a fd registered as ”inheritance” and marked as an inheritance.
    And this contradiction is precisely misleading the next person to read the code.
    """
    ready = threading.Barrier(2)
    seen: dict[str, tuple[int, ...]] = {}
    thread_ids: dict[str, int] = {}
    fds: dict[str, int] = {}

    def worker(*, name: str) -> None:
        fd = os.open(str(tmp_path / f"{name}.lock"), os.O_CREAT | os.O_RDWR, 0o644)
        fds[name] = fd
        thread_ids[name] = threading.get_ident()
        proc.hold_fd(fd=fd)
        ready.wait(timeout=_DEADLINE)  # Both sides are registered, read them all.
        seen[name] = proc.inherited_fds()

    threads = [
        threading.Thread(target=worker, kwargs={"name": "a"}),
        threading.Thread(target=worker, kwargs={"name": "b"}),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=_DEADLINE)

    try:
        assert seen["a"] == (fds["a"],)  # I see myself.
        assert seen["b"] == (fds["b"],)
        assert fds["b"] not in seen["a"] and fds["a"] not in seen["b"]  # Zero.
        assert os.get_inheritable(fds["a"]) and os.get_inheritable(fds["b"])

        proc.release_fds(
            thread_id=thread_ids["a"]
        )  # Write-off of work (registration only, no close - ownership is on call)
        assert proc.inherited_fds() == ()  # The main line never registered.
        assert proc._INHERIT.get(thread_ids["a"]) is None
        assert proc._INHERIT.get(thread_ids["b"]) == (
            fds["b"],
        )  # Write off one and don't move the other.
    finally:
        proc.release_fds(thread_id=thread_ids["b"])
        for fd in fds.values():
            os.close(fd)


def test_release_fds_on_an_unknown_thread_is_a_noop():
    """Spec-0065/T2: Unregistered thread id  →  silent no-op (the end path is never allowed to be thrown because it is not registered)."""
    proc.release_fds(thread_id=-12345)
    assert proc.inherited_fds() == ()


# --------------------------------------------------------------------------- #
# child_pids / kill_tree: True Process
# --------------------------------------------------------------------------- #


def _running(*, pid: int) -> bool:
    """Did id ** still run** (Zombie `Z` does not count: it is dead, but not dead). Can’t get  →  is considered dead."""
    out = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    )
    stat = out.stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def _wait_dead(*, pid: int) -> bool:
    """Short window rotation until the pid does not run (SIGKILL delivery is synchronized, reap is walk-in)."""
    end = time.monotonic() + _DEADLINE
    while time.monotonic() < end:
        if not _running(pid=pid):
            return True
        time.sleep(0.05)
    return not _running(pid=pid)


def _spawn_parent_with_grandchild() -> tuple[subprocess.Popen[str], int]:
    """A real two-layer process tree: Child (python)  → Grandchild (sleep 30); returns (child, grandchild_pid)."""
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, sys, time; "
            "g = subprocess.Popen(['sleep', '30']); "
            "print(g.pid, flush=True); "
            "time.sleep(30)",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    grandchild_pid = int(child.stdout.readline().strip())
    return child, grandchild_pid


def test_child_pids_lists_direct_children():
    """Spec-0065/T2: `child_pids()` lists ** The process is direct ** The son process (in which the grandson is not in)."""
    child, grandchild_pid = _spawn_parent_with_grandchild()
    try:
        pids = proc.child_pids()
        assert child.pid in pids
        assert grandchild_pid not in pids  # Grandchild's, pid, is child, not me.
    finally:
        proc.kill_tree(pid=child.pid)
        child.wait(timeout=_DEADLINE)


def test_kill_tree_kills_child_and_grandchild():
    """Spec-0065/T2：`kill_tree` Kill the whole tree.——The only way to kill the direct process is to stay and run. `sleep`(both running source)"""
    child, grandchild_pid = _spawn_parent_with_grandchild()
    try:
        assert _running(pid=grandchild_pid)  # Pre-Supple: The grandson is up.

        proc.kill_tree(pid=child.pid)

        assert child.wait(timeout=_DEADLINE) != 0  # Father was taken by SIGKILL (macOS:-9)
        assert _wait_dead(pid=grandchild_pid), "Grandchild survived kill_tree"
    finally:
        # Bottom: The test aircraft is not left with any residuals, as an example of failure.
        for pid in (grandchild_pid, child.pid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        child.wait(timeout=_DEADLINE)


def test_kill_tree_on_dead_pid_is_noop():
    """Spec-0065/T2: Target exited / PID does not exist  →  quiet no-op (exhaust time should not be thrown because it was ”late to kill”)."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=_DEADLINE)

    proc.kill_tree(pid=dead.pid)  # Reap Home-Friend Process
    proc.kill_tree(pid=2**30)  # No PIDs


def test_kill_tree_kills_nothing_when_the_handle_says_the_process_was_already_reaped(monkeypatch):
    """Spec-0065/T2: `handle.poll()` Non-None  →  Process** has been withdrawn and is reap** its PID has been returned to the core and may have been returned to another person
    Occupancy ** No signal to send**.

    The long-run watch night starts with a few gh/git, the PID turns around is a matter of time; then it’s a matter of time to kill naked PID, and the most likely victim is the other one of the processes**
    The worker’s agent** -- the worker’s half-life was killed, the line was re-leaded, and the double-run that was designed to eradicate. The cost of the leak was much smaller.
    The worst is to get stuck and get fucked by a dog, so the guard must** be ahead of everything.

    Use**True**& The reap Subprocess (in`Popen` + `wait()` → `poll()` Back to exit code)+ Yeah. `os.kill` It’s... spy Validation: once
    `kill` is not allowed to send out.
    """
    signalled: list[int] = []
    monkeypatch.setattr(proc.os, "kill", lambda pid, sig: signalled.append(pid))

    reaped = subprocess.Popen([sys.executable, "-c", "pass"])
    reaped.wait(timeout=_DEADLINE)
    assert reaped.poll() is not None  # Prefix: has quenched and is reap

    proc.kill_tree(pid=reaped.pid, handle=reaped)

    assert signalled == [], (
        "Recap PID may have been reused - kill by PID = kill of innocent people (source of double running)"
    )


def test_kill_tree_closes_captured_group_after_leader_was_reaped():
    """A captured session group remains killable after its leader is already reaped."""
    leader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess; c=subprocess.Popen(['sleep', '30']); print(c.pid, flush=True)",
        ],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert leader.stdout is not None
    child_pid = int(leader.stdout.readline().strip())
    pgid = os.getpgid(leader.pid)
    leader.wait(timeout=_DEADLINE)
    proc.remember_process_group(handle=leader, pgid=pgid)

    sibling = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        assert leader.poll() is not None
        assert _running(pid=child_pid)
        proc.kill_tree(pid=leader.pid, handle=leader)
        assert _wait_dead(pid=child_pid), (
            "captured process group child survived leader-reaped cleanup"
        )
        assert sibling.poll() is None, "cleanup crossed into an unrelated process group"
    finally:
        for pid in (child_pid, sibling.pid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        sibling.wait(timeout=_DEADLINE)


def test_kill_tree_still_kills_a_live_process_when_the_handle_says_it_is_running():
    """Spec-0065/T2: The handler is not allowed to ** over ** tighten — `poll()` is None (process is alive).

    The last one is a counter-example: without it, ”kill_tree directly returns” will pass the last one, and the dead agent will never be killed.
    """
    child, grandchild_pid = _spawn_parent_with_grandchild()
    try:
        assert child.poll() is None  # Prefix: Running (not readap)

        proc.kill_tree(pid=child.pid, handle=child)

        assert child.wait(timeout=_DEADLINE) != 0  # Take it away by SIGKILL
        assert _wait_dead(pid=grandchild_pid), "Grandchild survived kill_tree"
    finally:
        for pid in (grandchild_pid, child.pid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        child.wait(timeout=_DEADLINE)
