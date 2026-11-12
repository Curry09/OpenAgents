"""Spec-0017/T1 (Spec-0074 Empirical Adjustment): Deliver agent Phranometric Contract Single (without touching the real gh/LLM).

Spec-0074 returns deliver to pure git function: hint no longer contains any platform command (formerly `gh pr ready` in Gitea forge)
Unusable, induce agent to strung RET; draft is returning the machine underside branch (mark_ready passed) of the Vigil
Forge Platforms Landing. OUTPUT_SCHEMA remains the same.
"""

from __future__ import annotations

from string import Template

from openagents.agents import deliver


def test_prompt_is_template_and_substitutes():
    assert isinstance(deliver.PROMPT, Template)
    text = deliver.PROMPT.substitute(branch="openagents/issue-1", rebase_onto="main", pr_number=42)
    assert isinstance(text, str)


def test_prompt_has_no_platform_commands():
    # Spec-0074 empirical restoration: Transcript to the Vigil machine — the hint no longer contains gh/ platform API call (pure git duty).
    assert "gh pr ready" not in deliver.PROMPT.template
    assert "gh " not in deliver.PROMPT.template


def test_prompt_tells_agent_ready_is_not_its_job():
    # The "returning" message is "not yours" -- otherwise agent will follow the old custom of going to the site to find a platform order (the air-turning source of the production of the results).
    text = deliver.PROMPT.substitute(branch="openagents/issue-1", rebase_onto="main", pr_number=42)
    assert "Vigil handles draft promotion" in text


def test_prompt_requires_generated_spec_integrity_before_push():
    text = deliver.PROMPT.substitute(branch="openagents/issue-1", rebase_onto="main", pr_number=42)
    assert text.index("spec validate") < text.index("spec render") < text.index("spec graph")
    assert text.index("spec graph") < text.index("git push")
    assert "Do not handwrite generated files" in text


def test_output_schema_unchanged():
    # OUTPUT_SCHEMA maintains {delivered, base_sha, head_sha, summary} (transformation or not).
    assert deliver.OUTPUT_SCHEMA == {
        "delivered": bool,
        "base_sha": str,
        "head_sha": str,
        "summary": str,
    }
