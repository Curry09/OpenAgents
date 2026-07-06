"""Spec-0054/T2: --skip 逐闸旁路的消费短路单元测试（messages 层 + vigil 发现段）。

每道 CLI 可达的闸各断言一条「skip 命中 → 当 PASS 直接放行」：
  - spec  闸：不调 review_rfc、直接打 rfc-approved 标签进实现（reason=skip-spec）。
  - ci    闸：不查 check_status、当全绿直落代码闸。
  - code  闸：不调 review_code、视为 PASS 直落证据闸 / merge。
  - evidence 闸：不调 _evidence_gate、直落 merge。
  - issue 闸（vigil 发现段）：不调 precheck_issue、照常派单。
并断言默认 NONE 时不误触短路（零回归的行为骨架）。可合并性预检不受 skip 影响、照常执行。
"""

from openagents import messages as messages_module
from openagents import vigil as vigil_module
from openagents.github import Issue
from openagents.messages import APPROVAL_LABEL, Messages
from openagents.skip import parse_skip
from openagents.state import (
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
)
from openagents.vigil import Vigil


class _FakeState:
    """内存单 run，记录状态/指纹更新，rounds 不推进。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []
        self.fingerprints = []

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        self.status_updates.append(status)
        for record in self._runs:
            if record.issue_number == issue_number:
                record.status = status

    def increment_rounds(self, *, issue_number):
        return 0

    def reset_rounds(self, *, issue_number):
        pass

    def set_code_fingerprint(self, *, issue_number, fingerprint):
        self.fingerprints.append(fingerprint)


class _RecordingOrchestrator:
    """记录所有被调到的闸门方法，未被 skip 的闸才会留下痕迹。"""

    def __init__(self):
        self.review_rfc_calls = []
        self.review_code_calls = []
        self.implement_calls = []
        self.iterate_calls = []

    def review_rfc(self, *, pr_number):
        self.review_rfc_calls.append(pr_number)
        raise AssertionError("skip spec 下不应触发 review_rfc")

    def review_code(self, *, pr_number):
        self.review_code_calls.append(pr_number)
        raise AssertionError("skip code 下不应触发 review_code")

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)
        return "impl-summary"  # Spec-0051/T4：implement 返回本轮实现摘要（None→str）

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append((pr_number, reason))
        return "iterate-summary"


def _rfc_record():
    return RunRecord(
        issue_number=135,
        branch="openagents/issue-135",
        pr_number=5,
        pr_url="https://example/pull/5",
        status=STATUS_RFC_REVIEW,
        summary="",
    )


def _coding_record():
    return RunRecord(
        issue_number=135,
        branch="openagents/issue-135",
        pr_number=5,
        pr_url="https://example/pull/5",
        status=STATUS_PR_OPEN,
        summary="",
    )


class _MergeState:
    def __init__(self, *, status="CLEAN", mergeable="MERGEABLE"):
        self.merge_state_status = status
        self.mergeable = mergeable


def _stub_github(monkeypatch, **overrides):
    """给 messages.github 打桩一组安全默认，测试按需覆盖。"""
    gh = messages_module.github
    defaults = {
        "is_merged": lambda *, pr_number: False,
        "is_closed": lambda *, pr_number: False,
        "has_label": lambda *, pr_number, name: False,
        "add_label": lambda *, pr_number, name: None,
        "mergeability": lambda *, pr_number: _MergeState(),
        "merge_pr": lambda *, pr_number: None,
        "close_issue": lambda *, number: None,
        "code_fingerprint": lambda *, pr_number: "",
    }
    defaults.update(overrides)
    for name, fn in defaults.items():
        monkeypatch.setattr(gh, name, fn)
    return gh


def test_skip_spec_passes_gate_without_reviewer(monkeypatch):
    _stub_github(monkeypatch)
    added_labels = []
    monkeypatch.setattr(
        messages_module.github,
        "add_label",
        lambda *, pr_number, name: added_labels.append(name),
    )
    orch = _RecordingOrchestrator()
    state = _FakeState(runs=[_rfc_record()])
    msgs = Messages(orchestrator=orch, state=state, agent_id="agent-test")
    # 收口贴回执是尽力而为的真实 IO（发 PR 评论），与本闸门断言无关 → 打成 no-op。
    monkeypatch.setattr(msgs, "_post_agent_report", lambda *, pr_number, body: None)

    events = msgs.poll(skip=parse_skip(raw="spec"))

    assert orch.review_rfc_calls == [], "skip spec 下不应调 review_rfc"
    assert orch.implement_calls == [5], "skip spec 应直接进实现"
    assert APPROVAL_LABEL in added_labels, "skip spec 应直接打 rfc-approved 标签"
    assert any(e["reason"] == "skip-spec" for e in events)


def test_default_spec_gate_still_reviews(monkeypatch):
    # 零回归骨架：默认 NONE 时 spec 闸照常调 review_rfc（这里让它抛，证明确被调到）。
    _stub_github(monkeypatch)
    orch = _RecordingOrchestrator()
    state = _FakeState(runs=[_rfc_record()])
    msgs = Messages(orchestrator=orch, state=state, agent_id="agent-test")

    events = msgs.poll()  # 默认 NONE

    # review_rfc 被调 → 抛 AssertionError → 被 poll 的单 record 错误隔离兜成 error 事件。
    assert orch.review_rfc_calls == [5], "默认不 skip 时 spec 闸应调 review_rfc"
    assert any(e["reason"] == "error" for e in events)


def test_skip_ci_treats_ci_as_green(monkeypatch):
    # check_status 打成会抛的桩：skip ci 下不该被调到。code 闸也 skip 以便直落 merge。
    def _boom_check_status(*, pr_number):
        raise AssertionError("skip ci 下不应调 check_status")

    merged = []
    _stub_github(
        monkeypatch,
        check_status=_boom_check_status,
        merge_pr=lambda *, pr_number: merged.append(pr_number),
    )
    orch = _RecordingOrchestrator()
    state = _FakeState(runs=[_coding_record()])
    msgs = Messages(orchestrator=orch, state=state, agent_id="agent-test")

    events = msgs.poll(skip=parse_skip(raw="ci,code,evidence"))

    assert merged == [5], "skip ci+code+evidence 应一路直达 merge"
    assert any(e["reason"] == "merged" for e in events)


def test_skip_code_passes_without_review_code(monkeypatch):
    # CI 绿（check_status 返回 pass），skip code → 不调 review_code，直落证据闸(也 skip)→merge。
    class _Status:
        state = "pass"
        failed_logs = []

    merged = []
    _stub_github(
        monkeypatch,
        check_status=lambda *, pr_number: _Status(),
        merge_pr=lambda *, pr_number: merged.append(pr_number),
    )
    orch = _RecordingOrchestrator()
    state = _FakeState(runs=[_coding_record()])
    msgs = Messages(orchestrator=orch, state=state, agent_id="agent-test")

    events = msgs.poll(skip=parse_skip(raw="code,evidence"))

    assert orch.review_code_calls == [], "skip code 下不应调 review_code"
    assert merged == [5]
    assert any(e["reason"] == "merged" for e in events)


def test_skip_evidence_bypasses_evidence_gate(monkeypatch):
    # CI 绿 + skip code（PASS）+ skip evidence → 直接 merge，_evidence_gate 打成会抛的桩。
    class _Status:
        state = "pass"
        failed_logs = []

    merged = []
    _stub_github(
        monkeypatch,
        check_status=lambda *, pr_number: _Status(),
        merge_pr=lambda *, pr_number: merged.append(pr_number),
    )
    orch = _RecordingOrchestrator()
    state = _FakeState(runs=[_coding_record()])
    msgs = Messages(orchestrator=orch, state=state, agent_id="agent-test")

    def _boom_evidence(*, record):
        raise AssertionError("skip evidence 下不应调 _evidence_gate")

    monkeypatch.setattr(msgs, "_evidence_gate", _boom_evidence)

    events = msgs.poll(skip=parse_skip(raw="code,evidence"))

    assert merged == [5], "skip evidence 应绕过证据闸直接 merge"
    assert any(e["reason"] == "merged" for e in events)


def test_mergeability_precheck_not_bypassed_by_skip(monkeypatch):
    # 可合并性预检不设 skip：即便 skip=all，DIRTY 的 PR 仍照常短路（不 merge）。
    _stub_github(
        monkeypatch,
        mergeability=lambda *, pr_number: _MergeState(status="DIRTY", mergeable="CONFLICTING"),
    )
    orch = _RecordingOrchestrator()
    state = _FakeState(runs=[_coding_record()])
    msgs = Messages(orchestrator=orch, state=state, agent_id="agent-test")
    # 冲突分支会走 _block/_make_resolver；打桩成无解析器 + 记录 block，避免真实 IO。
    monkeypatch.setattr(msgs, "_make_resolver", lambda: None)
    blocked = []
    monkeypatch.setattr(msgs, "_block", lambda *, record, gate, blocker=None: blocked.append(gate))
    monkeypatch.setattr(msgs, "_conflict_blocker", lambda *, pr_number: "conflict")

    events = msgs.poll(skip=parse_skip(raw="all"))

    assert blocked == ["merge"], "skip=all 也不应绕过可合并性预检（DIRTY 仍短路）"
    assert any(e["reason"] == "unmergeable" for e in events)


class _VigilOrchestrator:
    """记录 precheck_issue / start_rfc；skip issue 下 precheck_issue 不应被调。"""

    def __init__(self):
        self.precheck_calls = []
        self.start_calls = []

    def precheck_issue(self, *, issue_number):
        self.precheck_calls.append(issue_number)
        raise AssertionError("skip issue 下不应调 precheck_issue")

    def start_rfc(self, *, issue_number, base, resume):
        self.start_calls.append(issue_number)


def _make_vigil(monkeypatch, *, orch, tmp_path):
    state = _FakeState(runs=[])
    vigil = Vigil(
        orchestrator=orch,
        messages=object(),
        state=state,
        work_dir=tmp_path,
        agent_id="agent-test",
    )
    # 只关心 issue 自检闸，_dispatch_kind 固定判 fresh（起草路径）。
    monkeypatch.setattr(vigil, "_dispatch_kind", lambda *, issue: "fresh")
    return vigil


def test_skip_issue_bypasses_precheck_in_discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(
        vigil_module.github,
        "list_issues",
        lambda *, labels: [Issue(number=135, title="t", body="b")],
    )
    orch = _VigilOrchestrator()
    vigil = _make_vigil(monkeypatch, orch=orch, tmp_path=tmp_path)

    dispatched = vigil.discover_and_dispatch(
        labels=["openagents"], base="main", skip=parse_skip(raw="issue")
    )

    assert orch.precheck_calls == [], "skip issue 下不应调 precheck_issue"
    assert dispatched == [135], "skip issue 应照常派单起草"


def test_default_discovery_still_prechecks(monkeypatch, tmp_path):
    # 零回归骨架：默认（不 skip）时 precheck_issue 被调（这里让它抛以证明确被调）。
    monkeypatch.setattr(
        vigil_module.github,
        "list_issues",
        lambda *, labels: [Issue(number=135, title="t", body="b")],
    )
    logs = []
    orch = _VigilOrchestrator()
    vigil = _make_vigil(monkeypatch, orch=orch, tmp_path=tmp_path)
    monkeypatch.setattr(vigil, "_log", lambda *, message: logs.append(message))

    # precheck 抛 AssertionError → 落入 per-issue except（OrchestratorError/GithubError）之外，
    # 故这里改断言：默认路径确实调到了 precheck（用非断言异常的 orch 变体不方便，直接捕获）。
    import pytest

    with pytest.raises(AssertionError):
        vigil.discover_and_dispatch(labels=["openagents"], base="main")
