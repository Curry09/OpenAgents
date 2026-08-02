"""Spec-0065/T2: recipes.vigil 的**队列层 + reconcile 收口**并发契约（`test_recipe_vigil.py` 的补集）。

姊妹文件钉的是「感知三纯函数 + 分支表 + flock 判死」的主干；这里钉的是那一版并发评审后加固出来的、
每一条都**只在并发下才会咬人、且咬人时静默**的边：

- **`_claim_next` 队头阻塞**：队首行的锁被瞬时持着（回队/回收与 `close(fd)` 之间的亚毫秒窗口）→ 必须
  **跳过它接着看下一行**，不能返回 None——返回 None 会被 worker 读成「队列空了」去睡一秒，一行的瞬时冲突
  就把**所有** worker 挡在门外。且跳过的那一行必须原样留在 `queued`（ROLLBACK ⇒ `attempts` 不被 +1）。
- **fd 不泄漏**：`_claim_next` 每条路径（空队列 / 跳过 / 领到）都只应留下**它返回的那一个** fd。泄漏一个
  fd = 那把 flock 永远不还给内核 = 该行永远判不了死（见 `_claim_next` 的 `except BaseException`）。
- **收工先删行、后释锁**：反过来开的窗口会让 `_reclaim_dead` 抢到锁、判「死了」、把行打回 queued → 双跑。
- **`_enqueue` 刷优先级但不刷 `enqueued_at`**：刷了 = 久候行永远排在后面（饿死）。
- **worker 隔离（`_run_claimed`）**：普通异常 → 回队且 worker 线程活着；`_ActTimeout` → **park，绝不回队**
  （被杀的 agent 是否已推东西无法证明，重发 = 双跑）；成功 → 删行。三条路径都必须 `close(fd)`。
- **`_run_claimed` 的上限短路**：`attempts` 已超顶的行只有一种来路——上一轮已判 park 但 `gh` 抛了 → 行被
  `_reclaim_dead` 正常回收。要重试的是**那次 park**，不是那次 agent 调用：`_reconcile` 一次都不许调。
- **`_sweep_stalled`（存活证明泄漏）**：`hold_fd` 把 flock 的 fd 传给 agent 子进程继承，它会**继续传给孙子**；
  一个泄漏的长命孙子（MCP server / 后台 dev server）会永久持着那把锁 → 该 subject 的 `queued` 行**永远领不走**，
  而三道护栏一个都看不见它（回收只扫 claimed、IN_FLIGHT 告警看 claimed_at、QUIET 看门狗只对 QUIET 生效，
  而它是 ACTIONABLE）。判据是结构性的：queued 行的锁**本就该自由**（合法持有者只有 claimed 行的 worker）。
- **`_reconcile` 振荡**：fp 每轮都变、却在两个状态间来回跳（review 打回 ↔ implement 推新 head）——
  `fp == last_fp` 只记得上一轮，识别不了周期 2 的环 → 靠 `_MAX_RECONCILE_ROUNDS` 收口 park，不能无限烧 LLM。
- **`_proposed_edges` 的爆炸半径**：一条坏边只冻结当事者，不冻结整个 ready 集；幻觉编号**绝不合成 issue #0**
  （会往一个无关/不存在的对象上写 label + 评论）。
- **`_reclaim_dead` 不谎报**：只数**真的**被它打回 queued 的行。

全程 tmp_path 上的真 SQLite + 真 flock + 真线程（并发断言只有真并发才证得了），但无 sleep、无网络、无 LLM：
全靠 event / deadline 同步，整个文件 < 5s。
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

# Spec-0065/T2: 所有「等一个并发事实发生」的等待都收在这个墙钟上限里——超时即失败（不 sleep、不自旋等固定时长）。
_DEADLINE_SECONDS = 5.0
_TICK_SECONDS = 0.005


# --------------------------------------------------------------------------------------------------
# 夹具：facts 造型 / config / 库 / fd 普查（fd 泄漏是本文件的一等断言）。
# --------------------------------------------------------------------------------------------------


def _facts(**overrides) -> _Facts:
    """一个「万事俱备、只欠合并」的 facts（与 test_recipe_vigil.py 同型），按需改单字段往回退。"""
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
    """本进程当前打开的 fd 集合（`F_GETFD` 普查）。用来钉「`_claim_next` 只留下它返回的那一个 fd」。

    fd 泄漏在这里不是「占资源」的小事：泄漏的 fd 持着 flock ⇒ 内核认为持有者永远活着 ⇒ 那一行**永远**
    回收不了、也永远重入不了队（`INSERT OR IGNORE` 撞 UNIQUE）⇒ 该 subject 就此死掉。
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
    """两次普查之间**多出来**的 fd（扣掉允许留下的那些）。断言只看这个方向。

    不能断言 `after == before`（或 `after - before == {fd}` 这种全等式）：本进程里跑着**别的**东西
    （pytest 的 cache 插件在写文件、上一批测试的垃圾在被 GC、sqlite 的 finalizer 在关句柄），任何一个都可能
    在两次普查之间**关掉**一个不相干的 fd —— 那个号随即被内核回收，`_try_lock` 下一次 open 正好复用它，于是
    「新 fd」在 `before` 里赫然在列，全等式当场假红（本仓真发生过：单跑绿、全量红）。
    我们要证的是**没有泄漏**（fd 只多不少才是病），故只看 `after - before`：外部关掉 fd 只会让集合变小，
    不影响这个方向；而任何真的泄漏都必然多出一个号。
    """
    return _open_fds() - before - allowed


def _await(predicate) -> None:
    """轮询到 `predicate()` 成立；超 `_DEADLINE_SECONDS` 即失败（无固定 sleep ⇒ 快且不 flaky）。"""
    deadline = time.monotonic() + _DEADLINE_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(_TICK_SECONDS)
    raise AssertionError("等待并发事实超时")


def _count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM work_queue").fetchone()["n"])


def _row(conn: sqlite3.Connection, *, subject: str):
    return conn.execute("SELECT * FROM work_queue WHERE subject=?", (subject,)).fetchone()


# --------------------------------------------------------------------------------------------------
# `_claim_next` 的争用：锁冲突必须**跳过**、不能当成「队列空了」（队头阻塞 = 所有 worker 一起罚睡）。
# --------------------------------------------------------------------------------------------------


