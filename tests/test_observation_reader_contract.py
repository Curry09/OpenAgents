"""Spec-0092/T4: exercise the portable reader check, not a duplicate decoder."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "reader_contract", Path(__file__).resolve().parents[1] / "scripts/check_observation_reader.py"
)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


def test_offline_reader_contract():
    assert reader.check_offline() == {"status": "passed", "accepted": 3, "rejected": 4}


def test_unavailable_evidence_is_not_a_pass():
    with pytest.raises(AssertionError):
        reader.verify_scope(
            scope={"sessions": [], "context": "证据不可用"},
            expected={"sessions": []},
            digest="0" * 64,
        )


def test_execution_contract_reaches_actual_role_backend_contexts():
    result = reader.check_execution_contract(
        fixture=Path(__file__).parent / "fixtures/execution_evidence_contract.json"
    )
    assert result["backend_contexts"] == 14
    assert result["model_calls"] == 0
    assert "architect" in result["roles"] and "drafter" in result["roles"]
