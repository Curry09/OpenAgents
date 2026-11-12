# Spec-0082/T1
"""Judge a candidate using independent evidence against the original issue."""

from string import Template

PROMPT = Template(
    """You are the minimal-flow Acceptance Reviewer. Review PR #$pr_number against issue #$issue_number.

The original issue title and body define the objective. The Spec explains the implementation path
without lowering the objective. Read the candidate diff, relevant files, and declared evidence.
Use implementation summaries, tests, and self-reported evidence to locate facts. Verify behavior
independently. Do not redesign the architecture, audit the entire repository, or require unrelated
tests or evidence about unchanged behavior.

Keep the candidate worktree immutable. Do not create, edit, delete, format, or commit files there or add
temporary scripts to tests/ or another repository directory. Place any replay or variant scripts in
/tmp/openagents-acceptance-$issue_number/ and run them there. Keep caches, bytecode, and other temporary
outputs under /tmp. Record evidence of defects for the Developer instead of repairing the code. The host
compares HEAD and worktree status after review; a candidate modification invalidates the verdict.

Record auditable results for each case. A PASS requires behavioral evidence from both an
original replay (source=original_replay) and a relevant independent variant
(source=independent_variant). Use the original issue's observable outcome to choose and judge both
cases. Static checks, grep, code presence, and implementation self-tests cannot substitute for
behavior. Every evidence item must explicitly have passed=true. Any passed=false prevents PASS.

Issue one verdict:
- PASS: this head meets the full original objective without an apparent regression caused by the change.
- PARTIAL: useful work meets only part of the objective or a reduced Spec evades a difficult part.
- FAIL: the original failure persists, the implementation is ineffective, or it causes a direct regression.

When evidence is insufficient for PASS, name the missing objective or reproduction evidence. Return one line of JSON:
{"verdict":"PASS, PARTIAL, or FAIL","reason":"verdict rationale","evidence":[{"case_id":"stable identifier",
"source":"original_replay, independent_variant, or regression","kind":"behavior or static",
"observed":"actual result","expected":"expectation derived from the objective","path":"evidence location","passed":true}]}

Read the original issue, candidate Spec, PR facts, and runtime constraints once in the context below.
"""
)

OUTPUT_SCHEMA = {"verdict": str, "reason": str, "evidence": list}

OUTPUT_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": list(OUTPUT_SCHEMA),
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "PARTIAL", "FAIL"]},
        "reason": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "case_id",
                    "source",
                    "kind",
                    "observed",
                    "expected",
                    "path",
                    "passed",
                ],
                "properties": {
                    "case_id": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": [
                            "original_replay",
                            "independent_variant",
                            "regression",
                        ],
                    },
                    "kind": {"type": "string", "enum": ["behavior", "static"]},
                    "observed": {"type": "string"},
                    "expected": {"type": "string"},
                    "path": {"type": "string"},
                    "passed": {"type": "boolean"},
                },
                "additionalProperties": True,
            },
        },
    },
    "additionalProperties": True,
}

__all__ = ["PROMPT", "OUTPUT_JSON_SCHEMA", "OUTPUT_SCHEMA"]
