"""Spec-0058/T2：标签代数 schedlabels 的单元测试。

覆盖：parse_blocked_by 从混合标签解出上游号；has_unsatisfied_block 存在性；plan_labels 把边集 +
当前标签对账成幂等 add / remove（上游不在 open 集的 blocked-by 进 removes、无剩余 blocked-by 者 add
sched-ready、有则 removes sched-ready）；同一世界重复调 plan_labels 产出稳定（幂等无抖动）；无 IO。
"""

from openagents import schedlabels
from openagents.schedlabels import (
    SCHED_READY,
    LabelPlan,
    has_unsatisfied_block,
    parse_blocked_by,
    plan_labels,
)
from openagents.scheduler import DepEdge, ScheduleVerdict

# --------------------------------------------------------------------------- #
# parse_blocked_by / has_unsatisfied_block
# --------------------------------------------------------------------------- #


def test_parse_blocked_by_extracts_upstreams():
    assert parse_blocked_by(labels=["blocked-by:#150", "openagents"]) == {150}


def test_parse_blocked_by_multiple():
    assert parse_blocked_by(labels=["blocked-by:#150", "blocked-by:#137", "sched-ready"]) == {
        150,
        137,
    }


def test_parse_blocked_by_ignores_non_numeric_and_empty():
    assert parse_blocked_by(labels=["blocked-by:#abc", "blocked-by:#", "openagents"]) == set()
    assert parse_blocked_by(labels=[]) == set()
    assert parse_blocked_by(labels=None) == set()


def test_has_unsatisfied_block_true_when_any_blocked_by():
    assert has_unsatisfied_block(labels=["openagents", "blocked-by:#150"]) is True


def test_has_unsatisfied_block_false_without_blocked_by():
    assert has_unsatisfied_block(labels=["sched-ready", "openagents"]) is False
    assert has_unsatisfied_block(labels=[]) is False


# --------------------------------------------------------------------------- #
# plan_labels
# --------------------------------------------------------------------------- #


def _verdict():
    # #137 依赖 #150（file-conflict）。
    return ScheduleVerdict(
        edges=(DepEdge(downstream=137, upstream=150, kind="file-conflict", reason="x"),)
    )


def test_plan_labels_adds_blocked_by_to_downstream():
    plan = plan_labels(
        verdict=_verdict(),
        open_issue_numbers={137, 150},
        current_labels={137: {"openagents"}, 150: {"openagents"}},
    )
    # 下游 #137 加 blocked-by:#150（不加 sched-ready，因为有未满足上游）。
    assert plan.adds[137] == {"blocked-by:#150"}
    assert SCHED_READY not in plan.adds.get(137, set())
    # 上游 #150 无未满足上游 → 加 sched-ready。
    assert plan.adds[150] == {SCHED_READY}


def test_plan_labels_independent_issue_gets_sched_ready():
    plan = plan_labels(
        verdict=ScheduleVerdict(edges=()),
        open_issue_numbers={160},
        current_labels={160: {"openagents"}},
    )
    assert plan.adds[160] == {SCHED_READY}


def test_plan_labels_removes_blocked_by_when_upstream_closed():
    # 上游 #150 已不在 open 集（合并/关闭）→ #137 的 blocked-by:#150 进 removes、转 sched-ready。
    plan = plan_labels(
        verdict=_verdict(),
        open_issue_numbers={137},  # 150 已 closed
        current_labels={137: {"openagents", "blocked-by:#150"}},
    )
    assert plan.removes[137] == {"blocked-by:#150"}
    assert plan.adds[137] == {SCHED_READY}


def test_plan_labels_removes_sched_ready_when_becomes_blocked():
    # 之前独立带 sched-ready 的 #137，现在被判出依赖 → 摘 sched-ready、加 blocked-by。
    plan = plan_labels(
        verdict=_verdict(),
        open_issue_numbers={137, 150},
        current_labels={137: {"openagents", "sched-ready"}, 150: {"openagents"}},
    )
    assert plan.adds[137] == {"blocked-by:#150"}
    assert plan.removes[137] == {SCHED_READY}


def test_plan_labels_idempotent_no_churn_when_already_consistent():
    # 世界已一致：#137 已挂 blocked-by:#150、#150 已挂 sched-ready → 无任何 add/remove。
    current = {137: {"openagents", "blocked-by:#150"}, 150: {"openagents", "sched-ready"}}
    plan = plan_labels(verdict=_verdict(), open_issue_numbers={137, 150}, current_labels=current)
    assert plan.adds == {}
    assert plan.removes == {}


def test_plan_labels_idempotent_repeated_calls_stable():
    current = {137: {"openagents"}, 150: {"openagents"}}
    kwargs = dict(verdict=_verdict(), open_issue_numbers={137, 150}, current_labels=current)
    first = plan_labels(**kwargs)
    second = plan_labels(**kwargs)
    assert first == second
    assert isinstance(first, LabelPlan)


# --------------------------------------------------------------------------- #
# 解耦：模块不做任何 IO
# --------------------------------------------------------------------------- #


def test_module_does_no_io():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(schedlabels))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)

    assert "argparse" not in imported
    assert not any(name.endswith("github") or name == "github" for name in imported)
    assert "print" not in called and "input" not in called
