"""Spec-0065/T1: agents.curator 提示词层单测——只含 PROMPT + OUTPUT_SCHEMA、零逻辑。

curator 是准入面唯一「排依赖」的 agent：吃 ready open issue 快照 + 已有边锚点 → 出建议 blocked_by
边集。此处断言其语义契约（PROMPT 是 Template、OUTPUT_SCHEMA 是 edges 列表、占位符可延后 substitute、
已有边原样带入作锚点）。「模块零逻辑 / 无 subprocess」的静态锚点由 test_agents_prompts.py 的 glob
参数化用例（覆盖 agents 目录下全部 *.py，含本文件新增的 curator.py）自动兜住，不触真实 LLM。
"""

from __future__ import annotations

from string import Template

from openagents.agents import curator


def test_curator_exposes_prompt_and_schema():
    assert isinstance(curator.PROMPT, Template)
    # 输出是「建议边列表」：edges 校验为 list（每条边的内部结构 issue/blocked_by/rationale 由 prompt
    # 自述、engine._validate 只做顶层键→类型，承既有极简 schema 约定）。
    assert curator.OUTPUT_SCHEMA == {"edges": list}


def test_curator_prompt_reads_dynamic_material_from_context_once():
    task = curator.PROMPT.substitute()
    assert "上下文" in task
    assert "$issue_snapshot" not in task
    assert "$existing_edges" not in task


def test_curator_states_existing_edges_are_context_anchor():
    anchor = '{"issue": 2, "blocked_by": [1]}'
    task = curator.PROMPT.substitute()
    assert anchor not in task
    # prompt 明示锚点纪律与 fail-open，避免 curator 整张重排或凭空造依赖。
    assert "锚点" in task
    assert "fail-open" in task.lower() or "凭空" in task
