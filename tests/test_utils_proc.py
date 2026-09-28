"""Spec-0065/T2: `openagents/utils/proc.py` 契约测试——**每线程 PID 认领桶** + **进程树 SIGKILL**。

四条不变式是这个模块存在的全部理由，故都用真东西验证（不打桩）：

1. **认领靠自报、按线程分桶**：K 个 worker 并发跑 agent 时，A 线程的 `publish()` 绝不能落进 B 的桶里
   （否则超时方会 SIGKILL 别人的进程——正是本模块要根除的 PID 误认）。桶是 `{PID: Popen 句柄}`。
2. **杀要杀整棵树**：agent CLI 常自己再起一层（shell / node wrapper），只杀直接子进程会留下还在跑的后代。
   故这里起**真**的 `subprocess.Popen`（孙子进程 `sleep`），`kill_tree` 后断言父与孙都不再运行。
3. **句柄验明正身**：`kill_tree(handle=…)` 且 `handle.poll()` 非 None ⇒ 那个进程**已退出并被 reap**，
   PID 已交还内核、可能已被别人占用 → **一个进程都不许杀**（杀了最可能是本进程另一个 worker 的 agent）。
4. **存活证明跟着干活的进程走**：`hold_fd` / `inherited_fds` / `release_fds` 按线程登记要被子进程继承的
   fd（守夜传的是 flock 的 fd），两条线程互不可见。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from openagents.utils import proc

# Spec-0065/T2：真进程用例的轮询上限（秒）。SIGKILL 是同步投递、reap 是异步的，给一个短窗口即可，
# 既不让用例慢，也不让它在负载高的 CI 上抖。
_DEADLINE = 5.0


# --------------------------------------------------------------------------- #
# 认领桶：track / publish / untrack
# --------------------------------------------------------------------------- #


def test_track_opens_empty_bucket_for_calling_thread():
    """Spec-0065/T2：`track()` 开桶（空桶），`untrack()` 取走它。桶是 `{PID: 句柄}` 的 dict。"""
    proc.track()
    assert proc.untrack(thread_id=threading.get_ident()) == {}


def test_publish_adds_pid_to_calling_thread_bucket():
    """Spec-0065/T2：`publish()` 落到**调用线程**自己的桶；`untrack()` 返回 `{PID: 句柄}` 并关桶。"""
    proc.track()
    proc.publish(pid=4242)
    proc.publish(pid=4243)

    me = threading.get_ident()
    assert proc.untrack(thread_id=me) == {4242: None, 4243: None}  # 没给句柄 → 记 None
    # 桶已被取走：再取一次 → 空桶（不是残留）。
    assert proc.untrack(thread_id=me) == {}


def test_publish_records_the_popen_handle_alongside_the_pid():
    """Spec-0065/T2：句柄是「这个 PID 还是不是当年那个进程」的**唯一**可靠依据（PID 会被内核回绕重发）。

    故 `publish(handle=…)` 必须把 `Popen` 原样存进桶里，供 `kill_tree` 验明正身——丢了它，超时方就只剩
    裸 PID 可杀，最可能的受害者恰是本进程另一个 worker 的 agent（→ 那行被回收重领 → 双跑）。
    """
    handle = object()  # 只要求原样存回，不要求是真 Popen
    proc.track()
    proc.publish(pid=4244, handle=handle)

    bucket = proc.untrack(thread_id=threading.get_ident())
    assert bucket == {4244: handle}
    assert bucket[4244] is handle  # 是**那一个**句柄，不是拷贝/替身


def test_track_twice_resets_bucket():
    """Spec-0065/T2：重复 `track()` 即清空重开（同一线程跑第二轮 agent，不能带上一轮的残留 PID）。"""
    proc.track()
    proc.publish(pid=111)
    proc.track()
    assert proc.untrack(thread_id=threading.get_ident()) == {}


def test_untrack_unknown_thread_returns_empty_bucket():
    """Spec-0065/T2：没开过桶的线程 id → 空桶而非 KeyError（尽力而为，绝不把守夜主循环带崩）。"""
    assert proc.untrack(thread_id=-12345) == {}


def test_publish_without_track_is_noop():
    """Spec-0065/T2：生产者线程里普通的 gh/git 子进程也会 `publish`，但它没开桶 → 静默 no-op。

    契约有两半：(a) 不抛异常；(b) 不凭空建桶——事后 `untrack` 仍是空桶，即该 PID **没有**被任何人认领。
    """
    me = threading.get_ident()
    proc.untrack(thread_id=me)  # 确保当前线程没桶（前面的用例可能开过）

    proc.publish(pid=999_001)  # 不得抛

    assert proc.untrack(thread_id=me) == {}


def test_concurrent_threads_do_not_see_each_other_pids():
    """Spec-0065/T2：**本模块的全部意义**——两条线程同时 publish，各记各的，零串味。

    用 Barrier 把两边的 publish 逼到同一时刻（真并发，不是先后串行），再各自 untrack 自己的桶。
    """
    ready = threading.Barrier(2)
    buckets: dict[str, set[int]] = {}

    def worker(*, name: str, pids: set[int]) -> None:
        proc.track()
        ready.wait(timeout=_DEADLINE)  # 两边都开好桶后再一起 publish
        for pid in pids:
            proc.publish(pid=pid)
            time.sleep(0)  # 让出 GIL，最大化交错
        buckets[name] = set(proc.untrack(thread_id=threading.get_ident()))  # 只比 PID 集

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
    assert not buckets["a"] & buckets["b"]  # 交集为空：谁也没认领到别人的 PID


def test_untrack_from_another_thread_gets_worker_bucket():
    """Spec-0065/T2：超时方在**别的**线程里按 `thread_id` 取桶（worker 挂死时正是这个路径）。"""
    worker_id: dict[str, int] = {}
    published = threading.Event()
    handle = object()

    def worker() -> None:
        proc.track()
        worker_id["id"] = threading.get_ident()
        proc.publish(pid=777, handle=handle)
        published.set()
        time.sleep(0.05)  # 模拟「还挂在 agent 调用里」——桶由外部线程取走

    t = threading.Thread(target=worker)
    t.start()
    assert published.wait(timeout=_DEADLINE)

    assert proc.untrack(thread_id=worker_id["id"]) == {777: handle}  # PID 与句柄一并交给超时方
    t.join(timeout=_DEADLINE)


# --------------------------------------------------------------------------- #
# 继承 fd 登记：hold_fd / inherited_fds / release_fds（存活证明跟着干活的进程走）
# --------------------------------------------------------------------------- #


def test_hold_fd_round_trips_per_thread_and_marks_the_fd_inheritable(tmp_path):
    """Spec-0065/T2：`hold_fd` 按**线程**登记要被子进程继承的 fd，两条线程互不可见；并把该 fd 置为可继承。

    **登记本身就是机制**：守夜把 flock 的 fd 登记在这里，backend 起
    `Popen(pass_fds=proc.inherited_fds())` 时把它交给 agent 子进程——锁于是变成「守夜进程**或**它的 agent
    还有一个活着」。若两条 worker 线程能看见对方的 fd，A 的 agent 会连 B 的锁一起继承：B 收工后锁仍被 A 的
    孤儿子进程持着 → B 那行永远判不了死。故**按线程隔离**是硬要求，也是本用例的主断言。

    真正让 fd 活着穿过 `exec` 的是 `pass_fds` 自己：CPython 的 `_posixsubprocess` 在 fork 之后、exec 之前，
    在**子进程里**逐个清掉 `pass_fds` 里那些 fd 的 CLOEXEC 位（PEP 446 只规定了「新建的 fd 默认不可继承」）。
    故父进程这次 `os.set_inheritable(fd, True)` **不是机制、只是状态一致性**：让这个 fd 的可继承位与我们对它
    的意图相符（它确实要传给子进程）。仍旧断言它——一个登记为「要继承」却标着不可继承的 fd 是自相矛盾的状态，
    而这份矛盾恰恰会误导下一个来读这段代码的人。
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
        ready.wait(timeout=_DEADLINE)  # 两边都登记完，再各自读——真并发下也不许串味
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
        assert seen["a"] == (fds["a"],)  # 各只看得见自己的
        assert seen["b"] == (fds["b"],)
        assert fds["b"] not in seen["a"] and fds["a"] not in seen["b"]  # 零串味
        assert os.get_inheritable(fds["a"]) and os.get_inheritable(fds["b"])

        proc.release_fds(
            thread_id=thread_ids["a"]
        )  # 收工注销（只清登记，不 close——所有权在调用方）
        assert proc.inherited_fds() == ()  # 主线程从来没登记过
        assert proc._INHERIT.get(thread_ids["a"]) is None
        assert proc._INHERIT.get(thread_ids["b"]) == (fds["b"],)  # 注销一个不许动另一个
    finally:
        proc.release_fds(thread_id=thread_ids["b"])
        for fd in fds.values():
            os.close(fd)


