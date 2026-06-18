"""Spec-0020/T2: --hold 配置模型 hold 的单元测试（纯函数，无 I/O）。

覆盖：空/None → 默认全不停；spec / merge / spec,merge / merge,spec 的布尔置位；未知 token
抛 ValueError 且信息列出合法值；多余空格 / 大小写归一化；Hold 为不可变值对象。
"""

import dataclasses

import pytest

from openagents.hold import NONE, Hold, parse_hold


def test_empty_and_none_default_to_no_hold():
    assert parse_hold(raw=None) == NONE
    assert parse_hold(raw="") == NONE
    # 默认全不停：两道闸都不停（等价现状全自动 vigil）。
    assert parse_hold(raw=None).at_spec is False
    assert parse_hold(raw=None).at_merge is False


def test_spec_only():
    hold = parse_hold(raw="spec")
    assert hold.at_spec is True
    assert hold.at_merge is False


def test_merge_only():
    hold = parse_hold(raw="merge")
    assert hold.at_spec is False
    assert hold.at_merge is True


def test_both_orders_set_both():
    assert parse_hold(raw="spec,merge") == Hold(at_spec=True, at_merge=True)
    assert parse_hold(raw="merge,spec") == Hold(at_spec=True, at_merge=True)


def test_unknown_token_raises_with_valid_values_listed():
    with pytest.raises(ValueError) as exc:
        parse_hold(raw="foo")
    message = str(exc.value)
    assert "spec" in message and "merge" in message


def test_unknown_token_among_valid_still_raises():
    # 严格报错：拼错的 token 不能被静默忽略（否则悄悄丢掉监督）。
    with pytest.raises(ValueError):
        parse_hold(raw="spec,spc")


def test_tolerates_whitespace_and_case():
    assert parse_hold(raw=" Spec , Merge ") == Hold(at_spec=True, at_merge=True)
    assert parse_hold(raw="SPEC").at_spec is True
    # 仅空白/逗号 → 视作空 → 默认全不停。
    assert parse_hold(raw="  ,  ") == NONE


def test_hold_is_immutable_value_object():
    hold = Hold(at_spec=True, at_merge=False)
    assert dataclasses.is_dataclass(hold)
    with pytest.raises(dataclasses.FrozenInstanceError):
        hold.at_spec = False