def test_claim_next_skips_a_flock_held_row_and_takes_the_next(tmp_path):
    """队首的锁被别人瞬时持着 → **跳过它领下一行**，绝不返回 None。

    这个窗口是真实存在的：`_requeue_or_park` 先 UPDATE 回 `queued`、再 `close(fd)`——两步之间那一行就是
    「queued 但锁还被持着」。若 `_claim_next` 此时返回 None，worker 会读成「队列空了」而去睡
    `_WORKER_POLL_SECONDS`，**整池 worker 被队首一行的亚毫秒冲突全挡在门外**（队头阻塞）。
    """
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW)  # 队首（优先级高）
    _enqueue(conn=conn, subject="issue:6", priority=1, now=_NOW)
    held = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert held is not None

    before = _open_fds()
    claimed = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w2", now=_NOW)
    assert claimed is not None, "队首锁冲突不得被读成「队列空了」"
    row, fd = claimed
    assert row["subject"] == "issue:6", "必须跳过锁着的队首、领下一行"

    # 被跳过的行原样留在 queued：跳过走的是 ROLLBACK，`attempts` 那一下 +1 也必须一起回滚。
    skipped = _row(conn, subject="issue:5")
    assert (skipped["status"], skipped["attempts"], skipped["worker"]) == ("queued", 0, None)
    # 除了「领到的那一个」，不许多出任何 fd：跳过失败的锁 fd 由 `_try_lock` 自己关掉，不泄漏。
    assert _leaked(before=before, allowed={fd}) == set()
    assert fd in _open_fds(), "领到的 fd 必须还开着——它就是这一行的存活证明"

    os.close(fd)
    os.close(held)
    # 锁一还，被跳过的那行立刻可领（跳过是「这一轮不领它」，不是把它废掉）。
    again = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w3", now=_NOW)
    assert again is not None and again[0]["subject"] == "issue:5"
    os.close(again[1])


def test_claim_next_on_empty_queue_returns_none_without_leaking_fd_or_txn(tmp_path):
    """空队列 → None；不留 fd、不留开着的事务（悬着的写事务会把生产者和其它 worker 全堵死）。"""
    _, conn = _db(tmp_path)
    before = _open_fds()
    assert _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW) is None
    assert _leaked(before=before, allowed=set()) == set()
    assert conn.in_transaction is False


def test_claim_next_all_rows_locked_returns_none_after_skipping_every_one(tmp_path):
    """全部行的锁都被持着 → 跳完所有行才返回 None（"没得领" 与 "队列空" 同一个出口，但不许泄漏 fd）。"""
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
    """真线程争用：K 个 claimer 同抢一张表 → 每行**恰好**被领走一次（`BEGIN IMMEDIATE` 序列化）。

    双跑是本 spec 唯一不可接受的失败——它必须由真并发来证，不能靠顺序调用两次「模拟」。
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

    assert sorted(claimed) == sorted(subjects), "每个 subject 恰好被领走一次（无双跑、无漏领）"
    assert _count(conn) == 0


# --------------------------------------------------------------------------------------------------
# 收工：先删行、后释锁（顺序即正确性——反过来就是一个双跑窗口）。
# --------------------------------------------------------------------------------------------------


def test_mark_done_deletes_the_row_before_releasing_the_lock(tmp_path, monkeypatch):
    """`close(fd)` 那一刻，行**必须已经不在表里**——否则 `_reclaim_dead` 会抢到锁、判死、把行打回 queued。"""
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

    assert at_close == [None], "释锁时行必须已删（先删行、后 close(fd)）"
    assert _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW) is None
    freed = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert freed is not None, "收工必须把 flock 还给内核"
    os.close(freed)


# --------------------------------------------------------------------------------------------------
# `_enqueue`：刷优先级（领取时定序不失真），但**不刷 `enqueued_at`**（刷了就是饿死久候行）。
# --------------------------------------------------------------------------------------------------


def test_enqueue_refreshes_priority_but_never_resets_enqueued_at(tmp_path):
    """排队期间 solve(1) → merge(5)：优先级要跟着变，`enqueued_at` 不能动（它是 FIFO tie-break）。"""
    _, conn = _db(tmp_path)
    assert _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW) is True

    later = _NOW + timedelta(minutes=30)
    assert _enqueue(conn=conn, subject="issue:5", priority=5, now=later) is False
    row = _row(conn, subject="issue:5")
    assert row["priority"] == 5, "排队期间优先级变了要刷（否则按过时的权重排序）"
    assert row["enqueued_at"] == _NOW.isoformat(), "刷 enqueued_at = 久候行永远排在后面（饿死）"
    assert _count(conn) == 1


def test_enqueue_inserts_a_brand_new_subject(tmp_path):
    """新 subject → 插入并返回 True（生产者据此计本 tick 的入队数 / 决定要不要打 `_hang`）。"""
    _, conn = _db(tmp_path)
    assert _enqueue(conn=conn, subject="pr:12", priority=6, now=_NOW) is True
    row = _row(conn, subject="pr:12")
    assert (row["status"], row["priority"], row["attempts"]) == ("queued", 6, 0)


def test_enqueue_does_not_touch_a_claimed_row(tmp_path):
    """已被领走的行不动它：它正在跑，改优先级毫无意义，改 `status` 更是直接制造双跑。"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)

    assert _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW) is False
    after = _row(conn, subject="issue:5")
    assert (after["status"], after["priority"], after["worker"]) == ("claimed", 1, "w")
    assert _is_claimed(conn=conn, subject="issue:5") is True
    os.close(fd)


# --------------------------------------------------------------------------------------------------
# worker 隔离（`_run_claimed`）：异常回队 / `_ActTimeout` park / 成功删行——三条路径都必须 close(fd)。
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
    """行的锁必须已还给内核——留着锁 = 那行永远判不了死（`_reclaim_dead` 认为持有者还活着）。"""
    freed = _try_lock(path=_lock_path(work_dir=tmp_path, subject=subject))
    assert freed is not None, f"{subject}：收尾必须释放 flock"
    os.close(freed)


def test_run_claimed_requeues_the_row_when_the_action_raises(tmp_path, monkeypatch):
    """普通异常（gh 抖动 / agent 崩）→ **回队重试**，且异常绝不越过 `_run_claimed`（worker 线程是地基）。"""
    _, conn = _db(tmp_path)
    row, fd = _claim_one(tmp_path, conn, subject="issue:5")
    monkeypatch.setattr(
        vigil_module,
        "_reconcile",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("gh 抽风")),
    )
    _run_it(tmp_path, conn, row, fd)  # 不上抛

    after = _row(conn, subject="issue:5")
    assert (after["status"], after["attempts"]) == ("queued", 1), "回队重排（attempts 领取时已 +1）"
    _assert_lock_released(tmp_path, subject="issue:5")