def test_release_fds_on_an_unknown_thread_is_a_noop():
    """Spec-0065/T2：没登记过的线程 id → 静默 no-op（收尾路径绝不许因为「本来就没登记」而抛）。"""
    proc.release_fds(thread_id=-12345)
    assert proc.inherited_fds() == ()


# --------------------------------------------------------------------------- #
# child_pids / kill_tree：真进程
# --------------------------------------------------------------------------- #


def _running(*, pid: int) -> bool:
    """pid 是否**还在运行**（僵尸 `Z` 不算：它已经死了，只是没被 reap）。取不到 → 视为已死。"""
    out = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    )
    stat = out.stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def _wait_dead(*, pid: int) -> bool:
    """短窗口轮询直到 pid 不再运行（SIGKILL 投递是同步的、reap 是异步的）。"""
    end = time.monotonic() + _DEADLINE
    while time.monotonic() < end:
        if not _running(pid=pid):
            return True
        time.sleep(0.05)
    return not _running(pid=pid)


def _spawn_parent_with_grandchild() -> tuple[subprocess.Popen[str], int]:
    """起一棵真的两层进程树：child(python) → grandchild(sleep 30)；返回 (child, grandchild_pid)。"""
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
    """Spec-0065/T2：`child_pids()` 列出本进程的**直接**子进程（孙子不在其中）。"""
    child, grandchild_pid = _spawn_parent_with_grandchild()
    try:
        pids = proc.child_pids()
        assert child.pid in pids
        assert grandchild_pid not in pids  # 孙子的 ppid 是 child，不是我
    finally:
        proc.kill_tree(pid=child.pid)
        child.wait(timeout=_DEADLINE)


