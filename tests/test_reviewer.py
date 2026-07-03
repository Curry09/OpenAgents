"""RFC-0012 T1: reviewer 编排模块（N 并行 + 裁决聚合）的单元测试。

打桩 AgentBackend（不触达真实 claude），覆盖：
- N=1 PASS → passed=True；
- N=3 含一个 REWORK → passed=False 且 feedback 含该反馈；
- RETHINK 同 REWORK 归为非 PASS；
- 裁决 token 解析鲁棒（大小写 / 前后缀 / 裸 token / 无法解析）；
- configured_reviewers 读 env 与缺省；
- 未知 kind 抛错。
"""

import threading

import pytest

from openagents.backends.base import AgentResult
from openagents.reviewer import (
    DEFAULT_REVIEWERS,
    REVIEWERS_ENV,
    UNPARSED_VERDICT,
    ReviewDecision,
    _parse_verdict,
    _task_for,
    configured_reviewers,
    render_decision,
    review,
)


class _ScriptedBackend:
    """伪后端：按序返回预设的 summary 列表（每次 run 取下一个）。

    记录每次 run 的入参，供断言任务模板与并发次数。
    """

    name = "scripted"

    def __init__(self, *, summaries):
        self._summaries = list(summaries)
        self._index = 0
        self.calls = []
        # review(n>1) 在 ThreadPoolExecutor 里并发调本 run，_index/_calls 是共享可变状态；
        # 用锁把「取 summary + 自增 index + 记 call」串行化，保证每条 summary 恰好被派发一次
        # （否则非原子的 _index += 1 在竞态下会跳号/重号，使 n=3 的断言不确定地翻红）。
        self._lock = threading.Lock()

    def run(self, *, work_dir, task, context):
        with self._lock:
            self.calls.append({"work_dir": work_dir, "task": task, "context": context})
            summary = self._summaries[self._index % len(self._summaries)]
            self._index += 1
        return AgentResult(changed=False, summary=summary)


def _backend(*summaries):
    return _ScriptedBackend(summaries=summaries)


# --------------------------------------------------------------------------- #
# 聚合规则：全票 PASS
# --------------------------------------------------------------------------- #


def test_single_reviewer_pass(tmp_path):
    backend = _backend("VERDICT: PASS\nREASON: 对齐需求")
    decision = review(backend=backend, work_dir=tmp_path, kind="rfc", pr_number=5, n=1)
    assert isinstance(decision, ReviewDecision)
    assert decision.passed is True
    assert decision.feedback == ""
    assert len(backend.calls) == 1


def test_three_reviewers_all_pass(tmp_path):
    backend = _backend("VERDICT: PASS")
    decision = review(backend=backend, work_dir=tmp_path, kind="code", pr_number=7, n=3)
    assert decision.passed is True
    assert len(backend.calls) == 3


def test_three_reviewers_one_rework_fails(tmp_path):
    backend = _backend(
        "VERDICT: PASS\nREASON: ok",
        "VERDICT: REWORK\nISSUES:\n- foo.py:10 缺边界处理\nNEXT: 补空输入分支",
        "VERDICT: PASS",
    )
    decision = review(backend=backend, work_dir=tmp_path, kind="code", pr_number=7, n=3)
    assert decision.passed is False
    # feedback 含未通过那条的反馈正文。
    assert "缺边界处理" in decision.feedback
    assert "补空输入分支" in decision.feedback


def test_rethink_treated_as_non_pass(tmp_path):
    backend = _backend("VERDICT: RETHINK\nREASON: 同类问题反复\nSUGGESTION: 换方案")
    decision = review(backend=backend, work_dir=tmp_path, kind="rfc", pr_number=1, n=1)
    assert decision.passed is False
    assert "换方案" in decision.feedback


def test_unparseable_verdict_is_non_pass(tmp_path):
    # 没有任何裁决 token → 疑罪从严视为未通过，feedback 给出提示。
    backend = _backend("我觉得还行吧，没什么大问题")
    decision = review(backend=backend, work_dir=tmp_path, kind="rfc", pr_number=1, n=1)
    assert decision.passed is False
    assert decision.feedback


