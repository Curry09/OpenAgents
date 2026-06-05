"""RFC-0004: openagents vigil —— 守夜人模式（自主 issue→PR 全流程循环）。

Vigil 是一个**薄调度循环**，本身不实现「解 issue」或「轮询 PR」——这些分别由
Orchestrator 与 Messages 提供（决策 1）。它唯一新增的业务能力是**issue 发现**
（决策 2/3）：去 GitHub 列出带约定标签、且尚未处理过的 open issue，逐个派单
Orchestrator.start_rfc 起草 RFC、开 draft PR（决策 5 串行、决策 8 错误隔离），
再调 Messages.poll 推进已开 PR。RFC-0005 把一站式 solve 拆成原子步骤后，发现段只
负责「起草 RFC」这一步，后续 refine→implement→iterate 整条 RFC-first 循环由守候段
Messages.poll 按 rfc-approved 标签 / 评论 / CI 自动分流驱动——vigil 无需感知这些步骤。
每轮循环都从 GitHub + 本地 State 重新推导「现在该做什么」，不持有不可重建的内存
状态——这是 issue #9「代码即 checkpoint、agent 一次性」的落点：vigil 被 kill/崩溃
后重跑即从断点继续（去重三道闸据 State+远端重新推导，RFC-0003 决策 7/8）。

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
from openagents.state import STATUS_SOLVING

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

        RFC-0010 决策 5/6：长驻（once=False）模式下，单轮 `_run_one_round` 失败记日志并
        进下一轮，不掀掉整个守夜进程——单点偶发（如 gh 504 穿透重试、git/orchestrator 异常）
        不该让无人值守的守夜整夜阵亡。once 模式（cron/CI 周期触发）则不吞异常、照旧上抛，
        让调度器从非零退出码看见真实失败。`except Exception` 天然放行 KeyboardInterrupt
        （非 Exception 子类），Ctrl-C 仍走既有干净退出分支。
        """
        try:
            while True:
                try:
                    self._run_one_round(labels=labels, base=base)
                except Exception as exc:  # noqa: BLE001 —— 决策 6：守夜第一要务是「活着进下一轮」
                    if once:
                        raise  # 决策 5：once 模式不吞，让 cron/CI 得到非零退出
                    self._log(message=f"✗ 本轮守夜失败，跳过、{interval}s 后再扫一轮：{exc}")
                if once:
                    return
                self._log(message=f"… 守夜中，{interval}s 后再扫一轮（Ctrl-C 停止）")
                time.sleep(interval)
        except KeyboardInterrupt:
            self._log(message="✓ 守夜人已停止（Ctrl-C）")
            return

    def _run_one_round(self, *, labels: list[str], base: str) -> None:
        """RFC-0010 T2：单轮——发现+派单，再 poll 已开 PR。

        从既有 run 循环体中机械抽取的私有方法，行为不变；抽出后供长驻模式 try/except
        包裹（单轮失败兜底）与 once 模式直接调用（异常上抛）复用。
        """
        self.discover_and_dispatch(labels=labels, base=base)
        self._messages.poll()

    def discover_and_dispatch(self, *, labels: list[str], base: str) -> list[int]:
        """发现段：列出标签门控的 open issue，按本地 State 三路分流派单（RFC-0004/0007）。

        RFC-0007 决策 1/3：用 `_dispatch_kind` 取代原 `_is_new`，对每个 issue 区分：
          - "fresh"  → start_rfc(resume=False)：无 run 记录且远端无分支，建全新 worktree。
          - "resume" → start_rfc(resume=True) ：solving/pr=0 的孤儿 run，复用残留 worktree 续跑。
          - None     → 跳过：已开 PR / rfc-review / pr-open / iterating / done / closed，交 poll 推进。
        RFC-0005：派单只调 start_rfc（开 RFC draft PR）；后续 refine/implement/iterate
        由守候段 Messages.poll 驱动。返回本轮实际派单（fresh+resume）的 issue 编号列表。
        """
        dispatched: list[int] = []
        for issue in github.list_issues(labels=labels):
            kind = self._dispatch_kind(issue=issue)
            if kind is None:
                continue
            resume = kind == "resume"
            verb = "恢复孤儿 run" if resume else "派单起草 RFC"
            try:
                self._log(message=f"▶ issue #{issue.number}：{issue.title} → {verb}")
                self._orchestrator.start_rfc(issue_number=issue.number, base=base, resume=resume)
                dispatched.append(issue.number)
            except (OrchestratorError, GithubError) as exc:
                # 决策 8：单个 issue 失败记录并跳过，不拖垮整轮守候。
                self._log(message=f"✗ issue #{issue.number} {verb}失败，跳过：{exc}")
        return dispatched

    def _dispatch_kind(self, *, issue: github.Issue) -> str | None:
        """RFC-0007 决策 1/3/6：据本地 State + 远端分支把 issue 归类为 fresh / resume / 跳过。

        返回 "fresh" | "resume" | None：
          - 无 run 记录 → 远端无分支才 "fresh"（去重闸 c：远端已有分支但无 run 视为在途，跳过）。
          - solving 且 pr_number==0 → "resume"（崩在起草/push/建 PR 段的孤儿 run）。
          - 其它（已带 PR：rfc-review/pr-open/iterating/done/closed）→ None，交 poll。
        resume 路径刻意不查远端分支去重闸——复用同名分支正是目的（决策 6(c)）。
        """
        record = self._state.find_by_issue(issue_number=issue.number)
        if record is None:
            if self._remote_branch_exists(branch=f"{_BRANCH_PREFIX}{issue.number}"):
                return None
            return "fresh"
        if record.status == STATUS_SOLVING and record.pr_number == 0:
            return "resume"
        return None

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