def test_run_claimed_clean_release_on_merge_not_ready(tmp_path, monkeypatch):
    """Spec-0074 实证：合并前 CI 仍在跑（`gates.MergeNotReady`）→ **删行干净收工、不烧 attempts、不 park**。

    与普通异常（回队 attempts+1）严格不同：pending 是暂态、不是失败，累计重试会在 CI 的
    pending→success 窗口内烧光 `_MAX_ATTEMPTS` → 误挂 needs-human。删行后生产者下轮 CI 绿了重判即合。
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
        vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: parked.append(subject)
    )
    _run_it(tmp_path, conn, row, fd)  # 不上抛

    assert _count(conn) == 0, (
        "CI 暂态 pending 当干净收工删行，绝不回队累计（否则窗口内烧光重试误交人）"
    )
    assert parked == [], "pending 不是失败——不 park"
    _assert_lock_released(tmp_path, subject="issue:5")


def test_run_claimed_parks_and_never_requeues_on_act_timeout(tmp_path, monkeypatch):
    """`_ActTimeout`（agent 挂死被强杀）→ **删行 + park 交人**，绝不回队。

    被杀的 agent 是否已经改了 / 推了东西无法证明——重发一次正是双跑。这是 `_ActTimeout` 与普通异常处置
    不同的**唯一**理由。
    """
    _, conn = _db(tmp_path)
    row, fd = _claim_one(tmp_path, conn, subject="issue:5")
    parked: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_reconcile",
        lambda **kwargs: (_ for _ in ()).throw(_ActTimeout("超 1800s 未返回")),
    )
    monkeypatch.setattr(
        vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: parked.append(subject)
    )
    _run_it(tmp_path, conn, row, fd)

    assert _count(conn) == 0, "挂死的活直接删行交人，不许回队（回队 = 可能双跑）"
    assert parked == ["issue:5"]
    _assert_lock_released(tmp_path, subject="issue:5")


def test_act_timeout_park_keeps_the_row_when_the_label_never_lands(tmp_path, monkeypatch):
    """# Spec-0065/T2: `_ActTimeout` 的 park 同样**先打 label、再删行**——`gh` 抛了就什么都不许变。

    反过来（先删行、后发 `gh`）时，一次 429 会把「交人」悄悄变成「重新派发」：行没了、label 也没打上，
    下一 tick 生产者从 GitHub 重新感知 → 还是 ACTIONABLE → 重新入队 → 那个**可能还活着**的挂死 agent 的活
    被重发一遍 → 双跑，而这恰恰是 `_ActTimeout` 不回队的**唯一**理由。行留 claimed + 锁已释放 ⇒
    `_reclaim_dead` 下一轮捡回去重试（幂等），「交人」这个决定丢不了。
    """
    _, conn = _db(tmp_path)
    row, fd = _claim_one(tmp_path, conn, subject="issue:5")
    monkeypatch.setattr(
        vigil_module,
        "_reconcile",
        lambda **kwargs: (_ for _ in ()).throw(_ActTimeout("超 1800s 未返回")),
    )
    monkeypatch.setattr(
        vigil_module,
        "_park_needs_human",
        lambda *, subject, body, agent_id: (_ for _ in ()).throw(RuntimeError("gh 限流")),
    )
    _run_it(tmp_path, conn, row, fd)  # 收尾失败不上抛

    after = _row(conn, subject="issue:5")
    assert after is not None and after["status"] == "claimed", (
        "label 没落地 → 行不许删（删=悄悄重新派发）"
    )
    _assert_lock_released(tmp_path, subject="issue:5")


def test_run_claimed_deletes_the_row_on_success(tmp_path, monkeypatch):
    """正常收工 → 行删掉（**不是** `status='done'`：UNIQUE 会把该 subject 永久锁死）+ 释锁。"""
    _, conn = _db(tmp_path)
    row, fd = _claim_one(tmp_path, conn, subject="issue:5")
    monkeypatch.setattr(vigil_module, "_reconcile", lambda **kwargs: None)
    _run_it(tmp_path, conn, row, fd)

    assert _count(conn) == 0
    _assert_lock_released(tmp_path, subject="issue:5")
    assert _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW) is True  # 能再入队


def test_run_claimed_over_the_cap_parks_without_calling_reconcile_at_all(tmp_path, monkeypatch):
    """# Spec-0065/T2: `attempts` 已超顶的行 → **零 agent 调用**，直接 park（要重试的是那次 park，不是那次活）。

    这样的行只有一种来路：上一轮已经判了「到顶交人」，但 park 的 `gh` 抛了（429 / 掉网）→ 行留在 `claimed`
    → 被 `_reclaim_dead` 正常回收 → 又被领走。若不在进门处拦住它，`_reconcile` 会**再叫起一次完整的 agent**：
    一个持续失败的 `gh` 于是变成一个无界的 LLM 烧钱环——`_MAX_ATTEMPTS` 存在的全部意义就是不让毒丸活无限重试。
    在超时 park 那条路上更糟：被强杀的 agent 是否已经推了东西无法证明，重发一次正是 label 里写着「未自动
    重试」要避免的双跑。
    """
    _, conn = _db(tmp_path)
    parked: list[str] = []
    reconciled: list[str] = []
    monkeypatch.setattr(
        vigil_module, "_reconcile", lambda **kwargs: reconciled.append(kwargs["subject"])
    )
    monkeypatch.setattr(
        vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: parked.append(subject)
    )
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    # 领取时 `attempts` +1 → 进 `_run_claimed` 时已是 `_MAX_ATTEMPTS + 1`（上一轮判了 park 但没落地）。
    conn.execute("UPDATE work_queue SET attempts=? WHERE subject='issue:5'", (_MAX_ATTEMPTS,))
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    assert row["attempts"] == _MAX_ATTEMPTS + 1

    _run_it(tmp_path, conn, row, fd)

    assert reconciled == [], "超顶的行绝不许再叫 agent（一次完整的 LLM 调用都不许有）"
    assert parked == ["issue:5"], "上一轮没落地的「交人」必须在这一轮重试"
    assert _count(conn) == 0, "park 落地了 → 行删掉"
    _assert_lock_released(tmp_path, subject="issue:5")


def test_run_claimed_over_the_cap_states_only_what_it_can_prove(tmp_path, monkeypatch):
    """# Spec-0065/T2: 超顶 park 的理由只许陈述**能证的事实**（领了 N 次、一次没收工），不许把成因当结论。

    「上一轮的交人未能落地」并不是唯一来路：agent 反复崩、守夜进程被无关的重启打死（`_reclaim_dead` 每次
    把行打回队、每次领取 `attempts` 又 +1）都会把一个**从没失败过**的健康 subject 推过上限。写死一句会骗人
    的诊断，会把接手的人直接引到错的方向（去查 `gh` 限流，而现场根本没有 429）。
    """
    _, conn = _db(tmp_path)
    bodies: list[str] = []
    monkeypatch.setattr(vigil_module, "_reconcile", lambda **kwargs: None)
    monkeypatch.setattr(
        vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: bodies.append(body)
    )
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    conn.execute("UPDATE work_queue SET attempts=? WHERE subject='issue:5'", (_MAX_ATTEMPTS,))
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)

    _run_it(tmp_path, conn, row, fd)

    assert len(bodies) == 1
    # 只看 `_run_claimed` 填进去的那一段「原因」，不看 `_finish` 的 body 模板里的公共话术。
    reason = bodies[0].split("原因：", 1)[1].split("\n\n", 1)[0]
    assert str(_MAX_ATTEMPTS + 1) in reason, "能证的事实：这一行被领取了几次（给人一个可查的锚点）"
    assert "可能" in reason, (
        "成因只能是**推测**（agent 反复崩 / 守夜被无关的重启打死 / 上一轮 park 的 `gh` 没发出去），"
        "把其中一种写死成断言 = 把接手的人引到错的方向（去查 429，而现场根本没有）"
    )


def test_worker_thread_survives_a_poisoned_subject_and_keeps_serving_others(tmp_path, monkeypatch):
    """毒丸 subject 反复抛 → worker **线程不死**：它继续服务别的 subject，毒丸自己到 `_MAX_ATTEMPTS` 被 park。

    一个 subject 崩掉就少一条 worker 线程 = 并发池静默缩水（日志里跟「一切正常」长得一模一样）。
    """
    db_path, conn = _db(tmp_path)
    parked: list[str] = []
    healthy = threading.Event()

    def _fake_reconcile(*, backend, state, work_dir, config, subject, agent_id, now_fn, lock_fd):
        if subject == "issue:5":
            raise RuntimeError("毒丸")
        healthy.set()

    monkeypatch.setattr(vigil_module, "_reconcile", _fake_reconcile)
    monkeypatch.setattr(
        vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: parked.append(subject)
    )
    _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW)  # 毒丸排队首
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
        assert healthy.is_set(), "毒丸不得挡住健康 subject（worker 线程必须活着继续领）"
        assert parked == ["issue:5"], f"毒丸到 {_MAX_ATTEMPTS} 次未收工 → 交人"
        assert worker.is_alive(), "单 subject 反复崩绝不许杀掉 worker 线程"
    finally:
        stop_event.set()
        worker.join(timeout=_DEADLINE_SECONDS)
    assert not worker.is_alive()
    _assert_lock_released(tmp_path, subject="issue:5")
    _assert_lock_released(tmp_path, subject="issue:6")


def test_requeue_or_park_releases_the_lock_at_max_attempts(tmp_path, monkeypatch):
    """到顶 park 也必须释锁：park 只是「删行 + 打 label」，锁留在手里的话下一次入队的行永远判不了死。"""
    _, conn = _db(tmp_path)
    monkeypatch.setattr(vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: None)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    for _ in range(_MAX_ATTEMPTS):
        row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
        _requeue_or_park(conn=conn, task_id=row["id"], subject="issue:5", fd=fd, agent_id="vigil-1")
    assert _count(conn) == 0
    _assert_lock_released(tmp_path, subject="issue:5")


def test_finish_closes_the_fd_exactly_once_when_park_raises(tmp_path, monkeypatch):
    """# Spec-0065/T2: park 的**网络调用抛出**时：fd 只许 close 一次，且那一行**必须留在 claimed**。

    两条不变式合在一处，因为它们是同一次失败的两面：

    1. **fd 恰好 close 一次**（双跑的最后一个入口）。到顶 park 委托给 `_requeue_or_park`，它的 `finally`
       已经关过一次。若 `_finish` 此时以为「helper 没关成」再兜底关一次，关掉的很可能已经不是这个 fd 号
       了——fd 号会被别的线程复用（另一个 worker 的 claims 锁、一个 sqlite 句柄），于是**放掉别人的
       flock** → 那个还在跑的 worker 被 `_reclaim_dead` 判死、行被回收重领 → 双跑。flock 挡得住一切，
       唯独挡不住「锁被别人替我放了」。
    2. **先打 label、再删行**（park ≠ 悄悄重新派发）。`gh` 抛出（429 / 网络抖动）时 label 根本没落地：若
       此时行已经被删掉，下一 tick 生产者从 GitHub 重新感知 → 还是 ACTIONABLE → 重新入队，且 `attempts`
       **从 0 起算** → 毒丸活永远到不了 `_MAX_ATTEMPTS`，白烧模型、无人知晓。故这一轮必须**什么都没变**：
       行仍是 `claimed`、`attempts` 停在上限——锁已还给内核，`_reclaim_dead` 下一轮把它捡回去重试 park
       （幂等），最坏多绕一圈，但「交人」这个决定丢不了。
    """
    _, conn = _db(tmp_path)
    monkeypatch.setattr(
        vigil_module,
        "_park_needs_human",
        lambda *, subject, body, agent_id: (_ for _ in ()).throw(RuntimeError("gh 限流")),
    )
    monkeypatch.setattr(
        vigil_module,
        "_reconcile",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("agent 崩")),
    )
    closed: list[int] = []
    real_close = os.close
    monkeypatch.setattr(os, "close", lambda fd: (closed.append(fd), real_close(fd))[1])

    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    for _ in range(_MAX_ATTEMPTS):  # 最后一轮撞上限 → park → _park_needs_human 抛
        row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
        closed.clear()  # 逐轮看：跨轮的 fd 号被内核重用是正常的，一轮内关两次才是 bug
        _run_it(tmp_path, conn, row, fd)  # 收尾失败也不上抛（worker 线程是地基）
        assert closed == [fd], f"本轮 close 了 {closed}，应恰好是这一个 fd 一次"

    after = _row(conn, subject="issue:5")
    assert (after["status"], after["attempts"]) == ("claimed", _MAX_ATTEMPTS), (
        "label 没落地 → 这一轮什么都不许变：行留 claimed 等回收重试，绝不能删（删=悄悄重新派发，attempts 归零）"
    )
    _assert_lock_released(
        tmp_path, subject="issue:5"
    )  # 锁必须还，否则 _reclaim_dead 判不了死、行永远卡住


# --------------------------------------------------------------------------------------------------
# `_sweep_stalled`：queued 行的锁本就该是自由的——被占且超龄 = 存活证明泄漏给了一个孙子进程 → 交人。
# --------------------------------------------------------------------------------------------------


# 「上一 tick 就见过它锁着」之后的**这一** tick：跨 tick 记忆里的首见时刻已超 `_STALE_LOCK_SECONDS`。
_LATER = _NOW + timedelta(seconds=_STALE_LOCK_SECONDS + 60)


def _stale_at(now: datetime) -> datetime:
    """把「入队时刻」推到 `now` 之前 `_STALE_LOCK_SECONDS` 以上（即：这行的 `enqueued_at` 已经很老了）。

    **注意它不再是判据**（见 `test_sweep_does_not_park_the_requeue_handoff_window`）：`enqueued_at` 在回队时
    **故意不刷新**（防饿死），故一个跑了很久才回队的健康行天生就是「老」的。留着这个夹具正是为了把「老」和
    「泄漏」造在同一行上，证明前者不蕴含后者。
    """
    return now - timedelta(seconds=_STALE_LOCK_SECONDS + 60)


def _sweep(conn, tmp_path, *, seen_locked: dict[str, datetime], now: datetime) -> int:
    return _sweep_stalled(
        conn=conn, work_dir=tmp_path, seen_locked=seen_locked, now=now, agent_id="vigil-1"
    )


def test_sweep_leaves_a_young_row_alone_even_when_its_lock_is_held(tmp_path, monkeypatch):
    """**首次**看见「queued + 锁被持着」→ 只记一笔、**不许 park**：这正是正常的交接窗口
    （`_requeue_or_park` / `_reclaim_dead` 都是先 UPDATE 回 queued、再 `close(fd)`），亚毫秒即散。

    跨 tick 记忆存在的唯一理由就是不把这个窗口误判成泄漏——没有它，一次正常的回队就会给 subject 挂上
    needs-human。第二次看见时若还没超阈值，同样不许动。
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    seen_locked: dict[str, datetime] = {}
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    held = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert held is not None

    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0
    assert seen_locked == {"issue:5": _NOW}, "首见只记一笔（计时从此刻起算）"
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW + timedelta(seconds=1)) == 0

    assert parked == [], "交接窗口内的锁冲突是常态，不是泄漏"
    assert _row(conn, subject="issue:5") is not None
    os.close(held)


