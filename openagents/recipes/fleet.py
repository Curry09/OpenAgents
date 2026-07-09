"""# Spec-0061/T3: recipes.fleet —— 多仓库并发守夜（每仓库一子进程跑新栈 vigil，纯控制流）。

新栈的「舰队」竖切：拿到一组 `RepoPlan`（`utils.fleet_config` 解析），为**每个仓库各起一个隔离
子进程**，在子进程里 `os.chdir(repo)` 后跑该仓库自己的新栈 `recipes.vigil` 守夜循环；父进程只做
监管——聚合日志、崩溃隔离、Ctrl-C 收口。为什么是进程而非线程：`gh` 调用绑**进程 cwd**、`os.chdir`
改进程全局 cwd，同进程多线程无法各持不同 cwd（两仓的 `gh issue list` 会串台），一仓一进程才拿到
cwd 隔离 + 崩溃隔离 + 真并行（对齐旧 fleet 的 Reference-level 论证）。

进程监管（fan-out / 日志前缀聚合 / 崩溃隔离 / 停止路径）是**与新旧栈无关的纯机制**，故按理念 1
（如无必要勿增实体）**直接复用**旧 `openagents.fleet.Fleet` 监管器 + `default_queue` + `_QueueWriter`
子进程 stderr 替身，不重写一行。本模块只提供**新栈专属的一件事**：per-repo 子进程目标 `_run_repo`
——它构造并跑**新栈** vigil（经 `cli._new_vigil_for`），取代旧 fleet 里构造旧 `Vigil` 的 `_run_repo`。
子进程内延迟 import cli/config（沿用旧栈「命令体内延迟 import」惯例，避免与 cli 顶层循环依赖）。
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any

# Spec-0061/T3: 复用旧 fleet 的进程监管纯机制（Fleet 监管器 + 真队列工厂 + 子进程 stderr 替身）。
from openagents.fleet import Fleet, _QueueWriter, default_queue
from openagents.utils.fleet_config import RepoPlan


def _run_repo(*, plan: RepoPlan, log_queue: Any, once: bool) -> None:
    """单仓库子进程目标：锁定 cwd → 构造并跑**新栈** vigil（发现段 + 守候段）。

    步骤：(1) `os.chdir(plan.path)` 把进程 cwd 钉到该仓库，使其后 gh/git 与状态读写全作用于本仓；
    (2) `resolve_project()` 解析项目上下文（非 git 仓库 → RuntimeError，由父进程当子进程非零退出记
    一行）；(3) `cli._new_vigil_for` 构造新栈 `recipes.vigil.Vigil` + 守候段 poll 偏函数；(4) 把
    stderr 临时换成 `_QueueWriter` 后 `vigil.run(..., poll=poll)`，守夜日志经队列回传父进程聚合。
    延迟 import cli/config，沿用本仓「命令体内延迟 import」惯例，避免顶层循环依赖。
    """
    os.chdir(plan.path)
    from openagents import cli, config

    ctx = config.resolve_project()
    if ctx is None:
        raise RuntimeError(f"{plan.path} 不是 git 仓库，无法守夜")

    vigil, poll = cli._new_vigil_for(ctx=ctx)

    writer = _QueueWriter(name=plan.name, log_queue=log_queue)
    original_stderr = sys.stderr
    sys.stderr = writer
    try:
        vigil.run(
            interval=plan.interval,
            labels=plan.labels,
            base=plan.base,
            once=once,
            poll=poll,
        )
    finally:
        writer.flush()
        sys.stderr = original_stderr


def _run_repo_entry(*, plan: RepoPlan, log_queue: Any, once: bool) -> None:
    """子进程真实入口：把 `_run_repo` 的任何失败转成一行干净日志 + 非零退出（不糊 traceback）。

    镜像旧 fleet._run_repo_entry：捕获后经队列回传一行带原因的失败日志（父进程加 `[name]` 前缀），
    再 `SystemExit(1)` 退出——父进程退出码监管看得见失败，用户不吃整页 traceback。`KeyboardInterrupt`
    放行（人 Ctrl-C 时由父进程统一 terminate）。
    """
    try:
        _run_repo(plan=plan, log_queue=log_queue, once=once)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 子进程兜底：任何失败转干净一行，不漏 traceback
        log_queue.put((plan.name, f"✗ 守夜失败：{exc}"))
        raise SystemExit(1) from exc


def default_spawn(*, plan: RepoPlan, log_queue: Any, once: bool) -> Any:
    """真正起一个子进程跑新栈 `_run_repo_entry`（CLI 注入）。

    `RepoPlan` 是可 pickle 的 frozen dataclass、`_run_repo_entry` 是模块级函数——满足 spawn 启动
    方式（macOS/Win 默认）对 target 与参数可序列化的要求。延迟 import multiprocessing 保持模块轻。
    """
    import multiprocessing

    process = multiprocessing.Process(
        target=_run_repo_entry,
        kwargs={"plan": plan, "log_queue": log_queue, "once": once},
        name=plan.name,
        daemon=True,
    )
    process.start()
    return process


def run_fleet(
    *,
    plans: list[RepoPlan],
    once: bool,
    spawn: Callable[..., Any] = default_spawn,
    queue_factory: Callable[[], Any] = default_queue,
) -> None:
    """多仓库并发守夜入口：复用 `Fleet` 监管器（注入新栈 spawn）为每个 plan 起子进程并监管到结束。

    `spawn` / `queue_factory` 可注入（默认新栈 `default_spawn` + 旧 `default_queue`）——单测注入假
    实现即可验「一 plan 一 spawn + Ctrl-C 逐个 terminate + join 回收」控制流，不触真子进程/gh/后端。
    """
    Fleet(spawn=spawn, queue_factory=queue_factory).run(plans=plans, once=once)
