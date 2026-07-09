"""# Spec-0060/T4: agents —— 提示词层：每个 agent 一个模块，仅含 PROMPT（string.Template）+
OUTPUT_SCHEMA（键→类型 dict），零逻辑。业务判断（实现/评审判定/交付解冲突/e2e 判读）全在
提示词里、由 agent 执行，Python 不含任何判断。

重导出 5 个 solve_issue 所需 agent，使 recipe 既可 `from openagents.agents import planner`
亦可 `from openagents import agents; agents.planner`。triager/replier 属后续批次的 vigil/
poll_comments，不在本组。
"""

from openagents.agents import deliver, implementer, planner, reviewer, tester

__all__ = ["planner", "implementer", "reviewer", "deliver", "tester"]
