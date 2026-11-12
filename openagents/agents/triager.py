# Spec-0061/T2
"""Decide whether an issue can be assigned without further clarification.

The prompt asks for a plain-language restatement and a check for contradictions
that would change the fix. Uncertain cases pass the admission gate. Recipes
consume only the structured verdict; the role has no scheduling logic.
"""

from string import Template

PROMPT = Template(
    """You triage issues. Decide whether issue #$issue_number is ready to assign:
1. Restate in plain language what the issue asks for, its scope, and what it explicitly excludes.
2. Check the title and body for contradictions that would change the fix (the five cases from issue #111):
   the title and body propose different fixes; the proposed fix does not address the stated root cause;
   mutually exclusive approaches are listed without a choice; the issue names problem A but fixes B;
   or a known trade-off is left undecided.

Fail open. Set actionable=false only when a real contradiction would send the implementer in the wrong
direction. Name the conflict and candidate fixes in reason so a person can resolve it. Otherwise set
actionable=true, including when uncertain or when an issue is rough but its direction is clear. Let the
implementer fill in ordinary details while reading the Spec.

Return one line of JSON with a boolean actionable and a string reason containing your restatement and decision rationale.
The runtime supplies the issue title and body once in the context below.
"""
)

OUTPUT_SCHEMA = {"actionable": bool, "reason": str}
