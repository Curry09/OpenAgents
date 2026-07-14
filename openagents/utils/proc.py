"""进程工具：子进程认领（backend 自报 PID）/ 进程树 SIGKILL / 直接子进程枚举。

# Spec-0065/T2：`_act` 的硬超时需要「杀掉这次 agent 调用起的子进程」——flock 只回答「进程在不在」，
# 回答不了「进程活着但挂死在一个不返回的调用上」。recipes 层不许直调 subprocess（Spec-0064 的分层锚点：
# recipe 只走 utils 稳定面），故这些薄封装落在 utils，vigil 只消费。

**认领靠自报，不靠猜。** 早前的实现用「调用前后 diff 本进程的子进程集合」来认领 agent 的子进程，这在守夜里
是错的：生产者线程同时在跑 `gh`/`git`（它们也是本进程的子进程），K 个 worker 也彼此并发——diff 会把**别人的**
`gh` 认成自己的 agent，于是超时时杀错进程、真正挂死的 agent 活着继续 push（甚至 SIGKILL 一个 PID 复用后的
无关进程）。改为：起子进程的那一层（backend）在 `Popen` 之后调 `publish()` 自报 PID，谁起的谁认领，零歧义。

`track()` 以**线程**为桶：`_TimedBackend` 在专跑 agent 的那个线程里开桶，backend 在同一线程里 `publish`，
超时方按 `thread_id` 取桶。故并发的 K 个 agent 各记各的，互不串味。

**存活证明要跟着真正在干活的那个进程走**（`hold_fd` / `inherited_fds`）。守夜的 flock 只证明「守夜进程活着」；
可真正在改代码、在 push 的是它起的 **agent 子进程**，而守夜被 SIGKILL/OOM/`docker stop` 打死时那个子进程是被
**孤儿化**、不是被杀。故把 flock 的 fd 传给 agent 子进程继承：锁于是变成「守夜进程**或**它的 agent 还有一个
活着」——孤儿 agent 还在跑，`_reclaim_dead` 就抢不到锁、那行就不会被打回队列重领。详见 `hold_fd`。

所有函数**只读 / 尽力而为**：拿不到进程表、子进程已退出、无权限 —— 一律静默返回空集 / no-op，绝不把守夜
主循环带崩（守夜第一要务是活着进下一轮）。
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from typing import Any

# Spec-0065/T2: thread ident → 该线程自报的子进程（PID → Popen 句柄，句柄可为 None）。只有 track() 开过桶的
# 线程才被记录，故普通的 gh/git 子进程（生产者线程里起的）不会污染任何 agent 的认领集。
_TRACKED: dict[int, dict[int, Any]] = {}
# Spec-0065/T2: thread ident → 该线程要**传给子进程继承**的 fd（守夜用它传 flock 存活证明，见 hold_fd）。
_INHERIT: dict[int, tuple[int, ...]] = {}
_TRACK_LOCK = threading.Lock()


def track() -> None:
    """当前线程开一个认领桶（重复调用即清空重开）。由跑 agent 的那个线程在调 backend 前调用。"""
    with _TRACK_LOCK:
        _TRACKED[threading.get_ident()] = {}


def publish(*, pid: int, handle: Any = None) -> None:
    """自报「我刚起了这个子进程」。当前线程没开桶（普通 gh/git 调用）→ no-op。

    `handle` 是 `Popen` 本身（有则强烈建议给）：它是判断「这个 PID 还是不是当年那个进程」的**唯一**可靠依据
    —— 子进程一旦被 reap，PID 就可被内核重新分配，长跑的守夜进程每 tick 起若干 gh/git，PID 回绕只是时间问题。
    拿着裸 PID 去 SIGKILL，最可能的受害者恰恰是**本进程的另一个子进程**（另一个 worker 的 agent）——那个
    worker 的 agent 半路被杀、行被回队重领 → 正是本设计要根除的双跑。见 `kill_tree`。
    """
    with _TRACK_LOCK:
        bucket = _TRACKED.get(threading.get_ident())
        if bucket is not None:
            bucket[pid] = handle


def untrack(*, thread_id: int) -> dict[int, Any]:
    """取走并关闭某线程的认领桶，返回 {PID: Popen 句柄或 None}（没开过桶 → 空 dict）。"""
    with _TRACK_LOCK:
        return _TRACKED.pop(thread_id, {})


def hold_fd(*, fd: int) -> None:
    """让当前线程之后起的子进程**继承**这个 fd（守夜传的是 flock 存活证明的那个 fd）。

    # Spec-0065/T2: **谁在干活，谁就得持有存活证明。** flock 绑在 open file description 上，子进程继承 fd 即
    # 一并持有那把锁。不这么做的话，锁只证明「守夜进程还活着」，证明不了「agent 进程还活着」：守夜被
    # SIGKILL / OOM / `docker stop` 打死时，它起的 claude 子进程会被**孤儿化而不是被杀**（它要到下一次写
    # stdout 才会发现父亲没了，而那可能是几分钟后——足够它把一次 `git push` 做完）。此时内核放掉守夜的锁，
    # 重启后的 `_reclaim_dead` 抢到锁、判「持有者已死」、把行打回 queued → 另一个 worker 领走同一个
    # subject → **双跑**，且恰好发生在文档声称「结构性为零」的那个场景里。
    # 让 agent 子进程继承这个 fd 之后，锁的语义变成「守夜进程**或**它起的 agent 还有一个活着」——孤儿 agent
    # 在跑，锁就抢不到，行就不会被回收。
    #
    # **代价必须配一道闸。** `pass_fds` 在子进程里清掉了这个 fd 的 CLOEXEC，而 agent 不是 python（不会像
    # `subprocess` 那样替我们关掉多余 fd），故锁会**继续传给 agent 的孙子进程**：agent 若留下一个长命的孙子
    # （MCP server、它自己起的后台 dev server），那个孙子会一直持着锁 → 那一行永远领不走。这**不是**「卡一会儿
    # 然后被看门狗交人」——所有看门狗都看不见它（回收只扫 claimed 行、IN_FLIGHT 告警看 claimed_at、QUIET 看门狗
    # 只对 QUIET 生效，而它是一个 queued 的 ACTIONABLE 行）。故 vigil 侧配了 `_sweep_stalled`：queued 行的锁本
    # 就该是自由的，被占且超时 = 泄漏 → park 交人。**没有那道闸，这里就是拿一个罕见的双跑换一个永久的静默停摆。**
    #
    # 注：真正让子进程拿到 fd 的是 `Popen(pass_fds=…)`（`_posixsubprocess` 在 fork 后、exec 前于**子进程里**清
    # CLOEXEC）；父进程这次 `set_inheritable` 只是让 fd 的状态与意图一致的兜底，不是机制本身。
    """
    os.set_inheritable(fd, True)
    with _TRACK_LOCK:
        current = _INHERIT.get(threading.get_ident(), ())
        _INHERIT[threading.get_ident()] = (*current, fd)


def inherited_fds() -> tuple[int, ...]:
    """当前线程要传给子进程继承的 fd（backend 起 `Popen` 时用作 `pass_fds`）；没登记过 → 空。"""
    with _TRACK_LOCK:
        return _INHERIT.get(threading.get_ident(), ())


def release_fds(*, thread_id: int) -> None:
    """注销某线程登记的继承 fd（收工时调；只清登记，**不** close——fd 的所有权在调用方那边）。"""
    with _TRACK_LOCK:
        _INHERIT.pop(thread_id, None)


def child_pids() -> set[int]:
    """本进程当前的**直接**子进程 PID 集合；取不到 → 空集。

    走全表 `ps -eo pid=,ppid=` 自己按 ppid 过滤，不用 `ps -P`（那是 BSD/macOS 专有，GNU coreutils 无此选项、
    语义也不同）——一条路径同时覆盖 macOS 与 Linux。
    """
    return {pid for pid, ppid in _ps_table() if ppid == os.getpid()}


def kill_tree(*, pid: int, handle: Any = None) -> None:
    """SIGKILL 一个子进程**及其所有后代**（先杀后代再杀自己）。

    agent CLI 常自己再起一层（shell / node wrapper / MCP server），只杀直接子进程会留下一整棵还在跑的树——
    而「还在跑」正是双跑的来源。已退出 / 无权限 / 取不到进程表 → 静默忽略（尽力而为）。

    # Spec-0065/T2: 给了 `handle` 就先验明正身：`poll()` 非 None = 那个进程**已经退出并被 reap**，它的 PID
    # 已交还内核、可能已被别的进程占用——此时按 PID 杀是在杀无辜者（最可能是本进程另一个 worker 的 agent，
    # 于是那行被回收重领 → 双跑）。这一层守卫比「杀不干净」重要得多：漏杀最坏是行卡住被看门狗交人。
    #
    # **守卫只覆盖根 PID，不覆盖后代**（诚实记账）：后代不是我们的子进程、我们从不 reap 它们，`ps` 读表与
    # `os.kill` 之间它们随时可能退出并被真正的父亲 reap，PID 于是可复用。要真正堵死得靠进程组（`setsid` +
    # `killpg`），那要求 backend 起进程时就开新会话——留给后续。当前窗口是毫秒级且需 PID 回绕，可接受。
    """
    if handle is not None and handle.poll() is not None:
        return
    for child in _descendants(pid=pid):
        _kill_one(pid=child)
    _kill_one(pid=pid)


def _descendants(*, pid: int) -> list[int]:
    """pid 的全部后代（展开 ppid 表得到的整棵子树，不含 pid 自己）。

    返回顺序**不保证**自底向上（兄弟分支会交错）——调用方 `kill_tree` 发的是 SIGKILL，不可被捕获、无需清理时机，
    杀的先后与结果无关；这里只保证「一个不漏」。
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
    """全进程表 `[(pid, ppid), …]`；取不到 → 空表。"""
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
    """SIGKILL 单个进程（已退出 / 无权限 → 静默忽略）。"""
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
