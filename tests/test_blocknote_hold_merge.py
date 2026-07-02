"""Spec-0041/T2：blocknote.build_hold_merge_pass 成功文案的单元测试（纯函数，无 IO）。

覆盖：
- 含「✅ 已通过评审，待你合并」措辞；
- 明确「点合并即完成 / 回评论即据此继续」两条指引；
- 不含任何失败/求救措辞（不含「卡住了」失败模板）、不含签名；
- 既有 build 输出逐字节不变（零回归）。
"""

from openagents import blocknote


def test_hold_merge_pass_has_success_wording():
    body = blocknote.build_hold_merge_pass()
    assert "✅ 已通过评审，待你合并" in body


def test_hold_merge_pass_states_two_guidances():
    body = blocknote.build_hold_merge_pass()
    # 两条出口指引：点合并 → 完成；回评论 → 据此继续。
    assert "点合并即完成" in body
    assert "回评论即据此继续" in body


def test_hold_merge_pass_has_no_failure_wording():
    # 成功文案绝不含失败/求救措辞——不复用「🤖 卡住了」失败模板。
    body = blocknote.build_hold_merge_pass()
    assert "卡住了" not in body
    assert "🤖" not in body
    assert "需要你的判断" not in body


def test_hold_merge_pass_contains_no_signature():
    # 签名由调用方（messages 经 identity.post_signed_comment）盖——本函数不得含签名标记。
    body = blocknote.build_hold_merge_pass()
    assert "openagents:agent=" not in body


def test_build_output_unchanged_zero_regression():
    # 既有失败模板 build 逐字节不变：新增成功文案不得回归 _GATE_REASONS / build。
    body = blocknote.build(gate="code", tried="试过了 N 轮", blocker="reviewer 说要重写")
    expected = (
        "🤖 OpenAgents 卡住了，需要你的判断\n\n"
        "**原因**：代码评审未通过（gate=code）\n"
        "**我试过**：试过了 N 轮\n"
        "**卡在哪**：\n> reviewer 说要重写\n\n"
        "**你可以怎么做**：直接在本 PR **回复一条评论**给出指导，我会据此继续；无需手动摘标签。"
    )
    assert body == expected
