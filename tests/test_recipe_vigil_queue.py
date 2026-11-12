"""Spec-0065/T2: ** Queue layer of recipes.vigil + reconcile ** Concluded (accumulation of `test_recipe_vigil.py`).

The sister file is the main cause of the ”Sension Pure Function + Sub-Sec + Flock Sentences”; it is the version that was reinforced by the evaluation.
Each one of them ** is silent only when it’s taken together and bites:**

- ** `_claim_next` head block**: The lock in the first row is held in seconds (submarinate window between the back/recovery and `close(fd)`)
  ** Skip it and watch the next line**, cannot return None -- Return None will be read by the ’line’ to sleep for a second, a line of instant clashes
  Block all** ** worker. The jump line must remain as it is at `queued` (ROLBACK  →  `attempts` is not +1).
- **fd not leak**: `_claim_next` Every path (empty queue / skip/ lead) should be left only ** the one it returns** fd.
  fd = That one. flock Never return to kernel. = The bank will never rule on death. `_claim_next` It’s... `except BaseException`）。
- ** Deleting the locks after closing the work**: The window that turns the other way will get `_reclaim_dead` to grab the lock, sentence ”dead” and hit back queued and run.
- ** `_enqueue` brush priority but not `enqueued_at`**: brushed = long waiting line is always behind (frozen death).
- **worker isolation (`_run_claimed`)**: normal abnormality return and worker line alive; `_ActTimeout` ** Park, never return**
  (Whether the item was pushed by the killed agent could not be proved, re-offending = double running); successful  →  delete line. All three paths must be `close(fd)`.
- **`_run_claimed` , and then the upper limit is short.**：`attempts` There’s only one way to go.——Last round is already in progress. park But... `gh` Throw it. → Lines
  `_reclaim_dead` is recovered. The retrace is ** that park**, not that agent call: `_reconcile` is not allowed to be called at any time.
- ** `_sweep_stalled` (survival certificate leak)**: `hold_fd` will pass fd of the block to agent son process, which will ** continue to pass on to grandsons**;
  A long-lived grandson.MCP server / Backstage. dev server）It’ll hold that lock forever. → The subject It’s... `queued` Okay.**I’ll never get away with it.**，
  The three columns were not seen (recycling only clamed, IN_FLIGHT alerts to claimed_at, QUIEET watchdogs only work with QUIET, but the QUIET dog is only active.
  The verdict is structural: the lock of the queued line** should be free (the only legal holder is the claired liner).
- ** `_reconcile` convulsion**:fp per wheel, but review back and forth between two states ( →  implement push head)
  `fp == last_fp` remembers only the last round, which does not recognize the cycle 2 ring, `_MAX_RECONCILE_ROUNDS` closing park, cannot burn LLM indefinitely.
-** `_proposed_edges` radius**: a bad side freezes only the person concerned, not the whole ready collection; hallucinogenic number** never synthesizes issue #0**
  (Asserts on a non-observed/ non-existent object will be written for a label + comment).
- ** `_reclaim_dead` does not lie**: only ** really ** Quueed’s line.

The real SQLite + true block + true thread (and the assertion that only true can be confirmed) on full tmp_path, but no sleep, no network, no LLM:
& & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & @ @ & & & & & & & & & & & & & & & & & & & @(((((((((((((((((((((((((((((((((((((((((((((((((((((( & & @ & & & & @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ @ file @ file @ @ @ @ file
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import (
    _ACT_FIX_CI,
    _MAX_ATTEMPTS,
    _MAX_RECONCILE_ROUNDS,
    _STALE_LOCK_SECONDS,
    _ActTimeout,
    _claim_next,
    _Clock,
    _connect,
    _cycle_members,
    _drain_queue,
    _enqueue,
    _Facts,
    _fingerprint,
    _init_db,
    _is_claimed,
    _lock_path,
    _mark_done,
    _Observed,
    _park_stalled,
    _proposed_edges,
    _reclaim_dead,
    _reconcile,
    _requeue_or_park,
    _run_claimed,
    _sweep_stalled,
    _try_lock,
    _worker_loop,
)
from openagents.utils import agent_config

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_HEAD = "abc1234def5678901234567890123456789abcde"
_SHA7 = _HEAD[:7]

# Spec-0065/T2: All "waiting for a simultaneous occurrence" is placed in the ceiling of this wall clock - time out or failure (no sleep, no swing, etc.).
_DEADLINE_SECONDS = 5.0
_TICK_SECONDS = 0.005


# --------------------------------------------------------------------------------------------------
# Plugin: acts model / config / library / fd census (fd leak is a first-class assertion of this document).
# --------------------------------------------------------------------------------------------------


def _facts(**overrides) -> _Facts:
    """A ”works ready, only to merge” fact (same as test_recipe_vigil.py) is returned by changing the field as needed."""
    base = _Facts(
        subject="issue:5",
        pr_number=12,
        head_sha=_HEAD,
        merged=False,
        closed=False,
        labels=frozenset({f"review-approved:{_SHA7}"}),
        deps_done=True,
        mergeable_state="clean",
        ci="success",
        e2e_head_sha=_HEAD,
        review_state="APPROVED",
        review_commit_id=_SHA7,
        latest_comment_is_ours=True,
    )
    return replace(base, **overrides)


@pytest.fixture(autouse=True)
def _stub_failure_snapshot(monkeypatch):
    monkeypatch.setattr(vigil_module, "_failure_facts", lambda **kwargs: _facts())


def _config() -> agent_config.AgentConfig:
    return agent_config.AgentConfig(
        version=1,
        agents=agent_config.AgentPolicy(backends={}),
        stages=agent_config.StagePolicy(owners={}),
        release=agent_config.ReleasePolicy(),
        interval=1,
        base="main",
        labels=["openagents"],
        repos=[],
    )


def _db(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    db_path = tmp_path / ".openagents" / "vigil-queue.db"
    _init_db(db_path=db_path)
    return db_path, _connect(db_path=db_path)


def _open_fds() -> set[int]:
    """The current fd collection of this process is open (`F_GETFD` census). This is used to nail ”`_claim_next` only the fd which it returns”.

    Fd, it’s not a little ”resource-bearing thing” here: the fd, with the kernel holding the kernel, thinks the owner is alive forever, givin’ the line**
    I can’t recover it, I can’t ever get back on the team.`INSERT OR IGNORE` Hit it! UNIQUE）⇒ The subject And that’s it.
    """
    live: set[int] = set()
    for fd in range(3, 256):
        try:
            fcntl.fcntl(fd, fcntl.F_GETFD)
        except OSError:
            continue
        live.add(fd)
    return live


def _leaked(*, before: set[int], allowed: set[int]) -> set[int]:
    """Between censuses**,** more fd (releases allowed). The assertion is only in this direction.

    `after == before` (or `after - before == {fd}`, which is a full equation): There’s something else going on in this process.
    (Pytest cache plugin in file writing, previous tested garbage in a key by GC, sqlite Finalizer)
    Turn off ** a separate fd -- the number was recovered from the kernel, `_try_lock` next time open just to reuse it, so...
    New fd is in the column `before`, full-size, on-site red (sun-coloured, full-size red).
    We’re going to testify that there’s no leak** (fd is only a few more cases of disease) so we’re just going to look at `after - before`: Turn off fd from the outside and just make the collection smaller.
    It does not affect this direction; any real leak must have an additional number.
    """
    return _open_fds() - before - allowed


def _await(predicate) -> None:
    """Query to `predicate()` set up; super`_DEADLINE_SECONDS` failed (no fixed sleep  →  fast and non-flaky)."""
    deadline = time.monotonic() + _DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(_TICK_SECONDS)
    raise AssertionError("Waiting for facts to be transmitted over time")


def _count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM work_queue").fetchone()["n"])


def _row(conn: sqlite3.Connection, *, subject: str):
    return conn.execute("SELECT * FROM work_queue WHERE subject=?", (subject,)).fetchone()


# --------------------------------------------------------------------------------------------------
# The competition for `_claim_next`: Lock conflict must ** skip** and not be considered "queuing empty" (team block = all worker sleeping together).
# --------------------------------------------------------------------------------------------------


def test_claim_next_skips_a_flock_held_row_and_takes_the_next(tmp_path):
    """The lock on the head is held by someone else at once. ** Skip it to take the next line.** Never return to None.

    This window is real: `_requeue_or_park`, UPDATE goes back to `queued`, and `close(fd)` -- the line between two steps is this.
    ”queued but the lock is still holding.” If `_claim_next` returns to None, the workingr will read ”queuing empty” and go to sleep.
    `_WORKER_POLL_SECONDS`,** the whole pool woker was blocked from the first line of the team’s submariseconds ** (teamhead blocking).
    """
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW)  # Team Leader (Priority High)
    _enqueue(conn=conn, subject="issue:6", priority=1, now=_NOW)
    held = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert held is not None

    before = _open_fds()
    claimed = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w2", now=_NOW)
    assert claimed is not None, "The first-locked conflict must not be read as ”out of line.”"
    row, fd = claimed
    assert row["subject"] == "issue:6", "We must skip the locked head and lead the next line."

    # Skipped lines left in queued: Skipping ROLBACK, `attempts` that +1 must also roll back together.
    skipped = _row(conn, subject="issue:5")
    assert (skipped["status"], skipped["attempts"], skipped["worker"]) == ("queued", 0, None)
    # Except for the "the one that got it" , there's not many fds: skip the failed lock fds by `_try_lock` itself, without leaking.
    assert _leaked(before=before, allowed={fd}) == set()
    assert fd in _open_fds(), (
        "The fd that you get, it has to be on -- it’s proof of survival in this business."
    )

    os.close(fd)
    os.close(held)
    # The line that was jumped was immediately accessible (the jump was "this round is not going to take it" and not to waste it).
    again = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w3", now=_NOW)
    assert again is not None and again[0]["subject"] == "issue:5"
    os.close(again[1])


def test_claim_next_on_empty_queue_returns_none_without_leaking_fd_or_txn(tmp_path):
    """Noone; no fd, no business (suspension of writing will block producers and other workers)."""
    _, conn = _db(tmp_path)
    before = _open_fds()
    assert _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW) is None
    assert _leaked(before=before, allowed=set()) == set()
    assert conn.in_transaction is False


def test_claim_next_all_rows_locked_returns_none_after_skipping_every_one(tmp_path):
    """All line locks are held and jump back to the net."""
    _, conn = _db(tmp_path)
    held = []
    for subject in ("issue:5", "issue:6"):
        _enqueue(conn=conn, subject=subject, priority=1, now=_NOW)
        lock = _try_lock(path=_lock_path(work_dir=tmp_path, subject=subject))
        assert lock is not None
        held.append(lock)

    before = _open_fds()
    assert _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW) is None
    assert _leaked(before=before, allowed=set()) == set()
    rows = conn.execute("SELECT status, attempts FROM work_queue").fetchall()
    assert [(row["status"], row["attempts"]) for row in rows] == [("queued", 0), ("queued", 0)]
    for lock in held:
        os.close(lock)


def test_concurrent_claimers_never_double_claim_a_subject(tmp_path):
    """The real-line process is contested: K a claimmer and a table is robbed.  →  Every line ** happens to be taken once (`BEGIN IMMEDIATE` sequenced).

    Double running is the only unacceptable failure of Ben spec - it must be proven by the truth and cannot be called twice in sequence.
    """
    db_path, conn = _db(tmp_path)
    subjects = [f"issue:{index}" for index in range(1, 7)]
    for subject in subjects:
        _enqueue(conn=conn, subject=subject, priority=1, now=_NOW)

    start = threading.Barrier(3)
    claimed: list[str] = []
    guard = threading.Lock()

    def _drain(worker_id: str) -> None:
        worker_conn = _connect(db_path=db_path)
        start.wait(timeout=_DEADLINE_SECONDS)
        try:
            while True:
                got = _claim_next(
                    conn=worker_conn, work_dir=tmp_path, worker_id=worker_id, now=_NOW
                )
                if got is None:
                    return
                row, fd = got
                with guard:
                    claimed.append(row["subject"])
                _mark_done(conn=worker_conn, task_id=row["id"], fd=fd)
        finally:
            worker_conn.close()

    threads = [
        threading.Thread(target=_drain, args=(f"w{index}",), name=f"claimer-{index}")
        for index in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=_DEADLINE_SECONDS)
        assert not thread.is_alive()

    assert sorted(claimed) == sorted(subjects), "Each subproject happens to be taken away once."
    assert _count(conn) == 0


# --------------------------------------------------------------------------------------------------
# Completion: Delete the line and release the lock (the sequence is correct — and in turn a double-run window).
# --------------------------------------------------------------------------------------------------


def test_mark_done_deletes_the_row_before_releasing_the_lock(tmp_path, monkeypatch):
    """`close(fd)` that moment, line** must have been out of the table** -- otherwise `_reclaim_dead` would have caught locks, sentenced to death, hit the line back."""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)

    at_close: list[object] = []
    real_close = os.close

    def _spy_close(target_fd):
        at_close.append(_row(conn, subject="issue:5"))
        real_close(target_fd)

    monkeypatch.setattr(vigil_module.os, "close", _spy_close)
    _mark_done(conn=conn, task_id=row["id"], fd=fd)
    monkeypatch.undo()

    assert at_close == [None], (
        "The line must be deleted when unlocking (line deleted, followed by close(fd))"
    )
    assert _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW) is None
    freed = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert freed is not None, "The job must be finished by returning theflock to the kernel."
    os.close(freed)


# --------------------------------------------------------------------------------------------------
# `_enqueue`: Draw priority (the order is not incorrect when received), but `enqueued_at`** (the brush is a hungry death waiting).
# --------------------------------------------------------------------------------------------------


def test_enqueue_refreshes_priority_but_never_resets_enqueued_at(tmp_path):
    """During queue, Solve(1)  →  merge(5): Priority changes, and `enqueued_at` is not moving (it is FFO tie-break)."""
    _, conn = _db(tmp_path)
    assert _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW) is True

    later = _NOW + timedelta(minutes=30)
    assert _enqueue(conn=conn, subject="issue:5", priority=5, now=later) is False
    row = _row(conn, subject="issue:5")
    assert row["priority"] == 5, (
        "Priority changed during queue (or else, in order of weight, obsolete)"
    )
    assert row["enqueued_at"] == _NOW.isoformat(), (
        "Scrap enqueued_at = long waiting line is always behind"
    )
    assert _count(conn) == 1


def test_enqueue_inserts_a_brand_new_subject(tmp_path):
    """New subject  →  Insert and return True (the number of queues for the producer’s tick based on this / decide whether to play `_hang`)."""
    _, conn = _db(tmp_path)
    assert _enqueue(conn=conn, subject="pr:12", priority=6, now=_NOW) is True
    row = _row(conn, subject="pr:12")
    assert (row["status"], row["priority"], row["attempts"]) == ("queued", 6, 0)


def test_enqueue_does_not_touch_a_claimed_row(tmp_path):
    """The line that has been taken is not moving: it’s running, it’s moving in the first place, it’s not making sense. `status` And it’s a direct double-drive."""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)

    assert _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW) is False
    after = _row(conn, subject="issue:5")
    assert (after["status"], after["priority"], after["worker"]) == ("claimed", 1, "w")
    assert _is_claimed(conn=conn, subject="issue:5") is True
    os.close(fd)


# --------------------------------------------------------------------------------------------------
# worker Segregation (`_run_claimed`）: Unusual Back Team / `_ActTimeout` park / Successfully deleted lines——All three paths must be made. close(fd)。
# --------------------------------------------------------------------------------------------------


def _claim_one(tmp_path, conn, *, subject: str):
    _enqueue(conn=conn, subject=subject, priority=1, now=_NOW)
    claimed = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    assert claimed is not None
    return claimed


def _run_it(tmp_path, conn, row, fd) -> None:
    _run_claimed(
        conn=conn,
        row=row,
        fd=fd,
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        agent_id="a",
        now_fn=lambda: _NOW,
    )


def _assert_lock_released(tmp_path, *, subject: str) -> None:
    """The lock of the line must have been returned to the core - the lock is left = the line will never be judged dead (`_reclaim_dead` thinks the holder is still alive)."""
    freed = _try_lock(path=_lock_path(work_dir=tmp_path, subject=subject))
    assert freed is not None, f"{subject}: End of the line must releaseflock"
    os.close(freed)


def test_run_claimed_requeues_the_row_when_the_action_raises(tmp_path, monkeypatch):
    """Normal anomalies (gh shaking / agent crash)** return to the team retry** and will never cross `_run_claimed` (worker thread is the foundation)."""
    _, conn = _db(tmp_path)
    row, fd = _claim_one(tmp_path, conn, subject="issue:5")
    monkeypatch.setattr(
        vigil_module,
        "_reconcile",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("gh, wind.")),
    )
    _run_it(tmp_path, conn, row, fd)  # No, I'm not.

    after = _row(conn, subject="issue:5")
    assert (after["status"], after["attempts"]) == ("queued", 1), (
        "Back in line (attempts already +1)"
    )
    _assert_lock_released(tmp_path, subject="issue:5")


def test_run_claimed_clean_release_on_merge_not_ready(tmp_path, monkeypatch):
    """Spec-0074: CI was still running (`gates.MergeNotReady`)  →  Delete clean-up, attempts, no Park**.

    It’s not like normal anomalies: pending is temporary, not a failure, and a cumulative re-test will be at the CI.
    Burning `_MAX_ATTEMPTS`  →  mis-shipped needs-human. The producer’s next round of heavy sentences is greened after the deletion.
    """
    from openagents.runtime import gates

    _, conn = _db(tmp_path)
    row, fd = _claim_one(tmp_path, conn, subject="issue:5")
    parked: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_reconcile",
        lambda **kwargs: (_ for _ in ()).throw(gates.MergeNotReady("CI pending")),
    )
    monkeypatch.setattr(
        vigil_module, "_fail_automation", lambda **kwargs: parked.append(kwargs["subject"])
    )
    _run_it(tmp_path, conn, row, fd)  # No, I'm not.

    assert _count(conn) == 0, (
        "CI interim pending and never return to team when clean-up is done (otherwise, burn-out re-dealing)"
    )
    assert parked == [], "Sending is not a failure -- no Park"
    _assert_lock_released(tmp_path, subject="issue:5")


def test_run_claimed_requeues_act_timeout_within_bounded_budget(tmp_path, monkeypatch):
    _, conn = _db(tmp_path)
    row, fd = _claim_one(tmp_path, conn, subject="issue:5")
    parked: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_reconcile",
        lambda **kwargs: (_ for _ in ()).throw(_ActTimeout("Over 1800s Not Returned")),
    )
    monkeypatch.setattr(
        vigil_module, "_fail_automation", lambda **kwargs: parked.append(kwargs["subject"])
    )
    _run_it(tmp_path, conn, row, fd)

    assert _count(conn) == 1
    assert _row(conn, subject="issue:5")["status"] == "queued"
    assert parked == []
    _assert_lock_released(tmp_path, subject="issue:5")


def test_act_timeout_below_budget_does_not_write_terminal_projection(tmp_path, monkeypatch):
    _, conn = _db(tmp_path)
    row, fd = _claim_one(tmp_path, conn, subject="issue:5")
    monkeypatch.setattr(
        vigil_module,
        "_reconcile",
        lambda **kwargs: (_ for _ in ()).throw(_ActTimeout("Over 1800s Not Returned")),
    )
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("gh restricted flow")),
    )
    _run_it(tmp_path, conn, row, fd)  # We're not gonna get through this.

    after = _row(conn, subject="issue:5")
    assert after is not None and after["status"] == "queued"
    _assert_lock_released(tmp_path, subject="issue:5")


def test_run_claimed_deletes_the_row_on_success(tmp_path, monkeypatch):
    """Normal close-out line deleted (** is not ** `status='done'`: UNIQUE will lock the subject permanently)+ unlock."""
    _, conn = _db(tmp_path)
    row, fd = _claim_one(tmp_path, conn, subject="issue:5")
    monkeypatch.setattr(vigil_module, "_reconcile", lambda **kwargs: None)
    _run_it(tmp_path, conn, row, fd)

    assert _count(conn) == 0
    _assert_lock_released(tmp_path, subject="issue:5")
    assert (
        _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW) is True
    )  # I can get in the line again.


def test_run_claimed_over_the_cap_parks_without_calling_reconcile_at_all(tmp_path, monkeypatch):
    """# Spec-0065/T2: `attempts` is super-maximum line  →  ** zero agent call**, straight ahead Park (to try again is the park, not the job).

    There’s only one way to go: the last round has already been given ”to the top” but Park’s `gh` dropped it and left the line at `claimed`.
     →  Recycled by `_reclaim_dead` normal and taken away. If it is not stopped at the door, `_reconcile` will** call for a full anggen**:
    A failed `gh` has become an unbounded LLM burn money ring -- the whole point of `_MAX_ATTEMPTS` is not to allow the poison pills to live indefinitely.
    It’s worse on the way over time Park: did the killed agent push something that couldn’t prove, and it was the label that wrote, ”Not automatic.”
    ”The two-runs that you have to avoid are retried.”
    """
    _, conn = _db(tmp_path)
    parked: list[str] = []
    reconciled: list[str] = []
    monkeypatch.setattr(
        vigil_module, "_reconcile", lambda **kwargs: reconciled.append(kwargs["subject"])
    )
    monkeypatch.setattr(
        vigil_module, "_fail_automation", lambda **kwargs: parked.append(kwargs["subject"])
    )
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    # When received `attempts` +1 → In `_run_claimed` It's the time. `_MAX_ATTEMPTS + 1`(Previously sentenced.) park But it landed.
    conn.execute("UPDATE work_queue SET attempts=? WHERE subject='issue:5'", (_MAX_ATTEMPTS,))
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    assert row["attempts"] == _MAX_ATTEMPTS + 1

    _run_it(tmp_path, conn, row, fd)

    assert reconciled == [], "No more agents."
    assert parked == ["issue:5"], "The last set of ”kids” must be retried at this round."
    assert _count(conn) == 0, "Park, land."
    _assert_lock_released(tmp_path, subject="issue:5")


def test_run_claimed_over_the_cap_states_only_what_it_can_prove(tmp_path, monkeypatch):
    """# Spec-0065/T2: The super-park argument is only a statement** of facts that are evidenced ** (taken N, confiscated a job) and cannot be concluded by cause.

    ”The last round of sex-related failure” is not the only way: agent repeatedly crashed and the vigil was shot by a non-related restart (`_reclaim_dead` every time)
    You can hit back on the line, and every time you get `attempts`, and +1), you push a healthy subject that’s never failed. Write a death sentence is a lie.
    The diagnosis leads the handler directly to the wrong direction (to check `gh` restricted flow, while there is no physical presence of 429).
    """
    _, conn = _db(tmp_path)
    bodies: list[str] = []
    monkeypatch.setattr(vigil_module, "_reconcile", lambda **kwargs: None)
    monkeypatch.setattr(
        vigil_module, "_fail_automation", lambda **kwargs: bodies.append(kwargs["reason"])
    )
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    conn.execute("UPDATE work_queue SET attempts=? WHERE subject='issue:5'", (_MAX_ATTEMPTS,))
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)

    _run_it(tmp_path, conn, row, fd)

    assert len(bodies) == 1
    # Read only the "cause" that `_run_claimed` has filled in, and not the body verse from the `_finish` template.
    reason = bodies[0]
    assert str(_MAX_ATTEMPTS + 1) in reason, (
        "Proven fact: Several times the business was taken (a searchable anchor was given)"
    )
    assert "may have crashed" in reason, (
        "The cause is...**Conjecture.**（agent Repeatedly. / The vigil was shot by a non-related reboot. / Previous round park It’s... `gh` I’m not sending it out."
        "= Lead the handler to the wrong direction."
    )


def test_worker_thread_survives_a_poisoned_subject_and_keeps_serving_others(tmp_path, monkeypatch):
    """Poison pills. subject Repeatedly. → worker **The thread is not dead.**: It continues to serve others subject The pills are on their own. `_MAX_ATTEMPTS` Pour park。

    A subproject collapses with a workingr = and a pool of silent water shrinks (the log looks exactly like ”everything is normal”).
    """
    db_path, conn = _db(tmp_path)
    parked: list[str] = []
    healthy = threading.Event()

    def _fake_reconcile(*, backend, state, work_dir, config, subject, agent_id, now_fn, lock_fd):
        if subject == "issue:5":
            raise RuntimeError("Poison pills.")
        healthy.set()

    monkeypatch.setattr(vigil_module, "_reconcile", _fake_reconcile)
    monkeypatch.setattr(
        vigil_module, "_fail_automation", lambda **kwargs: parked.append(kwargs["subject"])
    )
    _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW)  # The poison pills are in line.
    _enqueue(conn=conn, subject="issue:6", priority=1, now=_NOW)

    stop_event = threading.Event()
    worker = threading.Thread(
        target=_worker_loop,
        kwargs={
            "db_path": db_path,
            "backend": None,
            "state": None,
            "work_dir": tmp_path,
            "config": _config(),
            "agent_id": "a",
            "now_fn": lambda: _NOW,
            "stop_event": stop_event,
            "worker_id": "vigil-worker-0",
        },
        name="vigil-worker-0",
        daemon=True,
    )
    worker.start()
    try:
        _await(lambda: _count(conn) == 0)
        assert healthy.is_set(), "The pill must not block the health subproject."
        assert parked == ["issue:5"], f"The poison is here. {_MAX_ATTEMPTS} - No work done."
        assert worker.is_alive(), "The line is closed to the object."
    finally:
        stop_event.set()
        worker.join(timeout=_DEADLINE_SECONDS)
    assert not worker.is_alive()
    _assert_lock_released(tmp_path, subject="issue:5")
    _assert_lock_released(tmp_path, subject="issue:6")


def test_requeue_or_park_releases_the_lock_at_max_attempts(tmp_path, monkeypatch):
    """At the top of the park you must also release the lock: Park is simply ”deption + hit label” and the next line to join the team is never dead if the lock is left in hand."""
    _, conn = _db(tmp_path)
    monkeypatch.setattr(vigil_module, "_fail_automation", lambda **kwargs: None)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    for _ in range(_MAX_ATTEMPTS):
        row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
        _requeue_or_park(conn=conn, task_id=row["id"], subject="issue:5", fd=fd, agent_id="vigil-1")
    assert _count(conn) == 0
    _assert_lock_released(tmp_path, subject="issue:5")


def test_finish_closes_the_fd_exactly_once_when_park_raises(tmp_path, monkeypatch):
    """# Spec-0065/T2: park** Web call ** when thrown**: fd only closes once and that line ** must remain claimed**.

    The two articles are in one place, because they are two sides of the same failure:

    1. **fd Just right. close Once.**( last entrance to double running) To the top. park Delegation `_requeue_or_park`It’s... `finally`
       Already closed once. If `_finish` thinks ”helper’s not closed” at this time, it’s probably not the fd that turned off.
       The fd will be reused by another thread (an additional lock of claires for workker, a sqlite handle), and ** let go of others.
         The workingr who’s still running is sentenced to `_reclaim_dead`, recycled, retraced     Double run.     Lock can block everything,
       The only thing that can stop is ”the locks being set free for me.”
    2. Reporting the failure can fail even after deleting the queue row.
       The line has been deleted, and the next tick producer rediscovers from GitHub, `attempts`, CTIONABLE, re-entering the team.
       ** From 0 **  →  The pills never reach `_MAX_ATTEMPTS`, the white burning model, nobody knows. So this round must ** Nothing has changed:**
       Lines still `claimed`、`attempts` Stop at the limit——The lock was returned to the kernel.`_reclaim_dead` Next round, pick it up and try again. park
       (Quest) The worst part is to go around, but the decision to ”fuck” is not lost.
    """
    _, conn = _db(tmp_path)
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("gh restricted flow")),
    )
    monkeypatch.setattr(
        vigil_module,
        "_reconcile",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("- Yeah, yeah, yeah.")),
    )
    closed: list[int] = []
    real_close = os.close
    monkeypatch.setattr(os, "close", lambda fd: (closed.append(fd), real_close(fd))[1])

    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    for _ in range(_MAX_ATTEMPTS):  # Last round of impact caps, park _park_needs_human throw
        row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
        closed.clear()  # Round by round: It's normal for the cross-wheel fd to be reused with kernel, and it's a bug twice in the round.
        _run_it(tmp_path, conn, row, fd)  # And then you can't go up and finish.
        assert closed == [fd], f"This round closes. {closed}It’s exactly this fd one time."

    after = _row(conn, subject="issue:5")
    assert (after["status"], after["attempts"]) == ("claimed", _MAX_ATTEMPTS), (
        "  This round is not gonna change: stay clameed and retrace, never delete (deleted = quietly re-dispatch, attemmpts zero)"
    )
    _assert_lock_released(
        tmp_path, subject="issue:5"
    )  # The lock must be returned, otherwise _reclaim_dead will not be able to kill and the line will be stuck forever.


# --------------------------------------------------------------------------------------------------
# `_sweep_stalled`:queued lines should have been free - occupied and overage = survival certificates leaked to a grandchild process.
# --------------------------------------------------------------------------------------------------


# This ** tick: The first moment in the memory of the Tick is beyond `_STALE_LOCK_SECONDS`.
_LATER = _NOW + timedelta(seconds=_STALE_LOCK_SECONDS + 60)


def _stale_at(now: datetime) -> datetime:
    """`_STALE_LOCK_SECONDS` before `now` (i.e. `enqueued_at` in this line is very old).

    ** Note that it is no longer a sentence** (see `test_sweep_does_not_park_the_requeue_handoff_window`): `enqueued_at` was returning to the team
    ** Intentionally not to refresh** (to starve), so a healthy life that has been on the team for a long time is born ”old.”
    The “spill” is made in the same line of work, which proves that the former does not imply the latter.
    """
    return now - timedelta(seconds=_STALE_LOCK_SECONDS + 60)


def _sweep(conn, tmp_path, *, seen_locked: dict[str, datetime], now: datetime) -> int:
    return _sweep_stalled(
        conn=conn, work_dir=tmp_path, seen_locked=seen_locked, now=now, agent_id="vigil-1"
    )


def test_sweep_leaves_a_young_row_alone_even_when_its_lock_is_held(tmp_path, monkeypatch):
    """** First time I saw ”queued + lock held” ** and only one, ** no park**: this is the normal interface window
    (`_requeue_or_park` / `_reclaim_dead` is first UPDATE back queued, and `close(fd)`) and is milliseconds are scattered.

    The only reason for the cross-tick memory is not to misjudge this window as a leak -- without it, a normal return would hang on to the subject.
    Need-human. If you see it again, you stay still.
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    seen_locked: dict[str, datetime] = {}
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    held = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert held is not None

    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0
    assert seen_locked == {"issue:5": _NOW}, "First sight only one."
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW + timedelta(seconds=1)) == 0

    assert parked == [], "The lock conflict in the interlocking window is normal, not leak."
    assert _row(conn, subject="issue:5") is not None
    os.close(held)