def test_sweep_does_not_park_the_requeue_handoff_window(tmp_path, monkeypatch):
    """# Spec-0065/T2: 交接窗口里的行（queued + 锁持着）**哪怕 `enqueued_at` 老掉牙**也不是泄漏。

    这正是旧的「按 `enqueued_at` 判龄」判据错杀的那一类：`_requeue_or_park` 的
    `UPDATE … status='queued'`（已提交、别的连接立刻看得见）与 `os.close(fd)` 之间，这一行**就是**
    「queued + 锁还持着」；而 `enqueued_at` 在回队时**故意不刷新**（防饿死）——于是一个跑了 5 分钟的健康活
    一回队就天生「超龄」，一眼被判成泄漏、当场挨 needs-human + 删行。

    正确的判据只能是**跨 tick**：那个窗口活不过一次 tick 间隔，泄漏则永远活着。
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_stale_at(_NOW))  # 回队时不刷新 → 天生老
    held = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))  # 尚未 close 的那一瞬
    assert held is not None

    assert _sweep(conn, tmp_path, seen_locked={}, now=_NOW) == 0, (
        "首次看见即 park = 把每一次正常回队都当成泄漏"
    )
    assert parked == []
    assert _row(conn, subject="issue:5") is not None, "健康的、正要被重领的行，一个字节都不许动"
    os.close(held)


def test_sweep_leaves_an_old_row_alone_when_its_lock_is_free(tmp_path, monkeypatch):
    """**最要紧的一条**：久候但锁自由 → 一个字节都不许动（K 个 worker 全忙 + 长队列 = 完全正常）。

    「排了很久」本身**不是**故障信号——K=1 而队里排着 20 个 subject 时，队尾那行等上一小时是设计如此。
    真正的判据是**锁的归属**：queued 行的锁本该自由（合法持有者只有 claimed 行的 worker）。若这里改成按
    age 一刀切，一个正常的积压就会被整批打上 needs-human——比不扫更糟（护栏反过来杀掉了系统）。
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    seen_locked: dict[str, datetime] = {}
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_stale_at(_NOW))  # 排了很久，但没人持锁

    before = _open_fds()
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 0, "两轮都不许动它"

    assert parked == [], "锁自由 = 只是在等槽位，一切正常"
    assert seen_locked == {}, "锁自由的行不进跨 tick 记忆"
    assert _row(conn, subject="issue:5") is not None, "等槽位的行必须原样留在队里"
    assert _leaked(before=before, allowed=set()) == set(), (
        "试锁开的 fd 必须关掉（泄漏它 = 亲手制造下一轮的假泄漏）"
    )


