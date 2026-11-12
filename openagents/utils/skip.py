# Spec-0054/T1
"""Resolve one-run stage overrides passed to vigil --skip."""

from __future__ import annotations

from dataclasses import dataclass

# Spec-0054/T1: Five legal CLI accessible gates token + all - single point definition, analysis and misreporting information sharing,
# No more literally drifting. No "merge": integration cannot skip.
_GATE_ISSUE = "issue"
_GATE_SPEC = "spec"
_GATE_CODE = "code"
_GATE_CI = "ci"
_GATE_EVIDENCE = "evidence"
_GATE_ALL = "all"
_VALID_GATES = (_GATE_ISSUE, _GATE_SPEC, _GATE_CODE, _GATE_CI, _GATE_EVIDENCE, _GATE_ALL)


@dataclass(frozen=True)
class Skip:
    """Hold per-stage skips for one invocation (Spec-0054/T1)."""

    at_issue: bool = False
    at_spec: bool = False
    at_code: bool = False
    at_ci: bool = False
    at_evidence: bool = False


# Spec-0054/T1: "No Usage" default example - used when --skip is not available, is equal to the vigil behaviour that is now open on the full gate.
NONE = Skip()


def parse_skip(*, raw: str | None) -> Skip:
    """Spec-0054/T1: resolve the original --skip string to Skip.

    Empty string / None  →  Default Skip (All False, All Gate Open); commas separated issue / spec / code / c/
    ivence (forlerating extra spaces and casecases) corresponds to the boolean slot; `all` Z5-row; unknown token
    Invalid ’merge’) poachs ValueError and lists the valid values.
    """
    if raw is None:
        return NONE
    tokens = [token.strip().lower() for token in raw.split(",") if token.strip()]
    if not tokens:
        return NONE
    at_issue = False
    at_spec = False
    at_code = False
    at_ci = False
    at_evidence = False
    for token in tokens:
        if token == _GATE_ALL:
            at_issue = at_spec = at_code = at_ci = at_evidence = True
        elif token == _GATE_ISSUE:
            at_issue = True
        elif token == _GATE_SPEC:
            at_spec = True
        elif token == _GATE_CODE:
            at_code = True
        elif token == _GATE_CI:
            at_ci = True
        elif token == _GATE_EVIDENCE:
            at_evidence = True
        else:
            valid = " / ".join(_VALID_GATES)
            raise ValueError(f"Unknown --skip gate {token!r}; valid gates: {valid}")
    return Skip(
        at_issue=at_issue,
        at_spec=at_spec,
        at_code=at_code,
        at_ci=at_ci,
        at_evidence=at_evidence,
    )
