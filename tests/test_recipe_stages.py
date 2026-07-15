"""Spec-0064/T2: recipes.stages 九原子阶段函数契约单测——假 backend 喂 canned 裁决 / 假 github 读。

证明九阶段抽成 Vigil 类外自由函数后各 hermetic 可测：judgment 段按 agent 结构化裁决返回、机械段
读客观事实经 gates 分类；交付类阶段的三道硬闸真兜底（head 未前移 / 证据戳不符 → raise）；rfc 阶段
只依赖 drafter。全程不触真实 LLM/网络/仓库。
"""

from __future__ import annotations

import json

import pytest

from openagents.backends.base import AgentResult
from openagents.recipes import stages
from openagents.runtime import gates
from openagents.runtime.gates import GateError


def _seq_head_sha(monkeypatch, *, values):
    """把 gates.git.head_sha 打成「按调用序返回、耗尽后钉末值」的桩，区分交付前/后 head。"""
    seq = list(values)
    box = {"last": seq[-1] if seq else ""}

    def _fake(*, work_dir):
        if seq:
            box["last"] = seq.pop(0)
        return box["last"]

    monkeypatch.setattr(gates.git, "head_sha", _fake)


class _Backend:
    """按 task 里 agent 自称路由，回 canned 末行 JSON。"""

    name = "scripted"

    def __init__(self, *, payloads):
        self._payloads = payloads
        self.calls = []

    def run(self, *, work_dir, task, context):
        for marker, kind in (
            ("分诊 agent", "triager"),
            ("起草 agent", "drafter"),
            ("实现 agent", "implementer"),
            ("评审 agent", "reviewer"),
            ("交付 agent", "deliver"),
        ):
            if marker in task:
                self.calls.append(kind)
                return AgentResult(changed=True, summary=json.dumps(self._payloads[kind]))
        raise AssertionError(f"未知 agent task: {task[:40]}")


class _Issue:
    number = 7
    title = "t"
    body = "b"


# ---- judgment 段 ----


def test_triage_returns_actionable_verdict():
    backend = _Backend(payloads={"triager": {"actionable": True, "reason": "ok"}})
    verdict = stages.triage(backend=backend, work_dir=".", issue=_Issue())
    assert verdict["actionable"] is True
    assert backend.calls == ["triager"]


def test_review_returns_verdict():
    backend = _Backend(payloads={"reviewer": {"verdict": "REWORK", "reason": "fix"}})
    verdict = stages.review(
        backend=backend, work_dir=".", pr_number=3, issue_body="b", context_text="c"
    )
    assert verdict["verdict"] == "REWORK"


def test_implement_returns_summary():
    backend = _Backend(payloads={"implementer": {"summary": "done"}})
    out = stages.implement(
        backend=backend,
        work_dir=".",
        issue_number=1,
        pr_number=2,
        feedback="",
        context_text="c",
    )
    assert out["summary"] == "done"


def test_rfc_only_depends_on_drafter(monkeypatch):
    # 交付前后 head 不同 → head 前移闸放行；证据戳与交付后 head 一致。
    _seq_head_sha(monkeypatch, values=["BEFORE", "AFTER"])
    backend = _Backend(
        payloads={"drafter": {"delivered": True, "head_sha": "AFTER", "summary": "drafted"}}
    )
    verdict = stages.rfc(
        backend=backend,
        worktree="/wt",
        mode=stages.MODE_DRAFT,
        target="issue #1",
        branch="b",
        detail="d",
        context_text="c",
        require_delivered=False,
    )
    assert verdict["summary"] == "drafted"
    assert backend.calls == ["drafter"]


def test_rfc_backfill_require_delivered_shortcircuits(monkeypatch):
    # backfill 未过 validate（delivered=false）→ 原样返回、不进硬闸（caller 据此不开 PR）。
    _seq_head_sha(monkeypatch, values=["SAME", "SAME"])  # head 没动，但 require_delivered 先短路
    backend = _Backend(payloads={"drafter": {"delivered": False, "head_sha": "", "summary": "no"}})
    verdict = stages.rfc(
        backend=backend,
        worktree="/wt",
        mode=stages.MODE_BACKFILL,
        target="path",
        branch="b",
        detail="d",
        context_text="c",
        require_delivered=True,
    )
    assert verdict["delivered"] is False


# ---- 交付类硬闸 ----


def test_deliver_head_not_advanced_raises(monkeypatch):
    _seq_head_sha(monkeypatch, values=["SAME", "SAME"])  # 交付前后同 head → 未前移。
    backend = _Backend(
        payloads={
            "deliver": {
                "delivered": True,
                "base_sha": "x",
                "head_sha": "SAME",
                "summary": "s",
            }
        }
    )
    with pytest.raises(GateError):
        stages.deliver(backend=backend, worktree="/wt", branch="b", pr_number=1, issue_number=1)