def test_sweep_forgets_a_subject_once_its_lock_comes_free_again(tmp_path, monkeypatch):
    """锁一放，跨 tick 记忆里的那一笔必须**当场抹掉**（计时归零）——否则时钟只会单调向前，
    一次正常回队留下的旧时刻会在很久以后（下一次交接窗口撞上时）把一个健康的行送去交人。
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    seen_locked: dict[str, datetime] = {}
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    held = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert held is not None

    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0
    assert seen_locked == {"issue:5": _NOW}
    os.close(held)  # 交接窗口关闭：持有者把锁还给了内核
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW + timedelta(seconds=1)) == 0
    assert seen_locked == {}, "锁自由 → 忘掉它（下次再被锁住时重新计时）"

    held_again = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))  # 又一次正常回队
    assert held_again is not None
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 0, (
        "计时必须从**这一次**首见起算，不能沿用上一次交接窗口留下的旧时刻"
    )
    assert parked == []
    assert _row(conn, subject="issue:5") is not None
    os.close(held_again)


def test_sweep_parks_and_deletes_an_old_row_whose_lock_is_held_by_a_leak(tmp_path, monkeypatch):
    """**跨 tick 一直**锁着 → 判**存活证明泄漏**（agent 留下的长命孙子进程）→ park 交人 + 删行。

    没有这道闸，这一行就是永久静默停摆：`_reclaim_dead` 只扫 `claimed` 看不见它、IN_FLIGHT 告警读
    `claimed_at` 看不见它、QUIET 看门狗只对 QUIET 裁决生效（而它是 ACTIONABLE，正因如此才入的队）——
    每轮 `_claim_next` 抢不到锁就静默跳过，`_hang` 于是报「前沿空」，一句谎话报到宇宙热寂。

    这里持的是**真** flock（不是打桩）：泄漏的孙子进程持锁与测试线程持锁，在内核眼里是同一件事。
    """
    _, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    seen_locked: dict[str, datetime] = {}
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    _enqueue(conn=conn, subject="issue:6", priority=1, now=_stale_at(_NOW))  # 邻居：锁自由，无辜
    leaked = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))  # 泄漏的孙子进程

    assert leaked is not None
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0  # 第一 tick：只记一笔
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 1  # 还锁着 ⇒ 泄漏

    assert parked == ["issue:5"], "只交泄漏的那一个（爆炸半径收敛到当事者）"
    assert _row(conn, subject="issue:5") is None, (
        "交人了就删行——否则它继续占着 UNIQUE 的坑，永远领不走"
    )
    assert _row(conn, subject="issue:6") is not None, "邻居的锁是自由的，一个字节都不许动"
    os.close(leaked)


def test_sweep_drops_the_row_and_stays_recoverable_when_the_park_label_never_lands(
    tmp_path, monkeypatch
):
    """# Spec-0065/T2: park 的 `gh` 抛了（行已被 DELETE 抢下）→ **异常不许逃出 `_sweep_stalled`**，
    且这个 subject 必须**仍然可恢复**。

    这里的顺序（先删行、再说话）与 `_requeue_or_park`（先落 label、再删行）**故意相反**，因为两边丢 label
    的代价不对称：那边删的是自己的 `claimed` 行（没人抢得走），丢了 label 会让 `attempts` 归零 → 无限重派、
    白烧 LLM；这边删的是一个**谁都能领**的 `queued` 行，丢了 label 只是「行没了、label 没打」——下一 tick
    `_intake` 从 GitHub 现态把它重新推导出来（锁还被占着，照样领不走），再等一个 `_STALE_LOCK_SECONDS`
    重新 park：一次**有节流、零 LLM** 的重试而已。

    **异常必须就地隔离**：`_sweep_stalled` 跑在 `_producer_tick` 的最前面，抛出去就把 `_intake` 和整轮感知
    一起掀了（`_producer_tick` 侧的钉子见 `test_producer_tick_survives_a_park_that_never_lands`）。
    """
    _, conn = _db(tmp_path)
    monkeypatch.setattr(
        vigil_module,
        "_park_needs_human",
        lambda *, subject, body, agent_id: (_ for _ in ()).throw(RuntimeError("gh 限流")),
    )
    seen_locked: dict[str, datetime] = {}
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    leaked = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert leaked is not None

    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_NOW) == 0
    assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 0, (
        "park 没落地 → 不许计入 park 数，且**异常绝不上抛**（它会掀掉整个生产 tick）"
    )

    assert _row(conn, subject="issue:5") is None, "行是 DELETE 抢下来的——`gh` 抛了也不回滚它"
    assert _enqueue(conn=conn, subject="issue:5", priority=1, now=_LATER) is True, (
        "subject 必须仍可恢复：下一 tick 的 `_intake` 能重新入队（UNIQUE 的坑没被占死）"
    )
    os.close(leaked)


def test_park_stalled_reports_zero_parks_when_it_loses_the_row_to_a_worker(tmp_path, monkeypatch):
    """# Spec-0065/T2: 抢行失败（worker 先领走了）→ `_park_stalled` 必须返回 **0**，不是 1。

    返回值是「本轮真的交了几个人」，`_producer_tick` 的可观测性全挂在它上面。无条件返回 1 = 谎报一次并不
    存在的 park：日志里说「已交人」，GitHub 上没有 label，而那个 subject 其实好端端地正在被 worker 跑。
    """
    db_path, conn = _db(tmp_path)
    labels = _park_spy(monkeypatch)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)  # worker 抢先领走
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
    ), "一个字都没说、一行都没删 ⇒ 本轮 park 数是 0"

    assert labels == [], "抢不到行就不许开口（那把锁是 worker 的，天经地义）"
    after = _row(conn, subject="issue:5")
    assert after is not None and after["status"] == "claimed", "worker 的行一个字节都不许动"
    os.close(fd)


def test_sweep_does_not_park_a_row_a_worker_claimed_before_the_reservation(tmp_path, monkeypatch):
    """# Spec-0065/T2 **最险的一条**：SELECT 的是快照，park 要发好几秒的 `gh`——这期间 worker 完全可能
    正常领走**另一行**并锁上它。轮到我们探那一行时，锁当然是「被持着」的。

    不在 `BEGIN IMMEDIATE` 里**先把行抢下来**（`DELETE … AND status='queued'`，抢不到就一个字都不说），
    就会把一个**健康的、正被 worker 跑着的** subject 打上 `needs-human` —— 而 `needs-human` 是终态谓词：
    worker 下一圈 `_classify` 判 TERMINAL → 掉头就走 → `_mark_done` 删行 → 这个 issue **再也不会被动手**。
    **永久停摆，正是本函数要根除的那种东西**，只不过这次是护栏亲手造的。

    交错点用真 `_claim_next`（它自己去抢 flock）**确定性地**驱动，不靠 sleep：泄漏的孙子进程恰在探锁的那一
    刻死掉 → 锁自由 → worker 立刻领走这一行 → 我们探到的那把锁其实是 **worker 的**。
    """
    db_path, conn = _db(tmp_path)
    labels = _park_spy(monkeypatch)  # `_park_needs_human` 的调用 = 真的往 GitHub 上说了一句话
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    leaked = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert leaked is not None
    seen_locked = {"issue:5": _NOW}  # 上一 tick 就见它锁着 → 本 tick 已过阈值，本该 park

    worker_conn = _connect(db_path=db_path)
    real_try_lock = vigil_module._try_lock
    handed_off: list[int] = []

    def _try_lock_with_a_worker_cutting_in(*, path: Path):
        if not handed_off:  # 只在 sweep 的那一次探锁前交错（`_claim_next` 内的重入走真函数）
            handed_off.append(leaked)
            os.close(leaked)  # 泄漏进程死了 → 锁自由
            claimed = _claim_next(
                conn=worker_conn, work_dir=tmp_path, worker_id="w", now=_NOW
            )  # worker 正常领走它 + 拿到 flock
            assert claimed is not None
            handed_off.append(claimed[1])
        return real_try_lock(path=path)

    monkeypatch.setattr(vigil_module, "_try_lock", _try_lock_with_a_worker_cutting_in)
    try:
        assert _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER) == 0, (
            "worker 手里那把锁是天经地义的——不许把它读成泄漏"
        )
        assert labels == [], (
            "**一个字都不许说**：`needs-human` 落在正在被跑的 subject 上 = worker 下一圈判 TERMINAL 掉头就走"
        )
        row = _row(conn, subject="issue:5")
        assert row is not None and row["status"] == "claimed", (
            "绝不许把行从正在跑的 worker 底下删掉（它随后 `_mark_done` 删 0 行 → 静默双跑/永久停摆）"
        )
        worker_fd = handed_off[1]
        assert fcntl.fcntl(worker_fd, fcntl.F_GETFD) >= 0, "worker 的存活证明必须完好无损"
    finally:
        os.close(handed_off[1])
        worker_conn.close()


def test_sweep_never_labels_a_subject_a_worker_could_still_be_handed(tmp_path, monkeypatch):
    """# Spec-0065/T2 同一个 TOCTOU 的**第二段**（第五轮评审揪出的真 bug）：复核只保得住行，保不住**话**。

    旧顺序是「复核仍是 queued → 发两次 `gh`（数秒）→ `DELETE … AND status='queued'`」。那几秒里泄漏进程
    恰好死掉 → 锁自由 → worker 合法 `_claim_next` 领走并开跑 → DELETE 的守卫确实救下了**行**，但那条
    `needs-human` **已经说出去了**，落在一个健康且正在被执行的 subject 上：worker 下一圈 `_classify` 判
    TERMINAL → 掉头就走 → `_mark_done` 删行 → 这个 issue 再也不会被动手。**行删得掉、话收不回。**

    正确的顺序是**删行即预约**：`_claim_next` 只认 `queued`，行一被 DELETE 就从所有 worker 的视野里消失。
    故本测试的判据不是「行还在不在」，而是**「说话的那一刻，worker 还可能领到它吗」** —— 答案必须是不可能：
    在 `_park_needs_human` 里放一个真 `_claim_next`，它必须返回 **None**。
    """
    db_path, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    leaked = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert leaked is not None
    seen_locked = {"issue:5": _NOW}

    worker_conn = _connect(db_path=db_path)
    handouts: list[object] = []

    def _slow_park(*, subject: str, body: str, agent_id: str) -> None:
        # 正在发 `gh` 的这几秒里：泄漏进程死了 → 锁自由 → 一个 worker 立刻来领这一行。
        os.close(leaked)
        handouts.append(_claim_next(conn=worker_conn, work_dir=tmp_path, worker_id="w", now=_NOW))

    monkeypatch.setattr(vigil_module, "_park_needs_human", _slow_park)
    try:
        _sweep(conn, tmp_path, seen_locked=seen_locked, now=_LATER)

        assert handouts == [None], (
            "开口之前行必须已经被 DELETE 抢下 ⇒ `_claim_next` 根本发不出它 ⇒ 不可能有 worker 在跑它"
        )
        assert _row(conn, subject="issue:5") is None, "抢下的行就是我们的，说完话它也不该回来"
    finally:
        for got in handouts:
            if got is not None:
                os.close(got[1])  # 只有 mutant 才走得到这里（说话时行还发得出去）
        worker_conn.close()


# --------------------------------------------------------------------------------------------------
# `_reconcile` 振荡：fp 每轮都变、却在两个状态间兜圈子 —— `fp == last_fp` 只记得上一轮，识别不了周期 2 的环。
# --------------------------------------------------------------------------------------------------


def test_reconcile_parks_on_oscillation_instead_of_looping_forever(tmp_path, monkeypatch):
    """A→B→A→B… 的振荡（review 打回 ↔ implement 推新 head）→ 到 `_MAX_RECONCILE_ROUNDS` 收口 park。

    这是护栏一（attempt 戳）**识别不了**的死法：每一轮 fp 都真的变了（agent 真改了 GitHub），只是没走向
    终态。没有这道轮数闸，它会一轮一次 LLM 地无限转下去，直到两小时后 IN_FLIGHT 告警才有人管。
    """
    flip = [_facts(ci="failure"), _facts(ci="failure", head_sha="f" * 40, e2e_head_sha="f" * 40)]
    assert _fingerprint(facts=flip[0]) != _fingerprint(facts=flip[1])  # 每轮 fp 都真的变了
    box = {"index": 0}
    acted: list[str] = []
    stamps: list[str] = []
    parked: list[str] = []

    def _fake_sense(*, config, subject):
        facts = flip[box["index"] % 2]  # A→B→A→B…：周期 2 的环
        box["index"] += 1
        return _Observed(facts=facts, clock=_Clock(last_progress_at=_NOW))

    monkeypatch.setattr(vigil_module, "_sense", _fake_sense)
    monkeypatch.setattr(
        vigil_module,
        "_act",
        lambda **kwargs: acted.append(kwargs["verdict"].action) or "结论",
    )
    monkeypatch.setattr(
        vigil_module, "_post_attempt_stamp", lambda **kwargs: stamps.append(kwargs["fp"])
    )
    monkeypatch.setattr(
        vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: parked.append(subject)
    )

    _reconcile(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        subject="issue:5",
        agent_id="a",
        now_fn=lambda: _NOW,
        lock_fd=None,  # Spec-0065/T2: `_act` 已打桩，不起子进程 → 无 flock fd 可传
    )

    assert len(acted) == _MAX_RECONCILE_ROUNDS, "振荡必须在轮数上限处停下（不许无限烧 LLM）"
    assert acted[0] == _ACT_FIX_CI
    assert stamps == [], "振荡不是「零进展」——fp 每轮都变，护栏一（attempt 戳）根本认不出它"
    assert parked == ["issue:5"], "机器判不了的振荡 → 交人"


# --------------------------------------------------------------------------------------------------
# `_proposed_edges` / `_cycle_members`：一条幻觉边的爆炸半径必须收敛到当事者，且绝不合成 issue #0。
# --------------------------------------------------------------------------------------------------


def _park_spy(monkeypatch) -> list[str]:
    parked: list[str] = []
    monkeypatch.setattr(
        vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: parked.append(subject)
    )
    return parked


def test_one_bad_edge_parks_only_its_host_not_the_whole_ready_set(monkeypatch):
    """一条坏边（blocker 是幻觉编号）→ 整批否决，但**只 park 坏边的宿主**——别的 ready issue 一个不许动。

    否则 curator 的一次幻觉就冻结整条流水线（每个 ready issue 都挂上 needs-human，全靠人一个个摘）。
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
    ), "半张错图比没有图更糟 → 本轮不落任何边"
    assert parked == ["issue:7"], "爆炸半径必须收敛到当事者（5 / 6 是无辜的）"


