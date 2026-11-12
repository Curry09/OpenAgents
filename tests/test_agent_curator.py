"""Spec-0065/T1: agents.curator Phranometric - only PROMPT + OUTPUT_SCHEMA, zero logic.

curator The only ”dependant” on the access. agent: Eat ready open issue Quickshot + Border anchor → Recommendations blocked_by
Sideset. Here it is asserted that its semantic contract is Template, OUTPUT_SCHEMA is the Edges list, placeholder can delay substitute,
A border is already in place. The static anchor of ”module zero logic / no subprocess” is test_agents_prompts.py at the gram
Parameters are automatically rounded with examples (overriding all *.py, with curator.py added to this document) without touching the real LLM.
"""

from __future__ import annotations

from string import Template

from openagents.agents import curator


def test_curator_exposes_prompt_and_schema():
    assert isinstance(curator.PROMPT, Template)
    # Output is "Proposal Edges": check as list (internal structure issue/blocked_by/rationale per side by prompt)
    # The self-presentation, engine._validate only makes top-key type, with very simple schema engagements.
    assert curator.OUTPUT_SCHEMA == {"edges": list}


def test_curator_prompt_reads_dynamic_material_from_context_once():
    task = curator.PROMPT.substitute()
    assert "context" in task
    assert "$issue_snapshot" not in task
    assert "$existing_edges" not in task


def test_curator_states_existing_edges_are_context_anchor():
    anchor = '{"issue": 2, "blocked_by": [1]}'
    task = curator.PROMPT.substitute()
    assert anchor not in task
    # Prompt expressly indicates anchor discipline and fail-open, avoiding curator reordering in whole or reliance on empty.
    assert "anchors" in task
    assert "fail-open" in task.lower() or "The air." in task
