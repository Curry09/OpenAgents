"""Spec-0061/T2: agents.triager / agents.replier Phranometric - only PROMPT + OUTPUT_SCHEMA, zero logic.

A contract assertion for two or two batches of new agent (PROMPT is Template, OUTPUT_SCHEMA is a key type dict, placeholder can be delayed)
Substitute, schema key and type correct. The static anchor for ”module zero logic / no subprocess” is test_agents_prompts.py
, and only the semantic contracts of second-time parties are added here.
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
    # Spec-0081/T1: Only issue_number for consultation is reserved for consultation, the body is attached to the context.
    task = triager.PROMPT.substitute(issue_number=145)
    assert "145" in task
    assert "context below" in task


def test_replier_prompt_placeholders_substitute():
    # Spec-0081/T1: Answers the question only keep the cursor, comment on the body to which the text belongs.
    task = replier.PROMPT.substitute(pr_number=154, branch="openagents/issue-145")
    assert "154" in task
    assert "openagents/issue-145" in task
    assert "context below" in task
