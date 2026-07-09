"""# Spec-0061/T3: recipes.vigil —— 发现→分诊→派单 循环（纯控制流，零业务判断）。

新栈的守夜人：逐轮从 GitHub 列出标签门控的 open issue，对每个**新** issue 派 triager agent 出
分诊裁决，据裁决路由——可派单（actionable）→ 跑 `solve_issue` 竖切求解；不可派单 → 打
needs-human + 贴对齐评论、挂起等人。整条循环**只**做三件事：调 engine 派 agent、按 agent 的
结构化裁决分支、调确定性 utils/gates 兜底；自己不判「issue 讲清没/该不该做」（那是 triager 的活）、
也不直接碰 git/gh/subprocess（那是 utils 的活）。

去重三闸留在 recipe（**确定性**、非判断，故不下放 agent，对齐 Spec-0060 分界线）：
  ① 本地已有 run 记录 → 跳过（已在飞行/已完成，交守候段推进）；
  ② 远端已有该 issue 分支（`utils.git.remote_branch_exists`）→ 跳过（别的后端已认领在途）；
  ③ issue 带 BLOCKED_LABEL（needs-human）→ 跳过（已挂起待人对齐，人摘标签前不重判、防震荡）。
三闸都不命中才算「新」，才派 triager 分诊。每轮都从 GitHub+本地 State 重新推导「现在该做什么」，
不持内存态——被 kill/崩溃后重跑即从断点续（去重闸据 State+远端重新推导，理念「代码即 checkpoint」）。

派单动作（`dispatch`）默认走 `dispatch_solve`（建 worktree→组 Context→跑 solve_issue→记 run），
但作可注入依赖（理念 10 解耦）——单测注入假 dispatch 验证「发现+分诊+路由」控制流，不触真 git/后端。
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openagents.agents import triager
from openagents.recipes.solve_issue import solve_issue
from openagents.runtime import context, engine
from openagents.runtime.context import Context
from openagents.runtime.state import RuntimeState
from openagents.utils import git, github

# Spec-0061/T3: 单 issue → 单分支命名（与 solve_issue 交付、旧栈 orchestrator 一致）。
_BRANCH_PREFIX = "openagents/issue-"

# Spec-0061/T3: 新栈 run 记录的状态字面量——极简三态（求解中/已完成/已挂起），落 RuntimeState。
_STATUS_SOLVING = "solving"
_STATUS_DONE = "done"
_STATUS_BLOCKED = "blocked"


def dispatch_solve(
    *,
    issue_number: int,
    base: str,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
) -> dict:
    """默认派单：建隔离 worktree → 组装 Context → 跑 solve_issue 竖切 → 记 run 记录。

    worktree 建/拉（agent 无法自建沙箱的**编排** git）经 `utils.git.Workspace`；组 `Context`
    绑定该 worktree 供 solve_issue 各阶段读占位符；派单前先 set_run(solving) 落 checkpoint（崩溃
    重跑时去重闸①命中即不重派），solve_issue 返回后 set_run(done)。本函数是 recipe 的**默认**
    派单实现（可被注入替换），故允许经 utils 触 git——vigil 主循环自身仍零 git 直调。
    """
    branch = f"{_BRANCH_PREFIX}{issue_number}"
    workspace = git.Workspace(work_dir=Path(work_dir))
    worktree = workspace.prepare(issue_number=issue_number, branch=branch, base=base)
    state.set_run(issue_number=issue_number, status=_STATUS_SOLVING, branch=branch, pr_number=None)
    ctx = Context(work_dir=worktree, issue_number=issue_number, branch=branch)
    report = solve_issue(issue_number=issue_number, backend=backend, ctx=ctx)
    state.set_run(
        issue_number=issue_number,
        status=_STATUS_DONE,
        branch=branch,
        pr_number=report.get("pr_number"),
    )
    return report


class Vigil:
    """# Spec-0061/T3: 新栈守夜人——发现→分诊→派单，逐轮从 GitHub+State 重推进度（去中心、可重入）。"""

    def __init__(
        self,
        *,
        backend: Any,
        state: RuntimeState,
        work_dir: Path,
        agent_id: str = "",
        dispatch: Callable[..., Any] = dispatch_solve,
    ) -> None:
        self._backend = backend
        self._state = state
        self._work_dir = Path(work_dir)
        # 本实例身份——留作未来认领归属判定（对齐旧 vigil），当前分诊去重不消费，默认空串。
        self._agent_id = agent_id
        # 派单动作可注入（默认 dispatch_solve）：单测替假实现即可验发现+分诊+路由控制流。
        self._dispatch = dispatch

    def run(
        self,
        *,
        interval: int,
        labels: list[str],
        base: str,
        once: bool,
        poll: Callable[[], Any] | None = None,
    ) -> None:
        """守夜主循环：每轮先发现+分诊+派单，再（可选）跑守候段 poll_comments；到 Ctrl-C 停。

        once=True 跑一轮即返回（适配 cron/CI 周期触发），异常照旧上抛让调度器看见非零退出；
        长驻（once=False）模式单轮失败记日志进下一轮，不掀掉整夜守候（对齐旧 vigil 决策 5/6）。
        `except Exception` 天然放行 KeyboardInterrupt（非 Exception 子类），Ctrl-C 走干净退出。
        poll 可注入（守候段 recipes.poll_comments 的偏函数）；None 时只跑发现段。
        """
        try:
            while True:
                try:
                    self.discover_and_dispatch(labels=labels, base=base)
                    if poll is not None:
                        poll()
                except Exception as exc:  # noqa: BLE001 —— 守夜第一要务是「活着进下一轮」
                    if once:
                        raise
                    self._log(message=f"✗ 本轮守夜失败，跳过、{interval}s 后再扫一轮：{exc}")
                if once:
                    return
                self._log(message=f"… 守夜中，{interval}s 后再扫一轮（Ctrl-C 停止）")
                time.sleep(interval)
        except KeyboardInterrupt:
            self._log(message="✓ 守夜人已停止（Ctrl-C）")
            return

    def discover_and_dispatch(self, *, labels: list[str], base: str) -> list[int]:
        """发现段：列标签门控 open issue → 去重三闸滤新 → triager 分诊 → 据裁决路由。返回本轮派单编号。

        对每个「新」issue（三道确定性去重闸都不命中）派 triager 出 `actionable` 裁决：
          - actionable=True  → 调 dispatch 跑 solve_issue 求解（并记入派单列表）；
          - actionable=False → _park：打 needs-human + 贴 triager 的对齐理由，挂起等人（不派单）。
        单 issue 失败（gh/agent/worktree 异常）只记日志跳过，不拖垮整轮（错误隔离，对齐旧 vigil 决策 8）。
        """
        dispatched: list[int] = []
        for issue in github.list_issues(labels=labels):
            if not self._is_fresh(issue=issue):
                continue
            try:
                verdict = engine.run_agent(
                    triager,
                    backend=self._backend,
                    **context.for_triage(work_dir=self._work_dir, issue=issue),
                )
                if not verdict["actionable"]:
                    self._park(issue=issue, reason=verdict["reason"])
                    continue
                self._log(message=f"▶ issue #{issue.number}：{issue.title} → 分诊通过，派单求解")
                self._dispatch(
                    issue_number=issue.number,
                    base=base,
                    backend=self._backend,
                    state=self._state,
                    work_dir=self._work_dir,
                )
                dispatched.append(issue.number)
            except (
                github.GithubError,
                engine.AgentOutputError,
                git.WorkspaceError,
            ) as exc:
                self._log(message=f"✗ issue #{issue.number} 派单失败，跳过：{exc}")
        return dispatched

    def _is_fresh(self, *, issue: github.Issue) -> bool:
        """去重三闸（确定性）：本地无 run 记录 且 远端无分支 且 未挂 needs-human → 判「新」。"""
        if self._state.get_run(issue_number=issue.number) is not None:
            return False
        if git.remote_branch_exists(
            work_dir=self._work_dir, branch=f"{_BRANCH_PREFIX}{issue.number}"
        ):
            return False
        if github.BLOCKED_LABEL in issue.labels:
            return False
        return True

    def _park(self, *, issue: github.Issue, reason: str) -> None:
        """分诊判不可派单 → 确定性挂起：打 needs-human + 贴 triager 的对齐理由，记 blocked run。

        这是**据 agent 裁决执行的确定性动作**（打标签/贴评论/记状态），不含二次判断——「该不该
        挂起」已由 triager 判完，recipe 只落地。记 blocked run 使去重闸①下轮命中，人摘标签前不重判。
        """
        github.issue_add_label(number=issue.number, name=github.BLOCKED_LABEL)
        github.issue_comment(
            number=issue.number,
            body=f"⏸ openagents 分诊：本 issue 暂不可直接派单，请对齐后再触发。\n\n{reason}",
        )
        self._state.set_run(
            issue_number=issue.number,
            status=_STATUS_BLOCKED,
            branch=f"{_BRANCH_PREFIX}{issue.number}",
            pr_number=None,
        )
        self._log(message=f"⏸ issue #{issue.number}：分诊判需对齐，已挂 needs-human")

    def _log(self, *, message: str) -> None:
        """守夜进度打到 stderr，保证无人值守时仍有可观测轨迹（对齐旧 vigil._log）。"""
        print(message, file=sys.stderr, flush=True)
