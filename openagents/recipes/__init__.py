"""# Spec-0060/T6 + Spec-0064/T6: recipes —— 编排层：每个 flow 只有控制流 + runtime.run_agent
调用，无任何版本控制/远端/子进程直接调用。按 agent 的结构化裁决 / 确定性闸判读路由（顺序/循环/
分支/三态策略），自己不做任何业务判断。

Spec-0064 收敛后本层仅剩三模块：`stages`（九阶段抽成 Vigil 类外的独立自由函数）、`vigil`
（run_vigil 按 stages 三态策略路由编排 + 合并流水线打回回环 + 多仓 fleet 折入）、`backfill`
（path 驱动追溯单列）。旧 `solve_issue`/`merge_pr`/`poll_comments`/`rfc_lifecycle`/`fleet` 五 recipe
逻辑已溶入这三个，随两栈合一删除。
"""