def test_empty_summary_non_pass_has_placeholder_feedback(tmp_path):
    backend = _backend("")
    decision = review(backend=backend, work_dir=tmp_path, kind="rfc", pr_number=1, n=1)
    assert decision.passed is False
    assert "未给出可解析的裁决" in decision.feedback


# --------------------------------------------------------------------------- #
# 裁决 token 解析鲁棒性
# --------------------------------------------------------------------------- #


def test_parse_verdict_case_insensitive():
    assert _parse_verdict(summary="verdict: pass") == "PASS"
    assert _parse_verdict(summary="VERDICT: Rework") == "REWORK"


def test_parse_verdict_with_surrounding_text():
    assert _parse_verdict(summary="前言...\nVERDICT: PASS\n后记") == "PASS"


def test_parse_verdict_bare_token_fallback():
    # 模型漏写 VERDICT: 前缀时，回退到正文首个裸 token。
    assert _parse_verdict(summary="结论是 PASS，没问题") == "PASS"


def test_parse_verdict_none_when_absent():
    assert _parse_verdict(summary="无明确结论") is None


# --------------------------------------------------------------------------- #
# 任务模板 / kind
# --------------------------------------------------------------------------- #


def test_task_for_rfc_and_code_differ():
    rfc_task = _task_for(kind="rfc", pr_number=5)
    code_task = _task_for(kind="code", pr_number=5)
    assert "spec" in rfc_task
    assert "git diff" in code_task
    assert "#5" in rfc_task and "#5" in code_task


def test_code_review_task_defers_runtime_behavior_to_evidence_gate():
    # Spec-0040/T4：职责收口——code rubric 不再含 browser-e2e 措辞，改为明写「运行时行为由证据闸
    # 负责、你不判」，只留静态代码质量/安全/结构。
    code_task = _task_for(kind="code", pr_number=7)
    assert "浏览器工具" not in code_task
    assert "运行时行为" in code_task and "证据闸" in code_task
    assert "你不判" in code_task


def test_rfc_review_task_has_hard_e2e_rubric():
    # Spec-0040/T4：「要不要有 e2e」上移到 RFC 闸——前端/交互类改动未声明 e2e 粗规划 → REWORK。
    rfc_task = _task_for(kind="rfc", pr_number=5)
    assert "e2e 粗规划" in rfc_task
    assert "REWORK" in rfc_task
    assert "前端/交互类" in rfc_task


def test_code_review_task_has_evidence_rubric():
    # Spec-0044/T2：code rubric 含「宣称验证过但无证据 → REWORK」结构化检查项，
    # 且条件式触发（仅出现端到端/e2e/截图/已验证 UI 类措辞时才查，不误伤纯内部重构 PR）。
    code_task = _task_for(kind="code", pr_number=7)
    assert "宣称验证过但无证据 → REWORK" in code_task
    # 条件式：措辞触发词齐全 + 明说纯内部重构不误伤。
    assert "端到端" in code_task and "e2e" in code_task and "截图" in code_task
    assert "纯内部重构" in code_task


def test_evidence_rubric_only_on_code_not_rfc():
    # Spec-0044/T2：无证据检查项只挂代码 review（评实现/取证），不挂 spec 文档 review。
    rfc_task = _task_for(kind="rfc", pr_number=7)
    assert "宣称验证过但无证据 → REWORK" not in rfc_task


def test_review_uses_kind_template_in_backend_call(tmp_path):
    backend = _backend("VERDICT: PASS")
    review(backend=backend, work_dir=tmp_path, kind="code", pr_number=42, n=1)
    assert "git diff" in backend.calls[0]["task"]
    assert backend.calls[0]["work_dir"] == tmp_path


def test_unknown_kind_raises(tmp_path):
    with pytest.raises(ValueError):
        review(backend=_backend("VERDICT: PASS"), work_dir=tmp_path, kind="bogus", pr_number=1, n=1)


# --------------------------------------------------------------------------- #
# configured_reviewers（env 旋钮）
# --------------------------------------------------------------------------- #


def test_configured_reviewers_default_when_unset(monkeypatch):
    monkeypatch.delenv(REVIEWERS_ENV, raising=False)
    assert configured_reviewers() == DEFAULT_REVIEWERS


