from __future__ import annotations

import threading
import time
from pathlib import Path

from openagents.v02.model import (
    AcceptanceResult,
    DevelopmentResult,
    IssueInput,
    NodeResult,
    SpecNode,
)
from openagents.v02.runner import run_batch


class RecordingAdapter:
    def __init__(self, *, edges=(), develop_status=None, accept_status=None):
        self.edges = list(edges)
        self.develop_status = develop_status or {}
        self.accept_status = accept_status or {}
        self.events = []
        self.lock = threading.Lock()

    def _record(self, event):
        with self.lock:
            self.events.append(event)

    def write_spec(self, *, issue):
        self._record(("spec", issue.number))
        return SpecNode(
            issue=issue,
            branch=f"b{issue.number}",
            worktree=Path(f"/w/{issue.number}"),
            spec_path=Path(f"/w/{issue.number}/spec.md"),
            spec_digest=f"d{issue.number}",
            summary="ready",
        )

    def curate(self, *, nodes):
        self._record(("curate", tuple(node.number for node in nodes)))
        return self.edges

    def develop(self, *, node):
        self._record(("develop-start", node.number))
        time.sleep(0.01)
        status = self.develop_status.get(node.number, "DELIVERED")
        self._record(("develop-end", node.number))
        return DevelopmentResult(
            status=status,
            head_sha=f"h{node.number}" if status == "DELIVERED" else "",
            reason="developer stopped" if status != "DELIVERED" else "",
            pr_number=node.number + 100,
        )

    def accept(self, *, node, development):
        self._record(("accept", node.number))
        verdict = self.accept_status.get(node.number, "PASS")
        return AcceptanceResult(
            verdict=verdict,
            reason=f"acceptance {verdict}",
            head_sha=development.head_sha,
        )

    def merge(self, *, node, development):
        self._record(("merge", node.number))


def _issues(*numbers):
    return [IssueInput(number, f"issue {number}", "body") for number in numbers]


def test_parallel_layer_then_dependency_and_serial_merge():
    adapter = RecordingAdapter(edges=[{"issue": 3, "blocked_by": 1}])
    result = run_batch(issues=_issues(1, 2, 3), adapter=adapter, concurrency=2)
    assert result.plan is not None
    assert result.plan.batches == ((1, 2), (3,))
    assert result.specs[1]["spec_digest"] == "d1"
    assert {number: node.status for number, node in result.nodes.items()} == {
        1: "PASS",
        2: "PASS",
        3: "PASS",
    }
    assert adapter.events.index(("develop-end", 1)) < adapter.events.index(("develop-start", 3))
    assert adapter.events.index(("merge", 1)) < adapter.events.index(("merge", 2))


def test_failure_blocks_only_descendants_and_independent_node_continues():
    adapter = RecordingAdapter(
        edges=[{"issue": 3, "blocked_by": 1}], develop_status={1: "FAILED"}
    )
    result = run_batch(issues=_issues(1, 2, 3), adapter=adapter, concurrency=3)
    assert result.nodes[1].status == "FAILED"
    assert result.nodes[2].status == "PASS"
    assert result.nodes[3].status == "BLOCKED_BY_DEPENDENCY"
    assert ("develop-start", 3) not in adapter.events
    assert ("merge", 2) in adapter.events


def test_acceptance_partial_is_terminal_without_retry_or_merge():
    adapter = RecordingAdapter(accept_status={1: "PARTIAL"})
    result = run_batch(issues=_issues(1), adapter=adapter)
    assert result.nodes[1].status == "PARTIAL"
    assert [event for event in adapter.events if event[0] == "develop-start"] == [
        ("develop-start", 1)
    ]
    assert ("merge", 1) not in adapter.events


def test_partial_spec_is_audited_and_not_dispatched():
    adapter = RecordingAdapter()
    adapter.write_spec = lambda *, issue: NodeResult(issue.number, "PARTIAL", "not closed")
    result = run_batch(issues=_issues(1), adapter=adapter)
    assert result.plan is None
    assert result.nodes[1].status == "PARTIAL"
    assert not any(event[0] == "develop-start" for event in adapter.events)


def test_bad_global_plan_dispatches_zero_developers():
    adapter = RecordingAdapter(
        edges=[{"issue": 1, "blocked_by": 2}, {"issue": 2, "blocked_by": 1}]
    )
    result = run_batch(issues=_issues(1, 2), adapter=adapter)
    assert result.plan_error
    assert {node.status for node in result.nodes.values()} == {"PLAN_FAILED"}
    assert not any(event[0] == "develop-start" for event in adapter.events)


def test_acceptance_head_mismatch_prevents_merge():
    adapter = RecordingAdapter()

    def wrong_head(*, node, development):
        return AcceptanceResult(verdict="PASS", head_sha="stale")

    adapter.accept = wrong_head
    result = run_batch(issues=_issues(1), adapter=adapter)
    assert result.nodes[1].status == "FAILED"
    assert "当前 HEAD" in result.nodes[1].reason
    assert ("merge", 1) not in adapter.events
