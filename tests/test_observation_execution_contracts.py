"""Spec-0093/T1: validate source authority and result meaning before exposing context."""

import copy
import hashlib
import json

import pytest

from openagents.observations import evidence
from openagents.observations import execution_contracts as contracts


def sample_package(*, followup="unavailable", status="completed", passed=False):
    text = "Implement the original public objective; output result.txt."
    file_hash = hashlib.sha256(text.encode()).hexdigest()
    files = {"goal.md": text}
    files["manifest.json"] = json.dumps(
        {"session_id": "session-1", "files": [{"path": "goal.md", "sha256": file_hash}]}
    )
    declaration = {
        "session_id": "session-1",
        "task_id": "task-1",
        "task_digest": "1" * 64,
        "followup_input": followup,
        "task_budget_seconds": 7200,
        "budget_source": "task_metadata",
        "public_refs": [{"kind": "goal", "path": "session-1/goal.md", "sha256": file_hash}],
    }
    declaration["contract_id"] = contracts.canonical_sha256(declaration)
    summary = {
        "receipt_id": "assessment-1",
        "session_id": "session-1",
        "contract_id": declaration["contract_id"],
        "status": status,
        "passed": passed,
        "score": None,
        "metric_definition": None,
        "assessment_kind": "independent",
        "source_sha256": "2" * 64,
    }
    payload = {
        "schema_version": 1,
        "issue": 7,
        "execution_contracts": [declaration],
        "assessment_summaries": [summary],
    }
    payload["payload_sha256"] = contracts.canonical_sha256(payload)
    return {
        "format": evidence.MARKER,
        "issue": 7,
        "sessions": [{"session_id": "session-1", "status": "available", "files": files}],
        "execution_evidence": payload,
    }


def rehash(*, package):
    payload = package["execution_evidence"]
    for contract in payload["execution_contracts"]:
        old = contract["contract_id"]
        contract["contract_id"] = contracts.canonical_sha256(
            {k: v for k, v in contract.items() if k != "contract_id"}
        )
        for summary in payload["assessment_summaries"]:
            if summary["contract_id"] == old:
                summary["contract_id"] = contract["contract_id"]
    payload["payload_sha256"] = contracts.canonical_sha256(
        {k: v for k, v in payload.items() if k != "payload_sha256"}
    )


def test_public_conditions_are_projected_without_guessing_a_pass():
    package = sample_package()
    payload = contracts.validate(package=package, required=True)
    context = contracts.project(
        payload=payload, page_refs=[{"path": "execution-page-1.json", "sha256": "3" * 64}]
    )
    assert "followup_input=unavailable" in context
    assert "budget_seconds=7200" in context
    assert "passed=False" in context
    assert "assessment-1" in context
    assert (
        contracts.pages(payload=payload)[0]["contracts"][0]["public_refs"][0]["path"]
        == "session-1/goal.md"
    )


@pytest.mark.parametrize("status", ["unavailable", "ungradable", "not_configured", "timed_out"])
def test_missing_measurement_preserves_null(status):
    package = sample_package(status=status, passed=None)
    assert (
        contracts.validate(package=package, required=True)["assessment_summaries"][0]["passed"]
        is None
    )


def test_optional_absent_contract_is_an_ordinary_issue():
    package = sample_package()
    del package["execution_evidence"]
    assert contracts.validate(package=package, required=False) is None
    with pytest.raises(contracts.ExecutionContractUnavailable, match="missing"):
        contracts.validate(package=package, required=True)


@pytest.mark.parametrize(
    "corruption",
    [
        "unknown-version",
        "wrong-issue",
        "foreign-session",
        "empty",
        "missing-field",
        "fake-digest",
        "private-path",
        "false-file",
        "foreign-summary",
        "metric-secret",
    ],
)
def test_forged_or_incomplete_contracts_are_rejected(corruption):
    package = sample_package()
    payload = package["execution_evidence"]
    contract = payload["execution_contracts"][0]
    if corruption == "unknown-version":
        payload["schema_version"] = 99
    elif corruption == "wrong-issue":
        payload["issue"] = 8
    elif corruption == "foreign-session":
        contract["session_id"] = "someone-else"
    elif corruption == "empty":
        payload["execution_contracts"] = []
        payload["assessment_summaries"] = []
    elif corruption == "missing-field":
        del contract["followup_input"]
    elif corruption == "fake-digest":
        payload["payload_sha256"] = "0" * 64
    elif corruption == "private-path":
        contract["public_refs"][0]["path"] = "../private/grader.json"
    elif corruption == "false-file":
        contract["public_refs"][0]["sha256"] = "0" * 64
    elif corruption == "foreign-summary":
        payload["assessment_summaries"][0]["session_id"] = "someone-else"
    elif corruption == "metric-secret":
        payload["assessment_summaries"][0]["metric_definition"] = {"private_plan": "secret"}
    if corruption != "fake-digest":
        rehash(package=package)
    with pytest.raises(contracts.ExecutionContractUnavailable):
        contracts.validate(package=package, required=True)


def test_conflicting_receipts_cannot_be_deduplicated_silently():
    package = sample_package()
    duplicate = copy.deepcopy(package["execution_evidence"]["assessment_summaries"][0])
    duplicate["passed"] = True
    package["execution_evidence"]["assessment_summaries"].append(duplicate)
    rehash(package=package)
    with pytest.raises(contracts.ExecutionContractUnavailable, match="conflicting"):
        contracts.validate(package=package, required=True)


def test_nonfinite_scores_are_rejected_before_canonicalization():
    package = sample_package()
    package["execution_evidence"]["assessment_summaries"][0]["score"] = float("inf")
    with pytest.raises(contracts.ExecutionContractUnavailable, match="score"):
        contracts.validate(package=package, required=True)