def test_cycle_parks_exactly_the_nodes_on_the_cycle(monkeypatch):
    """A↔B 成环 + 一个无关的 C → 只冻结 A 和 B，C 照常并行（`_cycle_members` 返回**成员**而非 bool 的理由）。"""
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
    assert parked == ["issue:5", "issue:6"], "7 不在环上，不该被冻"


def test_cycle_members_returns_exactly_the_stuck_nodes():
    """Kahn：剥不掉的就是环（及被环卡住的）；剥得掉的一个都不许进集合。纯函数，无 IO。"""
    assert _cycle_members(graph={5: {6}, 6: {5}, 7: {8}, 8: set()}) == {5, 6}
    assert _cycle_members(graph={5: {6}, 6: set()}) == set()
    assert _cycle_members(graph={5: {6}, 6: {7}, 7: {5}}) == {5, 6, 7}  # 三元环全员在环上


def test_unparseable_issue_number_never_synthesizes_issue_zero(monkeypatch):
    """幻觉出一个非整数 / 不存在的 `issue` 字段 → 整批否决，但**绝不 park 到 issue #0 头上**。

    `bad.add(0)` 那种写法会往仓库里**编号 0** 的对象上写 label + 评论——一个无关的、甚至不存在的对象。
    故这里直接盯 github 的写侧：一次调用都不许有。
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

    for hallucination in ({"issue": "六", "blocked_by": [5]}, {"issue": None, "blocked_by": [5]}):
        assert (
            _proposed_edges(
                edges=[hallucination],
                known={5, 6},
                existing={5: [], 6: []},
                agent_id="vigil-1",
            )
            is None
        ), "引用不到任何真实 issue 的边 → 整批否决"
    assert calls == [], "幻觉编号不许被合成成 issue #0（那会打扰一个无关/不存在的对象）"


def test_proposed_edges_ignores_non_dict_junk_without_parking(monkeypatch):
    """agent 吐出的非 dict 垃圾条目直接跳过：它没指向任何 issue，谁都不该为它挨一发 needs-human。"""
    parked = _park_spy(monkeypatch)
    fresh = _proposed_edges(
        edges=["垃圾", None, {"issue": 6, "blocked_by": [5]}],
        known={5, 6},
        existing={5: [], 6: []},
        agent_id="vigil-1",
    )
    assert fresh == [(6, 5)]
    assert parked == []


# --------------------------------------------------------------------------------------------------
# `_reclaim_dead`：只数**真的**被它打回 queued 的行（谎报会让「回收了几行」这个可观测量彻底失真）。
# --------------------------------------------------------------------------------------------------


def test_reclaim_counts_only_the_rows_it_actually_reclaimed(tmp_path):
    """两行 claimed，一行的持有者还活着（锁在手）、一行的已死 → 只回收 1 行，只数 1。"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW)
    _enqueue(conn=conn, subject="issue:6", priority=1, now=_NOW)
    alive_row, alive_fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="alive", now=_NOW)
    dead_row, dead_fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="dead", now=_NOW)
    assert (alive_row["subject"], dead_row["subject"]) == ("issue:5", "issue:6")
    os.close(dead_fd)  # 「持有者进程死了」= 内核把它的 flock 收走了

    before = _open_fds()
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 1, "活着的持有者那行不算回收"
    assert _leaked(before=before, allowed=set()) == set(), "回收过程中开的锁 fd 必须全部关掉"
    assert _row(conn, subject="issue:5")["status"] == "claimed"  # 活人的行一个字节都不动
    reclaimed = _row(conn, subject="issue:6")
    assert (reclaimed["status"], reclaimed["worker"], reclaimed["claimed_at"]) == (
        "queued",
        None,
        None,
    )
    os.close(alive_fd)


