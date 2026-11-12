"""Behavior-evidence strength tests."""

import pytest

from openagents.runtime.evidence import EvidenceError, validate_manifest


def test_presence_only_evidence_cannot_pass_behavior() -> None:
    with pytest.raises(EvidenceError, match="static/grep"):
        validate_manifest(
            verdict="PASS",
            evidence=[
                {
                    "case_id": "p",
                    "kind": "static",
                    "observed": "yes",
                    "expected": "yes",
                    "path": "grep.log",
                }
            ],
        )


def test_observed_behavior_can_pass_when_prose_differs_from_expectation() -> None:
    validate_manifest(
        verdict="PASS",
        evidence=[
            {
                "case_id": "p",
                "kind": "behavior",
                "observed": "worker stopped after force_stop; test passed 3/3 runs",
                "expected": "command stops within the configured deadline",
                "path": "runtime.log",
                "passed": True,
            }
        ],
    )


def test_explicitly_failed_case_cannot_hide_under_pass_verdict() -> None:
    with pytest.raises(EvidenceError, match="Mark explicitly as not passed"):
        validate_manifest(
            verdict="PASS",
            evidence=[
                {
                    "case_id": "p",
                    "kind": "behavior",
                    "observed": "command exceeded the deadline",
                    "expected": "command stops within the configured deadline",
                    "path": "runtime.log",
                    "passed": False,
                }
            ],
        )


def test_legacy_manifest_without_passed_remains_compatible() -> None:
    validate_manifest(
        verdict="PASS",
        evidence=[
            {
                "case_id": "p",
                "kind": "behavior",
                "observed": "stopped after 30 seconds",
                "expected": "stops before the outer timeout",
                "path": "runtime.log",
            }
        ],
    )
