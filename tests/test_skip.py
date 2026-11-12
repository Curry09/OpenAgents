"""Spec-0054/T1: Unit test for --skip configuration model sskip (sole function, no I/O).

Overwrite: empty/None  →  Default All Off; Booleaning of Single / Multiple / All; unknown token (includes invalid)
’merge’) throws ValueError and the information lists the valid values; excess spaces/ case-in-cases are standardized; Skip is a non-variable object;
"""

import dataclasses

import pytest

from openagents.utils.skip import NONE, Skip, parse_skip


def test_empty_and_none_default_to_no_skip():
    assert parse_skip(raw=None) == NONE
    assert parse_skip(raw="") == NONE
    # The default is not closed: five gates are not jumped (the current price is all open for the vigil).
    default = parse_skip(raw=None)
    assert (
        default.at_issue
        or default.at_spec
        or default.at_code
        or default.at_ci
        or default.at_evidence
    ) is False


def test_single_gate_tokens():
    assert parse_skip(raw="issue").at_issue is True
    assert parse_skip(raw="spec").at_spec is True
    assert parse_skip(raw="code").at_code is True
    assert parse_skip(raw="ci").at_ci is True
    assert parse_skip(raw="evidence").at_evidence is True


def test_multiple_gates_set_each():
    skip = parse_skip(raw="spec,ci")
    assert skip == Skip(at_spec=True, at_ci=True)


def test_all_sets_every_gate():
    assert parse_skip(raw="all") == Skip(
        at_issue=True, at_spec=True, at_code=True, at_ci=True, at_evidence=True
    )


def test_whitespace_and_case_normalized():
    assert parse_skip(raw=" SPEC , Ci ") == Skip(at_spec=True, at_ci=True)


def test_unknown_token_raises_with_valid_values_listed():
    with pytest.raises(ValueError) as exc:
        parse_skip(raw="spc")
    message = str(exc.value)
    assert "spc" in message
    # Error message lists the valid take-off values, which contain all, excluding merge.
    assert "all" in message
    assert "issue" in message and "evidence" in message


def test_merge_is_not_a_valid_skip_token():
    # MERGE is an inert action  →  unknown token to report errors (preventing the silent release of the merge semantic).
    with pytest.raises(ValueError) as exc:
        parse_skip(raw="merge")
    assert "merge" in str(exc.value)


def test_skip_is_frozen_value_object():
    skip = parse_skip(raw="spec")
    assert dataclasses.is_dataclass(skip)
    with pytest.raises(dataclasses.FrozenInstanceError):
        skip.at_spec = False  # type: ignore[misc]
