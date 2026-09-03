# Spec-0084/T1, Spec-0085/T1
"""Immutable values shared by the v0.2 planner and batch runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class IssueInput:
    """The original objective authority for one batch node."""

    number: int
    title: str
    body: str


@dataclass(frozen=True)
class SpecNode:
    """A frozen READY Spec projected to the fields needed after design."""

    issue: IssueInput
    branch: str
    worktree: Path
    spec_path: Path
    spec_digest: str
    summary: str
    files: tuple[str, ...] = ()
    selected_intervention: dict = field(default_factory=dict)
    evidence_pack: tuple[dict, ...] = ()

    @property
    def number(self) -> int:
        return self.issue.number


@dataclass(frozen=True)
class Plan:
    """Validated blocker map and stable topological execution layers."""

    blocked_by: dict[int, tuple[int, ...]]
    batches: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class DevelopmentResult:
    status: str
    head_sha: str = ""
    summary: str = ""
    changed_files: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    reason: str = ""
    pr_number: int | None = None


@dataclass(frozen=True)
class AcceptanceResult:
    verdict: str
    reason: str = ""
    evidence: tuple[str, ...] = ()
    head_sha: str = ""


@dataclass(frozen=True)
class NodeResult:
    issue_number: int
    status: str
    reason: str = ""
    head_sha: str = ""
    pr_number: int | None = None
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchResult:
    plan: Plan | None
    nodes: dict[int, NodeResult]
    plan_error: str = ""
    specs: dict[int, dict] = field(default_factory=dict)
