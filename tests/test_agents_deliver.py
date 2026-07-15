"""Spec-0066/T1: deliver agent 承接「PR 转正」职责的提示词契约单测（不触真实 gh/LLM）。

deliver push 完代码后顺手 `gh pr ready`，其完成判据从「push 到 head」扩为「push 到 head 且 PR 非 draft」。
OUTPUT_SCHEMA 不变（零控制流改动）。
"""

from __future__ import annotations

from string import Template

from openagents.agents import deliver


def test_prompt_is_template_and_substitutes():
    assert isinstance(deliver.PROMPT, Template)
    text = deliver.PROMPT.substitute(branch="openagents/issue-1", pr_number=42)
    assert isinstance(text, str)


def test_prompt_contains_gh_pr_ready():
    # Spec-0066/T1: 转正动作写进 deliver 职责——push 之后 `gh pr ready $pr_number`。
    text = deliver.PROMPT.substitute(branch="openagents/issue-1", pr_number=42)
    assert "gh pr ready 42" in text


def test_prompt_completion_criterion_requires_non_draft():
    # 完成判据扩为「push 到 head 且 PR 非 draft」——提示词里要显式出现「非 draft」这条判据。
    text = deliver.PROMPT.substitute(branch="openagents/issue-1", pr_number=42)
    assert "非 draft" in text


def test_output_schema_unchanged():
    # OUTPUT_SCHEMA 保持 {delivered, base_sha, head_sha, summary}（转正不改结构化输出）。
    assert deliver.OUTPUT_SCHEMA == {
        "delivered": bool,
        "base_sha": str,
        "head_sha": str,
        "summary": str,
    }
