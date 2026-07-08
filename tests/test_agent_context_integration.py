"""Spec-0052/T4：#128 式历史复现集成测试——统一 agent 上下文注入的成果测试。

用内存假 github（评论账本）复现触发 issue #129 的 PR #128 式历史：历轮 reviewer FAIL 裁决评论
（用**真实** reviewer.render_decision 渲染 + identity 签名，drift-catching）、作者「已把 result.md
改成 PASS」refine 说明（用**真实** orchestrator._REFINE_COMMENT + 签名）、一条人类评论、一条 agent
认领便签噪声（用**真实** identity.build_claim_note）。断言：

1. build_agent_context 产出含 PR 号 + 三类历史（裁决/作者回复/人类评论，带作者与轮次）+ 本轮反馈；
2. 认领便签 / 隐藏签名噪声被滤除，不出现在 context 里；
3. 用捕获 prompt 的假 backend 驱动 orchestrator 的 refine_rfc / implement / iterate：其派给 backend
   的 task 含 PR 号、context 含历史（补上两个 PR 号缺口 + 全入口注入历史）；
4. reviewer.review(history=…) 把历史送进 backend.run 的 context，且评审任务模板含「落盘产物为准、
   评论仅供参考」rubric（保留独立性的同时可见历史）。

全程不触网、不调真实 gh/LLM/git 远端——机器噪声/裁决/refine 说明都由**真实产品渲染函数**造，故
agentcontext 里的本地分类标记若与产品渲染漂移，本测试会翻红（防启发式规则悄悄失配）。
"""

import subprocess

from openagents import agentcontext, identity, reviewer
from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Comment
from openagents.reviewer import ReviewDecision
from openagents.state import State

# --- PR #128 式历史账本：全部用真实产品渲染函数造，drift-catching ------------------- #

_REVIEWER_AGENT = "reviewer-1"
_AUTHOR_AGENT = "author-1"
_CLAIMER_AGENT = "claimer-9"

# ① 历轮 reviewer FAIL 裁决（真实 render_decision + 真实 identity 签名）。
_DECISION_BODY = identity.sign(
    body=reviewer.render_decision(
        decision=ReviewDecision(
            passed=False,
            feedback="result.md 仍是 skipped，未见真实运行证据",
            verdicts=("REWORK",),
            actionable=True,
        ),
        kind="code",
    ),
    agent_id=_REVIEWER_AGENT,
)
# ② 作者 refine 说明（真实 _REFINE_COMMENT + 签名）。
_REFINE_BODY = identity.sign(
    body=orch_module._REFINE_COMMENT.format(summary="已把 result.md 改成 PASS"),
    agent_id=_AUTHOR_AGENT,
)
# ③ 人类评论（无签名）。
_HUMAN_BODY = "人类补充判断：以仓库里 result.md 的真实内容为准，别只看评论说辞"
# ④ agent 认领便签噪声（真实 build_claim_note）。
_CLAIM_BODY = identity.build_claim_note(agent_id=_CLAIMER_AGENT)


def _ledger():
    return [
        Comment(id="1", author="claimer", body=_CLAIM_BODY, created_at="2026-06-01T00:00:00Z"),
        Comment(id="2", author="reviewer", body=_DECISION_BODY, created_at="2026-06-02T00:00:00Z"),
        Comment(id="3", author="author", body=_REFINE_BODY, created_at="2026-06-03T00:00:00Z"),
        Comment(id="4", author="alice", body=_HUMAN_BODY, created_at="2026-06-04T00:00:00Z"),
    ]


def _patch_ledger(monkeypatch):
    monkeypatch.setattr(agentcontext.github, "list_comments", lambda *, pr_number: _ledger())


# --- 断言 1 & 2：build_agent_context 三类历史进 / 噪声出 ---------------------------- #


def test_build_agent_context_reproduces_128_history_and_filters_noise(monkeypatch):
    _patch_ledger(monkeypatch)
    ctx = agentcontext.build_agent_context(
        pr_number=128, extra_detail="本轮反馈：请再核对 result.md"
    )

    # 断言 1：PR 号 + 三类历史（带作者与轮次）+ 本轮反馈。
    assert "本 PR 是 #128" in ctx
    assert "评审闸裁决" in ctx and "result.md 仍是 skipped" in ctx  # 历轮裁决
    assert "已把 result.md 改成 PASS" in ctx  # 作者 refine 回复
    assert "以仓库里 result.md 的真实内容为准" in ctx  # 人类评论
    assert "· reviewer ·" in ctx and "· author ·" in ctx and "· alice ·" in ctx  # 作者标注
    assert "轮 ·" in ctx  # 轮次标注
    assert "本轮反馈：请再核对 result.md" in ctx  # 本轮反馈

    # 断言 2：认领便签整条滤除 + 一切隐藏签名剥离。
    assert "认领本 issue" not in ctx  # 认领便签正文
    assert "openagents:claim" not in ctx  # 认领标记
    assert "openagents:agent=" not in ctx  # 任何 agent 签名

    # 轮次随时序：裁决(第1轮，claim 被滤) < refine < 人类。
    assert ctx.index("result.md 仍是 skipped") < ctx.index("已把 result.md 改成 PASS")
    assert ctx.index("已把 result.md 改成 PASS") < ctx.index("以仓库里 result.md 的真实内容为准")


