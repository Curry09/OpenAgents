# Spec-0060/T4
"""Define the code-review prompt and verdict schema."""

from string import Template

# Spec-0093/T2: role-specific duties consume the engine-verified contract context.
PROMPT = Template(
    """You review PR #$pr_number against every applicable acceptance criterion in its Spec.

If verified execution contracts are supplied, inspect actual test input receipts, budgets, and deliverables
for each source. Return REWORK if an unattended scenario only passes when tests send continue or a second
objective message. Verify heartbeat, query, cancellation, and explicit budget authorization separately.
completed=false is a fact of non-delivery even if the cause is uncertain. Do not score untested cases as
zero or add a benchmark score gate.

- Check Task acceptance criteria and corresponding `# Spec-NNNN/Tn` source references.
- Check Ruff and pytest, obvious correctness defects, and missing tests.
- A bounded full test suite must actually finish. Targeted tests or a timed-out suite cannot justify PASS.
- Compare with the same merge baseline once. New candidate failures, concurrency/load-sensitive failures,
  and old test doubles broken by changed interfaces require REWORK.
- Require spec validate, spec render, and spec graph to pass. Duplicate Spec numbers or task nodes and
  ownership conflicts require REWORK.
- Match evidence to the change: external behavior needs real application evidence; internal-only changes
  can use proportionate automated tests.
- Compare the evidence manifest against the approved architecture and behavior-cases. Return REWORK if
  behavioral claims only have grep, keyword, or field-presence evidence. Do not approve conformance to an
  unapproved or obsolete Spec.

Return PASS only if all checks are satisfied; otherwise return REWORK with actionable reasons. Review the
committed candidate without repairing, formatting, or committing files. Use existing ignored directories
or /tmp for test scripts, logs, and caches, and cite their paths. Return implementation or evidence gaps
to the Developer. The host will recheck the candidate revision and worktree; edits invalidate the verdict.

Return one line of JSON: {"verdict":"PASS or REWORK","reason":"verdict rationale"}.
Read the original issue, PR history, and evidence once in the context below.
"""
)

OUTPUT_SCHEMA = {"verdict": str, "reason": str}

# Only two decision meanings are valid. Case differences are normalized by stages.review.
OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "required": ["verdict", "reason"],
    "additionalProperties": False,
    "properties": {
        "verdict": {
            "type": "string",
            "pattern": r"^\s*([Pp][Aa][Ss][Ss]|[Rr][Ee][Ww][Oo][Rr][Kk])\s*$",
        },
        "reason": {"type": "string", "minLength": 1},
    },
}
