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
