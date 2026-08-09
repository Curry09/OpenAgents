"""Spec-0017/T3: merger agent 提示词契约单测（零逻辑 Template，不触真实 gh/LLM）。

merger 只在确定性硬闸 `gates.assert_merge_allowed` 放行后被派上来落合并动作，带 needs-human 一等出口。
Spec-0074/T1：平台命令参数化——提示词不再硬编码 gh，$merge_command/$verify_command 由 stages.merge
按当前 forge 注入。
"""

from __future__ import annotations

from string import Template

from openagents.agents import merger

_KW = {
    "pr_number": 42,
    "merge_command": "gh pr merge 42 --merge",
    "verify_command": "gh pr view 42 --json state",
}


def test_prompt_is_template_and_substitutes():
    assert isinstance(merger.PROMPT, Template)
    assert isinstance(merger.PROMPT.substitute(**_KW), str)


def test_prompt_parametrizes_platform_commands():
    # Spec-0074/T1: 落合并/验证动作按注入的平台命令执行（github=gh 原命令，gitea=openagents merge-pr）。
    text = merger.PROMPT.substitute(**_KW)
    assert "gh pr merge 42 --merge" in text
    assert "gh pr view 42 --json state" in text


def test_prompt_has_no_hardcoded_gh():
    # Spec-0074/T1: 模板本体不再含 gh 字面量——平台命令只经占位符进来。
    assert "gh pr merge" not in merger.PROMPT.template
    assert "gh pr view" not in merger.PROMPT.template


def test_prompt_has_structured_needs_human_exit():
    # Spec-0075/T3: 一等出口只报告控制意图，不直接修改 forge。
    text = merger.PROMPT.substitute(**_KW)
    assert '"needs_human": true' in text
    assert "不要自行修改 forge 标签" in text


def test_output_schema_is_merged_and_summary():
    assert merger.OUTPUT_SCHEMA == {"merged": bool, "summary": str}
