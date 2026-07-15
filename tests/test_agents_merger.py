"""Spec-0066/T3: merger agent 提示词契约单测（零逻辑 Template，不触真实 gh/LLM）。

merger 只在确定性硬闸 `gates.assert_merge_allowed` 放行后被派上来落 `gh pr merge`，带 needs-human 一等出口。
"""

from __future__ import annotations

from string import Template

from openagents.agents import merger


def test_prompt_is_template_and_substitutes():
    assert isinstance(merger.PROMPT, Template)
    assert isinstance(merger.PROMPT.substitute(pr_number=42), str)


def test_prompt_contains_gh_pr_merge():
    # Spec-0066/T3: 落合并动作 `gh pr merge $pr_number`。
    text = merger.PROMPT.substitute(pr_number=42)
    assert "gh pr merge 42" in text


def test_prompt_has_needs_human_exit():
    # Spec-0066/T3: 一等出口——察觉硬闸没覆盖的异常时主动打 needs-human，绝不硬合。
    text = merger.PROMPT.substitute(pr_number=42)
    assert "needs-human" in text


def test_output_schema_is_merged_and_summary():
    assert merger.OUTPUT_SCHEMA == {"merged": bool, "summary": str}
