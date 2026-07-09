"""Spec-0036/T2：replynote.build 引用原评论回应构造的单元测试（纯函数，无 IO）。

覆盖：
- 正常 original/response → 引用块 + 回应段齐全；
- original 多行 → 逐行引用块包裹；
- response 为空 → 占位不缺段；
- original 为空 → 引用段占位不缺段；
- 不含签名（签名由调用方盖）；
- 纯函数无 IO（仅靠入参产出）。
"""

import pytest

from openagents.utils import replynote


def test_build_has_quote_and_response():
    body = replynote.build(
        original="先解 OVERVIEW.md 再动 state.py", response="已按你的指导解冲突并 push"
    )
    # 引用块包裹原评论。
    assert "> 先解 OVERVIEW.md 再动 state.py" in body
    # 回应正文齐全。
    assert "已按你的指导解冲突并 push" in body


def test_build_wraps_multiline_original_in_quote():
    body = replynote.build(original="第一行\n第二行", response="收到")
    assert "> 第一行" in body
    assert "> 第二行" in body


def test_build_empty_response_has_placeholder():
    body = replynote.build(original="人类评论", response="")
    # 引用段仍在 + 回应段占位（结构完整，不缺段）。
    assert "> 人类评论" in body
    assert "（本轮无更多说明）" in body


def test_build_blank_response_has_placeholder():
    # 仅空白的 response 也占位（strip 后为空）。
    body = replynote.build(original="人类评论", response="   \n  ")
    assert "（本轮无更多说明）" in body


def test_build_empty_original_has_placeholder():
    body = replynote.build(original="", response="我做了 X")
    # 引用段不缺（占位），回应段照常。
    assert "（原评论为空）" in body
    assert "我做了 X" in body


def test_build_contains_no_signature():
    # 签名由调用方盖——build 自身不得含隐藏签名标记。
    body = replynote.build(original="x", response="y")
    assert "openagents:agent=" not in body


def test_build_is_pure_function():
    # 同一入参两次调用产出逐字节相同（无隐藏状态 / 无 IO / 不读时钟）。
    a = replynote.build(original="x", response="y")
    b = replynote.build(original="x", response="y")
    assert a == b


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
