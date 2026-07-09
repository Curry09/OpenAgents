"""Spec-0058/T6：跨 issue 调度全链闭环集成测试（内存 GitHub 世界 + 桩 backend，全程 hermetic）。

一个 fixture 世界（两 spec 文件交集 + 一条逻辑依赖 + 一个独立 issue）驱动完整 schedule，断言闭环：
1. 下游落 blocked-by:#<上游>、独立落 sched-ready、上游不被打 blocked；再跑一次同一世界，标签 add/remove
   稳定无抖动（幂等）。
2. messages 门控对挂 blocked-by 的 issue 停在 rfc-review（implement 未调），摘除后放行（零回归）。
3. 上游 closed 后保鲜 schedule 自动剪边、下游转 sched-ready（自动解封铁证）。
4. schedgraph.render 产出 DAG 图产物（dag.png 或降级 dag.dot），产物存在且 DOT 含预期边与波次分层。
"""

from openagents import messages as messages_module
from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import Issue
from openagents.hold import NONE as NO_HOLD
from openagents.messages import APPROVAL_LABEL, Messages
from openagents.reviewer import ReviewDecision
from openagents.skip import NONE as NO_SKIP
from openagents.state import STATUS_RFC_REVIEW, RunRecord, State

# 调度 agent 判出两条边：#137←#150（file-conflict，都改 messages.py）、#170←#150（logical，复用接口）。
_EDGE_SUMMARY = (
    "边：137 <- 150\n类型：file-conflict\n理由：两者都改 openagents/messages.py\n"
    "边：170 <- 150\n类型：logical\n理由：#170 复用 #150 的接口\n"
)


class _StubBackend:
    name = "stub"

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=False, summary=_EDGE_SUMMARY)


class _World:
    """内存 GitHub 世界：issue 号 → {labels: set, state: open/closed}，schedule 的标签读写落在此。"""

    def __init__(self):
        # #150 上游、#137 文件冲突下游、#170 逻辑下游、#160 独立。
        self.issues = {
            150: {"title": "调度", "body": "b", "labels": {"openagents"}, "state": "open"},
            137: {"title": "执行器", "body": "b", "labels": {"openagents"}, "state": "open"},
            170: {"title": "复用者", "body": "b", "labels": {"openagents"}, "state": "open"},
            160: {"title": "独立", "body": "b", "labels": {"openagents"}, "state": "open"},
        }
        self.add_calls = []
        self.remove_calls = []

    def install(self, monkeypatch):
        gh = orch_module.github  # 与 messages.github 同一模块对象，一次 patch 双方可见

        def list_issues(*, labels, state):
            return [
                Issue(number=n, title=d["title"], body=d["body"], labels=tuple(sorted(d["labels"])))
                for n, d in self.issues.items()
                if d["state"] == "open" and set(labels) <= d["labels"]
            ]

        def get_issue(*, number):
            d = self.issues[number]
            return Issue(
                number=number, title=d["title"], body=d["body"], labels=tuple(sorted(d["labels"]))
            )

        def issue_add_label(*, number, name):
            self.add_calls.append((number, name))
            self.issues[number]["labels"].add(name)

        def issue_remove_label(*, number, name):
            self.remove_calls.append((number, name))
            self.issues[number]["labels"].discard(name)

        monkeypatch.setattr(gh, "list_issues", list_issues)
        monkeypatch.setattr(gh, "get_issue", get_issue)
        monkeypatch.setattr(gh, "issue_add_label", issue_add_label)
        monkeypatch.setattr(gh, "issue_remove_label", issue_remove_label)
        # dot 缺失 → render 确定性降级为 dag.dot（hermetic，不依赖本机 graphviz）。
        monkeypatch.setattr(orch_module, "_run_dot", _raise_no_dot)


def _raise_no_dot(*, args):
    raise FileNotFoundError("dot not found")


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


def _fixture_specs(tmp_path):
    specs = tmp_path / "docs" / "specs"
    # 两 spec 文件交集：#150 与 #137 都声明 openagents/messages.py。
    _write_spec(specs, number="0150", slug="a", issue=150, files=["openagents/messages.py"])
    _write_spec(specs, number="0137", slug="b", issue=137, files=["openagents/messages.py"])
    # 逻辑依赖：#170 改另一文件（无文件冲突），依赖由正文/agent 判读。
    _write_spec(specs, number="0170", slug="d", issue=170, files=["openagents/vigil.py"])
    # 独立：#160 改文档，与谁都无关。
    _write_spec(specs, number="0160", slug="c", issue=160, files=["docs/readme.md"])


def _orchestrator(tmp_path):
    return orch_module.Orchestrator(
        backend=_StubBackend(),
        state=State(path=tmp_path / ".openagents" / "state.json"),
        work_dir=tmp_path,
        agent_id="agent-x",
    )


def _labels(world, number):
    return world.issues[number]["labels"]


# --------------------------------------------------------------------------- #
# 1. 落标签 + 幂等无抖动 + DAG 出图
# --------------------------------------------------------------------------- #


