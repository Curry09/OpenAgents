"""Spec-0061/T2: agents.triager / agents.replier 提示词层单测——只含 PROMPT + OUTPUT_SCHEMA、零逻辑。

批次二两个新 agent 的契约断言（PROMPT 是 Template、OUTPUT_SCHEMA 是键→类型 dict、占位符可延后
substitute、schema 键与类型正确）。「模块零逻辑 / 无 subprocess」的静态锚点由 test_agents_prompts.py
的 glob 参数化用例（覆盖 agents 目录下全部 *.py）自动兜住，此处只补批次二 agent 的语义契约。
"""

from __future__ import annotations

from string import Template

from openagents.agents import replier, triager


def test_triager_exposes_prompt_and_schema():
    assert isinstance(triager.PROMPT, Template)
    assert triager.OUTPUT_SCHEMA == {"actionable": bool, "reason": str}


def test_replier_exposes_prompt_and_schema():
    assert isinstance(replier.PROMPT, Template)
    assert replier.OUTPUT_SCHEMA == {"reply": str, "resolved": bool}


def test_triager_prompt_placeholders_substitute():
    # Spec-0081/T1：分诊 task 只保留 issue_number，正文归 context。
    task = triager.PROMPT.substitute(issue_number=145)
    assert "145" in task
    assert "下方“上下文”区" in task


def test_replier_prompt_placeholders_substitute():
    # Spec-0081/T1：回复 task 只保留定位标量，评论正文归 context。
    task = replier.PROMPT.substitute(pr_number=154, branch="openagents/issue-145")
    assert "154" in task
    assert "openagents/issue-145" in task
    assert "下方“上下文”区" in task
