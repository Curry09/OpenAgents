"""# Spec-0060/T6: recipes.solve_issue —— 求解一个 issue 的编排（纯控制流，零业务判断）。

契约竖切：`plan → implement → review(loop while REWORK) → deliver`。本模块**只**做两件事——
调 `engine.run_agent` 派 agent、按 agent 返回的**结构化裁决**路由（顺序/循环/分支）；自己不判
「代码对不对/评审过没/冲突怎么解」，也不含任何版本控制/远端/子进程直接调用（那些是 agent
或 utils 的活）。分支条件只来自 reviewer agent 的 `verdict`，这正是「recipe 零业务判断」的技术支点。

两道最小硬闸兜底 agent 自述（防死循环 / 防空转撒谎）：
- `gates.round_cap`：评审循环轮次上限——reviewer 恒 REWORK 时兜底 raise；
- `gates.assert_head_advanced`：交付后断言 head 真前移——deliver agent 自判完成却没落地时兜底 raise。
"""

from __future__ import annotations

from openagents.agents import deliver, implementer, planner, reviewer
from openagents.runtime import engine, gates


def solve_issue(*, issue_number: int, backend: object, ctx: object) -> dict:
    """按结构化裁决路由把一个 issue 从起草跑到交付，返回 deliver 的结构化交付报告。

    ctx 提供各阶段占位符（`for_plan/for_implement/for_review/for_iterate/for_deliver`）与
    `workspace`（worktree 路径）；backend 是派 agent 的后端。全程零业务判断——唯一分支来自
    reviewer 的 `verdict`（PASS→next / REWORK→loop）。
    """
    # 起草 → 首轮实现（顺序）。
    engine.run_agent(planner, backend=backend, **ctx.for_plan(issue_number=issue_number))
    engine.run_agent(implementer, backend=backend, **ctx.for_implement(issue_number=issue_number))

    # 评审循环：只看 verdict 决定 loop（REWORK 迭代）还是 next（PASS 跳出）；round_cap 兜底死循环。
    for _ in gates.round_cap():
        verdict = engine.run_agent(
            reviewer, backend=backend, **ctx.for_review(issue_number=issue_number)
        )
        if verdict["verdict"] == "PASS":
            break
        engine.run_agent(
            implementer,
            backend=backend,
            **ctx.for_iterate(issue_number=issue_number, feedback=verdict["reason"]),
        )

    # 交付（下放 agent）→ head 前移硬闸兜底：deliver 自报交付前基点 base_sha，硬闸读实际 head 比对。
    report = engine.run_agent(
        deliver, backend=backend, **ctx.for_deliver(issue_number=issue_number)
    )
    gates.assert_head_advanced(before=report["base_sha"], workspace=ctx.workspace)
    return report
