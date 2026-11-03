"""Spec-0093/T3: shared wire, transport, recovery and final role-input boundaries.

These assertions observe deterministic delivery, not model understanding. The
separate real-role canary and its limits are described in docs/VERIFICATION.md.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from openagents.observations import execution_contracts

FIXTURE = Path(__file__).parent / "fixtures/execution_evidence_contract.json"


def test_mixed_sources_keep_separate_conditions_and_assessment_meanings():
    package = json.loads(FIXTURE.read_text())["package"]
    payload = execution_contracts.validate(package=package, required=True)
    by_session = {row["session_id"]: row for row in payload["execution_contracts"]}
    assert by_session["session-1"]["followup_input"] == "unavailable"
    assert by_session["session-2"]["followup_input"] == "possible"
    summaries = {row["session_id"]: row for row in payload["assessment_summaries"]}
    assert summaries["session-1"]["passed"] is False
    assert summaries["session-2"]["passed"] is None
    assert summaries["session-2"]["score"] is None
    assert set(by_session) == {row["session_id"] for row in package["sessions"]}


def test_large_source_set_has_explicit_complete_pages_not_silent_truncation():
    package = json.loads(FIXTURE.read_text())["package"]
    payload = package["execution_evidence"]
    # Projection is independently exercised at its bound; validation tests cover authority.
    template = payload["execution_contracts"][0]
    payload["execution_contracts"] = [{**template, "session_id": f"source-{n}"} for n in range(40)]
    payload["assessment_summaries"] = []
    pages = execution_contracts.pages(payload=payload)
    assert sum(len(page["contracts"]) for page in pages) == 40
    assert all(len(page["contracts"]) <= execution_contracts.PAGE_SIZE for page in pages)
    refs = [
        {"path": f"page-{n}.json", "sha256": execution_contracts.canonical_sha256(page)}
        for n, page in enumerate(pages)
    ]
    text = execution_contracts.project(payload=payload, page_refs=refs)
    assert "presentation=paginated" in text
    assert "40 contracts" in text
    assert "未覆盖全部来源" in text
    assert all(ref["path"] in text for ref in refs)


def test_private_material_is_not_a_public_reference_even_when_file_exists():
    package = json.loads(FIXTURE.read_text())["package"]
    row = package["execution_evidence"]["execution_contracts"][0]
    sid = row["session_id"]
    row["public_refs"][0]["path"] = f"{sid}/evaluation/hidden.json"
    with pytest.raises(execution_contracts.ExecutionContractUnavailable, match="path"):
        execution_contracts.validate(package=package, required=True)


def test_joint_publisher_canonical_protocol_when_checkout_supplied():
    checkout = os.environ.get("AUTO_DESIGNER_CHECKOUT")
    if not checkout:
        pytest.skip("set AUTO_DESIGNER_CHECKOUT for the explicit two-repository protocol check")
    root = Path(checkout)
    module_path = root / "backend/ahe_beta/execution_contract.py"
    spec = importlib.util.spec_from_file_location("publisher_execution_contract", module_path)
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    package = json.loads(FIXTURE.read_text())["package"]
    payload = package["execution_evidence"]
    rebuilt = publisher.build_execution_evidence(
        issue=package["issue"],
        contracts=payload["execution_contracts"],
        summaries=payload["assessment_summaries"],
    )
    assert rebuilt == payload
    assert (
        execution_contracts.validate(
            package={**package, "execution_evidence": rebuilt}, required=True
        )
        == payload
    )