def test_sweep_does_not_park_the_requeue_handoff_window(tmp_path, monkeypatch):
    """# Spec-0065/T2: queued + locked in the switch window ** Even `enqueued_at` is not leaking.**

    This is the type of `_requeue_or_park` that was wrongly convicted of killing by `enqueued_at`.
    Between `UPDATE … status='queued'` (filed, other connections are immediately visible) and `os.close(fd)`, the line** is**
    ”queued + locks still holding”; and `enqueued_at` returned to the team with no intention of updating** - a 5-minute health operation.
    The team was born ”overage” and was convicted of leaking and on the spot of a need-human+ strike.

    The correct verdict can only be ** across tick**: the window will not live a tick interval and the leak will live forever.
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    _enqueue(
        conn=conn, subject="issue:5", priority=1, now=_stale_at(_NOW)
    )  # Back in line, you don't have to refresh.
    held = _try_lock(
        path=_lock_path(work_dir=tmp_path, subject="issue:5")
    )  # Not yet close that moment
    assert held is not None

    assert _sweep(conn, tmp_path, seen_locked={}, now=_NOW) == 0, (
        "First time I saw it, I thought I’d take every normal return as a leak."
    )
    assert parked == []
    assert _row(conn, subject="issue:5") is not None, (
        "A healthy, re-enacted line, and no one moves a byte."
    )
    os.close(held)


def test_sweep_leaves_an_old_row_alone_when_its_lock_is_free(tmp_path, monkeypatch):
    """** The most important item**: long waiting but locking free and not moving a byte (K. working + long queue = fully normal).

    ”Long queue” ** is not a ** malfunction signal -- K = 1 and the line is designed for an hour in the line of 20 sub-subjects.
    The true verdict is that the lock belongs to the lock**: queued lines should be free (lawful owners only have clameed lines) . If this is changed to press
    A normal backlog is hit in a single line, and it’s a whole lot of needs-human — worse than not to sweep (the fence in turn kills the system).
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    seen_locked: dict[str, datetime] = {}
    _enqueue(
        conn=conn, subject="issue:5", priority=1, now=_stale_at(_NOW)
    )  # It's been a long time, but nobody holds a lock.

    before = _open_fds()
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 0, "Don’t move it either."

    assert parked == [], "= Just waiting for the slot. Everything’s fine."
    assert seen_locked == {}, "Lock free lines to tick memory"
    assert _row(conn, subject="issue:5") is not None, (
        "The line of waiting for the slot must remain in line as it is."
    )
    assert _leaked(before=before, allowed=set()) == set(), (
        "The fd that’s locked must be turned off."
    )


