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
    _RUBRIC_TAIL,
    DEFAULT_REVIEWERS,
    REVIEWERS_ENV,
    UNPARSED_VERDICT,
    DecisionContent,
    ReviewDecision,
    _parse_verdict,
    _task_for,
    configured_reviewers,
    extract_decision_content,
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
    rfc_task = _task_for(kind="rfc", pr_number=5, ui_capable=True)
    code_task = _task_for(kind="code", pr_number=5, ui_capable=False)
    assert "spec" in rfc_task
    assert "git diff" in code_task
    assert "#5" in rfc_task and "#5" in code_task


def test_code_review_task_now_judges_runtime_behavior():
    # Spec-0054/T4：反转 0040/T4——code reviewer 现在**判运行时行为**（读 executor 证据 + 亲眼看截图），
    # 不再「运行时行为由证据闸负责、你不判」。
    code_task = _task_for(kind="code", pr_number=7, ui_capable=False)
    assert "也判运行时行为" in code_task
    assert "取消了独立证据闸" in code_task
    # 明写读统一证据落点 + 亲眼看截图。
    assert "docs/e2e-results/7/" in code_task
    assert "Read" in code_task and "截图" in code_task


def test_rfc_review_task_has_hard_e2e_rubric():
    # Spec-0054/T4：「要不要有 e2e」在 RFC 闸把关——前端/交互类改动未声明 e2e 测法 → REWORK。
    rfc_task = _task_for(kind="rfc", pr_number=5, ui_capable=True)
    assert "e2e 测法" in rfc_task
    assert "REWORK" in rfc_task
    assert "前端/交互类" in rfc_task


def test_rfc_e2e_rubric_branches_on_ui_capable():
    # Spec-0054/T4：起草/评审据固化的 ui_capable 分流——具备浏览器时 UI 改动 method 必须要求截图；
    # 不具备时不得因缺截图 REWORK。两条规则互斥地进入 RFC 任务。
    capable = _task_for(kind="rfc", pr_number=5, ui_capable=True)
    incapable = _task_for(kind="rfc", pr_number=5, ui_capable=False)
    assert "本机具备浏览器能力" in capable
    assert "method 必须要求真实导航后的截图为证" in capable
    assert "本机无浏览器能力" in incapable
    assert "不得因 method 没要求真实截图就 REWORK" in incapable


def test_code_review_task_has_evidence_rubric():
    # Spec-0054/T4：code rubric 含「读证据判运行时行为」+ 缺证据/证据对不上 → REWORK，
    # 统一证据落点 docs/e2e-results/<pr>/（并入 0044 的 docs/evidence）。
    code_task = _task_for(kind="code", pr_number=7, ui_capable=False)
    assert "缺运行时证据" in code_task
    assert "证据与意图对不上" in code_task
    assert "docs/e2e-results/7/" in code_task
    # 无浏览器时软判（不因缺截图 REWORK）。
    assert "软判" in code_task


def test_evidence_rubric_only_on_code_not_rfc():
    # Spec-0054/T4：运行时行为/证据检查只挂代码 review，不挂 spec 文档 review。
    rfc_task = _task_for(kind="rfc", pr_number=7, ui_capable=True)
    assert "docs/e2e-results/7/" not in rfc_task
    assert "缺运行时证据" not in rfc_task


# --------------------------------------------------------------------------- #
# Spec-0050/T1：裁决理由语言/长度硬化——理由必须一段简短中文
# --------------------------------------------------------------------------- #


def test_rubric_tail_requires_short_chinese_reason():
    # Spec-0050/T1：_RUBRIC_TAIL 含「面向人类的裁决理由…必须用一段简短的中文」硬规约，
    # 且明确覆盖 REASON/ISSUES/NEXT——把「用中文简短说」从示例偏置升级为硬性输出要求。
    assert "简短" in _RUBRIC_TAIL
    assert "中文" in _RUBRIC_TAIL
    assert "REASON" in _RUBRIC_TAIL
    assert "ISSUES" in _RUBRIC_TAIL
    assert "NEXT" in _RUBRIC_TAIL
    # 语义锚点：并列于裁决前置的一句明确语言/长度硬规约。
    assert "必须用一段简短的中文" in _RUBRIC_TAIL


def test_rubric_tail_examples_are_short_chinese_samples():
    # Spec-0050/T1：REASON/ISSUES/NEXT 示例文案显式绑定「一句话中文」，作为简短中文正样板。
    assert "一句话中文说明核对的关键验证标准" in _RUBRIC_TAIL
    assert "一句话中文点出问题" in _RUBRIC_TAIL
    assert "一句话中文说明修复方向" in _RUBRIC_TAIL


def test_short_chinese_constraint_on_both_code_and_rfc_gates():
    # Spec-0050/T1：共享 tail 使两道闸同时生效——code 与 rfc 生成的完整任务文本都含该语言/长度约束。
    code_task = _task_for(kind="code", pr_number=9, ui_capable=False)
    rfc_task = _task_for(kind="rfc", pr_number=9, ui_capable=True)
    for task in (code_task, rfc_task):
        assert "必须用一段简短的中文" in task
        assert "REASON / ISSUES / NEXT" in task


