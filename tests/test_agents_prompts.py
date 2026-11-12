"""Spec-0060/T4: angents prompt word layer symmetry - only PROMPT (Template) + OUTPUT_SCHEMA (dict), zero logic.

Yes 5 agent modules assert the contract by one; and do ”source no def / no subproces gh git call” static anchor
(with e2e script grep, locking to death ”attent, logic is not Python”)
"""

from __future__ import annotations

import ast
from pathlib import Path
from string import Template

import pytest

from openagents import agents
from openagents.agents import (
    acceptance,
    deliver,
    drafter,
    executor,
    implementer,
    replier,
    reviewer,
    spec_writer,
    tester,
    triager,
)

# Spec-0064/T6: planner has been merged into the daFFter and has now been identified as the actual agent collection (drafter/triager/replier to add).
_MODULES = [
    drafter,
    spec_writer,
    executor,
    implementer,
    acceptance,
    reviewer,
    deliver,
    tester,
    triager,
    replier,
]
_AGENTS_DIR = Path(agents.__file__).parent


@pytest.mark.parametrize("module", _MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_module_exposes_prompt_and_schema(module):
    assert isinstance(module.PROMPT, Template)
    assert isinstance(module.OUTPUT_SCHEMA, dict)
    # OUTPUT_SCHEMA is a key-type Python map.
    assert all(isinstance(v, type) for v in module.OUTPUT_SCHEMA.values())


def test_reviewer_schema_has_verdict_and_reason():
    assert reviewer.OUTPUT_SCHEMA == {"verdict": str, "reason": str}


def test_deliver_schema_reports_base_sha():
    # Recipe feeds base_sha with DIliver, assert_head_advanced, which must be in the schema.
    assert "base_sha" in deliver.OUTPUT_SCHEMA
    assert deliver.OUTPUT_SCHEMA["delivered"] is bool


@pytest.mark.parametrize(
    "path", sorted(p for p in _AGENTS_DIR.glob("*.py") if p.name != "__init__.py")
)
def test_prompt_module_has_no_logic(path):
    # Z0 Logical Static anchor: The top layer of the module allows only the import + PROMPT/OUTPUT_SCHEMA grant and prohibits any function/class definition.
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        assert not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)), (
            f"{path.name} Include logical definition {type(node).__name__}(AGENT RUMBLING Zero-SCIENTIZING)"
        )
    # Bans the effect subprocess (the stronger IO anchor; the git/gh word in the prompt string is a script, not a call).
    src = path.read_text(encoding="utf-8")
    assert "import subprocess" not in src
    assert "subprocess." not in src


def test_prompt_placeholders_substitute():
    # Template can be delayed by substitute (all placeholders are not dropped), to verify the prompt string form.
    reviewer.PROMPT.substitute(pr_number=1, issue_body="x")
    deliver.PROMPT.substitute(branch="openagents/issue-1", rebase_onto="main", pr_number=1)
    drafter.PROMPT.substitute(mode="draft", target="issue #1", branch="b", detail="d")
    implementer.PROMPT.substitute(issue_number=1, pr_number=1, feedback="")
    executor.PROMPT.substitute(issue_number=1, pr_number=1)
    tester.PROMPT.substitute(pr_number=1, issue_body="x")
    spec_writer.PROMPT.substitute(issue_number=1, branch="b", mode="AUTHOR")
    acceptance.PROMPT.substitute(issue_number=1, pr_number=1)


def test_minimal_roles_keep_original_issue_as_authority():
    assert "original issue" in spec_writer.PROMPT.template
    assert "preserves the original" in spec_writer.PROMPT.template
    assert "causal chain" in spec_writer.PROMPT.template
    assert "PARTIAL" in spec_writer.PROMPT.template
    assert "Do not use PARTIAL just because future" in spec_writer.PROMPT.template
    assert "Developer implements it and Acceptance checks behavior" in spec_writer.PROMPT.template
    assert "head_sha" not in spec_writer.OUTPUT_SCHEMA
    assert "independent, falsifiable" in spec_writer.PROMPT.template
    assert "PARTIAL" in acceptance.PROMPT.template
    assert acceptance.OUTPUT_SCHEMA == {"verdict": str, "reason": str, "evidence": list}
    assert "only writable worktree" in spec_writer.PROMPT.template
    assert "Inspect the loaded NexAU and other runtime" in spec_writer.PROMPT.template
    assert "No file, line, or tool-call quota" in spec_writer.PROMPT.template
    assert "Do not modify" in spec_writer.PROMPT.template
    assert "delivery" in spec_writer.PROMPT.template
    assert "control_effect" in spec_writer.PROMPT.template
    assert "evidence_level" in spec_writer.PROMPT.template
    assert "same evidentiary standard" in spec_writer.PROMPT.template
    assert "does not prove reachability" in spec_writer.PROMPT.template
    assert "Do not use the spec CLI" in spec_writer.PROMPT.template
    assert "docs/objectives/issue-$issue_number.md" in spec_writer.PROMPT.template
    assert "candidate_assessments" in spec_writer.OUTPUT_SCHEMA
    assert "intervention_candidates" not in spec_writer.OUTPUT_SCHEMA
    assert "Explain why change is necessary" in spec_writer.PROMPT.template
    assert "Leave the concrete" in spec_writer.PROMPT.template
    assert "class or function names" in spec_writer.PROMPT.template
    assert "control semantics at most" in spec_writer.PROMPT.template
    assert "Do not prescribe" in spec_writer.PROMPT.template
    assert "Name the choices left to the" in spec_writer.PROMPT.template
    assert "The Developer owns the concrete design" in spec_writer.PROMPT.template
    assert "Check and deliver" in spec_writer.PROMPT.template
    assert "DELIVERY_REPAIR" in spec_writer.PROMPT.template
    assert "CONTRACT_REPAIR" in spec_writer.PROMPT.template
    assert "scope_coverage=FULL and evidence_level=HYPOTHESIS" in spec_writer.PROMPT.template
    assert "Do not explore the repository again" in spec_writer.PROMPT.template
    assert "A draft" in spec_writer.PROMPT.template
    assert "estimated coordination surface" in spec_writer.PROMPT.template
    assert "source=original_replay" in acceptance.PROMPT.template
    assert "source=independent_variant" in acceptance.PROMPT.template
    assert "Any passed=false prevents PASS" in acceptance.PROMPT.template
    assert "Keep the candidate worktree immutable" in acceptance.PROMPT.template
    assert "/tmp/openagents-acceptance-$issue_number/" in acceptance.PROMPT.template
    assert "a candidate modification invalidates the verdict" in acceptance.PROMPT.template


def test_spec_writer_contract_does_not_embed_case_specific_answers():
    prompt = spec_writer.PROMPT.template
    leaked_phrases = (
        "First time",
        "Stop X",
        "After",
        "prompt-only",
        "heartbeat",
        "tool wrapper",
    )
    assert all(phrase not in prompt for phrase in leaked_phrases)


def test_generate_only_executor_is_constrained_and_does_not_validate():
    assert "compact objective Spec" in executor.PROMPT.template
    assert "do not run Ruff" in executor.PROMPT.template
    assert "Do not change forge labels" in executor.PROMPT.template
    assert executor.OUTPUT_SCHEMA["head_sha"] is str
