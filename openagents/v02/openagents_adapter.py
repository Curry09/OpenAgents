# Spec-0085/T1
"""Production adapter from the v0.2 scheduler to existing OpenAgents mechanics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openagents.agents import developer, spec_curator
from openagents.recipes import stages
from openagents.runtime import context, engine, gates, research
from openagents.utils import forge, git
from openagents.utils.workspace import Workspace
from openagents.v02.model import (
    AcceptanceResult,
    DevelopmentResult,
    IssueInput,
    NodeResult,
    SpecNode,
)

_BRANCH_PREFIX = "openagents/v02-issue-"


class OpenAgentsAdapter:
    """Run v0.2 roles while keeping git/forge facts in deterministic code."""

    def __init__(self, *, backend: Any, work_dir: Path, base: str = "main") -> None:
        self._backend = backend
        self._work_dir = Path(work_dir)
        self._base = base

    def write_spec(self, *, issue: IssueInput) -> SpecNode | NodeResult:
        branch = f"{_BRANCH_PREFIX}{issue.number}"
        worktree = Workspace(work_dir=self._work_dir).prepare(
            issue_number=issue.number, branch=branch, base=self._base
        )
        report = stages.minimal_spec(
            backend=self._backend,
            worktree=worktree,
            issue_number=issue.number,
            issue_title=issue.title,
            issue_body=issue.body,
            branch=branch,
            context_text=_runtime_contract(base=self._base),
        )
        status = str(report["status"])
        if status != "READY":
            return NodeResult(
                issue.number,
                status,
                str(report.get("blocker") or report.get("summary") or status),
                str(report.get("head_sha") or ""),
                evidence=tuple(_strings(report.get("evidence_pack", []))),
            )
        snapshot = stages.minimal_design_snapshot(work_dir=worktree, issue_number=issue.number)
        selected = dict(report.get("selected_intervention") or {})
        files = _selected_files(selected=selected)
        if not files:
            return NodeResult(
                issue.number,
                "FAILED",
                "READY Spec 缺少 selected_intervention.files，无法生成可靠 DAG",
                str(report.get("head_sha") or ""),
            )
        return SpecNode(
            issue=issue,
            branch=branch,
            worktree=worktree,
            spec_path=Path(snapshot["spec_path"]),
            spec_digest=snapshot["design_digest"],
            summary=str(report.get("summary") or ""),
            files=files,
            selected_intervention=selected,
            evidence_pack=tuple(research.normalize(report.get("evidence_pack", []))),
        )

    def curate(self, *, nodes: tuple[SpecNode, ...]) -> list[dict]:
        frozen = [
            {
                "issue": node.number,
                "summary": node.summary,
                "files": list(node.files),
                "selected_intervention": node.selected_intervention,
            }
            for node in nodes
        ]
        verdict = engine.run_agent(
            spec_curator,
            backend=self._backend,
            work_dir=self._work_dir,
            context=context.sections(
                ("frozen READY specs", json.dumps(frozen, ensure_ascii=False, sort_keys=True))
            ),
        )
        return list(verdict["edges"])

    def develop(self, *, node: SpecNode) -> DevelopmentResult:
        stages.assert_minimal_design_approved(
            work_dir=node.worktree,
            issue_number=node.number,
            approved_digest=node.spec_digest,
        )
        pr = forge.find_pr_by_branch(branch=node.branch)
        if pr is None:
            pr = forge.create_pr(
                branch=node.branch,
                base=self._base,
                title=f"feat: issue #{node.number} {node.issue.title}".strip(),
                body=f"Closes #{node.number}\n\nOpenAgents v0.2 frozen-Spec delivery.",
                draft=True,
            )
        before = gates.snapshot_head(workspace=node.worktree)
        spec_text = node.spec_path.read_text(encoding="utf-8")
        verdict = engine.run_agent(
            developer,
            backend=self._backend,
            work_dir=node.worktree,
            context=context.sections(
                ("original issue", f"# {node.number} {node.issue.title}\n\n{node.issue.body}"),
                ("frozen compact spec", spec_text),
                ("runtime contract", _runtime_contract(base=self._base)),
            ),
            issue_number=node.number,
            branch=node.branch,
        )
        status = str(verdict["status"])
        if status not in {"DELIVERED", "FAILED", "NEEDS_DECISION"}:
            raise gates.GateError(f"v0.2 Developer 返回未知状态：{status!r}")
        if status != "DELIVERED":
            return DevelopmentResult(
                status=status,
                summary=str(verdict["summary"]),
                reason=str(verdict["reason"]),
                evidence=tuple(_strings(verdict["evidence"])),
                pr_number=pr.number,
            )
        after = gates.assert_head_advanced(before=before, workspace=node.worktree)
        gates.assert_evidence_stamp(head_sha=after, claimed=str(verdict["head_sha"]))
        if dirty := git.porcelain(work_dir=node.worktree):
            raise gates.GateError(f"Developer 交付后 worktree 不干净：{dirty[:200]}")
        Workspace(work_dir=self._work_dir).assert_delivered(
            worktree=node.worktree, branch=node.branch
        )
        stages.assert_minimal_design_approved(
            work_dir=node.worktree,
            issue_number=node.number,
            approved_digest=node.spec_digest,
        )
        return DevelopmentResult(
            status=status,
            head_sha=after,
            summary=str(verdict["summary"]),
            changed_files=tuple(_strings(verdict["changed_files"])),
            evidence=tuple(_strings(verdict["evidence"])),
            reason=str(verdict["reason"]),
            pr_number=pr.number,
        )

    def accept(self, *, node: SpecNode, development: DevelopmentResult) -> AcceptanceResult:
        if development.pr_number is None:
            raise gates.GateError(f"issue #{node.number} 没有 PR，不能验收")
        if dirty := git.porcelain(work_dir=node.worktree):
            raise gates.GateError(f"Acceptance 前 worktree 不干净：{dirty[:200]}")
        before = gates.snapshot_head(workspace=node.worktree)
        evidence = {
            "developer_summary": development.summary,
            "developer_changed_files": list(development.changed_files),
            "developer_evidence": list(development.evidence),
            "frozen_spec_digest": node.spec_digest,
            "candidate_head": development.head_sha,
        }
        verdict = stages.acceptance(
            backend=self._backend,
            work_dir=node.worktree,
            issue_number=node.number,
            pr_number=development.pr_number,
            issue_title=node.issue.title,
            issue_body=node.issue.body,
            context_text=context.sections(
                ("frozen compact spec", node.spec_path.read_text(encoding="utf-8")),
                ("objective execution record", json.dumps(evidence, ensure_ascii=False)),
            ),
        )
        after = gates.snapshot_head(workspace=node.worktree)
        if after != before or after != development.head_sha:
            raise gates.GateError("Acceptance 期间 HEAD 发生变化，裁决作废")
        if dirty := git.porcelain(work_dir=node.worktree):
            raise gates.GateError(f"Acceptance 修改了 worktree，裁决作废：{dirty[:200]}")
        return AcceptanceResult(
            verdict=str(verdict["verdict"]),
            reason=str(verdict["reason"]),
            evidence=tuple(_strings(verdict["evidence"])),
            head_sha=after,
        )

    def merge(self, *, node: SpecNode, development: DevelopmentResult) -> None:
        if development.pr_number is None:
            raise gates.GateError(f"issue #{node.number} 没有 PR，不能合并")
        current = gates.snapshot_head(workspace=node.worktree)
        if current != development.head_sha:
            raise gates.GateError("Developer HEAD 在合并前已变化，Acceptance PASS 作废")
        stages.assert_minimal_design_approved(
            work_dir=node.worktree,
            issue_number=node.number,
            approved_digest=node.spec_digest,
        )
        label = f"review-approved:{current[:7]}"
        forge.add_label(pr_number=development.pr_number, name=label)
        if forge.is_draft(pr_number=development.pr_number):
            forge.mark_ready(pr_number=development.pr_number)
        stages.merge_mechanical(
            pr_number=development.pr_number,
            head_sha=current,
            require_ci=True,
        )


def _selected_files(*, selected: dict) -> tuple[str, ...]:
    raw = selected.get("files") or selected.get("affected_files") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ()
    return tuple(sorted({item.strip() for item in raw if isinstance(item, str) and item.strip()}))


def _strings(raw: object) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(item) for item in raw]


def _runtime_contract(*, base: str) -> str:
    return (
        "当前 worktree 是唯一可写仓库。不得访问父 checkout、其它 worktree 或宿主路径。"
        f"开始实现前 fetch origin/{base} 并在需要时把当前分支 rebase 到该基线；"
        "只允许对当前 v0.2 issue 分支使用 --force-with-lease。不得修改冻结 compact Spec。"
    )


__all__ = ["OpenAgentsAdapter"]