def test_configured_reviewers_reads_env(monkeypatch):
    monkeypatch.setenv(REVIEWERS_ENV, "3")
    assert configured_reviewers() == 3


def test_configured_reviewers_invalid_falls_back(monkeypatch):
    monkeypatch.setenv(REVIEWERS_ENV, "not-a-number")
    assert configured_reviewers() == DEFAULT_REVIEWERS


def test_configured_reviewers_below_one_falls_back(monkeypatch):
    monkeypatch.setenv(REVIEWERS_ENV, "0")
    assert configured_reviewers() == DEFAULT_REVIEWERS


def test_review_n_below_one_runs_once(tmp_path):
    backend = _backend("VERDICT: PASS")
    decision = review(backend=backend, work_dir=tmp_path, kind="rfc", pr_number=1, n=0)
    assert decision.passed is True
    assert len(backend.calls) == 1


# --------------------------------------------------------------------------- #
# RFC-0018: verdicts 暴露 + render_decision 渲染
# --------------------------------------------------------------------------- #


def test_verdicts_length_matches_reviewer_count(tmp_path):
    # RFC-0018 决策 3：verdicts 与 N 等长且元素为合法 token。
    backend = _backend("VERDICT: PASS")
    decision = review(backend=backend, work_dir=tmp_path, kind="code", pr_number=7, n=3)
    assert decision.verdicts == ("PASS", "PASS", "PASS")


def test_verdicts_map_each_token(tmp_path, monkeypatch):
    # PASS / REWORK / RETHINK 分别映射到对应 token，保持 summaries 顺序。
    # 这里要断言的是 review() 的「逐位 summary→verdict」纯映射逻辑，而非并发调度：
    # 真并行下哪条 summary 落在哪个 future 由线程调度决定（即便给 backend 加锁也只保证
    # 每条 summary 派发一次、不保证 summary→future 的对应），故打桩 _run_reviewers 固定
    # 按序返回 summaries，把映射断言与线程时序解耦——避免 CI 不确定地翻红（核对：「PR 的 CI 全通过」）。
    summaries = ["VERDICT: PASS", "VERDICT: REWORK", "VERDICT: RETHINK"]
    monkeypatch.setattr(
        "openagents.reviewer._run_reviewers",
        lambda *, backend, work_dir, task, n: summaries,
    )
    decision = review(backend=_backend("unused"), work_dir=tmp_path, kind="code", pr_number=7, n=3)
    assert decision.verdicts == ("PASS", "REWORK", "RETHINK")


def test_verdicts_unparsed_normalized(tmp_path):
    # 无法解析裁决 → 归一化为 UNPARSED（疑罪从严，非 PASS）。
    backend = _backend("我觉得还行吧，没什么大问题")
    decision = review(backend=backend, work_dir=tmp_path, kind="rfc", pr_number=1, n=1)
    assert decision.verdicts == (UNPARSED_VERDICT,)


def test_review_decision_verdicts_defaults_empty():
    # 向后兼容：既有构造点不传 verdicts 时默认空元组。
    decision = ReviewDecision(passed=True, feedback="")
    assert decision.verdicts == ()


def test_render_decision_pass_contains_kind_and_votes():
    decision = ReviewDecision(passed=True, feedback="", verdicts=("PASS", "PASS"))
    body = render_decision(decision=decision, kind="rfc")
    assert "Spec 文档" in body
    assert "PASS" in body
    assert "2 票中 2 票 PASS" in body


def test_render_decision_rework_contains_feedback_summary():
    decision = ReviewDecision(
        passed=False,
        feedback="foo.py:10 缺边界处理",
        verdicts=("PASS", "REWORK"),
        actionable=True,
    )
    body = render_decision(decision=decision, kind="code")
    assert "代码" in body
    assert "REWORK" in body
    assert "2 票中 1 票 PASS" in body
    assert "缺边界处理" in body