def test_sweep_forgets_a_subject_once_its_lock_comes_free_again(tmp_path, monkeypatch):
    """The lock, the one in the memory of the Tick, must be erased on the spot** -- otherwise the clock will only be in one-way motion, and the clock will be closed.
    The old moment of a normal return is sent to the hand-over in a long time (the next time the switch window hits).
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    seen_locked: dict[str, datetime] = {}
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    held = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert held is not None

    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0
    assert seen_locked == {"issue:5": _NOW}
    os.close(held)  # Switching window closed: Holder returned the lock to kernel
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW + timedelta(seconds=1)) == 0
    assert seen_locked == {}, "Lock your freedom, twirl. Forget it."

    held_again = _try_lock(
        path=_lock_path(work_dir=tmp_path, subject="issue:5")
    )  # Once again, we're back in line.
    assert held_again is not None
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 0, (
        "Time must start at the beginning of this time** and cannot follow the old time left by the last turn-over window"
    )
    assert parked == []
    assert _row(conn, subject="issue:5") is not None
    os.close(held_again)


def test_sweep_parks_and_deletes_an_old_row_whose_lock_is_held_by_a_leak(tmp_path, monkeypatch):
    """** Cross tick has been ** locked ** Survivors’ certificate leak** (Agent’s long-lived grandson process) + deleted.

    Without this gate, this business is a permanent quiet:`_reclaim_dead` Just sweep. `claimed` Can’t see it.IN_FLIGHT - I’m gonna call the cops.
    `claimed_at` can’t see it, QuiET the watchdog only has effect on the QuiET ruling.
    Every round of `_claim_next` skips without a lock, and `_hang` goes ”Front Empty” and a lie goes to the universe.

    Here’s the real**flock (not a peg): leaking grandchildren are locked in the test thread, and the same thing is in the inner nucleus.
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    seen_locked: dict[str, datetime] = {}
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    _enqueue(
        conn=conn, subject="issue:6", priority=1, now=_stale_at(_NOW)
    )  # Neighbor: Lock free, innocent
    leaked = _try_lock(
        path=_lock_path(work_dir=tmp_path, subject="issue:5")
    )  # The leaking grandchild process.

    assert leaked is not None
    assert (
        _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0
    )  # Number one tick: one note only
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 1  # It's still locked.

    assert parked == ["issue:5"], "Only the one that leaked."
    assert _row(conn, subject="issue:5") is None, (
        "Delete it when you have a friend -- otherwise it will continue to take over the pit of UniQUE and never take it away."
    )
    assert _row(conn, subject="issue:6") is not None, (
        "The neighbors’ locks are free. Don’t move a byte."
    )
    os.close(leaked)


