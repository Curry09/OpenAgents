# Spec-0085/T1
"""Minimal v0.2 batch orchestration, independent from the legacy Vigil state machine."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from openagents.v02.model import (
    AcceptanceResult,
    BatchResult,
    DevelopmentResult,
    IssueInput,
    NodeResult,
    SpecNode,
)
from openagents.v02.planner import build_plan

_SUCCESS = "PASS"


class BatchAdapter(Protocol):
    """All repository, model and forge effects used by the pure batch scheduler."""

    def write_spec(self, *, issue: IssueInput) -> SpecNode | NodeResult: ...

    def curate(self, *, nodes: tuple[SpecNode, ...]) -> list[dict]: ...

    def develop(self, *, node: SpecNode) -> DevelopmentResult: ...

    def accept(self, *, node: SpecNode, development: DevelopmentResult) -> AcceptanceResult: ...

    def merge(self, *, node: SpecNode, development: DevelopmentResult) -> None: ...


def run_batch(
    *, issues: list[IssueInput], adapter: BatchAdapter, concurrency: int = 4
) -> BatchResult:
    """Run one finite batch with no retry loop and no synchronous human wait."""
    if concurrency < 1:
        raise ValueError("v0.2 concurrency 必须 >= 1")
    numbers = [issue.number for issue in issues]
    if len(set(numbers)) != len(numbers):
        raise ValueError("v0.2 batch 不能重复输入同一 issue")

    results: dict[int, NodeResult] = {}
    ready: dict[int, SpecNode] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(adapter.write_spec, issue=issue): issue for issue in issues}
        for future in as_completed(futures):
            issue = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # isolate a broken Spec from independent nodes
                results[issue.number] = NodeResult(issue.number, "FAILED", str(exc))
                continue
            if isinstance(outcome, SpecNode):
                ready[issue.number] = outcome
            else:
                results[issue.number] = outcome

    nodes = tuple(ready[number] for number in sorted(ready))
    specs = {
        node.number: {
            "branch": node.branch,
            "spec_path": str(node.spec_path),
            "spec_digest": node.spec_digest,
            "summary": node.summary,
            "files": list(node.files),
        }
        for node in nodes
    }
    if not nodes:
        return BatchResult(plan=None, nodes=results, specs=specs)
    try:
        plan = build_plan(nodes=nodes, semantic_edges=adapter.curate(nodes=nodes))
    except Exception as exc:
        # A bad global plan must dispatch zero Developers.
        for node in nodes:
            results[node.number] = NodeResult(node.number, "PLAN_FAILED", str(exc))
        return BatchResult(plan=None, nodes=results, plan_error=str(exc), specs=specs)

    for batch in plan.batches:
        runnable: list[SpecNode] = []
        for number in batch:
            failed = [
                blocker
                for blocker in plan.blocked_by[number]
                if results.get(blocker) is None or results[blocker].status != _SUCCESS
            ]
            if failed:
                results[number] = NodeResult(
                    number,
                    "BLOCKED_BY_DEPENDENCY",
                    "未通过的前置 issue：" + ", ".join(f"#{item}" for item in failed),
                )
            else:
                runnable.append(ready[number])

        accepted: dict[int, tuple[SpecNode, DevelopmentResult, AcceptanceResult]] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_develop_and_accept, adapter, node): node for node in runnable}
            for future in as_completed(futures):
                node = futures[future]
                try:
                    development, acceptance = future.result()
                except Exception as exc:
                    results[node.number] = NodeResult(node.number, "FAILED", str(exc))
                    continue
                if development.status != "DELIVERED":
                    results[node.number] = NodeResult(
                        node.number,
                        development.status,
                        development.reason or development.summary,
                        development.head_sha,
                        development.pr_number,
                        development.evidence,
                    )
                    continue
                if acceptance.verdict != _SUCCESS:
                    results[node.number] = NodeResult(
                        node.number,
                        acceptance.verdict,
                        acceptance.reason,
                        acceptance.head_sha or development.head_sha,
                        development.pr_number,
                        acceptance.evidence,
                    )
                    continue
                accepted[node.number] = (node, development, acceptance)

        # Irreversible operations are deliberately serial even when development was parallel.
        for number in sorted(accepted):
            node, development, acceptance = accepted[number]
            try:
                if acceptance.head_sha != development.head_sha:
                    raise RuntimeError("Acceptance PASS 未绑定 Developer 当前 HEAD")
                adapter.merge(node=node, development=development)
            except Exception as exc:
                results[number] = NodeResult(
                    number,
                    "FAILED",
                    str(exc),
                    development.head_sha,
                    development.pr_number,
                    acceptance.evidence,
                )
            else:
                results[number] = NodeResult(
                    number,
                    _SUCCESS,
                    acceptance.reason,
                    development.head_sha,
                    development.pr_number,
                    acceptance.evidence,
                )
    return BatchResult(plan=plan, nodes=results, specs=specs)


def _develop_and_accept(
    adapter: BatchAdapter, node: SpecNode
) -> tuple[DevelopmentResult, AcceptanceResult]:
    development = adapter.develop(node=node)
    if development.status != "DELIVERED":
        return development, AcceptanceResult(verdict="NOT_RUN")
    acceptance = adapter.accept(node=node, development=development)
    return development, acceptance


__all__ = ["BatchAdapter", "run_batch"]
