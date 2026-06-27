"""Spec-0026/T2: 多仓库统管的并发编排（每仓库一子进程跑现有 Vigil + 日志聚合 + 错误隔离）。

`openagents vigil-all` 的执行核心：拿到 T1 解析出的一组 `RepoPlan`，为**每个仓库各起一个
隔离子进程**，在子进程里 `os.chdir(repo)` 后复用现有 CLI 工厂 `_vigil_for` 构造 `Vigil` 跑
各自的守夜循环。父进程只做监管：把子进程日志经 `multiprocessing.Queue` 收回、加 `[name]`
前缀聚合到 stderr；某子进程崩溃只记一行不拖垮其余（错误隔离）；`Ctrl-C` 逐个 terminate
后干净退出。

为什么是进程而非线程（见 Spec-0026 Reference-level / 备选 A）：`github` 的 `gh` 调用绑
**进程工作目录**（`subprocess.run(["gh", ...])` 不传 cwd），而 `os.chdir` 改的是进程全局
cwd——同一进程内多线程无法各持不同 cwd，两个仓库的 `gh issue list` 会串台。给每个仓库一个
独立子进程则一举拿到 cwd 隔离、内存/状态隔离、崩溃隔离与真正并行。

编排逻辑与「真正起进程」解耦（理念 10）：`Fleet` 把 `spawn` / `queue_factory` 作为可注入
依赖，单测注入假 spawn/假 queue 即可驱动 fan-out / 前缀聚合 / 崩溃隔离 / 停止路径，不触达
真实子进程与 gh/后端。CLI（T3）注入下面的 `default_spawn` / `default_queue` 起真进程。
"""

from __future__ import annotations

import os
import queue as _queue
import sys
from collections.abc import Callable
from typing import Any

from openagents.fleet_config import RepoPlan

# Spec-0026/T2：父进程轮询日志队列的阻塞窗口（秒）。短超时让父进程在「无新日志」与
# 「检查子进程是否都已退出」之间快速轮转，既不忙等也不错过停止时机。
_DRAIN_TIMEOUT = 0.2


class _QueueWriter:
    """Spec-0026/T2：子进程内的 stderr 替身——把 Vigil._log 的写入按行投到日志队列。

    `Vigil._log` 用 `print(..., file=sys.stderr)` 打日志；子进程内把 `sys.stderr` 临时换成
    本对象，于是每写满一行就 `queue.put((name, line))` 回传父进程（父进程统一加 `[name]`
    前缀）。按 `\\n` 切行并缓冲半行，避免把一条日志拆成多片。
    """

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
        # 冲掉无换行结尾的残留半行，避免最后一条日志丢失。
        if self._buffer:
            self._queue.put((self._name, self._buffer))
            self._buffer = ""


def _run_repo(*, plan: RepoPlan, log_queue: Any, once: bool) -> None:
    """Spec-0026/T2：单仓库子进程的目标函数——锁定 cwd 后复用现有 Vigil 守夜。

    步骤：(1) `os.chdir(plan.path)` 把进程 cwd 钉到该仓库，使其后的 `gh`/`git` 与状态读写
    全部作用于本仓库；(2) `resolve_project()` 解析项目上下文（非 git 仓库 → RuntimeError，
    由父进程当作子进程非零退出报一行）；(3) 复用 CLI 工厂 `_vigil_for` 构造 `Vigil`、
    `parse_hold` 解析闸门；(4) 把 stderr 临时换成 `_QueueWriter` 后调 `vigil.run`，于是守夜
    日志经队列回传父进程聚合。延迟 import `cli`/`config`/`hold`，沿用本仓库「命令体内延迟
    import」惯例，避免与 cli 形成顶层循环依赖。
    """
    os.chdir(plan.path)
    from openagents import cli, config
    from openagents.hold import parse_hold

    ctx = config.resolve_project()
    if ctx is None:
        raise RuntimeError(f"{plan.path} 不是 git 仓库，无法守夜")

    vigil = cli._vigil_for(ctx=ctx)
    hold = parse_hold(raw=plan.hold)

    writer = _QueueWriter(name=plan.name, log_queue=log_queue)
    original_stderr = sys.stderr
    sys.stderr = writer
    try:
        vigil.run(
            interval=plan.interval,
            labels=plan.labels,
            base=plan.base,
            once=once,
            hold=hold,
        )
    finally:
        writer.flush()
        sys.stderr = original_stderr