def test_deliver_evidence_stamp_mismatch_raises(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE", "AFTER"])
    backend = _Backend(
        payloads={
            "deliver": {
                "delivered": True,
                "base_sha": "x",
                "head_sha": "WRONG",  # 自报 ≠ 实际 AFTER。
                "summary": "s",
            }
        }
    )
    with pytest.raises(GateError):
        stages.deliver(backend=backend, worktree="/wt", branch="b", pr_number=1, issue_number=1)


# ---- conflict（deliver rebase）----


def test_conflict_no_backend_unmergeable():
    out = stages.conflict(backend=None, work_dir=".", pr_number=1, issue_number=1, branch="b")
    assert out["reason"] == "unmergeable"
    assert out["delivered"] is False


def test_conflict_delivered_resolved(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE", "AFTER"])
    backend = _Backend(
        payloads={
            "deliver": {"delivered": True, "base_sha": "x", "head_sha": "AFTER", "summary": "s"}
        }
    )
    out = stages.conflict(backend=backend, work_dir="/wt", pr_number=1, issue_number=1, branch="b")
    assert out["reason"] == "resolved"


# ---- 机械段 ci / e2e / merge ----


def test_ci_reads_check_status(monkeypatch):
    class _Status:
        def __init__(self, state):
            self.state = state
            self.failed_logs = []

    monkeypatch.setattr(stages.github, "check_status", lambda *, pr_number: _Status("fail"))
    assert stages.ci(pr_number=1) == stages.CI_FAIL
    monkeypatch.setattr(stages.github, "check_status", lambda *, pr_number: _Status("pending"))
    assert stages.ci(pr_number=1) == stages.CI_PENDING
    monkeypatch.setattr(stages.github, "check_status", lambda *, pr_number: _Status("pass"))
    assert stages.ci(pr_number=1) == stages.CI_PASS


def test_e2e_no_stamp_ok(monkeypatch):
    monkeypatch.setattr(stages, "_pr_evidence_stamp", lambda *, pr_number: None)
    assert stages.e2e(pr_number=1) == stages.E2E_OK


def test_e2e_stale_stamp(monkeypatch):
    # 实际 head != 自报 → stale。
    monkeypatch.setattr(stages, "_pr_evidence_stamp", lambda *, pr_number: ("REAL", "CLAIMED"))
    assert stages.e2e(pr_number=1) == stages.E2E_STALE


def test_e2e_matching_stamp_ok(monkeypatch):
    monkeypatch.setattr(stages, "_pr_evidence_stamp", lambda *, pr_number: ("H", "H"))
    assert stages.e2e(pr_number=1) == stages.E2E_OK


def test_merge_gate_passes_then_dispatches_merger(monkeypatch):
    # Spec-0066/T3: 硬闸放行 → 经 engine.run_agent 派 merger agent 落合并（返回 {merged, summary}）。
    gate_calls = {}
    agent_calls = []
    monkeypatch.setattr(
        stages.gates,
        "assert_merge_allowed",
        lambda *, pr_number, head_sha: gate_calls.update(pr=pr_number, head=head_sha),
    )

    def _fake_run_agent(agent_module, *, backend, **kw):
        agent_calls.append((agent_module.__name__, kw))
        return {"merged": True, "summary": "已合并"}

    monkeypatch.setattr(stages.engine, "run_agent", _fake_run_agent)

    out = stages.merge(
        backend=object(),
        pr_number=42,
        head_sha="abc123",
        work_dir="/tmp/wt",
        context_text="ctx",
    )
    assert gate_calls == {"pr": 42, "head": "abc123"}  # 闸先被调、绑 head sha
    assert len(agent_calls) == 1 and agent_calls[0][0].endswith("merger")  # 放行后才派 merger
    assert out == {"merged": True, "summary": "已合并"}


def test_merge_gate_blocks_and_agent_not_dispatched(monkeypatch):
    # Spec-0066/T3: 闸抛 GateError → **决不派 agent**（agent 只能在闸放行后落合并动作，防合未审代码）。
    agent_calls = []

    def _boom(*, pr_number, head_sha):
        raise GateError("CI 非全绿")

    monkeypatch.setattr(stages.gates, "assert_merge_allowed", _boom)
    monkeypatch.setattr(
        stages.engine,
        "run_agent",
        lambda *a, **k: agent_calls.append(1) or {"merged": True, "summary": ""},
    )
    with pytest.raises(GateError):
        stages.merge(
            backend=object(),
            pr_number=42,
            head_sha="abc123",
            work_dir="/tmp/wt",
            context_text="ctx",
        )
    assert agent_calls == []  # merger 未被调用
