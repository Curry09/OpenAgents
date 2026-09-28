"""Spec-0054/T1: --skip 配置模型 skip 的单元测试（纯函数，无 I/O）。

覆盖：空/None → 默认全不关；单闸 / 多闸 / all 的布尔置位；未知 token（含已不合法的
'merge'）抛 ValueError 且信息列出合法值；多余空格 / 大小写归一化；Skip 为不可变值对象；
"""

import dataclasses

import pytest

from openagents.utils.skip import NONE, Skip, parse_skip


def test_empty_and_none_default_to_no_skip():
    assert parse_skip(raw=None) == NONE
    assert parse_skip(raw="") == NONE
    # 默认全不关：五道闸都不跳（等价现状全闸开启的 vigil）。
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
    # 报错信息列出合法取值，含 all，不含 merge。
    assert "all" in message
    assert "issue" in message and "evidence" in message


def test_merge_is_not_a_valid_skip_token():
    # merge 是不可跳过的动作 → 未知 token 报错（防止悄悄放行合并语义）。
    with pytest.raises(ValueError) as exc:
        parse_skip(raw="merge")
    assert "merge" in str(exc.value)


def test_skip_is_frozen_value_object():
    skip = parse_skip(raw="spec")
    assert dataclasses.is_dataclass(skip)
    with pytest.raises(dataclasses.FrozenInstanceError):
        skip.at_spec = False  # type: ignore[misc]