def test_kill_tree_kills_child_and_grandchild():
    """Spec-0065/T2：`kill_tree` 杀整棵树——只杀直接子进程会留下还在跑的 `sleep`（双跑之源）。"""
    child, grandchild_pid = _spawn_parent_with_grandchild()
    try:
        assert _running(pid=grandchild_pid)  # 前置：孙子确实起来了

        proc.kill_tree(pid=child.pid)

        assert child.wait(timeout=_DEADLINE) != 0  # 父被 SIGKILL 收走（macOS: -9）
        assert _wait_dead(pid=grandchild_pid), "grandchild survived kill_tree（进程树没杀干净）"
    finally:
        # 兜底：用例失败也不给测试机留残兵。
        for pid in (grandchild_pid, child.pid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        child.wait(timeout=_DEADLINE)


def test_kill_tree_on_dead_pid_is_noop():
    """Spec-0065/T2：目标已退出 / PID 不存在 → 静默 no-op（超时方不该因为「杀晚了」而抛）。"""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=_DEADLINE)

    proc.kill_tree(pid=dead.pid)  # 已 reap 的自家子进程
    proc.kill_tree(pid=2**30)  # 压根不存在的 PID


def test_kill_tree_kills_nothing_when_the_handle_says_the_process_was_already_reaped(monkeypatch):
    """Spec-0065/T2：`handle.poll()` 非 None ⇒ 进程**已退出并被 reap** ⇒ 它的 PID 已交还内核、可能已被别人
    占用 ⇒ **一个信号都不许发**。

    长跑的守夜每 tick 起若干 gh/git，PID 回绕只是时间问题；此时按裸 PID 杀，最可能的受害者恰是本进程**另一个
    worker 的 agent**——那个 worker 的活半路被杀、行被回队重领 → 正是本设计要根除的双跑。漏杀的代价小得多
    （最坏是行卡住、被看门狗交人），故这道守卫**必须**先于一切。

    用**真**的已 reap 子进程（`Popen` + `wait()` → `poll()` 返回退出码）+ 对 `os.kill` 的 spy 验证：一次
    `kill` 都不许发出去。
    """
    signalled: list[int] = []
    monkeypatch.setattr(proc.os, "kill", lambda pid, sig: signalled.append(pid))

    reaped = subprocess.Popen([sys.executable, "-c", "pass"])
    reaped.wait(timeout=_DEADLINE)
    assert reaped.poll() is not None  # 前置：确已退出并被 reap

    proc.kill_tree(pid=reaped.pid, handle=reaped)

    assert signalled == [], "已 reap 的 PID 可能已被别人复用——按 PID 杀 = 杀无辜者（双跑之源）"


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
    """Spec-0065/T2：句柄守卫不许**过度**收紧——`poll()` 为 None（进程还活着）时照杀不误。

    与上一条互为反例：没有这一条，「kill_tree 直接 return」也能让上一条通过，而挂死的 agent 就永远杀不掉了。
    """
    child, grandchild_pid = _spawn_parent_with_grandchild()
    try:
        assert child.poll() is None  # 前置：还在跑（未 reap）

        proc.kill_tree(pid=child.pid, handle=child)

        assert child.wait(timeout=_DEADLINE) != 0  # 被 SIGKILL 收走
        assert _wait_dead(pid=grandchild_pid), "grandchild survived kill_tree（进程树没杀干净）"
    finally:
        for pid in (grandchild_pid, child.pid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        child.wait(timeout=_DEADLINE)
