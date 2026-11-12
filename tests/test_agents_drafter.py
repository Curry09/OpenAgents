"""Spec-0062/T1: agents.drafter Phranometric - Only PROMPT+OUTPUT_SCHEMA, zero logic.

Draffer single agent with five drafting judgments (draft/backfill/refine/implement/iterate) for the RFC life cycle, using the same
Template skeleton + `$mode` placeholder split. Here you assert that your contract (PROMPT) is the correct type of Template, schema key, five Mode
Placeholder can delay substitute and make a static anchor point for ”module zero dev / zero subprocess” (with test_agents_prompts.py)
The Global Voices website uses examples of cases that are redundant and locks to death in ant, not Python.
"""

from __future__ import annotations

import ast
from pathlib import Path
from string import Template

from openagents.agents import drafter


def test_drafter_exposes_prompt_and_schema():
    assert isinstance(drafter.PROMPT, Template)
    assert drafter.OUTPUT_SCHEMA == {"delivered": bool, "head_sha": str, "summary": str}


def test_drafter_prompt_substitutes_for_every_mode():
    # Five Mode returns the same placeholder set (mode/target/branch/detail) - each mode can fill and not throw.
    for mode in ("draft", "backfill", "refine", "implement", "iterate"):
        task = drafter.PROMPT.substitute(
            mode=mode, target="issue #145「t」", branch="openagents/issue-145"
        )
        assert mode in task
        assert "openagents/issue-145" in task
        assert "context below" in task


def test_drafter_module_has_no_logic():
    # Z0 Logical Static anchor: The top layer of the module allows only the import + PROMPT/OUTPUT_SCHEMA/__all__ grant and prohibits any function/class definition.
    path = Path(drafter.__file__)
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        assert not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)), (
            f"Drager contains logical definitions {type(node).__name__}(AGENT RUMBLING Zero-SCIENTIZING)"
        )
    # Disable subproces (Strengthed IO anchor; text, non-calling git/gh in prompt).
    assert "import subprocess" not in src
    assert "subprocess." not in src
