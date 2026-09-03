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
            ("Spec Writer", "spec_writer"),
            ("实现 agent", "implementer"),
            ("coding executor", "executor"),
            ("Acceptance Reviewer", "acceptance"),
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
        payloads={
            "drafter": {
                "delivered": True,
                "head_sha": "AFTER",
                "summary": "drafted",
                "evidence_pack": [],
            }
        }
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


def test_minimal_spec_ready_is_delivery_gated(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE", "AFTER"])
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: False)
    backend = _Backend(
        payloads={
            "spec_writer": {
                "status": "READY",
                "head_sha": "AFTER",
                "summary": "compact spec",
                "blocker": "",
                "objective_coverage": [{"scope_coverage": "FULL", "evidence_level": "STRUCTURAL"}],
                "candidate_assessments": [{
                    "candidate": "one", "ownership": "runtime", "delivery": "wired",
                    "control_effect": "guard", "evidence": "source", "assumptions": "none",
                    "failure_modes": "bypass", "verdict": "selected",
                }],
                "selected_intervention": {},
                "evidence_pack": [],
                "falsifiers": [],
            }
        }
    )
    verdict = stages.minimal_spec(
        backend=backend,
        worktree="/wt",
        issue_number=7,
        issue_title="objective",
        issue_body="must stay intact",
        branch="openagents/issue-7",
        context_text="minimal",
    )
    assert verdict["status"] == "READY"
    assert backend.calls == ["spec_writer"]


def test_minimal_spec_blocked_does_not_require_empty_commit(monkeypatch):
    _seq_head_sha(monkeypatch, values=["SAME"])
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: False)
    backend = _Backend(
        payloads={
            "spec_writer": {
                "status": "BLOCKED",
                "head_sha": "",
                "summary": "cannot preserve objective",
                "blocker": "read-only boundary",
                "objective_coverage": [],
                "candidate_assessments": [],
                "selected_intervention": {},
                "evidence_pack": [],
                "falsifiers": [],
            }
        }
    )
    verdict = stages.minimal_spec(
        backend=backend,
        worktree="/wt",
        issue_number=7,
        issue_title="objective",
        issue_body="must stay intact",
        branch="openagents/issue-7",
        context_text="minimal",
    )
    assert verdict["status"] == "BLOCKED"


def test_minimal_spec_partial_is_retained_with_delivery_gate(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE", "AFTER"])
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: False)
    backend = _Backend(
        payloads={
            "spec_writer": {
                "status": "PARTIAL",
                "head_sha": "AFTER",
                "summary": "useful but incomplete",
                "blocker": "one objective is unclosed",
                "objective_coverage": [{"scope_coverage": "PARTIAL", "evidence_level": "HYPOTHESIS"}],
                "candidate_assessments": [{
                    "candidate": "one", "ownership": "model", "delivery": "unknown",
                    "control_effect": "unknown", "evidence": "none", "assumptions": "compliance",
                    "failure_modes": "ignored", "verdict": "selected",
                }],
                "selected_intervention": {},
                "evidence_pack": [],
                "falsifiers": [],
            }
        }
    )
    verdict = stages.minimal_spec(
        backend=backend,
        worktree="/wt",
        issue_number=7,
        issue_title="objective",
        issue_body="must stay intact",
        branch="openagents/issue-7",
        context_text="minimal",
    )
    assert verdict["status"] == "PARTIAL"


def test_minimal_spec_rejects_non_uniform_candidate_evidence(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE"])
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: False)
    backend = _Backend(
        payloads={
            "spec_writer": {
                "status": "PARTIAL",
                "head_sha": "AFTER",
                "summary": "compressed away the evidence standard",
                "blocker": "open",
                "objective_coverage": [{"scope_coverage": "PARTIAL", "evidence_level": "HYPOTHESIS"}],
                "candidate_assessments": [{"candidate": "one", "reason": "looks good"}],
                "selected_intervention": {},
                "evidence_pack": [],
                "falsifiers": [],
            }
        }
    )
    with pytest.raises(GateError, match="候选未使用统一证据字段"):
        stages.minimal_spec(
            backend=backend,
            worktree="/wt",
            issue_number=7,
            issue_title="objective",
            issue_body="must stay intact",
            branch="openagents/issue-7",
            context_text="minimal",
        )


