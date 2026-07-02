"""Spec-0032/T3: 结构化阻塞评论构造（纯函数模块，解耦理念 10）。

把「needs-human 挂起评论长什么样」收敛进一个可单测的纯函数 `build`：按挂起的闸（gate）
把『原因 / 我试过 / 卡在哪 / 你可以怎么做』四段拼成模板 markdown 正文。**不含签名**——签名由
调用方（messages 经 identity.post_signed_comment）盖；本模块只管展示，不做任何 IO。

messages 路由层只负责据上下文组装 `tried`（试过什么）/ `blocker`（具体卡点原文）后调本函数，
再盖签名贴出——展示逻辑与路由逻辑解耦，模板可独立断言（四段齐全、gate→原因短语正确）。
"""

from __future__ import annotations

# gate → 人类可读「原因」短语映射。覆盖 _block 会传入的全部 gate 取值（与 state.block_gate /
# messages 一致：rfc / code / merge / *-unparseable）；未知 gate 回落到通用短语，绝不抛错。
_GATE_REASONS = {
    "rfc": "RFC 评审未通过",
    "code": "代码评审未通过",
    "merge": "与目标分支存在无法自动解决的冲突",
    "rfc-unparseable": "RFC 评审输出无法解析",
    "code-unparseable": "代码评审输出无法解析",
}
_DEFAULT_REASON = "流程卡住，需要人工判断"

# 模板固定文案：标题 + 「你可以怎么做」指引（含『回复即继续』承诺，对齐解挂只认人类新评论的语义）。
_HEADER = "🤖 OpenAgents 卡住了，需要你的判断"
_GUIDANCE = "直接在本 PR **回复一条评论**给出指导，我会据此继续；无需手动摘标签。"
_EMPTY_BLOCKER = "> （暂无更多细节）"


def build(*, gate: str, tried: str, blocker: str) -> str:
    """Spec-0032/T3：按 gate 把四段拼成挂起评论正文（纯函数，不含签名、无 IO）。

    - 原因：gate → 人类可读短语（含 gate 字面量便于运维定位）；
    - 我试过：调用方据 gate + 回合数组装的 `tried`；
    - 卡在哪：调用方传入的 `blocker`（reviewer 反馈原文 / 冲突提示 / CI 日志摘要），用 markdown
      引用块逐行包裹；为空时占位，保证四段齐全；
    - 你可以怎么做：固定『回复即继续』指引。
    """
    reason = _GATE_REASONS.get(gate, _DEFAULT_REASON)
    blocker_quote = _as_quote(text=blocker) if blocker.strip() else _EMPTY_BLOCKER
    return (
        f"{_HEADER}\n\n"
        f"**原因**：{reason}（gate={gate}）\n"
        f"**我试过**：{tried}\n"
        f"**卡在哪**：\n{blocker_quote}\n\n"
        f"**你可以怎么做**：{_GUIDANCE}"
    )


def _as_quote(*, text: str) -> str:
    """把多行文本逐行包成 markdown 引用块（每行前缀 "> "）。私有纯函数，调用方显式传参。"""
    return "\n".join(f"> {line}" for line in text.splitlines())


# Spec-0041/T2：hold-merge PASS 后「夯住待合并」的成功文案固定串。语气为成功待合并——
# 与 build 的「🤖 卡住了」失败模板并列但语义相反：这条不是求救，是「已通过、只差你点合并」。
# 两条指引对齐 merge-hold 的两个人触发出口（messages 决策 A/B）：点合并 → is_merged reconcile
# 成 done；回评论 → merge-hold gate 走 iterate(reason="human") 据评论继续。
_HOLD_MERGE_HEADER = "✅ 已通过评审，待你合并"
_HOLD_MERGE_BODY = (
    "本 PR 已通过代码评审闸，且当前以 `--hold merge` 运行——最后一下的合并留给你。\n\n"
    "**你可以怎么做**：\n"
    "- **点合并即完成**：在本 PR 上手动合并，我下一轮就会把 issue 收口为完成。\n"
    "- **回评论即据此继续**：若还想改，直接回一条评论，我会据此让写码 agent 继续迭代。"
)


def build_hold_merge_pass() -> str:
    """Spec-0041/T2：产出「✅ 已通过评审，待你合并」的签名前正文（纯函数，不含签名、无 IO）。

    与 build 的四段失败模板并列的成功文案：hold-merge PASS 冻结时由 messages 贴出（经
    identity.post_signed_comment 盖签名）。明确「点合并即完成 / 回评论即据此继续」两条指引，
    不含任何失败/求救措辞。既有 build / _GATE_REASONS 不改（零回归）。
    """
    return f"{_HOLD_MERGE_HEADER}\n\n{_HOLD_MERGE_BODY}"