def test_sweep_drops_the_row_and_stays_recoverable_when_the_park_label_never_lands(
    tmp_path, monkeypatch
):
    """# Spec-0065/T2: Park’s `gh` dropped (line stolen by BELETE) ** Unusually not to escape `_sweep_stalled`**,
    And this subject must ** still recover**.

    The order here (exclude, then speak) is the opposite of `_requeue_or_park` (slip, delete)** because the label is dropped on both sides**
    The cost is asymmetric: It’s its own. `claimed` Okay. label Will let `attempts` Zero. → The Infinite Re-According,
    LLM; here’s a `queued` line, missing. Label, just ”Low, Label, no fight” -- next tick.
    `_intake` From GitHub We’ll re-invert it. `_STALE_LOCK_SECONDS`
    Repark: A re-test with no-flash, no-LLM**.

    **It’s an anomaly that has to be isolated.**：`_sweep_stalled` Run in `_producer_tick` In the front, throw it. `_intake` And the whole cycle of perception.
    Together, they lifted (the nails on the side of `_producer_tick` see `test_producer_tick_survives_a_park_that_never_lands`).
    """
    _, conn = _db(tmp_path)
    monkeypatch.setattr(
        vigil_module,
        "_fail_automation",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("gh restricted flow")),
    )
    seen_locked: dict[str, datetime] = {}
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    leaked = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert leaked is not None

    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 0, (
        "Park Unlanded Do not count the number of Parks and** won’t throw up in any way."
    )

    assert _row(conn, subject="issue:5") is None, (
        "The line is Delete, the one that took it -- `gh`, and threw it away and never rolled back."
    )
    assert _enqueue(conn=conn, subject="issue:5", priority=1, now=_LATER) is True, (
        "The subject must still be restored: the next tick `_intake` can re-enter the team (UNIQUE’s pit is not occupied dead)"
    )
    os.close(leaked)