def test_minimal_design_snapshot_requires_fixed_compact_contract(tmp_path):
    path = tmp_path / "docs" / "objectives" / "issue-7.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Issue 7\n\n"
        "## Objective ledger\nfull\n\n"
        "## Repository evidence\nfacts\n\n"
        "## Intervention analysis\ncandidates\n\n"
        "## Selected mechanism and causal chain\nchain\n\n"
        "## Implementation task\nfiles\n\n"
        "## Independent acceptance\nreplay\n",
        encoding="utf-8",
    )
    first = stages.minimal_design_snapshot(work_dir=tmp_path, issue_number=7)
    stages.assert_minimal_design_approved(
        work_dir=tmp_path, issue_number=7, approved_digest=first["design_digest"]
    )
    path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    with pytest.raises(GateError, match="发生变化"):
        stages.assert_minimal_design_approved(
            work_dir=tmp_path, issue_number=7, approved_digest=first["design_digest"]
        )


def test_execute_compact_spec_uses_executor_and_head_gates(monkeypatch, tmp_path):
    backend = _Backend(
        payloads={
            "executor": {
                "summary": "implemented",
                "head_sha": "after",
                "lookup_exception_reason": "",
            }
        }
    )
    heads = iter(["before", "after", "after"])
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: next(heads))
    monkeypatch.setattr(gates, "assert_head_advanced", lambda *, before, workspace: None)
    stamps = []
    monkeypatch.setattr(
        gates,
        "assert_evidence_stamp",
        lambda *, head_sha, claimed: stamps.append((head_sha, claimed)),
    )

    result = stages.execute_compact_spec(
        backend=backend,
        work_dir=tmp_path,
        issue_number=3,
        pr_number=8,
        context_text="compact",
    )

    assert backend.calls == ["executor"]
    assert result["summary"] == "implemented"
    assert stamps == [("after", "after")]


def test_acceptance_has_three_terminal_verdicts(monkeypatch):
    backend = _Backend(
        payloads={
            "acceptance": {
                "verdict": "PARTIAL",
                "reason": "hard half missing",
                "evidence": ["replayed original failure"],
            }
        }
    )
    verdict = stages.acceptance(
        backend=backend,
        work_dir=".",
        issue_number=7,
        pr_number=8,
        issue_title="objective",
        issue_body="complete behavior",
        context_text="minimal",
    )
    assert verdict["verdict"] == "PARTIAL"
    assert backend.calls == ["acceptance"]


def test_rfc_backfill_require_delivered_shortcircuits(monkeypatch):
    # backfill 未过 validate（delivered=false）→ 原样返回、不进硬闸（caller 据此不开 PR）。
    _seq_head_sha(monkeypatch, values=["SAME", "SAME"])  # head 没动，但 require_delivered 先短路
    backend = _Backend(
        payloads={
            "drafter": {
                "delivered": False,
                "head_sha": "",
                "summary": "no",
                "evidence_pack": [],
            }
        }
    )
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


def test_rfc_retry_accepts_unchanged_already_delivered_head(monkeypatch):
    _seq_head_sha(monkeypatch, values=["EXISTING", "EXISTING"])
    delivered = {}
    monkeypatch.setattr(
        stages.Workspace,
        "assert_delivered",
        lambda self, *, worktree, branch: delivered.update(branch=branch),
    )
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: True)
    backend = _Backend(
        payloads={
            "drafter": {
                "delivered": True,
                "head_sha": "EXISTING",
                "summary": "validated existing artifact",
                "evidence_pack": [],
            }
        }
    )

    verdict = stages.rfc(
        backend=backend,
        worktree="/wt",
        mode=stages.MODE_DRAFT,
        target="issue #1",
        branch="openagents/issue-1",
        detail="d",
        context_text="c",
        require_delivered=False,
    )

    assert verdict["head_sha"] == "EXISTING"
    assert delivered == {"branch": "openagents/issue-1"}


def test_design_snapshot_prefers_branch_changed_spec_on_duplicate_issue(tmp_path, monkeypatch):
    from openagents.spec import model
    from openagents.spec.model import Group, Metadata, Overview

    root = tmp_path / "docs" / "specs"
    for number, slug in (("0001", "seed"), ("0004", "candidate")):
        model.dump_group(
            group=Group(
                number=number,
                metadata=Metadata(title=slug, issue=7, slug=slug, summary="s"),
                tasks=[],
                overview=Overview(
                    summary="s", motivation="m", reference_level="r", rationale_alternatives="a"
                ),
            ),
            path=root / f"{number}-{slug}.md",
        )
    monkeypatch.setattr(
        stages.Workspace,
        "changed_spec_group",
        lambda self, *, worktree, base: root / "0004-candidate.md",
    )

    snapshot = stages.design_snapshot(work_dir=tmp_path, issue_number=7)

    assert snapshot["spec_path"].endswith("0004-candidate.md")


