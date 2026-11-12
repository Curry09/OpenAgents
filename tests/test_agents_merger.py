"""Spec-0017/T3: Memer ant-word contract single (zero logic Template, untouched for real gh/LLM).

The merger was sent up and down to merge after the release of the sexual hard-hand gate `gates.assert_merge_allowed`, with a first-class exit of needs-human.
Spec-0074/T1: Argumentation of Platform Commands - no more hard-coding of hints gh, $merge_command/ $verify_command by stages.merge
Press current forge injection.
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
    # Spec-0074/T1: Drop consolidation/validation action by the injection Platform command (github=gh original command, gitea=openagents merge-pr).
    text = merger.PROMPT.substitute(**_KW)
    assert "gh pr merge 42 --merge" in text
    assert "gh pr view 42 --json state" in text


def test_prompt_has_no_hardcoded_gh():
    # Spec-0074/T1: Templates are no longer gh-text-based - Platform commands are only entered by placeholders.
    assert "gh pr merge" not in merger.PROMPT.template
    assert "gh pr view" not in merger.PROMPT.template


def test_prompt_reports_failure_in_role_schema():
    text = merger.PROMPT.substitute(**_KW)
    assert '"merged":false' in text
    assert "change forge labels" in text


def test_output_schema_is_merged_and_summary():
    assert merger.OUTPUT_SCHEMA == {"merged": bool, "summary": str}
