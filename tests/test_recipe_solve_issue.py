"""Spec-0060/T6: recipes.solve_issue 契约路由单测——假 backend 喂 canned 结构化输出。

证明架构契约：recipe 只按 agent 的结构化裁决路由（PASS→next / REWORK→loop）、自身零业务判断；
最小硬闸真能兜底（head 未前移 / 证据戳不符 / 超轮次 → raise）。head 前移的基点由 recipe 经
`gates.snapshot_head` **确定性记录**（不取 agent 自述 base_sha），故用桩序列区分交付前/后 head。
全程假 backend，不触真实 LLM/网络/仓库。
"""

from __future__ import annotations

import json

import pytest

from openagents.backends.base import AgentResult
from openagents.recipes.solve_issue import solve_issue
from openagents.runtime import gates
from openagents.runtime.gates import GateError


def _seq_head_sha(monkeypatch, *, values):
    """把 gates.git.head_sha 打成「按调用序返回、耗尽后钉在末值」的桩，以区分交付前/后 head。"""
    seq = list(values)
    state = {"last": seq[-1] if seq else ""}

    def _fake(*, work_dir):
        if seq:
            state["last"] = seq.pop(0)
        return state["last"]

    monkeypatch.setattr(gates.git, "head_sha", _fake)


class _ScriptedBackend:
    """按 task prompt 里的 agent 自称路由，回该 agent 的 canned 末行 JSON。"""

    name = "scripted"

    def __init__(self, *, reviewer_verdicts, delivered_head="HEADSHA"):
        self._reviews = list(reviewer_verdicts)
        self._delivered_head = delivered_head
        self.calls = []

    def run(self, *, work_dir, task, context):
        if "起草 agent" in task:
            kind, summary = "planner", json.dumps({"summary": "drafted"})
        elif "实现 agent" in task:
            kind, summary = "implementer", json.dumps({"summary": "impl"})
        elif "评审 agent" in task:
            verdict = self._reviews.pop(0) if self._reviews else "REWORK"
            kind, summary = "reviewer", json.dumps({"verdict": verdict, "reason": "r"})
        elif "交付 agent" in task:
            kind = "deliver"
            summary = json.dumps(
                {
                    "delivered": True,
                    "base_sha": "AGENT_SELF_REPORTED",  # 仅交叉校验用，硬闸不信它
                    "head_sha": self._delivered_head,
                    "summary": "pushed",
                }
            )
        else:  # pragma: no cover - 测试里不应出现
            raise AssertionError(f"未知 agent task: {task[:40]}")
        self.calls.append(kind)
        return AgentResult(changed=True, summary=summary)


class _FakeCtx:
    """最简上下文桩：产出各阶段占位符 dict（含 work_dir）+ workspace 路径。"""

    workspace = "/tmp/wt"

    def for_plan(self, *, issue_number):
        return {"work_dir": ".", "issue_number": issue_number, "issue_body": "b"}

    def for_implement(self, *, issue_number):
        return {"work_dir": ".", "issue_number": issue_number, "pr_number": 1, "feedback": ""}

    def for_iterate(self, *, issue_number, feedback):
        payload = self.for_implement(issue_number=issue_number)
        payload["feedback"] = feedback
        return payload

    def for_review(self, *, issue_number):
        return {"work_dir": ".", "pr_number": 1, "issue_body": "b"}

    def for_deliver(self, *, issue_number):
        return {"work_dir": ".", "branch": "openagents/issue-1", "pr_number": 1}


def test_rework_rework_pass_loops_then_delivers(monkeypatch):
    # 交付前 snapshot_head 读 "BASE"，交付后 assert_head_advanced 读 "MOVED"（前移）→ 放行；
    # deliver 自述 head_sha 与实际 after "MOVED" 一致 → 证据戳通过。
    _seq_head_sha(monkeypatch, values=["BASE", "MOVED"])
    backend = _ScriptedBackend(
        reviewer_verdicts=["REWORK", "REWORK", "PASS"], delivered_head="MOVED"
    )

    report = solve_issue(issue_number=145, backend=backend, ctx=_FakeCtx())

    # implementer：1 首轮 + 2 迭代 = 3；reviewer：3 次；循环在 PASS 后 next 到 deliver。
    assert backend.calls.count("implementer") == 3
    assert backend.calls.count("reviewer") == 3
    assert backend.calls == [
        "planner",
        "implementer",
        "reviewer",
        "implementer",
        "reviewer",
        "implementer",
        "reviewer",
        "deliver",
    ]
    assert report["delivered"] is True


def test_deliver_head_not_advanced_raises(monkeypatch):
    # 交付前后 head 恒为 "BASE"（head 未前移，哪怕 agent 自述 base_sha 造假也拦不住）→ 硬闸 raise。
    _seq_head_sha(monkeypatch, values=["BASE"])  # 耗尽后钉在 "BASE"，交付前后同值
    backend = _ScriptedBackend(reviewer_verdicts=["PASS"])
    with pytest.raises(GateError):
        solve_issue(issue_number=145, backend=backend, ctx=_FakeCtx())


def test_deliver_evidence_stamp_mismatch_raises(monkeypatch):
    # head 确实前移（BASE→MOVED），但 deliver 自述 head_sha 报了个别处的 SHA → 证据戳硬闸 raise。
    _seq_head_sha(monkeypatch, values=["BASE", "MOVED"])
    backend = _ScriptedBackend(reviewer_verdicts=["PASS"], delivered_head="ELSEWHERE")
    with pytest.raises(GateError):
        solve_issue(issue_number=145, backend=backend, ctx=_FakeCtx())


def test_reviewer_always_rework_hits_round_cap(monkeypatch):
    monkeypatch.setattr(gates, "DEFAULT_MAX_ROUNDS", 3)
    _seq_head_sha(monkeypatch, values=["MOVEDSHA"])
    backend = _ScriptedBackend(reviewer_verdicts=[])  # 恒回 REWORK
    with pytest.raises(GateError):
        solve_issue(issue_number=145, backend=backend, ctx=_FakeCtx())
    # 跑满 3 轮：reviewer 3 次、implementer 1 首轮 + 3 迭代 = 4，从未走到 deliver。
    assert backend.calls.count("reviewer") == 3
    assert "deliver" not in backend.calls