def test_architecture_dispatches_before_implementation(tmp_path, monkeypatch):
    from openagents.spec import model
    from openagents.spec.model import Group, Metadata, Overview

    root = tmp_path / "docs" / "specs"
    model.dump_group(
        group=Group(
            number="0001",
            metadata=Metadata(title="x", issue=7, slug="x", summary="s"),
            tasks=[],
            overview=Overview(
                summary="s", motivation="m", reference_level="r", rationale_alternatives="a"
            ),
        ),
        path=root / "0001-x.md",
    )
    captured = {}
    monkeypatch.setattr(
        stages.engine,
        "run_agent",
        lambda module, *, backend, **kwargs: (
            captured.update(kwargs)
            or {
                "verdict": "PASS",
                "objective_fidelity": "ok",
                "intervention_fit": "ok",
                "boundary_integrity": "ok",
                "verification_strength": "ok",
                "reason": "ok",
                "findings": [],
            }
        ),
    )
    result = stages.architecture(
        backend=object(),
        work_dir=tmp_path,
        issue_number=7,
        evidence_pack=[
            {
                "fact": "timeout is polled",
                "path": "entry.py",
                "symbol": "_run_supervised",
                "verification": "read body",
                "decision": "must not cross the role boundary",
            }
        ],
    )
    assert result["verdict"] == "PASS"
    assert result["design_digest"] == captured["design_digest"]
    assert "timeout is polled" in captured["context"]
    assert "decision" not in captured["context"]
    assert "spec_text" not in captured


def test_implement_receives_normalized_evidence_pack(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        stages.engine,
        "run_agent",
        lambda module, *, backend, **kwargs: captured.update(kwargs) or {"summary": "done"},
    )
    stages.implement(
        backend=object(),
        work_dir=".",
        issue_number=1,
        pr_number=2,
        feedback="",
        context_text="c",
        evidence_pack=[{"fact": "f", "path": "entry.py", "judgment": "choose A"}],
    )
    assert '"fact":"f"' in captured["context"]
    assert "judgment" not in captured["context"]


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
    out = stages.conflict(
        backend=backend,
        work_dir="/wt",
        pr_number=1,
        issue_number=1,
        branch="b",
        base="trunk",
    )
    assert out["reason"] == "resolved"
    assert backend.calls == ["deliver"]


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
    # Spec-0017/T3: 硬闸放行 → 经 engine.run_agent 派 merger agent 落合并（返回 {merged, summary}）。
    gate_calls = {}
    agent_calls = []
    monkeypatch.setattr(
        stages.gates,
        "assert_merge_allowed",
        lambda *, pr_number, head_sha, require_ci=True: gate_calls.update(
            pr=pr_number, head=head_sha, require_ci=require_ci
        ),
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
    assert gate_calls == {"pr": 42, "head": "abc123", "require_ci": True}  # 闸先被调、绑 head sha
    assert len(agent_calls) == 1 and agent_calls[0][0].endswith("merger")  # 放行后才派 merger
    assert out == {"merged": True, "summary": "已合并"}


def test_merge_gate_blocks_and_agent_not_dispatched(monkeypatch):
    # Spec-0017/T3: 闸抛 GateError → **决不派 agent**（agent 只能在闸放行后落合并动作，防合未审代码）。
    agent_calls = []

    def _boom(*, pr_number, head_sha, require_ci=True):
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


def test_merge_mechanical_uses_gate_then_forge_without_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        stages.gates,
        "assert_merge_allowed",
        lambda *, pr_number, head_sha, require_ci=True: calls.append(
            ("gate", pr_number, head_sha, require_ci)
        ),
    )
    monkeypatch.setattr(
        stages.github,
        "merge_pr",
        lambda *, pr_number: calls.append(("merge", pr_number)),
    )
    out = stages.merge_mechanical(pr_number=42, head_sha="abc", require_ci=True)
    assert calls == [("gate", 42, "abc", True), ("merge", 42)]
    assert out["merged"] is True