def test_park_stalled_reports_zero_parks_when_it_loses_the_row_to_a_worker(tmp_path, monkeypatch):
    """# Spec-0065/T2: The robbery failed (worker first took) `_park_stalled` must return ****, not 1.

    Return value is ”a few people actually delivered this round”, and the `_producer_tick` is all attached to it. Unconditional returns 1 = falsely reported once
    Existing Park: The log says ”off-put” and GitHub does not have a label, and the subject is actually being run by the worker.
    """
    db_path, conn = _db(tmp_path)
    labels = _park_spy(monkeypatch)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(
        conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW
    )  # Go ahead, worker. Take it.
    assert row is not None

    assert (
        _park_stalled(
            conn=_connect(db_path=db_path),
            task_id=int(row["id"]),
            subject="issue:5",
            path=_lock_path(work_dir=tmp_path, subject="issue:5"),
            held=_STALE_LOCK_SECONDS + 60,
            agent_id="vigil-1",
        )
        == 0
    ), "No word, no line, no line."

    assert labels == [], "Don’t talk if you can’t get it."
    after = _row(conn, subject="issue:5")
    assert after is not None and after["status"] == "claimed", (
        "Do not move a byte on the worker line"
    )
    os.close(fd)


def test_sweep_does_not_park_a_row_a_worker_claimed_before_the_reservation(tmp_path, monkeypatch):
    """Spec-0065/T2** The most dangerous one**: SELEECT is a snapshot, Park will send out a few seconds of `gh` -- and it’s possible that the time is time for the worker
    The other line is taken and locked. The lock is ”held” when we look at it.

    * Not in `BEGIN IMMEDIATE`.** First take it off.** (`DELETE … AND status='queued'`, if you can’t get it, you won’t say a word.)
    I’ll put one.**Healthy, being... worker He ran.** subject Hit it. `needs-human` —— And... `needs-human` It’s the final word:
    worker Next round. `_classify` Judgement TERMINAL → Turn around and leave. → `_mark_done` Delete Line → This. issue **I’ll never get laid again.**。
    ** Permanently, exactly the kind of thing that this function is going to eradicate** except this time it was made by hand.

    `_claim_next` (which itself robs theflock)** is driven with certainty**, not sleep: The leaked grandson process is the lock.
    The carving of the freedom lock  →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →
    """
    db_path, conn = _db(tmp_path)
    labels = _park_spy(monkeypatch)  # `_park_needs_human` = really said a word to GitHub
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    leaked = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert leaked is not None
    seen_locked = {
        "issue:5": _NOW
    }  #   The last tick it locked     Ben tick has crossed the threshold, should park

    worker_conn = _connect(db_path=db_path)
    real_try_lock = vigil_module._try_lock
    handed_off: list[int] = []

    def _try_lock_with_a_worker_cutting_in(*, path: Path):
        if not handed_off:  # Only stagger before the lock (re-entry real function in `_claim_next`)
            handed_off.append(leaked)
            os.close(leaked)  # The leak is dead.
            claimed = _claim_next(
                conn=worker_conn, work_dir=tmp_path, worker_id="w", now=_NOW
            )  # Worker takes it normal + get the lock
            assert claimed is not None
            handed_off.append(claimed[1])
        return real_try_lock(path=path)

    monkeypatch.setattr(vigil_module, "_try_lock", _try_lock_with_a_worker_cutting_in)
    try:
        assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 0, (
            "The lock in his hand is meant to be a sacred one."
        )
        assert labels == [], (
            "** No word: `needs-human` falls on the runaway subject = worker next round Terminal turns around and leaves"
        )
        row = _row(conn, subject="issue:5")
        assert row is not None and row["status"] == "claimed", (
            "Never run away from the one who’s running. worker Delete it from the bottom. `_mark_done` Delete 0 Okay. → Quietly running together./  I’ll never stop  "
        )
        worker_fd = handed_off[1]
        assert fcntl.fcntl(worker_fd, fcntl.F_GETFD) >= 0, (
            "The worker’s survival certificate must be intact."
        )
    finally:
        os.close(handed_off[1])
        worker_conn.close()


