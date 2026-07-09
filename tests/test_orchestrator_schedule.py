"""Spec-0058/T4：orchestrator.schedule 的单元测试（hermetic：github/backend/render 注入或打桩）。

覆盖：对含一条文件交集边 + 一个独立 issue 的内存 GitHub 世界——下游 add blocked-by:#<上游>、独立
issue add sched-ready、上游不被打 blocked；幂等重跑标签 add/remove 稳定（世界已一致→零动作）；上游
closed 后保鲜剪边（remove blocked-by、转 sched-ready）；无 spec 组的 issue 容错跳过；schedgraph.render
被调产出图路径（本机无 graphviz 降级 dag.dot）。
"""

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import Issue
from openagents.state import State


class _StubBackend:
    name = "stub"

    def __init__(self, *, summary):
        self.calls = 0
        self._summary = summary

    def run(self, *, work_dir, task, context):
        self.calls += 1
        return AgentResult(changed=False, summary=self._summary)


# 调度 agent 判出：#137 依赖 #150（两者都改 openagents/messages.py，file-conflict）。
_EDGE_SUMMARY = "边：137 <- 150\n类型：file-conflict\n理由：两者都改 openagents/messages.py\n"


def _write_spec(specs_root, *, number, slug, issue, files):
    specs_root.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f'number: "{number}"',
        f"title: t{issue}",
        f"issue: {issue}",
        f"slug: {slug}",
        "summary: s",
        "tasks:",
        "  - id: T1",
        "    files:",
        *(f"      - {f}" for f in files),
        "---",
        "",
        "# 正文",
        "",
    ]
    (specs_root / f"{number}-{slug}.md").write_text("\n".join(lines), encoding="utf-8")


def _make(tmp_path, *, summary):
    backend = _StubBackend(summary=summary)
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = orch_module.Orchestrator(
        backend=backend, state=state, work_dir=tmp_path, agent_id="agent-x"
    )
    specs = tmp_path / "docs" / "specs"
    _write_spec(specs, number="0150", slug="a", issue=150, files=["openagents/messages.py"])
    _write_spec(specs, number="0137", slug="b", issue=137, files=["openagents/messages.py"])
    _write_spec(specs, number="0160", slug="c", issue=160, files=["docs/readme.md"])
    return orch, backend


def _patch(monkeypatch, *, issues):
    calls = {"add": [], "remove": []}
    monkeypatch.setattr(orch_module.github, "list_issues", lambda *, labels, state: issues)
    monkeypatch.setattr(
        orch_module.github,
        "issue_add_label",
        lambda *, number, name: calls["add"].append((number, name)),
    )
    monkeypatch.setattr(
        orch_module.github,
        "issue_remove_label",
        lambda *, number, name: calls["remove"].append((number, name)),
    )

    # 强制 dot 缺失 → render 确定性降级为 dag.dot（hermetic，不依赖本机 graphviz）。
    def _no_dot(*, args):
        raise FileNotFoundError("dot not found")

    monkeypatch.setattr(orch_module, "_run_dot", _no_dot)
    return calls


def test_schedule_labels_downstream_and_independent(tmp_path, monkeypatch):
    orch, backend = _make(tmp_path, summary=_EDGE_SUMMARY)
    issues = [
        Issue(number=150, title="调度", body="b", labels=("openagents",)),
        Issue(number=137, title="执行器", body="b", labels=("openagents",)),
        Issue(number=160, title="独立", body="b", labels=("openagents",)),
    ]
    calls = _patch(monkeypatch, issues=issues)

    orch.schedule()

    # 下游 #137 加 blocked-by:#150；独立 #160 与上游 #150 加 sched-ready；#150 不被打 blocked。
    assert (137, "blocked-by:#150") in calls["add"]
    assert (160, "sched-ready") in calls["add"]
    assert (150, "sched-ready") in calls["add"]
    assert not any(name.startswith("blocked-by") for num, name in calls["add"] if num == 150)
    # DAG 图（降级 dag.dot）已产出。
    dot = tmp_path / "docs" / "schedule" / "dag.dot"
    assert dot.exists()
    assert '"#150" -> "#137"' in dot.read_text(encoding="utf-8")


def test_schedule_idempotent_no_churn_when_consistent(tmp_path, monkeypatch):
    orch, backend = _make(tmp_path, summary=_EDGE_SUMMARY)
    # 世界已一致：#137 已挂 blocked-by:#150、#150/#160 已挂 sched-ready。
    issues = [
        Issue(number=150, title="调度", body="b", labels=("openagents", "sched-ready")),
        Issue(number=137, title="执行器", body="b", labels=("openagents", "blocked-by:#150")),
        Issue(number=160, title="独立", body="b", labels=("openagents", "sched-ready")),
    ]
    calls = _patch(monkeypatch, issues=issues)

    orch.schedule()

    assert calls["add"] == []
    assert calls["remove"] == []


def test_schedule_auto_unblocks_when_upstream_closed(tmp_path, monkeypatch):
    orch, backend = _make(tmp_path, summary=_EDGE_SUMMARY)
    # 上游 #150 已 closed（不在 open 列表）；#137 仍挂着旧的 blocked-by:#150。
    issues = [
        Issue(number=137, title="执行器", body="b", labels=("openagents", "blocked-by:#150")),
        Issue(number=160, title="独立", body="b", labels=("openagents", "sched-ready")),
    ]
    calls = _patch(monkeypatch, issues=issues)

    orch.schedule()

    # 自动剪边解封：blocked-by:#150 被摘、#137 转 sched-ready。
    assert (137, "blocked-by:#150") in calls["remove"]
    assert (137, "sched-ready") in calls["add"]


def test_schedule_skips_issue_without_spec_group(tmp_path, monkeypatch):
    orch, backend = _make(tmp_path, summary="")
    # #999 无 spec 组 → 容错跳过，不进 contexts、不落任何标签。
    issues = [Issue(number=999, title="无 spec", body="b", labels=("openagents",))]
    calls = _patch(monkeypatch, issues=issues)

    orch.schedule()

    assert calls["add"] == []
    assert calls["remove"] == []
    # 无可排 issue → 不调 backend。
    assert backend.calls == 0
