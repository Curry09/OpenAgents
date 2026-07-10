"""# Spec-0060/T4 + Spec-0064/T6: agents —— 提示词层：每个 agent 一个模块，仅含 PROMPT
（string.Template）+ OUTPUT_SCHEMA（键→类型 dict），零逻辑。业务判断（起草/实现/评审判定/交付
解冲突/分诊/回评论/e2e 判读）全在提示词里、由 agent 执行，Python 不含任何判断。

Spec-0064/T6：`planner` 合并进 `drafter`（二者都「起草 spec、不写实现代码」，是新旧栈残留重复；
drafter 已承接五 mode 起草判断，planner 是死代码），本组不再重导出 planner。重导出新栈实际使用的
agent，使 recipe 既可 `from openagents.agents import drafter` 亦可 `agents.drafter`。
"""

from openagents.agents import deliver, drafter, implementer, replier, reviewer, tester, triager

__all__ = ["drafter", "implementer", "reviewer", "deliver", "tester", "triager", "replier"]