def test_sweep_never_labels_a_subject_a_worker_could_still_be_handed(tmp_path, monkeypatch):
    """#Spec-0065/T2 ** Second paragraph of the same TOCTOU** (the true bug from the fifth round): Review is only a valid one, it is not a valid one **.

    The old order was, ”Revision is still the same. queued → Twice. `gh`(secs)→ `DELETE … AND status='queued'`」。The process was leaked in those seconds.
    Just as he died. → Lock free. → worker Legal `_claim_next` Take it and run. → DELETE The guards did save him.**Okay.**But that one.
    `needs-human`** has been stated**, falling on a healthy and executed subject: next round of `_classify` sentences
    THRINAL turns around and goes `_mark_done` delete this issue will never be killed again.** Deletes the line and cannot be answered.**

    The correct order is** delete line and make an appointment**: `_claim_next` only admits `queued`, and the line disappears from all the worlds.
    The test’s test is not ”is the line still in place” but ** ”Is it possible that the moment you speak, the worldr will still get it?”** - The answer must be impossible:
    Puts a real `_claim_next` in `_park_needs_human`, which must return **None**.
    """
    db_path, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    leaked = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert leaked is not None
    seen_locked = {"issue:5": _NOW}

    worker_conn = _connect(db_path=db_path)
    handouts: list[object] = []

    def _slow_park(**kwargs) -> None:
        # In the few seconds that `gh` is being sent: leaking process is dead, locking freedom, a worker is coming to take this line right away.
        os.close(leaked)
        handouts.append(_claim_next(conn=worker_conn, work_dir=tmp_path, worker_id="w", now=_NOW))

    monkeypatch.setattr(vigil_module, "_fail_automation", _slow_park)
    try:
        _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER)

        assert handouts == [None], (
            "Before you start, you must have been robbed by Delete, and `_claim_next`, and you can’t send it."
        )
        assert _row(conn, subject="issue:5") is None, (
            "We’re the ones who took the money. He shouldn’t have come back after talking."
        )
    finally:
        for got in handouts:
            if got is not None:
                os.close(got[1])  # Only mutant can get here.
        worker_conn.close()


