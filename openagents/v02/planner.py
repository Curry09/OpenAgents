# Spec-0084/T1
"""Validate Curator edges, add deterministic file edges, and layer the DAG."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from openagents.v02.model import Plan, SpecNode


class PlanError(ValueError):
    """The Curator output cannot form a safe execution DAG."""


def build_plan(*, nodes: Sequence[SpecNode], semantic_edges: Iterable[dict]) -> Plan:
    """Build a stable DAG. Edge dictionaries use ``issue -> blocked_by`` direction."""
    by_number = {node.number: node for node in nodes}
    if len(by_number) != len(nodes):
        raise PlanError("The same issue appears more than once in the v0.2 DAG")
    blockers: dict[int, set[int]] = {number: set() for number in by_number}
    for raw in semantic_edges:
        if not isinstance(raw, dict):
            raise PlanError(f"Curator edge is not an object: {raw!r}")
        issue = raw.get("issue")
        blocked_by = raw.get("blocked_by")
        if (
            isinstance(issue, bool)
            or not isinstance(issue, int)
            or isinstance(blocked_by, bool)
            or not isinstance(blocked_by, int)
        ):
            raise PlanError(f"Curator edge lacks integer issue/blocked_by: {raw!r}") from None
        if issue not in by_number or blocked_by not in by_number:
            raise PlanError(f"Curator edge references an unknown issue: {issue} -> {blocked_by}")
        if issue == blocked_by:
            raise PlanError(f"Curator edge points to itself: issue #{issue}")
        blockers[issue].add(blocked_by)

    _assert_acyclic(blockers=blockers)
    # File overlap is a scheduling conflict, not a semantic dependency. Preserve any semantic
    # ordering; otherwise anchor the larger issue behind the smaller one deterministically.
    ordered = sorted(nodes, key=lambda node: node.number)
    for index, left in enumerate(ordered):
        left_files = set(left.files)
        if not left_files:
            continue
        for right in ordered[index + 1 :]:
            if not left_files.intersection(right.files):
                continue
            if _reachable(start=left.number, target=right.number, blockers=blockers):
                continue
            if _reachable(start=right.number, target=left.number, blockers=blockers):
                continue
            blockers[right.number].add(left.number)
    _assert_acyclic(blockers=blockers)
    return Plan(
        blocked_by={number: tuple(sorted(values)) for number, values in blockers.items()},
        batches=_topological_batches(blockers=blockers),
    )


def _reachable(*, start: int, target: int, blockers: dict[int, set[int]]) -> bool:
    """Return whether ``start`` transitively depends on ``target``."""
    pending = list(blockers[start])
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(blockers[current])
    return False


def _topological_batches(*, blockers: dict[int, set[int]]) -> tuple[tuple[int, ...], ...]:
    remaining = set(blockers)
    completed: set[int] = set()
    batches: list[tuple[int, ...]] = []
    while remaining:
        ready = tuple(sorted(number for number in remaining if blockers[number] <= completed))
        if not ready:
            cycle = ", ".join(f"#{number}" for number in sorted(remaining))
            raise PlanError(f"v0.2 DAG contains a cycle: {cycle}")
        batches.append(ready)
        completed.update(ready)
        remaining.difference_update(ready)
    return tuple(batches)


def _assert_acyclic(*, blockers: dict[int, set[int]]) -> None:
    _topological_batches(blockers=blockers)


__all__ = ["PlanError", "build_plan"]
