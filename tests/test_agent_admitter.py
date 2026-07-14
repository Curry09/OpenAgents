"""Spec-0065/T1: agents.admitter 提示词层单测——只含 PROMPT + OUTPUT_SCHEMA、零逻辑。

admitter 是 `triage: human` 准入面唯一的 agent：读**人在准入对话里的回话** → 判「人到底点头没有」。
此处断言其语义契约（PROMPT 是 Template、占位符含 `$issue_body` / `$dialogue`、OUTPUT_SCHEMA 是
{approved: bool, reason: str}、纪律是 **fail-closed**）。「模块零逻辑 / 无 subprocess」的静态锚点由
test_agents_prompts.py 的 glob 参数化用例（覆盖 agents 目录下全部 *.py，含本文件所锚的 admitter.py）
自动兜住，不触真实 LLM。
"""

from __future__ import annotations

from string import Template

from openagents.agents import admitter


def test_admitter_exposes_prompt_and_schema():
    assert isinstance(admitter.PROMPT, Template)
    # recipes.vigil 只按 `approved` 决定打不打 `ready`、把 `reason` 原样贴给人看——两个键都是硬依赖。
    assert admitter.OUTPUT_SCHEMA == {"approved": bool, "reason": str}


def test_admitter_prompt_carries_the_dialogue_next_to_the_issue_body():
    # 两个占位符缺一不可：判据是**人说的那句话**（dialogue），而 issue 正文只是背景（人可能只说「可以」）。
    task = admitter.PROMPT.substitute(
        issue_number=5,
        issue_body="给 CLI 加个 --once",
        dialogue="- **alice**：可以，先做 CLI 那一半",
    )
    assert "给 CLI 加个 --once" in task
    assert "可以，先做 CLI 那一半" in task


def test_admitter_prompt_states_the_fail_closed_discipline():
    # 纪律与 triager（fail-open）**相反**且必须写在 prompt 里：拿不准 → approved=false。
    # 误判（人没点头却判点头）= 违背人的意愿开工、不可逆；漏判只是多等一轮。
    task = admitter.PROMPT.substitute(issue_number=5, issue_body="正文", dialogue="嗯……")
    assert "fail-closed" in task
    assert "approved=false" in task
