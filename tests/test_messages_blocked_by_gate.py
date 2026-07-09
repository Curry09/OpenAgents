"""Spec-0058/T5：messages 实现门控（派 implement 前查 blocked-by）单元测试。

覆盖：挂 blocked-by:#N 的 issue 经 _process_rfc_review 本轮 implement 未被调、无 rfc-approved 标签、
返回 reason=blocked-by、停在 rfc-review；摘除 blocked-by 后同一 PR 照常评审 / implement（零回归）；
已带 rfc-approved（2a）/ skip.at_spec 的强放行意图仍放行（门控不覆盖人工放行）。
"""

from openagents import messages as messages_module
from openagents.github import Issue
from openagents.hold import NONE as NO_HOLD
from openagents.messages import APPROVAL_LABEL, Messages
from openagents.reviewer import ReviewDecision
from openagents.skip import NONE as NO_SKIP
from openagents.skip import parse_skip
from openagents.state import STATUS_RFC_REVIEW, RunRecord


class _FakeState:
    def __init__(self):
        self.status_updates = []

    def update_status(self, *, issue_number, status):
        self.status_updates.append(status)

    def increment_rounds(self, *, issue_number):
        return 0

    def reset_rounds(self, *, issue_number):
        pass


class _Orch:
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
        return "impl-summary"


def _record():
    return RunRecord(
        issue_number=137,
        branch="openagents/issue-137",
        pr_number=5,
        pr_url="https://example/pull/5",
        status=STATUS_RFC_REVIEW,
        summary="",
    )


def _stub_github(monkeypatch, *, issue_labels, has_approval=False):
    gh = messages_module.github
    added = []
    monkeypatch.setattr(
        gh,
        "get_issue",
        lambda *, number: Issue(number=number, title="t", body="b", labels=tuple(issue_labels)),
    )
    monkeypatch.setattr(gh, "has_label", lambda *, pr_number, name: has_approval)
    monkeypatch.setattr(gh, "add_label", lambda *, pr_number, name: added.append(name))
    return added


def _messages(monkeypatch, orch, state):
    msgs = Messages(orchestrator=orch, state=state, agent_id="agent-test")
    # 收口贴回执是尽力而为的真实 IO → 打 no-op。
    monkeypatch.setattr(msgs, "_post_agent_report", lambda *, pr_number, body: None)
    return msgs


# --------------------------------------------------------------------------- #
# 挂 blocked-by → 停在 rfc-review
# --------------------------------------------------------------------------- #


def test_blocked_by_gate_stops_before_implement(monkeypatch):
    added = _stub_github(monkeypatch, issue_labels=["openagents", "blocked-by:#150"])
    orch = _Orch()
    state = _FakeState()
    msgs = _messages(monkeypatch, orch, state)

    event = msgs._process_rfc_review(record=_record(), hold=NO_HOLD, skip=NO_SKIP)

    assert event == {"pr_number": 5, "reason": "blocked-by"}
    # 不评审、不 implement、不打 rfc-approved。
    assert orch.review_rfc_calls == []
    assert orch.implement_calls == []
    assert APPROVAL_LABEL not in added
    # 停在 rfc-review（不改状态）。
    assert state.status_updates == []


# --------------------------------------------------------------------------- #
# 摘除 blocked-by → 照常评审 / implement（零回归）
# --------------------------------------------------------------------------- #


def test_gate_lets_through_when_unblocked(monkeypatch):
    added = _stub_github(monkeypatch, issue_labels=["openagents", "sched-ready"])
    orch = _Orch(decision=ReviewDecision(passed=True, feedback="", verdicts=[], actionable=False))
    state = _FakeState()
    msgs = _messages(monkeypatch, orch, state)

    event = msgs._process_rfc_review(record=_record(), hold=NO_HOLD, skip=NO_SKIP)

    # 门控放行 → 照常评审 → 全票 PASS → 打 rfc-approved → implement。
    assert orch.review_rfc_calls == [5]
    assert orch.implement_calls == [5]
    assert APPROVAL_LABEL in added
    assert event["reason"] == "rfc-pass"


# --------------------------------------------------------------------------- #
# 人工放行意图不被门控覆盖
# --------------------------------------------------------------------------- #


def test_gate_does_not_override_manual_rfc_approved(monkeypatch):
    # 已带 rfc-approved（2a）——即便还挂 blocked-by，人工放行意图仍尊重，直接 implement。
    _stub_github(monkeypatch, issue_labels=["openagents", "blocked-by:#150"], has_approval=True)
    orch = _Orch()
    state = _FakeState()
    msgs = _messages(monkeypatch, orch, state)

    event = msgs._process_rfc_review(record=_record(), hold=NO_HOLD, skip=NO_SKIP)

    assert orch.implement_calls == [5]
    assert event["reason"] == "approved"


def test_gate_does_not_override_skip_spec(monkeypatch):
    # skip.at_spec 强放行——即便还挂 blocked-by，仍直接打 rfc-approved + implement。
    added = _stub_github(monkeypatch, issue_labels=["openagents", "blocked-by:#150"])
    orch = _Orch()
    state = _FakeState()
    msgs = _messages(monkeypatch, orch, state)

    event = msgs._process_rfc_review(record=_record(), hold=NO_HOLD, skip=parse_skip(raw="spec"))

    assert orch.implement_calls == [5]
    assert APPROVAL_LABEL in added
    assert event["reason"] == "skip-spec"