def test_reclaim_does_not_report_a_row_that_the_holder_finished_first(tmp_path):
    """持有者在 SELECT 与 UPDATE 之间**正常收工删了行** → `rowcount=0` → 什么也没回收，**不许谎报**。

    这个窗口天天发生（收工与回收各自持锁一瞬）。谎报的代价不是崩溃，是「回收了 N 行」这个唯一能看出
    「有 worker 在批量猝死」的信号被噪声淹没。
    """
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    os.close(fd)  # 锁已放（持有者已死 / 已收工），故 `_reclaim_dead` 抢得到

    class _RacingConn:
        """在 `_reclaim_dead` 拿到 SELECT 结果、正要 `BEGIN IMMEDIATE` 的那一刻，把行删掉（持有者收工了）。"""

        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner
            self._fired = False

        def execute(self, sql, params=()):
            if sql.startswith("BEGIN IMMEDIATE") and not self._fired:
                self._fired = True
                self._inner.execute("DELETE FROM work_queue WHERE id=?", (row["id"],))
            return self._inner.execute(sql, params)

    assert _reclaim_dead(conn=_RacingConn(conn), work_dir=tmp_path) == 0, "0 行被改 ⇒ 0 行被回收"
    assert _count(conn) == 0


# --------------------------------------------------------------------------------------------------
# `_drain_queue`：`once=True` 的同步点——可以放弃，但**不能永不返回**（`oa vigil --once` 挂死是最糟的结局）。
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
    """一行卡住（worker 死在收尾 / agent 挂死）→ 到 `_DRAIN_MAX_SECONDS` 就返回，把活留在队里下次接上。"""
    db_path, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)  # 永远没人消费
    monkeypatch.setattr(vigil_module, "_DRAIN_MAX_SECONDS", 0)
    _drain(tmp_path, db_path)  # 不许挂死
    assert _count(conn) == 1, "排空是尽力而为的同步点，不是正确性来源——真相在 GitHub"


