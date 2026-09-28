"""Spec-0017/T1（Spec-0074 实证修复调整）: deliver agent 提示词契约单测（不触真实 gh/LLM）。

Spec-0074 后 deliver 回归纯 git 职责：提示词不再含任何平台命令（原 `gh pr ready` 在 Gitea forge
下不可用，诱发 agent 临场拼 REST 空转）；draft 转正收回守夜判定表的机械兜底分支（mark_ready 经
forge 各平台落地）。OUTPUT_SCHEMA 不变。
"""

from __future__ import annotations

from string import Template

from openagents.agents import deliver


def test_prompt_is_template_and_substitutes():
    assert isinstance(deliver.PROMPT, Template)
    text = deliver.PROMPT.substitute(branch="openagents/issue-1", rebase_onto="main", pr_number=42)
    assert isinstance(text, str)


def test_prompt_has_no_platform_commands():
    # Spec-0074 实证修复：转正归守夜机械兜底——提示词不再含 gh/平台 API 调用（纯 git 职责）。
    assert "gh pr ready" not in deliver.PROMPT.template
    assert "gh " not in deliver.PROMPT.template


def test_prompt_tells_agent_ready_is_not_its_job():
    # 显式告知「转正不归你」——否则 agent 会按旧习惯临场找平台命令补转正（生产实测的空转来源）。
    text = deliver.PROMPT.substitute(branch="openagents/issue-1", rebase_onto="main", pr_number=42)
    assert "不归你" in text


def test_prompt_requires_generated_spec_integrity_before_push():
    text = deliver.PROMPT.substitute(branch="openagents/issue-1", rebase_onto="main", pr_number=42)
    assert text.index("spec validate") < text.index("spec render") < text.index("spec graph")
    assert text.index("spec graph") < text.index("git push")
    assert "不得手工猜测或拼接生成文档" in text


def test_output_schema_unchanged():
    # OUTPUT_SCHEMA 保持 {delivered, base_sha, head_sha, summary}（转正不改结构化输出）。
    assert deliver.OUTPUT_SCHEMA == {
        "delivered": bool,
        "base_sha": str,
        "head_sha": str,
        "summary": str,
    }
