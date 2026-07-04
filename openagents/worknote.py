"""Spec-0050/T3: agent「本轮做了什么」回执渲染（纯函数模块，解耦理念 10，与 blocknote/replynote 对称）。

把「派 agent 执行完后在 PR 回贴的『我干了什么』说明」长什么样收敛进三个可单测的纯函数：
`render_implement`（实现代码）/ `render_iterate`（据反馈迭代）/ `render_runbook`（定稿 e2e 说明书）。
三者只吃**基元参数**（str）、只拼字符串、**无副作用、不含签名、不做任何 IO**——签名由调用方
（messages 经 identity.post_signed_comment）盖；也**不反向 import** orchestrator/handle 类型，
避免展示模块与编排层耦合（与 blocknote/replynote 延续同一「纯拼字符串、被 messages 调用」范式）。

每个回执以稳定抬头（`## 实现自述` 等）开头，作 messages 收口点防刷屏去重（Spec-0050/T5
`_report_already_posted`）的锚点；`summary` 为空时回落占位「（无摘要）」（与 orchestrator._REFINE_COMMENT
的空摘要处理一致），保证结构不缺、渲染不报错。
"""

from __future__ import annotations

# 三类回执的稳定抬头（render_* 的首行锚点）。迭代自述把 reason 中文化嵌进标题，使 ci/review/e2e
# 天然分桶（去重按标题行分组，不同 reason 的迭代互不抑制；Spec-0050/T5 _report_already_posted）。
_IMPLEMENT_HEADER = "## 实现自述"
_ITERATE_HEADER = "## 迭代自述"
_RUNBOOK_HEADER = "## 说明书定稿"

# 迭代 reason → 人类可读短语。覆盖 _process_coding / _evidence_gate 会传入的三种反馈来源；
# 未知 reason 回落到原字面量（绝不抛错，与 blocknote._GATE_REASONS 的兜底同风格）。
_REASON_LABELS = {
    "ci": "CI 反馈",
    "review": "代码评审反馈",
    "e2e": "证据闸反馈",
}

# summary 为空时的占位（与 orchestrator._REFINE_COMMENT 的空摘要回落一致）。
_EMPTY_SUMMARY = "（无摘要）"


def render_implement(*, summary: str) -> str:
    """Spec-0050/T3：渲「实现自述」回执——抬头 `## 实现自述` + agent 本轮实现摘要（空则占位）。"""
    return f"{_IMPLEMENT_HEADER}\n\n{_summary_body(summary=summary)}"


def render_iterate(*, reason: str, summary: str) -> str:
    """Spec-0050/T3：渲「迭代自述」回执——抬头 `## 迭代自述（<reason 中文化>）` + 本轮迭代摘要。

    reason ∈ {ci, review, e2e}（中文化嵌进标题使其天然分桶）；未知 reason 回落原字面量。
    """
    label = _REASON_LABELS.get(reason, reason or _EMPTY_SUMMARY)
    return f"{_ITERATE_HEADER}（{label}）\n\n{_summary_body(summary=summary)}"


def render_runbook(*, form: str, runbook_path: str) -> str:
    """Spec-0050/T3：渲「说明书定稿」回执——抬头 `## 说明书定稿` + e2e 形态 + runbook 路径。

    只吃基元 str（form / runbook_path 由调用方从 RunbookHandle 取），空值各自占位、不报错。
    """
    return (
        f"{_RUNBOOK_HEADER}\n\n"
        f"- 执行形态：{form or '（未声明）'}\n"
        f"- 说明书：{runbook_path or '（未知路径）'}"
    )


def _summary_body(*, summary: str) -> str:
    """摘要正文：非空 strip 后原样，空则回落占位（私有纯函数，调用方显式传参）。"""
    return summary.strip() if summary.strip() else _EMPTY_SUMMARY