def _run_repo_entry(*, plan: RepoPlan, log_queue: Any, once: bool) -> None:
    """Spec-0026/T2：子进程真实入口——把 `_run_repo` 的任何失败转成一行干净日志 + 非零退出。

    单仓库 `openagents vigil` 的运行期错误经 CLI `_run` 转成干净一行（不糊 traceback，RFC-0003
    决策 9）；子进程里没有那条通道，未捕获异常会被 multiprocessing 默认打印成整页 traceback。
    这里补上同一哲学：捕获后经队列回传一行带原因的失败日志（父进程加 `[name]` 前缀），再以
    `SystemExit(1)` 退出——既让父进程的退出码监管看到失败（错误隔离照旧记一行），又不向用户糊
    traceback。`KeyboardInterrupt` 放行（人按 Ctrl-C 时由父进程统一 terminate）。
    """
    try:
        _run_repo(plan=plan, log_queue=log_queue, once=once)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 子进程兜底：任何失败都转干净一行，不漏 traceback
        log_queue.put((plan.name, f"✗ 守夜失败：{exc}"))
        raise SystemExit(1) from exc


def default_queue() -> Any:
    """Spec-0026/T2：真正的跨进程日志队列工厂（CLI 注入）。延迟 import 保持本模块轻。"""
    import multiprocessing

    return multiprocessing.Queue()


def default_spawn(*, plan: RepoPlan, log_queue: Any, once: bool) -> Any:
    """Spec-0026/T2：真正起一个子进程跑 `_run_repo`（CLI 注入）。

    `RepoPlan` 是可 pickle 的 frozen dataclass、`_run_repo` 是模块级函数——满足 spawn 启动
    方式（macOS/Win 默认）对 target 与参数可序列化的要求。
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


class Fleet:
    """Spec-0026/T2：多仓库守夜编排器——为每个 RepoPlan 起一隔离子进程并监管其生命周期。

    `spawn` / `queue_factory` 为可注入依赖（理念 10 解耦）：生产用 `default_spawn` /
    `default_queue` 起真进程，单测注入假实现验证编排逻辑而不触达真实子进程与 gh/后端。
    """

    def __init__(self, *, spawn: Callable[..., Any], queue_factory: Callable[[], Any]) -> None:
        self._spawn = spawn
        self._queue_factory = queue_factory

    def run(self, *, plans: list[RepoPlan], once: bool) -> None:
        """为每个 plan 起一子进程并发守夜，聚合日志，监管到全部结束或 Ctrl-C。

        正常路径：起 N 个子进程 → 循环排空日志队列（加 `[name]` 前缀打 stderr）→ 队列空且
        全部子进程退出 → 报告非零退出码的崩溃 → join 回收。`KeyboardInterrupt`（人按下
        Ctrl-C，亦由队列 get 抛出穿透 supervise）→ 逐个 terminate 后干净退出，不上抛。
        finally 兜底 join 全部子进程，杜绝僵尸。
        """
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
        """排空日志队列并聚合打印，直到队列空且所有子进程退出；末了报告崩溃的子进程。"""
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
        """子进程异常退出（exitcode 非 0）记一行——错误隔离：报告而不拖垮其余。"""
        for name, handle in handles.items():
            code = handle.exitcode
            if code:
                self._emit(message=f"[{name}] ✗ 守夜进程退出（code {code}）")

    def _emit(self, *, message: str) -> None:
        """聚合日志统一打到 stderr（与 Vigil._log 同通道，保证无人值守时可观测）。"""
        print(message, file=sys.stderr, flush=True)
