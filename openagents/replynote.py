"""Spec-0036/T2: 引用原评论的回应构造（纯函数模块，解耦理念 10，与 blocknote 对称）。

把「agent 完成本轮动作后对触发它的那条人类评论的回应」长什么样收敛进一个可单测的纯函数
`build`：把『引用原评论（markdown 引用块包裹人类评论正文）+ agent 回应正文』拼成回应评论的
markdown 正文。**不含签名**——签名由调用方（messages 经 identity.post_signed_comment）盖；
本模块只管展示，不做任何 IO。

messages 路由层只负责「取回应文本（agent summary / 结论文案）+ 调本函数 + 盖签名贴出」——
展示逻辑与路由逻辑解耦，模板可独立断言（引用块包裹正确、回应段齐全）。与 blocknote 延续同一
解耦范式（纯函数造评论正文、不含签名、调用方盖签名贴出）。
"""

from __future__ import annotations

# 固定文案：引用抬头 + 回应抬头。引用抬头点明「下方是我在回应你的这条评论」，回应段用机器人
# emoji 与挂起/裁决评论视觉一致。response 为空时占位，保证「引用 + 回应」两段结构始终齐全。
_QUOTE_HEADER = "↩️ 回应你的这条评论："
_RESPONSE_HEADER = "🤖"
_EMPTY_RESPONSE = "（本轮无更多说明）"


def build(*, original: str, response: str) -> str:
    """Spec-0036/T2：把「引用原评论 + agent 回应」拼成回应评论正文（纯函数，不含签名、无 IO）。

    - 引用原评论：markdown 引用块逐行包裹人类评论 `original`（为空时占位，保证引用段不缺）；
    - 回应正文：agent 本轮动作的 `response`（summary / 结论文案），为空时占位「（本轮无更多
      说明）」保证结构完整。
    """
    quoted = _as_quote(text=original) if original.strip() else "> （原评论为空）"
    body = response.strip() if response.strip() else _EMPTY_RESPONSE
    return f"{_QUOTE_HEADER}\n{quoted}\n\n{_RESPONSE_HEADER} {body}"


def _as_quote(*, text: str) -> str:
    """把多行文本逐行包成 markdown 引用块（每行前缀 "> "）。私有纯函数，调用方显式传参。"""
    return "\n".join(f"> {line}" for line in text.splitlines())