# --------------------------------------------------------------------------------------------------
# `_reconcile` concussion: fp changes every wheel, but circles between two states -- `fp == last_fp` remembers only the last round, and does not recognize the cycle 2 ring.
# --------------------------------------------------------------------------------------------------


def test_reconcile_parks_on_oscillation_instead_of_looping_forever(tmp_path, monkeypatch):
    """A B-B-B-B-B-B-- and after the claim steps have run out, it’s still a ring and it has to be closed.

    This is the death of the guard I: it’s not possible to identify **: every fp has really changed.
    Final. Without this wheel-to-manufacturer, it’ll be round once. LLM The earth goes down in infinite numbers until two hours later. IN_FLIGHT The police are the ones who do it.
    """
    flip = [_facts(ci="failure"), _facts(ci="failure", head_sha="f" * 40, e2e_head_sha="f" * 40)]
    assert _fingerprint(facts=flip[0]) != _fingerprint(
        facts=flip[1]
    )  # Every fp has really changed.
    box = {"index": 0}
    acted: list[str] = []
    stamps: list[str] = []
    parked: list[str] = []

    def _fake_sense(*, config, subject):
        facts = flip[box["index"] % 2]  # A → B → B → B: Ring of cycle 2
        box["index"] += 1
        return _Observed(facts=facts, clock=_Clock(last_progress_at=_NOW))

    monkeypatch.setattr(vigil_module, "_sense", _fake_sense)
    monkeypatch.setattr(vigil_module, "_capture_label_targets", lambda *, facts: {})
    monkeypatch.setattr(
        vigil_module,
        "_act",
        lambda **kwargs: acted.append(kwargs["verdict"].action) or "Conclusions",
    )
    monkeypatch.setattr(
        vigil_module, "_post_attempt_stamp", lambda **kwargs: stamps.append(kwargs["fp"])
    )
    monkeypatch.setattr(
        vigil_module, "_fail_automation", lambda **kwargs: parked.append(kwargs["subject"])
    )

    _reconcile(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        subject="issue:5",
        agent_id="a",
        now_fn=lambda: _NOW,
        lock_fd=None,  # Spec-0065/T2: `_act` staked, uninhabited subprocess  → lock fd passable
    )

    assert len(acted) == _MAX_RECONCILE_ROUNDS, (
        "The continuous oscillation must stop at the maximum number of wheels."
    )
    assert acted[0] == _ACT_FIX_CI
    assert stamps == [], "Vibration is not ”zero progress” -- fp, it changes every round."
    assert parked == ["issue:5"], "The machine can’t judge the vibrations."


# --------------------------------------------------------------------------------------------------
# `_proposed_edges` / `_cycle_members`: An explosion radius by a hallucination must be constricted to the person concerned and never synthesize #issue #0.
# --------------------------------------------------------------------------------------------------


def _park_spy(monkeypatch) -> list[str]:
    parked: list[str] = []
    monkeypatch.setattr(
        vigil_module, "_fail_automation", lambda **kwargs: parked.append(kwargs["subject"])
    )
    return parked


def test_one_bad_edge_parks_only_its_host_not_the_whole_ready_set(monkeypatch):
    """A bad side (blocker is hallucinating number)  →  whole rejection, but ** only park bad side host** — other ready issue one is not moving.

    Otherwise, a curator’s illusion freezes the whole water line (each body issue hangs on a needs-human, all by himself).
    """
    parked = _park_spy(monkeypatch)
    assert (
        _proposed_edges(
            edges=[{"issue": 6, "blocked_by": [5]}, {"issue": 7, "blocked_by": [999]}],
            known={5, 6, 7},
            existing={5: [], 6: [], 7: []},
            agent_id="vigil-1",
        )
        is None
    ), "Half the wrong graphs are worse than no graphs."
    assert parked == ["issue:7"], (
        "The explosion radius must be constricted to the person concerned (5 / 6 is innocent)"
    )


def test_cycle_parks_exactly_the_nodes_on_the_cycle(monkeypatch):
    """A → B Ring + A non-related C  →  freezes only A and B, C in parallel (the reason for `_cycle_members` returns** member** instead of bool)."""
    parked = _park_spy(monkeypatch)
    assert (
        _proposed_edges(
            edges=[{"issue": 5, "blocked_by": [6]}, {"issue": 6, "blocked_by": [5]}],
            known={5, 6, 7},
            existing={5: [], 6: [], 7: []},
            agent_id="vigil-1",
        )
        is None
    )
    assert parked == ["issue:5", "issue:6"], "Seven, not on the ring. Shouldn’t be frozen."


def test_cycle_members_returns_exactly_the_stuck_nodes():
    """Kahn: The one that can’t be stripped is the ring (and the one that’s stuck in the ring); none of the ones that can be stripped is allowed in the collection. Pure function, no IO."""
    assert _cycle_members(graph={5: {6}, 6: {5}, 7: {8}, 8: set()}) == {5, 6}
    assert _cycle_members(graph={5: {6}, 6: set()}) == set()
    assert _cycle_members(graph={5: {6}, 6: {7}, 7: {5}}) == {
        5,
        6,
        7,
    }  # The three ring is all on the ring.


def test_unparseable_issue_number_never_synthesizes_issue_zero(monkeypatch):
    """The illusion produces a non-integer / non-existent `issue` field  →  whole-of-a-part rejection, but** never park to issue #0**.

    `bad.add(0)` is written in the warehouse** object number 0** with a label + comment - a non-observed object.
    So here’s the side of the github: no one calls at a time.
    """
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: calls.append(("label", number)),
    )
    monkeypatch.setattr(
        vigil_module.github,
        "issue_comment",
        lambda *, number, body: calls.append(("comment", number)),
    )
    monkeypatch.setattr(
        vigil_module.github,
        "add_label",
        lambda *, pr_number, name: calls.append(("label", pr_number)),
    )
    monkeypatch.setattr(
        vigil_module.github,
        "post_comment",
        lambda *, pr_number, body: calls.append(("comment", pr_number)),
    )

    for hallucination in ({"issue": "Six.", "blocked_by": [5]}, {"issue": None, "blocked_by": [5]}):
        assert (
            _proposed_edges(
                edges=[hallucination],
                known={5, 6},
                existing={5: [], 6: []},
                agent_id="vigil-1",
            )
            is None
        ), "No reference to any real issue side of the veto"
    assert calls == [], (
        "No hallucinating numbers can be synthesized into a ”issue #0” (that would disturb a non-existent/involved object)"
    )


