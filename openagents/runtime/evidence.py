# Spec-0076/T5
"""Validate head-bound behavioral evidence emitted by Tester.

Exports:
    EvidenceError: Invalid or insufficient evidence.
    validate_manifest: Validate evidence shape and behavioral strength.
"""


class EvidenceError(ValueError):
    """Raise when a claimed behavioral result lacks observable evidence."""


def validate_manifest(
    *, verdict: str, evidence: list, require_behavior: bool = True, required_source: str | None = None
) -> None:
    """Validate evidence items and reject presence-only or explicitly failed PASS claims.

    ``observed`` records what actually happened while ``expected`` records the
    acceptance criterion.  They are evidence, not values whose prose must be
    byte-for-byte identical.  New manifests should provide ``passed``; legacy
    manifests remain valid when the Tester has issued an overall PASS.
    """
    if verdict != "PASS":
        return
    if not evidence:
        raise EvidenceError("PASS 缺少 evidence manifest")
    required = {"case_id", "kind", "observed", "expected", "path"}
    for item in evidence:
        if not isinstance(item, dict) or not required.issubset(item):
            raise EvidenceError("evidence item 缺少 case_id/kind/observed/expected/path")
        if not all(isinstance(item[field], str) and item[field].strip() for field in required):
            raise EvidenceError(
                "evidence item 的 case_id/kind/observed/expected/path 必须是非空字符串"
            )
        passed = item.get("passed")
        if passed is not None and not isinstance(passed, bool):
            raise EvidenceError(f"case {item['case_id']} 的 passed 必须是布尔值")
        if passed is False:
            raise EvidenceError(f"case {item['case_id']} 明确标记为未通过")
    if require_behavior and not any(item.get("kind") == "behavior" for item in evidence):
        raise EvidenceError("行为变化不能仅由 static/grep 证据放行")
    if required_source is not None and not any(
        item.get("kind") == "behavior" and item.get("source") == required_source
        for item in evidence
    ):
        raise EvidenceError(f"PASS 缺少 source={required_source} 的实际行为证据")
