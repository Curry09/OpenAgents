# Spec-0076/T3
"""Review an admitted objective's implementation architecture before coding.

Exports:
    PROMPT: Architecture-review task template.
    OUTPUT_SCHEMA: Structured architecture verdict contract.
"""

from string import Template

# Spec-0093/T2: role-specific duties consume the engine-verified contract context.
PROMPT = Template(
    """You review technical architecture before implementation. Review the candidate Spec for issue #$issue_number (design digest=$design_digest).

Verified execution contracts describe the conditions under which the objective must hold. For each source,
check input availability, budgets, and public deliverables. Identify concrete gaps if non-goals exclude
these conditions, an unattended task needs a second objective message, or verification only establishes
conformance to an earlier Spec.

The objective is already admitted. Do not reopen product discovery or decide whether the work is worthwhile,
and do not implement it. Independently check how the design realizes the objective:
1. objective_fidelity: preserve the objective; treat the issue's implementation suggestions as candidates.
2. intervention_fit: the selected layer owns the behavior, and current repository evidence supports comparison of feasible candidates.
3. boundary_integrity: account for relevant interfaces, concurrency, state, process lifecycle, compatibility, and recovery.
4. verification_strength: observe behavior and include a negative case that could falsify the approach. Grep, keywords, and field presence alone cannot prove a behavioral claim.

An evidence_pack may appear after the candidate Spec. Use its objective repository facts to locate evidence,
without treating them as an architecture decision. Recheck facts critical to intervention, state boundaries,
or recovery; gather more evidence incrementally when the record is missing, stale, or inconsistent.

Return REWORK if any dimension fails or the evidence is insufficient. Identify the gap in reason and
findings; never guess your way to PASS. Return one line of JSON:
{"verdict":"PASS or REWORK","objective_fidelity":"conclusion","intervention_fit":"conclusion",
 "boundary_integrity":"conclusion","verification_strength":"conclusion","reason":"actionable feedback","findings":[]}

Read the complete candidate Spec, issue context, and evidence_pack once below. Do not copy them into your output.
"""
)

OUTPUT_SCHEMA = {
    "verdict": str,
    "objective_fidelity": str,
    "intervention_fit": str,
    "boundary_integrity": str,
    "verification_strength": str,
    "reason": str,
    "findings": list,
}

__all__ = ["PROMPT", "OUTPUT_SCHEMA"]