def test_schedule_full_loop_labels_idempotent_and_graph(tmp_path, monkeypatch):
    _fixture_specs(tmp_path)
    world = _World()
    world.install(monkeypatch)
    orch = _orchestrator(tmp_path)

    orch.schedule()

    # 下游落 blocked-by:#150；独立与上游落 sched-ready；上游 #150 不被打 blocked。
    assert "blocked-by:#150" in _labels(world, 137)
    assert "blocked-by:#150" in _labels(world, 170)
    assert "sched-ready" in _labels(world, 160)
    assert "sched-ready" in _labels(world, 150)
    assert not any(lb.startswith("blocked-by") for lb in _labels(world, 150))

    # 4. DAG 图产物（降级 dag.dot）存在且含预期下游←上游有向边 + 波次分层。
    dot = tmp_path / "docs" / "schedule" / "dag.dot"
    assert dot.exists()
    text = dot.read_text(encoding="utf-8")
    assert '"#150" -> "#137"' in text
    assert '"#150" -> "#170"' in text
    assert "#150\\n(wave 0)" in text
    assert "#137\\n(wave 1)" in text

    # 幂等：同一世界再跑一次，无任何 add/remove（标签无抖动）。
    world.add_calls.clear()
    world.remove_calls.clear()
    orch.schedule()
    assert world.add_calls == []
    assert world.remove_calls == []


# --------------------------------------------------------------------------- #
# 2. messages 门控：挂 blocked-by 停 rfc-review、摘除放行
# --------------------------------------------------------------------------- #


class _GateOrch:
    def __init__(self, *, decision=None):
        self.review_rfc_calls = []
        self.implement_calls = []
        self._decision = decision

    def e2e_block_missing(self, *, pr_number):
        return None

    def review_rfc(self, *, pr_number):
        self.review_rfc_calls.append(pr_number)
        return self._decision

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)
        return "impl"


class _GateState:
    def update_status(self, *, issue_number, status):
        pass

    def increment_rounds(self, *, issue_number):
        return 0

    def reset_rounds(self, *, issue_number):
        pass


def _rfc_record(issue_number):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=5,
        pr_url="u",
        status=STATUS_RFC_REVIEW,
        summary="",
    )


def test_gate_blocks_then_unblocks(tmp_path, monkeypatch):
    _fixture_specs(tmp_path)
    world = _World()
    world.install(monkeypatch)
    _orchestrator(tmp_path).schedule()  # 先落标签：#137 挂 blocked-by:#150

    added = []
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: False)
    monkeypatch.setattr(
        messages_module.github, "add_label", lambda *, pr_number, name: added.append(name)
    )

    # 挂 blocked-by → 停在 rfc-review，implement 未调。
    orch = _GateOrch()
    msgs = Messages(orchestrator=orch, state=_GateState(), agent_id="a")
    monkeypatch.setattr(msgs, "_post_agent_report", lambda *, pr_number, body: None)
    event = msgs._process_rfc_review(record=_rfc_record(137), hold=NO_HOLD, skip=NO_SKIP)
    assert event["reason"] == "blocked-by"
    assert orch.implement_calls == []
    assert APPROVAL_LABEL not in added

    # 摘掉 blocked-by（模拟上游合并后保鲜剪边）→ 同一 PR 照常评审 / implement（零回归）。
    world.issues[137]["labels"].discard("blocked-by:#150")
    orch2 = _GateOrch(
        decision=ReviewDecision(passed=True, feedback="", verdicts=[], actionable=False)
    )
    msgs2 = Messages(orchestrator=orch2, state=_GateState(), agent_id="a")
    monkeypatch.setattr(msgs2, "_post_agent_report", lambda *, pr_number, body: None)
    event2 = msgs2._process_rfc_review(record=_rfc_record(137), hold=NO_HOLD, skip=NO_SKIP)
    assert orch2.implement_calls == [5]
    assert event2["reason"] == "rfc-pass"


# --------------------------------------------------------------------------- #
# 3. 上游 closed → 保鲜剪边、下游转 sched-ready（自动解封）
# --------------------------------------------------------------------------- #


def test_upstream_closed_auto_unblocks_on_refresh(tmp_path, monkeypatch):
    _fixture_specs(tmp_path)
    world = _World()
    world.install(monkeypatch)
    orch = _orchestrator(tmp_path)
    orch.schedule()
    assert "blocked-by:#150" in _labels(world, 137)

    # 上游 #150 合并（closed）→ 再跑一次保鲜 schedule。
    world.issues[150]["state"] = "closed"
    orch.schedule()

    # 自动剪边解封：#137 / #170 的 blocked-by:#150 被摘、转 sched-ready。
    assert "blocked-by:#150" not in _labels(world, 137)
    assert "sched-ready" in _labels(world, 137)
    assert "blocked-by:#150" not in _labels(world, 170)
    assert "sched-ready" in _labels(world, 170)