def test_proposed_edges_ignores_non_dict_junk_without_parking(monkeypatch):
    """Angent spits non-dict trash entry and skips it: it doesn’t point to any issue, and no one should take a hit on it."""
    parked = _park_spy(monkeypatch)
    fresh = _proposed_edges(
        edges=["Garbage.", None, {"issue": 6, "blocked_by": [5]}],
        known={5, 6},
        existing={5: [], 6: []},
        agent_id="vigil-1",
    )
    assert fresh == [(6, 5)]
    assert parked == []


# --------------------------------------------------------------------------------------------------
# `_reclaim_dead`: Only ** really ** it hit back on the queued (false lies would make the observed amount of "recovered several lines" completely distorted).
# --------------------------------------------------------------------------------------------------


def test_reclaim_counts_only_the_rows_it_actually_reclaimed(tmp_path):
    """Two rows of claimed, one row of holders are still alive (locked to hand), one line of dead persons are recovered only 1 line, only 1 count."""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW)
    _enqueue(conn=conn, subject="issue:6", priority=1, now=_NOW)
    alive_row, alive_fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="alive", now=_NOW)
    dead_row, dead_fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="dead", now=_NOW)
    assert (alive_row["subject"], dead_row["subject"]) == ("issue:5", "issue:6")
    os.close(dead_fd)  #   The holder's Process Dead     The kernel took itsflock away

    before = _open_fds()
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 1, (
        "The line of living possession is not recycled."
    )
    assert _leaked(before=before, allowed=set()) == set(), (
        "The locks that were opened during the recycling process, fd, must be shut down."
    )
    assert _row(conn, subject="issue:5")["status"] == "claimed"  # The living don't move a byte.
    reclaimed = _row(conn, subject="issue:6")
    assert (reclaimed["status"], reclaimed["worker"], reclaimed["claimed_at"]) == (
        "queued",
        None,
        None,
    )
    os.close(alive_fd)


def test_reclaim_does_not_report_a_row_that_the_holder_finished_first(tmp_path):
    """The holder has been officially closed between SELECT and UPDATE** and deleted** `rowcount=0`  →  nothing has been recovered** and no lies are allowed**.

    This window happens every day. The price of false reporting is not crash, it’s the only thing that can be seen in ”recovered N.”
    The signal ”there’s a hordes of dead people” was flooded with noise.
    """
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    os.close(fd)  # Locks are released (possesser dead/ closed) so `_reclaim_dead` can be seized

    class _RacingConn:
        """The moment `_reclaim_dead` gets SELEECT, it’s about `BEGIN IMMEDIATE`, it’s off."""

        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner
            self._fired = False

        def execute(self, sql, params=()):
            if sql.startswith("BEGIN IMMEDIATE") and not self._fired:
                self._fired = True
                self._inner.execute("DELETE FROM work_queue WHERE id=?", (row["id"],))
            return self._inner.execute(sql, params)

    assert _reclaim_dead(conn=_RacingConn(conn), work_dir=tmp_path) == 0, (
        "0 Line modified 0 Line recycled"
    )
    assert _count(conn) == 0


# --------------------------------------------------------------------------------------------------
# `_drain_queue`: Synchronization point for `once=True` - can be abandoned, but** cannot never return** (`oa vigil --once` hanging to the worst end).
# --------------------------------------------------------------------------------------------------


def _drain(tmp_path, db_path, *, seen_locked=None, now=_NOW) -> None:
    _drain_queue(
        db_path=db_path,
        work_dir=tmp_path,
        seen_locked=seen_locked if seen_locked is not None else {},
        now_fn=lambda: now,
        stop_event=threading.Event(),
        agent_id="vigil-1",
    )


def test_drain_returns_immediately_when_the_queue_is_empty(tmp_path):
    db_path, _ = _db(tmp_path)
    started = time.monotonic()
    _drain(tmp_path, db_path)
    assert time.monotonic() - started < _DEADLINE_SECONDS


def test_drain_gives_up_at_the_hard_cap_instead_of_hanging_forever(tmp_path, monkeypatch):
    """The line that’s stuck (worker dying at the end/ agent hanging) goes to `_DRAIN_MAX_SECONDS` and returns and leaves the life on the team next time."""
    db_path, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)  # No one ever consumes it.
    monkeypatch.setattr(vigil_module, "_DRAIN_MAX_SECONDS", 0)
    _drain(tmp_path, db_path)  # Don't hang up.
    assert _count(conn) == 1, (
        "The emptiness is a synchronous point of the best, not the source of the correctness -- the truth in GitHub."
    )


def test_drain_sweeps_a_leaked_lock_row_instead_of_spinning_to_the_hard_cap(tmp_path, monkeypatch):
    """#Spec-0065/T2: The ”survival certificate leak” must also be cleaned during the runoff # #the line ** never ** can’t get away #

    Only once at tick start with `oa vigil --once` will wait in `_drain_queue` for full `_DRAIN_MAX_SECONDS` (1h)
    Return: No `_claim_next` can take it (silently skip without a lock on a round) nor a second tick to sweep it (`--once`)
    Just one. CLI and e2e both go this way -- one hour is the worst end.
    """
    db_path, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    monkeypatch.setattr(vigil_module, "_DRAIN_MAX_SECONDS", 3)  # It didn't get done.
    monkeypatch.setattr(vigil_module, "_WORKER_POLL_SECONDS", 0.01)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    leaked = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert leaked is not None

    started = time.monotonic()
    _drain(
        tmp_path, db_path, seen_locked={"issue:5": _NOW}, now=_LATER
    )  # The last tick saw it locked.
    elapsed = time.monotonic() - started

    assert parked == ["issue:5"], (
        "You have to give them in the air, or nobody in this business can see it."
    )
    assert _count(conn) == 0, "Park, land, line, delete."
    assert elapsed < vigil_module._DRAIN_MAX_SECONDS, "Don’t take it to the hard limit."
    os.close(leaked)


def test_drain_survives_a_sweep_that_blows_up_on_the_lock_file(tmp_path, monkeypatch):
    """# Spec-0065/T2: Emptyed the Qur’an lock (`_try_lock` Throw `OSError`: EMFILE / catalogues dropped by chmod)
    ** Do not escape `_drain_queue`**.

    The main Vigil cycle wraps the entire `_producer_tick` in except, ** the net is not on this road **:
    The anomaly escapes from here and kills `oa vigil --once` (CLI and e2e both). No move, no move, no emptiness -- as usual, just back to point.
    """
    db_path, conn = _db(tmp_path)
    monkeypatch.setattr(vigil_module, "_DRAIN_MAX_SECONDS", 1)
    monkeypatch.setattr(vigil_module, "_WORKER_POLL_SECONDS", 0.01)
    monkeypatch.setattr(
        vigil_module,
        "_try_lock",
        lambda *, path: (_ for _ in ()).throw(OSError(24, "Too many open files")),
    )
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)

    started = time.monotonic()
    _drain(tmp_path, db_path)  # Don't throw it.

    assert time.monotonic() - started < _DEADLINE_SECONDS, (
        "You’ll return to the hard limit. Don’t hang up."
    )
    assert _count(conn) == 1, (
        "If you can’t move, you can’t. Stay in the team. Next time, start and follow."
    )