def test_render_decision_renders_unparsed_vote_type():
    # 含 UNPARSED 的混合票型：票数正确、票型逐项展示。
    decision = ReviewDecision(
        passed=False,
        feedback="（reviewer 未给出可解析的裁决）",
        verdicts=("PASS", UNPARSED_VERDICT),
    )
    body = render_decision(decision=decision, kind="rfc")
    assert "2 票中 1 票 PASS" in body
    assert UNPARSED_VERDICT in body


# --------------------------------------------------------------------------- #
# Spec-0021/T1: 区分「评审无效」与「真 REWORK」+ 首行解析 + 单次重解析
# --------------------------------------------------------------------------- #


def test_truncated_praise_is_invalid_not_rework(tmp_path):
    # 截断好评：summary 全是好评但无 VERDICT、重跑仍无 → passed=False 且 actionable=False
    # （评审无效）。verdicts 仍含 UNPARSED 占位、长度=N。
    backend = _backend("代码看起来不错，逻辑清晰，测试也挺全的，挺好的，没发现什么问题")
    decision = review(backend=backend, work_dir=tmp_path, kind="code", pr_number=61, n=1)
    assert decision.passed is False
    assert decision.actionable is False
    assert decision.verdicts == (UNPARSED_VERDICT,)


def test_actionable_rework_with_issues(tmp_path):
    # 真 REWORK：首行 VERDICT: REWORK + ISSUES 正文 → passed=False、actionable=True、
    # feedback 含 ISSUES 正文。
    backend = _backend("VERDICT: REWORK\nISSUES:\n- foo.py:10 缺边界处理\nNEXT: 补空输入分支")
    decision = review(backend=backend, work_dir=tmp_path, kind="code", pr_number=7, n=1)
    assert decision.passed is False
    assert decision.actionable is True
    assert "缺边界处理" in decision.feedback


def test_parse_verdict_first_line_priority_over_body_bare_token():
    # 首行 VERDICT: PASS + 正文里出现裸 "REWORK" 字样 → 解析为 PASS（首行优先，不被正文污染）。
    summary = "VERDICT: PASS\nREASON: 对齐需求\n（注：上一轮 reviewer 曾判 REWORK，本轮已修复）"
    assert _parse_verdict(summary=summary) == "PASS"


def test_unparsed_then_retry_pass(tmp_path):
    # 首跑 UNPARSED、重跑给出 VERDICT: PASS → 该 reviewer 的 backend.run 被调用两次，最终 passed=True。
    backend = _backend("被截断了一半的论证……", "VERDICT: PASS\nREASON: ok")
    decision = review(backend=backend, work_dir=tmp_path, kind="rfc", pr_number=1, n=1)
    assert decision.passed is True
    assert len(backend.calls) == 2


def test_unparsed_retry_only_once(tmp_path):
    # 重跑仍 UNPARSED → 只重跑一次（不无限），落「评审无效」（actionable=False）。
    backend = _backend("没有裁决 token 的一段话")
    decision = review(backend=backend, work_dir=tmp_path, kind="rfc", pr_number=1, n=1)
    assert decision.passed is False
    assert decision.actionable is False
    assert len(backend.calls) == 2  # 首跑 + 单次重跑，不再继续


def test_all_pass_is_not_actionable(tmp_path):
    backend = _backend("VERDICT: PASS")
    decision = review(backend=backend, work_dir=tmp_path, kind="code", pr_number=7, n=3)
    assert decision.passed is True
    assert decision.actionable is False
    assert decision.feedback == ""


def test_review_decision_actionable_defaults_false():
    # 向后兼容：既有构造点不传 actionable 时默认 False。
    decision = ReviewDecision(passed=True, feedback="")
    assert decision.actionable is False


def test_render_decision_invalid_distinct_from_rework():
    # 「评审无效」与「REWORK」渲染出不同标识文案。
    invalid = render_decision(
        decision=ReviewDecision(
            passed=False, feedback="x", verdicts=(UNPARSED_VERDICT,), actionable=False
        ),
        kind="code",
    )
    rework = render_decision(
        decision=ReviewDecision(passed=False, feedback="x", verdicts=("REWORK",), actionable=True),
        kind="code",
    )
    assert "评审无效" in invalid
    assert "评审无效" not in rework
    assert "❌ REWORK" in rework
