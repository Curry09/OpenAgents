"""Spec-0041/T3：reviewer._distill_feedback 净化 scratchpad 的单元测试（纯函数 + 经 review 聚合）。

覆盖：
- 含内心独白的样本 summary 净化后不含独白、仍保留可操作反馈；
- 净化后为空（全独白）回落既有占位（经 review 聚合）；
- 命中过程前缀但含可操作信号（文件:行号 / 裁决关键词）的句子被保留（不误删）；
- 经 review() 聚合的 decision.feedback 不含独白、passed/actionable/verdicts 逐字节不变（零回归）。
"""

from openagents.backends.base import AgentResult
from openagents.reviewer import _distill_feedback, review


class _ScriptedBackend:
    """伪后端：按序返回预设 summary（每次 run 取下一个）——复用 test_reviewer 同款约定。"""

    name = "scripted"

    def __init__(self, *, summaries):
        self._summaries = list(summaries)
        self._index = 0

    def run(self, *, work_dir, task, context):
        summary = self._summaries[self._index]
        self._index += 1
        return AgentResult(changed=False, summary=summary)


# 含内心独白的 REWORK 样本：前有过程叙述，后有可操作 ISSUES/NEXT。
_MONOLOGUE = (
    "VERDICT: REWORK\n"
    "All 32 tests pass. I have enough to finalize. Let me capture my findings.\n"
    "ISSUES:\n"
    "- messages.py:430 hold-merge 分支是空操作，未夯住 run\n"
    "NEXT: 改成 _hold_merge_freeze 复用冻结骨架"
)


def test_distill_strips_monologue_keeps_actionable():
    out = _distill_feedback(summary=_MONOLOGUE)
    # 内心独白被剥离。
    assert "I have enough" not in out
    assert "Let me capture" not in out
    assert "All 32 tests pass" not in out
    # 可操作反馈保留。
    assert "messages.py:430" in out
    assert "VERDICT: REWORK" in out
    assert "NEXT: 改成 _hold_merge_freeze 复用冻结骨架" in out


def test_distill_all_monologue_returns_empty():
    out = _distill_feedback(summary="Let me think. I have enough. Now I finalize.")
    assert out == ""


def test_distill_keeps_actionable_even_with_process_prefix():
    # 命中过程前缀但含文件:行号 → 保留（保守：不误删可操作反馈）。
    out = _distill_feedback(summary="Let me note that messages.py:430 应改成夯住。")
    assert "messages.py:430" in out


def test_distill_empty_summary_returns_empty():
    assert _distill_feedback(summary="") == ""


def test_review_aggregated_feedback_excludes_monologue():
    backend = _ScriptedBackend(summaries=[_MONOLOGUE])
    decision = review(backend=backend, work_dir=".", kind="code", pr_number=1, n=1)
    assert decision.passed is False
    # actionable 判定不变（有实质 REWORK 正文）——零回归。
    assert decision.actionable is True
    assert decision.verdicts == ("REWORK",)
    # 喂人的 feedback 已净化。
    assert "I have enough" not in decision.feedback
    assert "messages.py:430" in decision.feedback


def test_review_all_monologue_falls_back_to_placeholder():
    # summary 全是独白（无可解析裁决）→ 净化为空 → 回落既有占位文案。
    # UNPARSED 会触发一次重跑，故备两条同样全独白的 summary。
    monologue = "Let me think. I have enough. Now I finalize."
    backend = _ScriptedBackend(summaries=[monologue, monologue])
    decision = review(backend=backend, work_dir=".", kind="code", pr_number=1, n=1)
    assert decision.passed is False
    assert "按疑罪从严视为未通过" in decision.feedback


def test_review_pass_unaffected_zero_regression():
    # 全票 PASS 路径不经净化、feedback 仍为空——零回归。
    backend = _ScriptedBackend(summaries=["VERDICT: PASS\nREASON: ok"])
    decision = review(backend=backend, work_dir=".", kind="code", pr_number=1, n=1)
    assert decision.passed is True
    assert decision.feedback == ""
    assert decision.verdicts == ("PASS",)
