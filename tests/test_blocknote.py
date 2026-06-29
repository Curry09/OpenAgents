"""Spec-0032/T3：blocknote.build 结构化阻塞评论构造的单元测试（纯函数，无 IO）。

覆盖：
- 各 gate 产出四段齐全（原因 / 我试过 / 卡在哪 / 你可以怎么做）；
- gate → 原因短语映射正确；
- 含『回复即继续』指引、不含签名；
- blocker 用引用块包裹；空 blocker 有占位（仍四段齐全）；
- 未知 gate 回落通用短语、不抛。
"""

import pytest

from openagents import blocknote

_FOUR_SECTIONS = ("**原因**", "**我试过**", "**卡在哪**", "**你可以怎么做**")


@pytest.mark.parametrize(
    "gate,phrase",
    [
        ("rfc", "RFC 评审未通过"),
        ("code", "代码评审未通过"),
        ("merge", "与目标分支存在无法自动解决的冲突"),
        ("rfc-unparseable", "RFC 评审输出无法解析"),
        ("code-unparseable", "代码评审输出无法解析"),
    ],
)
def test_build_has_four_sections_and_reason(gate, phrase):
    body = blocknote.build(gate=gate, tried="试过了 N 轮", blocker="reviewer 说要重写")
    for section in _FOUR_SECTIONS:
        assert section in body
    assert phrase in body
    assert f"gate={gate}" in body


def test_build_includes_reply_guidance():
    body = blocknote.build(gate="code", tried="x", blocker="y")
    assert "回复一条评论" in body
    assert "无需手动摘标签" in body


def test_build_contains_no_signature():
    # 签名由调用方盖——build 自身不得含隐藏签名标记。
    body = blocknote.build(gate="code", tried="x", blocker="y")
    assert "openagents:agent=" not in body


def test_build_wraps_blocker_in_quote():
    body = blocknote.build(gate="code", tried="x", blocker="第一行\n第二行")
    assert "> 第一行" in body
    assert "> 第二行" in body


def test_build_empty_blocker_has_placeholder_and_four_sections():
    body = blocknote.build(gate="merge", tried="x", blocker="")
    for section in _FOUR_SECTIONS:
        assert section in body
    assert "暂无更多细节" in body


def test_build_unknown_gate_falls_back():
    body = blocknote.build(gate="weird", tried="x", blocker="y")
    assert "流程卡住" in body
    for section in _FOUR_SECTIONS:
        assert section in body


def test_build_includes_tried_text():
    body = blocknote.build(gate="rfc", tried="迭代了 3 轮仍 REWORK", blocker="y")
    assert "迭代了 3 轮仍 REWORK" in body


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
