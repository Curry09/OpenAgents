from pathlib import Path

import pytest

from openagents.v02.model import IssueInput, SpecNode
from openagents.v02.planner import PlanError, build_plan


def _node(number: int, *files: str) -> SpecNode:
    return SpecNode(
        issue=IssueInput(number, f"issue {number}", "body"),
        branch=f"b{number}",
        worktree=Path(f"/w/{number}"),
        spec_path=Path(f"/w/{number}/spec.md"),
        spec_digest=f"d{number}",
        summary=f"s{number}",
        files=tuple(files),
    )


def test_semantic_and_file_edges_form_stable_parallel_batches():
    nodes = [_node(1, "a.py"), _node(2, "b.py"), _node(3, "a.py"), _node(4, "c.py")]
    plan = build_plan(nodes=nodes, semantic_edges=[{"issue": 4, "blocked_by": 2}])
    assert plan.blocked_by[3] == (1,)
    assert plan.blocked_by[4] == (2,)
    assert plan.batches == ((1, 2), (3, 4))


@pytest.mark.parametrize(
    "edge",
    [
        {"issue": 1, "blocked_by": 1},
        {"issue": 1, "blocked_by": 99},
        {"issue": "x", "blocked_by": 1},
        {"issue": True, "blocked_by": 1},
    ],
)
def test_invalid_curator_edges_fail_closed(edge):
    with pytest.raises(PlanError):
        build_plan(nodes=[_node(1), _node(2)], semantic_edges=[edge])


def test_cycle_fails_closed():
    with pytest.raises(PlanError, match="cycle"):
        build_plan(
            nodes=[_node(1), _node(2)],
            semantic_edges=[
                {"issue": 1, "blocked_by": 2},
                {"issue": 2, "blocked_by": 1},
            ],
        )


def test_duplicate_issue_fails_closed():
    with pytest.raises(PlanError, match="more than once"):
        build_plan(nodes=[_node(1), _node(1)], semantic_edges=[])
