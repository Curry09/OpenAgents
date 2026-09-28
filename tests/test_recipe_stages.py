"""Spec-0064/T2: recipes.stages 九原子阶段函数契约单测——假 backend 喂 canned 裁决 / 假 github 读。

证明九阶段抽成 Vigil 类外自由函数后各 hermetic 可测：judgment 段按 agent 结构化裁决返回、机械段
读客观事实经 gates 分类；交付类阶段的三道硬闸真兜底（head 未前移 / 证据戳不符 → raise）；rfc 阶段
只依赖 drafter。全程不触真实 LLM/网络/仓库。
Spec-0056 补充：2026-09-09-delivery-review-snapshot-tests-design.md 的 push-only 恢复回归。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openagents.backends.base import AgentResult
from openagents.recipes import stages
from openagents.runtime import gates
from openagents.runtime.gates import GateError
from openagents.utils.workspace import WorkspaceError


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
        self.tasks = []
        self.contexts = []

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
                self.tasks.append(task)
                self.contexts.append(context)
                payload = self._payloads[kind]
                if isinstance(payload, list):
                    payload = payload.pop(0)
                return AgentResult(changed=True, summary=json.dumps(payload))
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
    delivered = []
    monkeypatch.setattr(
        stages.Workspace,
        "assert_delivered",
        lambda self, *, worktree, branch: delivered.append((worktree, branch)),
    )
    backend = _Backend(
        payloads={
            "spec_writer": {
                "status": "READY",
                "head_sha": "MODEL-COPIED-WRONG-SHA",
                "summary": "compact spec",
                "blocker": "",
                "objective_coverage": [{"scope_coverage": "FULL", "evidence_level": "HYPOTHESIS"}],
                "candidate_assessments": [
                    {
                        "candidate": "one",
                        "ownership": "runtime",
                        "delivery": "wired",
                        "control_effect": "guard",
                        "evidence": "source",
                        "assumptions": "none",
                        "failure_modes": "bypass",
                        "verdict": "selected",
                    }
                ],
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
    assert verdict["head_sha"] == "AFTER"
    assert verdict["reported_head_sha"] == "MODEL-COPIED-WRONG-SHA"
    assert delivered == [(Path("/wt"), "openagents/issue-7")]
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


def test_minimal_spec_repairs_ready_with_partial_coverage_before_implementation(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE", "AFTER"])
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: False)
    monkeypatch.setattr(
        stages.Workspace,
        "assert_delivered",
        lambda self, *, worktree, branch: None,
    )
    common = {
        "summary": "compact spec",
        "candidate_assessments": [
            {
                "candidate": "one",
                "ownership": "runtime",
                "delivery": "wired",
                "control_effect": "guard",
                "evidence": "source",
                "assumptions": "behavior awaits implementation",
                "failure_modes": "bypass",
                "verdict": "selected",
            }
        ],
        "selected_intervention": {},
        "evidence_pack": [],
        "falsifiers": [],
    }
    backend = _Backend(
        payloads={
            "spec_writer": [
                common
                | {
                    "status": "READY",
                    "blocker": "",
                    "objective_coverage": [
                        {
                            "id": "OC-1",
                            "scope_coverage": "PARTIAL",
                            "evidence_level": "HYPOTHESIS",
                        }
                    ],
                },
                common
                | {
                    "status": "READY",
                    "blocker": "",
                    "objective_coverage": [
                        {
                            "id": "OC-1",
                            "scope_coverage": "FULL",
                            "evidence_level": "HYPOTHESIS",
                        }
                    ],
                },
            ]
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
    assert verdict["objective_coverage"][0] == {
        "id": "OC-1",
        "scope_coverage": "FULL",
        "evidence_level": "HYPOTHESIS",
    }
    assert backend.calls == ["spec_writer", "spec_writer"]
    assert "`AUTHOR`" in backend.tasks[0]
    assert "`CONTRACT_REPAIR`" in backend.tasks[1]
    assert "不是要求在实现前提供行为证据" in backend.contexts[1]


def test_minimal_spec_rejects_ready_still_partial_after_contract_repair(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE"])
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: False)
    inconsistent = {
        "status": "READY",
        "summary": "still contradictory",
        "blocker": "",
        "objective_coverage": [
            {"id": "OC-1", "scope_coverage": "PARTIAL", "evidence_level": "HYPOTHESIS"}
        ],
        "candidate_assessments": [
            {
                "candidate": "one",
                "ownership": "runtime",
                "delivery": "wired",
                "control_effect": "guard",
                "evidence": "source",
                "assumptions": "unknown",
                "failure_modes": "bypass",
                "verdict": "selected",
            }
        ],
        "selected_intervention": {},
        "evidence_pack": [],
        "falsifiers": [],
    }
    backend = _Backend(payloads={"spec_writer": [inconsistent, inconsistent]})

    with pytest.raises(GateError, match="CONTRACT_REPAIR 后仍自相矛盾"):
        stages.minimal_spec(
            backend=backend,
            worktree="/wt",
            issue_number=7,
            issue_title="objective",
            issue_body="must stay intact",
            branch="openagents/issue-7",
            context_text="minimal",
        )

    assert backend.calls == ["spec_writer", "spec_writer"]


def test_minimal_spec_repairs_written_but_uncommitted_artifact_once(monkeypatch, tmp_path):
    spec_path = tmp_path / "docs" / "objectives" / "issue-7.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("draft awaiting delivery\n", encoding="utf-8")
    _seq_head_sha(monkeypatch, values=["BEFORE", "BEFORE", "AFTER"])
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: False)
    delivered = []
    monkeypatch.setattr(
        stages.Workspace,
        "assert_delivered",
        lambda self, *, worktree, branch: delivered.append((worktree, branch)),
    )
    backend = _Backend(
        payloads={
            "spec_writer": {
                "status": "READY",
                "summary": "compact spec",
                "blocker": "",
                "objective_coverage": [{"scope_coverage": "FULL", "evidence_level": "STRUCTURAL"}],
                "candidate_assessments": [
                    {
                        "candidate": "one",
                        "ownership": "runtime",
                        "delivery": "wired",
                        "control_effect": "guard",
                        "evidence": "source",
                        "assumptions": "none",
                        "failure_modes": "bypass",
                        "verdict": "selected",
                    }
                ],
                "selected_intervention": {},
                "evidence_pack": [],
                "falsifiers": [],
            }
        }
    )

    verdict = stages.minimal_spec(
        backend=backend,
        worktree=tmp_path,
        issue_number=7,
        issue_title="objective",
        issue_body="must stay intact",
        branch="openagents/issue-7",
        context_text="minimal",
    )

    assert verdict["status"] == "READY"
    assert verdict["head_sha"] == "AFTER"
    assert backend.calls == ["spec_writer", "spec_writer"]
    assert "`AUTHOR`" in backend.tasks[0]
    assert "`DELIVERY_REPAIR`" in backend.tasks[1]
    assert "上次结构化结论" in backend.tasks[1]
    assert delivered == [(tmp_path, "openagents/issue-7")]


def test_minimal_spec_does_not_repair_when_no_artifact_exists(monkeypatch, tmp_path):
    _seq_head_sha(monkeypatch, values=["SAME", "SAME", "SAME"])
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: False)
    backend = _Backend(
        payloads={
            "spec_writer": {
                "status": "READY",
                "summary": "claimed without artifact",
                "blocker": "",
                "objective_coverage": [{"scope_coverage": "FULL", "evidence_level": "STRUCTURAL"}],
                "candidate_assessments": [
                    {
                        "candidate": "one",
                        "ownership": "runtime",
                        "delivery": "wired",
                        "control_effect": "guard",
                        "evidence": "source",
                        "assumptions": "none",
                        "failure_modes": "bypass",
                        "verdict": "selected",
                    }
                ],
                "selected_intervention": {},
                "evidence_pack": [],
                "falsifiers": [],
            }
        }
    )

    with pytest.raises(GateError, match="head 未前移"):
        stages.minimal_spec(
            backend=backend,
            worktree=tmp_path,
            issue_number=7,
            issue_title="objective",
            issue_body="must stay intact",
            branch="openagents/issue-7",
            context_text="minimal",
        )

    assert backend.calls == ["spec_writer"]


def test_minimal_spec_partial_is_retained_with_delivery_gate(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE", "AFTER"])
    monkeypatch.setattr(stages.Workspace, "remote_branch_exists", lambda self, *, branch: False)
    monkeypatch.setattr(
        stages.Workspace,
        "assert_delivered",
        lambda self, *, worktree, branch: None,
    )
    backend = _Backend(
        payloads={
            "spec_writer": {
                "status": "PARTIAL",
                "head_sha": "AFTER",
                "summary": "useful but incomplete",
                "blocker": "one objective is unclosed",
                "objective_coverage": [
                    {"scope_coverage": "PARTIAL", "evidence_level": "HYPOTHESIS"}
                ],
                "candidate_assessments": [
                    {
                        "candidate": "one",
                        "ownership": "model",
                        "delivery": "unknown",
                        "control_effect": "unknown",
                        "evidence": "none",
                        "assumptions": "compliance",
                        "failure_modes": "ignored",
                        "verdict": "selected",
                    }
                ],
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
                "objective_coverage": [
                    {"scope_coverage": "PARTIAL", "evidence_level": "HYPOTHESIS"}
                ],
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
        "## Objective contract\nfull\n\n"
        "## Observed mechanism and evidence\nfacts\n\n"
        "## Decision rationale\ncandidates\n\n"
        "## Invariants and risk ledger\nrisks\n\n"
        "## Developer design envelope\nboundaries\n\n"
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


def test_minimal_design_snapshot_warns_on_noncanonical_format(tmp_path):
    """格式差异只告警；非空 Objective Contract 仍可冻结 digest 并进入开发。"""
    path = tmp_path / "docs" / "objectives" / "issue-7.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Objective Contract — Issue #7\n\n"
        "## 1. Objective contract\nobjective\n\n"
        "## 2. Observed mechanism and evidence\nevidence\n\n"
        "## 3. Decision rationale\nrationale\n\n"
        "## 4. Invariants and risk ledger\nrisks\n\n"
        "## 5. Developer design envelope\nboundaries\n\n"
        "## 6. Independent acceptance\nacceptance\n",
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match="格式警告"):
        snapshot = stages.minimal_design_snapshot(work_dir=tmp_path, issue_number=7)

    assert snapshot["design_digest"]
    assert snapshot["format_warning"].startswith("minimal objective spec 格式警告")


def test_minimal_design_snapshot_rejects_empty_contract(tmp_path):
    path = tmp_path / "docs" / "objectives" / "issue-7.md"
    path.parent.mkdir(parents=True)
    path.write_text("  \n", encoding="utf-8")

    with pytest.raises(GateError, match="为空"):
        stages.minimal_design_snapshot(work_dir=tmp_path, issue_number=7)


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
                "evidence": [
                    {
                        "case_id": "original",
                        "source": "original_replay",
                        "kind": "behavior",
                        "observed": "failure remains",
                        "expected": "failure removed",
                        "path": "pytest test_original",
                        "passed": False,
                    }
                ],
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


def test_acceptance_pass_requires_original_replay_and_independent_variant():
    backend = _Backend(
        payloads={
            "acceptance": {
                "verdict": "PASS",
                "reason": "both objective-level cases pass",
                "evidence": [
                    {
                        "case_id": "original",
                        "source": "original_replay",
                        "kind": "behavior",
                        "observed": "prohibited action did not execute",
                        "expected": "course correction changes the next action",
                        "path": "artifacts/original.log",
                        "passed": True,
                    },
                    {
                        "case_id": "paraphrase",
                        "source": "independent_variant",
                        "kind": "behavior",
                        "observed": "different correction was also respected",
                        "expected": "semantic variant is not overfit to the sample",
                        "path": "artifacts/paraphrase.log",
                        "passed": True,
                    },
                ],
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

    assert verdict["verdict"] == "PASS"


def test_acceptance_host_rejects_pass_with_explicit_failed_case():
    backend = _Backend(
        payloads={
            "acceptance": {
                "verdict": "PASS",
                "reason": "claimed pass despite failure",
                "evidence": [
                    {
                        "case_id": "original",
                        "source": "original_replay",
                        "kind": "behavior",
                        "observed": "directive was ignored",
                        "expected": "directive changes behavior",
                        "path": "artifacts/original.log",
                        "passed": False,
                    },
                    {
                        "case_id": "variant",
                        "source": "independent_variant",
                        "kind": "behavior",
                        "observed": "variant passed",
                        "expected": "variant passes",
                        "path": "artifacts/variant.log",
                        "passed": True,
                    },
                ],
            }
        }
    )

    with pytest.raises(GateError, match="明确标记为未通过"):
        stages.acceptance(
            backend=backend,
            work_dir=".",
            issue_number=7,
            pr_number=8,
            issue_title="objective",
            issue_body="complete behavior",
            context_text="minimal",
        )


def test_acceptance_host_rejects_pass_without_independent_variant():
    backend = _Backend(
        payloads={
            "acceptance": {
                "verdict": "PASS",
                "reason": "only replayed developer sample",
                "evidence": [
                    {
                        "case_id": "original",
                        "source": "original_replay",
                        "kind": "behavior",
                        "observed": "sample passed",
                        "expected": "sample passes",
                        "path": "artifacts/original.log",
                        "passed": True,
                    }
                ],
            }
        }
    )

    with pytest.raises(GateError, match="independent_variant"):
        stages.acceptance(
            backend=backend,
            work_dir=".",
            issue_number=7,
            pr_number=8,
            issue_title="objective",
            issue_body="complete behavior",
            context_text="minimal",
        )


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
        "changed_spec_groups",
        lambda self, *, worktree, base: [root / "0004-candidate.md"],
    )

    snapshot = stages.design_snapshot(work_dir=tmp_path, issue_number=7)

    assert snapshot["spec_path"].endswith("0004-candidate.md")
    # Spec-0088/T1: both audit identity and versioned semantic identity are retained.
    group = model.load_group(path=root / "0004-candidate.md")
    assert snapshot["design_raw_digest"] == model.legacy_design_digest(group=group)
    assert snapshot["design_digest"] == model.design_digest(group=group)


def test_design_snapshot_selects_own_spec_after_foreign_spec(tmp_path, monkeypatch):
    from openagents.spec import model
    from openagents.spec.model import Group, Metadata, Overview

    root = tmp_path / "docs" / "specs"
    for number, slug, issue in (("0004", "foreign", 35), ("0006", "candidate", 54)):
        model.dump_group(
            group=Group(
                number=number,
                metadata=Metadata(title=slug, issue=issue, slug=slug, summary="s"),
                tasks=[],
                overview=Overview(
                    summary="s", motivation="m", reference_level="r", rationale_alternatives="a"
                ),
            ),
            path=root / f"{number}-{slug}.md",
        )
    monkeypatch.setattr(
        stages.Workspace,
        "changed_spec_groups",
        lambda self, *, worktree, base: [
            root / "0004-foreign.md",
            root / "0006-candidate.md",
        ],
    )

    snapshot = stages.design_snapshot(work_dir=tmp_path, issue_number=54)

    assert snapshot["spec_path"].endswith("0006-candidate.md")


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


def _stub_delivery_git(monkeypatch, *, head, remote):
    """Spec-0056 recovery: exercise the delivery gate against explicit offline Git facts."""

    def workspace_git(self, *, args, cwd, check):
        if args[0] == "rev-parse":
            output = head if args[1] == "HEAD" else remote
        elif args[0] in {"fetch", "status"}:
            output = ""
        else:
            raise RuntimeError(f"delivery test has no Git stub for {args!r}")
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(stages.Workspace, "_git", workspace_git)


def test_deliver_unpublished_commit_raises(monkeypatch):
    _seq_head_sha(monkeypatch, values=["SAME", "SAME"])
    _stub_delivery_git(monkeypatch, head="SAME", remote="OLDER")
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
    with pytest.raises(WorkspaceError):
        stages.deliver(backend=backend, worktree="/wt", branch="b", pr_number=1, issue_number=1)


def test_delivery_snapshot_push_only_delivery_does_not_require_an_empty_commit(monkeypatch):
    """Spec-0056 补充：已 commit 的实现补 push 即交付，不应再要求 HEAD 前移。"""
    head = "b" * 40
    remote = {"head": "a" * 40}
    _seq_head_sha(monkeypatch, values=[head])
    monkeypatch.setattr(gates.git, "porcelain", lambda *, work_dir: "")

    def workspace_git(self, *, args, cwd, check):
        if args[0] == "rev-parse":
            output = head if args[1] == "HEAD" else remote["head"]
        elif args[0] == "ls-remote":
            output = f"{remote['head']}\trefs/heads/b\n"
        elif args[0] in {"fetch", "status"}:
            output = ""
        else:
            raise RuntimeError(f"push-only test has no Git stub for {args!r}")
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(stages.Workspace, "_git", workspace_git)
    backend = _Backend(
        payloads={
            "deliver": {
                "delivered": True,
                "base_sha": head,
                "head_sha": head,
                "summary": "pushed existing commit",
            }
        }
    )
    run = backend.run

    def push_and_return(*, work_dir, task, context):
        remote["head"] = head
        return run(work_dir=work_dir, task=task, context=context)

    monkeypatch.setattr(backend, "run", push_and_return)
    error = None
    try:
        stages.deliver(backend=backend, worktree="/wt", branch="b", pr_number=1, issue_number=1)
    except GateError as exc:
        error = exc
    assert backend.calls == ["deliver"] and remote["head"] == head
    assert error is None, f"补 push 已完成，不能因没造新 commit 而报无进展：{error}"


def test_deliver_evidence_stamp_mismatch_raises(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE", "AFTER"])
    _stub_delivery_git(monkeypatch, head="AFTER", remote="AFTER")
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
    _stub_delivery_git(monkeypatch, head="AFTER", remote="AFTER")
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


def test_conflict_preserves_undelivered_agent_diagnostics(monkeypatch):
    _seq_head_sha(monkeypatch, values=["BEFORE", "AFTER"])
    _stub_delivery_git(monkeypatch, head="AFTER", remote="BEFORE")
    backend = _Backend(
        payloads={
            "deliver": {
                "delivered": False,
                "base_sha": "BEFORE",
                "head_sha": "AFTER",
                "summary": "rebase continue failed on generated index",
            }
        }
    )

    out = stages.conflict(
        backend=backend,
        work_dir="/wt",
        pr_number=1,
        issue_number=1,
        branch="b",
    )

    assert out["delivered"] is False
    assert "generated index" in out["reason"]
    assert out["gate"] == "conflict"


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
        lambda *, pr_number, head_sha: calls.append(("merge", pr_number, head_sha)),
    )
    out = stages.merge_mechanical(pr_number=42, head_sha="abc", require_ci=True)
    assert calls == [("gate", 42, "abc", True), ("merge", 42, "abc")]
    assert out["merged"] is True