# --------------------------------------------------------------------------- #
# Spec-0048/T1：防 design-as-implementation——三处 rubric 硬化
# --------------------------------------------------------------------------- #


def test_code_review_task_has_automation_integrity_rubric():
    # Spec-0048/T1：code rubric 含「自动化完整性硬规则」，明列主流程触发点 / artifact 自动产生并
    # commit / 正例·反例 / 集成路径而非局部函数 五问，并写明判罚话术。
    code_task = _task_for(kind="code", pr_number=7, ui_capable=False)
    assert "自动化完整性" in code_task
    assert "主流程触发点" in code_task
    assert "artifact 自动产生并 commit" in code_task
    assert "正例·反例" in code_task
    assert "集成路径而非局部函数" in code_task
    assert "缺完整链路证据 → REWORK，理由：只实现骨架，未证明完整链路" in code_task


def test_automation_integrity_rubric_is_conditional_not_on_pure_refactor():
    # Spec-0048/T1：条件式触发——明说纯静态/重构/文档不查，避免误伤纯内部改动（与 _EVIDENCE_RUBRIC 同构）。
    code_task = _task_for(kind="code", pr_number=7, ui_capable=False)
    assert "自动化执行链路" in code_task
    assert "纯静态" in code_task and "重构" in code_task


def test_rfc_review_task_has_automation_overpromise_rubric():
    # Spec-0048/T1：rfc 闸多一条「自动化 spec 防过度承诺」——承诺自动化链路则 Reference-level 必须声明
    # 触发时机/调用方/artifact 落点/失败路径/正·反例验收。
    rfc_task = _task_for(kind="rfc", pr_number=5, ui_capable=True)
    assert "自动化 spec 防过度承诺" in rfc_task
    for anchor in ("触发时机", "调用方", "artifact 落点", "失败路径", "正·反例验收"):
        assert anchor in rfc_task


def test_rfc_automation_rubric_only_on_rfc_not_code():
    # Spec-0048/T1：闸别隔离——「自动化 spec 防过度承诺」只挂 rfc 闸，不出现在 code 闸（与无证据检查镜像）。
    code_task = _task_for(kind="code", pr_number=7, ui_capable=False)
    assert "自动化 spec 防过度承诺" not in code_task
    assert "artifact 落点" not in code_task


def test_evidence_rubric_extended_to_automation_capability_claims():
    # Spec-0048/T1：无证据检查延伸到「宣称实现了自动化执行/门控能力…无真实产物或集成证据 → REWORK」，
    # 且仍只挂 code 闸、不挂 rfc 闸。
    code_task = _task_for(kind="code", pr_number=7, ui_capable=False)
    assert "宣称实现了自动化执行/门控能力" in code_task
    assert "无真实产物或集成证据 → REWORK" in code_task
    rfc_task = _task_for(kind="rfc", pr_number=7, ui_capable=True)
    assert "宣称实现了自动化执行/门控能力" not in rfc_task