# --- 断言 3：捕获 prompt 的假 backend 驱动 orchestrator 三入口 ---------------------- #


class _CaptureBackend:
    name = "capture"

    def __init__(self, *, summaries=("VERDICT: PASS",)):
        self._summaries = list(summaries)
        self._index = 0
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"task": task, "context": context})
        summary = self._summaries[self._index % len(self._summaries)]
        self._index += 1
        return AgentResult(changed=True, summary=summary)


class _GitRecorder:
    def __call__(self, args, **kwargs):
        class _Proc:
            returncode = 0
            # Spec-0056/T2：交付后 harness 调 assert_delivered（rev-parse origin/<branch> 与 HEAD
            # 对比）；两处 rev-parse 回同一 SHA → head 前移硬闸放行（模拟 agent 已推上）。
            if "comments" in args:
                stdout = '{"comments": []}'
            elif "rev-parse" in args:
                stdout = "deadbeefcafe"
            else:
                stdout = ""
            stderr = ""

        return _Proc()


def _orch(tmp_path, monkeypatch, *, backend):
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = orch_module.Orchestrator(
        backend=backend, state=state, work_dir=tmp_path, agent_id="agent-x"
    )
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    # orchestrator 与 agentcontext 引用同一 github 模块；一次 patch 覆盖 build_agent_context 的拉取。
    monkeypatch.setattr(orch_module.github, "list_comments", lambda *, pr_number: _ledger())
    monkeypatch.setattr(orch_module.github, "post_comment", lambda *, pr_number, body: None)
    monkeypatch.setattr(orch_module.github, "mark_ready", lambda *, pr_number: None)
    monkeypatch.setattr(
        orch_module.identity, "post_signed_comment", lambda *, pr_number, body, agent_id: None
    )
    state.record_run(
        issue_number=3, branch="openagents/issue-3", pr=PR(number=128, url="u/pull/128")
    )
    return orch


def test_orchestrator_entrypoints_inject_pr_number_and_history(tmp_path, monkeypatch):
    backend = _CaptureBackend()
    orch = _orch(tmp_path, monkeypatch, backend=backend)

    orch.refine_rfc(pr_number=128, detail="reviewer 本轮意见", announce=False)
    orch.implement(pr_number=128)
    orch.iterate(pr_number=128, reason="ci", detail="CI 反馈")

    refine_call, implement_call, iterate_call = backend.calls
    # refine / implement 的 task 都含 PR 号（缺口一）。
    assert "PR #128" in refine_call["task"]
    assert "PR #128" in implement_call["task"]
    # 三入口 context 都含本 PR 历史 + PR 号（缺口二），认领噪声不进。
    for call in (refine_call, implement_call, iterate_call):
        assert "本 PR 是 #128" in call["context"]
        assert "评审闸裁决" in call["context"]
        assert "以仓库里 result.md 的真实内容为准" in call["context"]
        assert "openagents:claim" not in call["context"]
    # 各入口本轮反馈进 context。
    assert "reviewer 本轮意见" in refine_call["context"]
    assert "CI 反馈" in iterate_call["context"]


# --- 断言 4：reviewer 得历史 + rubric 生效 ---------------------------------------- #


def test_reviewer_receives_history_and_templates_have_primacy_rubric(tmp_path, monkeypatch):
    backend = _CaptureBackend(summaries=("VERDICT: PASS",))
    orch = _orch(tmp_path, monkeypatch, backend=backend)

    decision = orch.review_code(pr_number=128)

    assert decision.passed is True
    ctx = backend.calls[0]["context"]
    # reviewer 的 backend context 收到本 PR 历史（不再失忆）。
    assert "本 PR 是 #128" in ctx
    assert "评审闸裁决" in ctx
    assert "以仓库里 result.md 的真实内容为准" in ctx
    # 两个评审任务模板均含「落盘产物为准、评论仅供参考」rubric。
    for template in (reviewer._RFC_REVIEW_TASK, reviewer._CODE_REVIEW_TASK):
        assert "落盘产物为准" in template
        assert "评论仅供参考" in template
