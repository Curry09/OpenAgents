"""RFC-0004: openagents vigil —— 守夜人模式（自主 issue→PR 全流程循环）。

Vigil 是一个**薄调度循环**，本身不实现「解 issue」或「轮询 PR」——这些分别由
Orchestrator 与 Messages 提供（决策 1）。它唯一新增的业务能力是**issue 发现**
（决策 2/3）：去 GitHub 列出带约定标签、且尚未处理过的 open issue，逐个派单
Orchestrator.solve（决策 5 串行、决策 8 错误隔离），再调 Messages.poll 处理已开 PR
的 merge/CI/comment。每轮循环都从 GitHub + 本地 State 重新推导「现在该做什么」，
不持有不可重建的内存状态——这是 issue #9「代码即 checkpoint、agent 一次性」的落点：
vigil 被 kill/崩溃后重跑即从断点继续（solve 幂等，RFC-0003 决策 7/8）。

依赖注入：orchestrator（Orchestrator）、messages（Messages）、state（State）、
work_dir（repo 根，供发现段去重闸 (c) 的 git ls-remote）。time.sleep 可在测试中 mock。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from openagents import github
from openagents.github import GithubError
from openagents.messages import Messages
from openagents.orchestrator import Orchestrator, OrchestratorError

# 与 orchestrator 一致的分支命名：单 issue → 单分支。
_BRANCH_PREFIX = "openagents/issue-"


class Vigil:
    """RFC-0004：守夜人——主动发现新 issue 并派单，同时守候已开 PR。"""

    def __init__(
        self, *, orchestrator: Orchestrator, messages: Messages, state, work_dir: Path
    ) -> None:
        self._orchestrator = orchestrator
        self._messages = messages
        self._state = state
        self._work_dir = Path(work_dir)

    def run(self, *, interval: int, labels: list[str], base: str, once: bool) -> None:
        """守夜人主循环：每轮先发现+派单，再 poll 已开 PR；持续到 Ctrl-C（决策 6）。

        once=True 跑一轮即返回（适配 cron/CI 周期触发）；否则 sleep(interval) 续循环。
        KeyboardInterrupt 是人类的停止信号 → 干净退出，不抛出（决策 8）。
        """
        try:
            while True:
                self.discover_and_solve(labels=labels, base=base)
                self._messages.poll()
                if once:
                    return
                self._log(message=f"… 守夜中，{interval}s 后再扫一轮（Ctrl-C 停止）")
                time.sleep(interval)
        except KeyboardInterrupt:
            self._log(message="✓ 守夜人已停止（Ctrl-C）")
            return

    def discover_and_solve(self, *, labels: list[str], base: str) -> list[int]:
        """发现段：列出标签门控的 open issue，过滤出「新」的逐个 solve（决策 2/3/5/8）。

        返回本轮实际派单的 issue 编号列表（便于日志/测试断言）。
        """
        dispatched: list[int] = []
        for issue in github.list_issues(labels=labels):
            if not self._is_new(issue=issue):
                continue
            try:
                self._log(message=f"▶ 发现新 issue #{issue.number}：{issue.title} → 派单 solve")
                self._orchestrator.solve(issue_number=issue.number, base=base)
                dispatched.append(issue.number)
            except (OrchestratorError, GithubError) as exc:
                # 决策 8：单个 issue 失败记录并跳过，不拖垮整轮守候。
                self._log(message=f"✗ issue #{issue.number} 求解失败，跳过：{exc}")
        return dispatched

    def _is_new(self, *, issue: github.Issue) -> bool:
        """决策 3 去重三道闸（标签已在 list 层）：State 无 run 且远端无分支才算「新」。"""
        if self._state.find_by_issue(issue_number=issue.number) is not None:
            return False
        return not self._remote_branch_exists(branch=f"{_BRANCH_PREFIX}{issue.number}")

    def _remote_branch_exists(self, *, branch: str) -> bool:
        """决策 3(c)：远端是否已存在该 issue 分支（State 丢失时的兜底）。"""
        result = subprocess.run(
            ["git", "-C", str(self._work_dir), "ls-remote", "--heads", "origin", branch],
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())

    def _log(self, *, message: str) -> None:
        """守夜进度打到 stderr，保证无人值守时仍有可观测的运行轨迹。"""
        print(message, file=sys.stderr, flush=True)