def test_code_rubric_guides_skeleton_pr_toward_rework():
    # Spec-0048/T1 fixture 风格：构造真实 _task_for(kind="code")，对「只加 executor/evidence_gate
    # 模块、门控位置对、只有模块级单测、无主流程接线」的骨架冒充 PR（PR #105 复刻场景），断言 review 任务
    # 文本齐备五问要素，足以把 reviewer 导向 REWORK（受限于 reviewer 依赖真 backend 推理不可 hermetic，
    # 这里断言的是「引导文本齐备」而非真跑一个 agent，见 spec Drawbacks）。
    code_task = _task_for(kind="code", pr_number=105, ui_capable=False)
    # 场景：PR 声称新增 executor/evidence_gate 自动化链路——触发条件命中。
    assert "executor" in code_task and "evidence gate" in code_task
    # 五问要素齐备，逐条对应该场景的每个缺口：
    # ① 触发点缺失（无主流程接线）
    assert "主流程触发点" in code_task
    # ② 未接线（只定义模块）
    assert "被调用证据" in code_task or "没接线" in code_task
    # ③ artifact 未自动产出/commit
    assert "artifact 自动产生并 commit" in code_task
    # ④ 无正反例
    assert "正例" in code_task and "反例" in code_task
    # ⑤ 只测局部而非集成路径
    assert "集成路径而非局部函数" in code_task
    # 判罚话术齐备：缺任一 → REWORK，理由「只实现骨架，未证明完整链路」。
    assert "只实现骨架，未证明完整链路" in code_task


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
    # Spec-0052/T2：_run_reviewers 新增 history 形参（默认空）；打桩 lambda 的签名随之带上
    # history（否则 review() 传 history=… 时 lambda 报意外 kwarg）——仅同步 mock 签名，不改断言。
    monkeypatch.setattr(
        "openagents.reviewer._run_reviewers",
        lambda *, backend, work_dir, task, n, history="": summaries,
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


# --------------------------------------------------------------------------- #
# Spec-0047/T1：extract_decision_content——render_decision 的逆向去重身份解析器
# --------------------------------------------------------------------------- #


def test_extract_roundtrips_with_render_rework():
    # render → extract 往返一致：抽出的类型/裁决行与 render 一致，反馈规范化后含原文关键句。
    decision = ReviewDecision(
        passed=False,
        feedback="foo.py:10 缺边界处理\nbar.py:3 未处理 None",
        verdicts=("REWORK",),
        actionable=True,
    )
    body = render_decision(decision=decision, kind="code")
    content = extract_decision_content(body=body)
    assert content is not None
    assert content.kind_line == "- 类型：代码"
    assert content.verdict_line == "- 裁决：❌ REWORK"
    assert content.feedback_norm == "foo.py:10 缺边界处理\nbar.py:3 未处理 None"


def test_extract_excludes_identity_signature_tail():
    # 含 identity 署名尾巴的 comment.body 仍正确抽出三段，且 feedback_norm 不含签名。
    decision = ReviewDecision(
        passed=False, feedback="缺单测", verdicts=("REWORK",), actionable=True
    )
    rendered = render_decision(decision=decision, kind="code")
    signed = rendered + "\n\n---\n🤖 由 agent-x 自动发布\n"
    content = extract_decision_content(body=signed)
    assert content is not None
    assert content.verdict_line == "- 裁决：❌ REWORK"
    assert content.feedback_norm == "缺单测"
    assert "agent-x" not in content.feedback_norm
    assert "🤖" not in content.feedback_norm


def test_extract_pass_has_empty_feedback_norm():
    # PASS 裁决 render 不产「反馈摘要」块 → feedback_norm == ""。
    decision = ReviewDecision(passed=True, feedback="", verdicts=("PASS", "PASS"))
    body = render_decision(decision=decision, kind="rfc")
    content = extract_decision_content(body=body)
    assert content is not None
    assert content.verdict_line == "- 裁决：✅ PASS"
    assert content.feedback_norm == ""


def test_extract_feedback_norm_whitespace_insensitive():
    # 两段仅缩进/空行不同的反馈，规范化后相等。
    base = render_decision(
        decision=ReviewDecision(
            passed=False, feedback="a\nb", verdicts=("REWORK",), actionable=True
        ),
        kind="code",
    )
    # 手工在反馈块里塞入前导空格与多余空行，模拟措辞未变仅排版漂移。
    drifted = base.replace("a\nb", "  a  \n\n   b\n")
    left = extract_decision_content(body=base)
    right = extract_decision_content(body=drifted)
    assert left is not None and right is not None
    assert left.feedback_norm == right.feedback_norm == "a\nb"


def test_extract_feedback_with_code_fence_not_truncated():
    # issue #116 / PR #117 回归：反馈正文本身含代码围栏（```）时不被截断——
    # render 把 feedback 裹在外层围栏里，内部围栏须被完整纳入 feedback_norm。
    feedback = "```\ndef f():\n    ...\n```\n卡点：f 未处理 None"
    body = render_decision(
        decision=ReviewDecision(
            passed=False, feedback=feedback, verdicts=("REWORK",), actionable=True
        ),
        kind="code",
    )
    content = extract_decision_content(body=body)
    assert content is not None
    # 内部围栏行与其后正文都在，未被首个闭合围栏截断。
    assert content.feedback_norm == "```\ndef f():\n...\n```\n卡点：f 未处理 None"


def test_extract_two_fenced_reworks_differ_not_deduped():
    # issue #116 核心验收：两条**理由不同**但都以 fenced code 示例开头的 REWORK，
    # feedback_norm 必须不同——否则会被 _decision_already_posted 误判重复而静默抑制。
    def norm(feedback):
        body = render_decision(
            decision=ReviewDecision(
                passed=False, feedback=feedback, verdicts=("REWORK",), actionable=True
            ),
            kind="code",
        )
        content = extract_decision_content(body=body)
        assert content is not None
        return content.feedback_norm

    first = norm("```\nx = 1\n```\n第一轮卡点：缺边界处理")
    second = norm("```\nx = 1\n```\n第二轮卡点：越权访问")
    assert first != second
    assert first != "" and second != ""


def test_extract_non_decision_markdown_is_none():
    # 无稳定抬头的普通评论 → None。
    assert extract_decision_content(body="随便一条 PR 评论\n看看代码") is None
    assert extract_decision_content(body="") is None


def test_extract_missing_kind_or_verdict_is_none():
    # 有抬头但缺类型/裁决行（残缺评论）→ None，不误判为裁决。
    assert extract_decision_content(body="## 评审闸裁决\n- 票数：1 票中 1 票 PASS") is None


def test_decision_content_is_frozen():
    # frozen dataclass：去重身份不可变。
    content = DecisionContent(
        kind_line="- 类型：代码", verdict_line="- 裁决：✅ PASS", feedback_norm=""
    )
    with pytest.raises(AttributeError):
        content.feedback_norm = "x"