def test_drain_sweeps_a_leaked_lock_row_instead_of_spinning_to_the_hard_cap(tmp_path, monkeypatch):
    """# Spec-0065/T2: 排空期间也必须扫「存活证明泄漏」——那种行**永远**领不走。

    只在 tick 开头扫一次的话，`oa vigil --once` 会在 `_drain_queue` 里干等满 `_DRAIN_MAX_SECONDS`（1h）才
    返回：没有 worker 领得走它（`_claim_next` 每轮抢不到锁就静默跳过），也没有第二个 tick 来扫它（`--once`
    只跑一个）。CLI 与 e2e 都走这条路——挂一小时是最糟的结局。
    """
    db_path, conn = _db(tmp_path)
    parked = _park_spy(monkeypatch)
    monkeypatch.setattr(vigil_module, "_DRAIN_MAX_SECONDS", 3)  # 没扫到 → 只能耗到这个上限才返回
    monkeypatch.setattr(vigil_module, "_WORKER_POLL_SECONDS", 0.01)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    leaked = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert leaked is not None

    started = time.monotonic()
    _drain(tmp_path, db_path, seen_locked={"issue:5": _NOW}, now=_LATER)  # 上一 tick 已见它锁着
    elapsed = time.monotonic() - started

    assert parked == ["issue:5"], "排空里也要交人，否则这一行没有任何人看得见它"
    assert _count(conn) == 0, "park 落地 → 行删掉 → 队列排空 → 立刻返回"
    assert elapsed < vigil_module._DRAIN_MAX_SECONDS, "不许耗到硬上限（那就是挂着）"
    os.close(leaked)


def test_drain_survives_a_sweep_that_blows_up_on_the_lock_file(tmp_path, monkeypatch):
    """# Spec-0065/T2: 排空期扫陈锁炸了（`_try_lock` 抛 `OSError`：EMFILE / claims 目录被 chmod 掉）→
    **不许逃出 `_drain_queue`**。

    守夜主循环把 `_producer_tick` 整个包在 except 里（第一要务是活着进下一轮），**排空这条路上没有那层网**：
    异常从这里逃出去就直接打死 `oa vigil --once`（CLI 与 e2e 都走它）。扫不动 ≠ 排不空——照常等、照常到点返回。
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
    _drain(tmp_path, db_path)  # 不许抛

    assert time.monotonic() - started < _DEADLINE_SECONDS, "到硬上限就返回，不许挂死"
    assert _count(conn) == 1, "扫不动就扫不动——行留在队里，下次启动接着来"
