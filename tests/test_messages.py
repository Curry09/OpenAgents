"""RFC-0001 T5 + RFC-0005 + RFC-0012: Messages 按阶段路由 GitHub 事件的单元测试。

RFC-0012 把两处「等人」换成「调 reviewer 闸 + 自动推进」，本测试相应改为 reviewer 驱动：

外部副作用全部 mock/注入：
- orchestrator：注入伪 Orchestrator，review_rfc / review_code 返回可配 ReviewDecision，
  并记录 implement / refine_rfc / iterate 调用。
- state：注入伪 State（all_runs / update_status / increment_rounds / reset_rounds）。
- github.*：monkeypatch（is_merged / is_closed / has_label / check_status / merge_pr / add_label）。
- rebase.rebase_open_prs / time.sleep：桩为 no-op。

覆盖：merged→done+扇出（优先级最高）；closed→closed；rfc 闸 标签/reviewer PASS→implement、
reviewer 非 PASS→refine+rounds++、超 K→BLOCKED+needs-human(PR 不关)；coding 闸 CI fail→
iterate(ci)、CI pending→等待、CI 绿+reviewer PASS→merge+done+扇出、reviewer 非 PASS→
iterate(review)+rounds++、超 K→BLOCKED；仅 open 状态被轮询；MAX_ROUNDS 边界；watch 循环。
"""

import time

import pytest

from openagents import messages as messages_module
from openagents.github import CheckStatus
from openagents.messages import APPROVAL_LABEL, Messages, _configured_max_rounds
from openagents.reviewer import ReviewDecision
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
)

_AGENT_ID = "agent-self"

_PASS = ReviewDecision(passed=True, feedback="")
_FAIL = ReviewDecision(passed=False, feedback="补单测；处理空输入")


class _FakeOrchestrator:
    """记录原子操作调用、并按预设裁决回应 review_rfc / review_code 的伪编排器。"""

    def __init__(self, *, rfc_decision=_PASS, code_decision=_PASS):
        self.implement_calls = []
        self.refine_calls = []
        self.iterate_calls = []
        self.review_rfc_calls = []
        self.review_code_calls = []
        self._rfc_decision = rfc_decision
        self._code_decision = code_decision

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)

    def refine_rfc(self, *, pr_number, detail):
        self.refine_calls.append({"pr_number": pr_number, "detail": detail})

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})

    def review_rfc(self, *, pr_number):
        self.review_rfc_calls.append(pr_number)
        return self._rfc_decision

    def review_code(self, *, pr_number):
        self.review_code_calls.append(pr_number)
        return self._code_decision


class _FakeState:
    """伪 State：内存维护 runs，记录状态更新与回合数。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        self.status_updates.append({"issue_number": issue_number, "status": status})
        for record in self._runs:
            if record.issue_number == issue_number:
                record.status = status

    def increment_rounds(self, *, issue_number):
        for record in self._runs:
            if record.issue_number == issue_number:
                record.rounds += 1
                return record.rounds
        return 0

    def reset_rounds(self, *, issue_number):
        for record in self._runs:
            if record.issue_number == issue_number:
                record.rounds = 0


def _run(*, issue_number, pr_number, status, rounds=0):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url=f"https://github.com/acme/widget/pull/{pr_number}",
        status=status,
        summary="",
        rounds=rounds,
    )


def _make(*, runs, rfc_decision=_PASS, code_decision=_PASS, agent_id=_AGENT_ID):
    orch = _FakeOrchestrator(rfc_decision=rfc_decision, code_decision=code_decision)
    state = _FakeState(runs=runs)
    msgs = Messages(orchestrator=orch, state=state, agent_id=agent_id)
    return msgs, orch, state


def _patch_github(monkeypatch, *, merged=False, closed=False, has_label=False, check=None):
    """统一 monkeypatch github 模块函数；返回 merge_pr / add_label 调用的记录器。"""
    rec = {"merged": [], "labels": []}
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: merged)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: closed)
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: has_label)
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: check or CheckStatus(state="pass", failed_logs=[]),
    )
    monkeypatch.setattr(
        messages_module.github,
        "merge_pr",
        lambda *, pr_number, method="merge": rec["merged"].append(pr_number),
    )
    monkeypatch.setattr(
        messages_module.github,
        "add_label",
        lambda *, pr_number, name: rec["labels"].append((pr_number, name)),
    )
    # 合并分支会扇出 rebase；默认桩为 no-op，保持 hermetic。
    monkeypatch.setattr(
        messages_module.rebase,
        "rebase_open_prs",
        lambda *, merged_pr_number=None, agent_id=None: [],
    )
    return rec


# --------------------------------------------------------------------------- #
# merged / closed 终止
# --------------------------------------------------------------------------- #


def test_merged_pr_set_done_and_not_routed(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, merged=True, has_label=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert orch.implement_calls == []
    assert any(e["reason"] == "merged" for e in events)


def test_closed_pr_set_closed_and_not_routed(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, closed=True, has_label=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_CLOSED}]
    assert orch.implement_calls == []
    assert any(e["reason"] == "closed" for e in events)


def test_merged_takes_precedence_over_closed(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, merged=True, closed=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert any(e["reason"] == "merged" for e in events)


def test_blocked_and_terminal_runs_not_polled(monkeypatch):
    # blocked / closed / done / solving 都不在 _OPEN_STATUSES，poll 跳过。
    msgs, orch, state = _make(
        runs=[
            _run(issue_number=1, pr_number=11, status=STATUS_DONE),
            _run(issue_number=2, pr_number=22, status="solving"),
            _run(issue_number=3, pr_number=33, status=STATUS_CLOSED),
            _run(issue_number=4, pr_number=44, status=STATUS_BLOCKED),
        ]
    )
    seen = []
    monkeypatch.setattr(
        messages_module.github, "is_merged", lambda *, pr_number: seen.append(pr_number) or False
    )

    events = msgs.poll()

    assert seen == []
    assert events == []


# --------------------------------------------------------------------------- #
# RFC 评审闸（RFC-0012 决策 1/3）
# --------------------------------------------------------------------------- #


def test_rfc_existing_label_triggers_implement(monkeypatch):
    # 已带 rfc-approved（人/上一轮 reviewer 打的）→ 直接 implement，不再评审（向后兼容）。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, has_label=True)

    events = msgs.poll()

    assert orch.implement_calls == [5]
    assert orch.review_rfc_calls == []
    assert any(e["reason"] == "approved" for e in events)


def test_rfc_reviewer_pass_labels_and_implements(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)], rfc_decision=_PASS
    )
    rec = _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert orch.review_rfc_calls == [5]
    assert (5, APPROVAL_LABEL) in rec["labels"]
    assert orch.implement_calls == [5]
    assert any(e["reason"] == "rfc-pass" for e in events)


def test_rfc_reviewer_fail_refines_and_increments_rounds(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)], rfc_decision=_FAIL
    )
    _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert orch.refine_calls == [{"pr_number": 5, "detail": _FAIL.feedback}]
    assert orch.implement_calls == []
    assert state.all_runs()[0].rounds == 1
    assert any(e["reason"] == "refine" for e in events)


def test_rfc_reviewer_fail_over_k_blocks(monkeypatch):
    # rounds 预置到 K-1，本轮非 PASS 使其达 K → BLOCKED + needs-human + PR 不关。
    monkeypatch.setattr(messages_module, "MAX_ROUNDS", 3)
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW, rounds=2)],
        rfc_decision=_FAIL,
    )
    rec = _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert orch.refine_calls == []  # 超 K 不再 refine
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_BLOCKED}]
    assert (5, BLOCKED_LABEL) in rec["labels"]
    blocked = next(e for e in events if e["reason"] == "blocked")
    assert blocked["gate"] == "rfc"


# --------------------------------------------------------------------------- #
# 代码评审闸（RFC-0012 决策 1）
# --------------------------------------------------------------------------- #


def test_coding_ci_fail_triggers_iterate_ci_no_round(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(
        monkeypatch, check=CheckStatus(state="fail", failed_logs=["lint [FAILURE] http://x"])
    )

    events = msgs.poll()

    assert len(orch.iterate_calls) == 1
    assert orch.iterate_calls[0]["reason"] == "ci"
    assert orch.review_code_calls == []
    # CI 回合不计入 rounds（行为保持）。
    assert state.all_runs()[0].rounds == 0
    assert any(e["reason"] == "ci" for e in events)


def test_coding_ci_pending_waits(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(monkeypatch, check=CheckStatus(state="pending", failed_logs=[]))

    events = msgs.poll()

    assert orch.review_code_calls == []
    assert orch.iterate_calls == []
    assert events == []


def test_coding_ci_green_reviewer_pass_merges_and_fans_out(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)], code_decision=_PASS
    )
    rec = _patch_github(monkeypatch)
    seen = {}

    def _fake_rebase(*, merged_pr_number=None, agent_id=None):
        seen["merged_pr_number"] = merged_pr_number
        seen["agent_id"] = agent_id
        return [{"pr_number": 8, "result": "updated"}]

    monkeypatch.setattr(messages_module.rebase, "rebase_open_prs", _fake_rebase)

    events = msgs.poll()

    assert orch.review_code_calls == [5]
    assert rec["merged"] == [5]
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert seen == {"merged_pr_number": 5, "agent_id": _AGENT_ID}
    merged_event = next(e for e in events if e["reason"] == "merged")
    assert merged_event["synced"] == [{"pr_number": 8, "result": "updated"}]


def test_coding_reviewer_fail_iterates_review_and_increments(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)], code_decision=_FAIL
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.iterate_calls == [{"pr_number": 5, "reason": "review", "detail": _FAIL.feedback}]
    assert rec["merged"] == []
    assert state.all_runs()[0].rounds == 1
    assert any(e["reason"] == "review" for e in events)


def test_coding_reviewer_fail_over_k_blocks(monkeypatch):
    monkeypatch.setattr(messages_module, "MAX_ROUNDS", 2)
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_ITERATING, rounds=1)],
        code_decision=_FAIL,
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.iterate_calls == []
    assert rec["merged"] == []
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_BLOCKED}]
    assert (5, BLOCKED_LABEL) in rec["labels"]
    blocked = next(e for e in events if e["reason"] == "blocked")
    assert blocked["gate"] == "code"


# --------------------------------------------------------------------------- #
# MAX_ROUNDS 边界（K-1 不 block、K block）
# --------------------------------------------------------------------------- #


def test_rounds_boundary_k_minus_one_does_not_block(monkeypatch):
    monkeypatch.setattr(messages_module, "MAX_ROUNDS", 3)
    # rounds 起始 1，本轮非 PASS → rounds=2 < 3 → refine（不 block）。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW, rounds=1)],
        rfc_decision=_FAIL,
    )
    _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert len(orch.refine_calls) == 1
    assert state.all_runs()[0].rounds == 2
    assert any(e["reason"] == "refine" for e in events)
    assert all(e["reason"] != "blocked" for e in events)


# --------------------------------------------------------------------------- #
# 轮询范围 / watch / 常量
# --------------------------------------------------------------------------- #


def test_only_open_runs_are_polled(monkeypatch):
    msgs, orch, state = _make(
        runs=[
            _run(issue_number=1, pr_number=11, status=STATUS_DONE),
            _run(issue_number=2, pr_number=22, status="solving"),
            _run(issue_number=3, pr_number=33, status=STATUS_RFC_REVIEW),
            _run(issue_number=4, pr_number=44, status=STATUS_PR_OPEN),
        ]
    )
    # 全量打桩 github（含 check_status / merge_pr），再覆盖 is_merged 为记录器。
    _patch_github(monkeypatch, has_label=True)
    seen = []
    monkeypatch.setattr(
        messages_module.github, "is_merged", lambda *, pr_number: seen.append(pr_number) or False
    )

    msgs.poll()

    # rfc-review(33) 走 has_label→implement；pr-open(44) 走 coding；done/solving 跳过。
    assert seen == [33, 44]


def test_approval_label_constant():
    assert APPROVAL_LABEL == "rfc-approved"


def test_configured_max_rounds_default(monkeypatch):
    monkeypatch.delenv(messages_module.MAX_ROUNDS_ENV, raising=False)
    assert _configured_max_rounds() == 3


def test_configured_max_rounds_reads_env(monkeypatch):
    monkeypatch.setenv(messages_module.MAX_ROUNDS_ENV, "5")
    assert _configured_max_rounds() == 5


def test_configured_max_rounds_invalid_falls_back(monkeypatch):
    monkeypatch.setenv(messages_module.MAX_ROUNDS_ENV, "oops")
    assert _configured_max_rounds() == 3


def test_configured_max_rounds_below_one_falls_back(monkeypatch):
    monkeypatch.setenv(messages_module.MAX_ROUNDS_ENV, "0")
    assert _configured_max_rounds() == 3


def test_watch_loops_then_exits_when_no_open_pr(monkeypatch):
    runs = [_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)]
    msgs, orch, state = _make(runs=runs)

    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    poll_count = {"n": 0}
    real_poll = msgs.poll

    def _counting_poll():
        poll_count["n"] += 1
        if poll_count["n"] == 2:
            state.update_status(issue_number=3, status=STATUS_DONE)
        return real_poll()

    monkeypatch.setattr(msgs, "poll", _counting_poll)
    _patch_github(monkeypatch)

    msgs.watch(interval=7)

    assert poll_count["n"] >= 1
    assert all(s == 7 for s in sleeps)


def test_watch_exits_on_keyboard_interrupt(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    monkeypatch.setattr(time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    _patch_github(monkeypatch)

    msgs.watch(interval=1)


# --------------------------------------------------------------------------- #
# RFC-0012 集成：真实 Messages + 真实 Orchestrator 的 RFC 闸自动放行
# --------------------------------------------------------------------------- #


def test_integration_real_orchestrator_rfc_pass_implements(monkeypatch, tmp_path):
    """端到端一轮 rfc-review poll（真实 Messages ↔ 真实 Orchestrator）：

    reviewer backend 返回 PASS → review_rfc 聚合 passed=True → 自动打 rfc-approved →
    implement（写码 + mark_ready + pr-open + reset_rounds）。验证跨 messages → orchestrator
    → reviewer → state 的整条放行链路。
    """
    from openagents.backends.base import AgentResult
    from openagents.github import PR
    from openagents.orchestrator import Orchestrator
    from openagents.state import State

    agent_id = "agent-integration"

    class _StubBackend:
        name = "stub"

        def run(self, *, work_dir, task, context):
            # reviewer 评 RFC 时返回 PASS；implement 写码时返回普通摘要。
            summary = "VERDICT: PASS" if "审核员" in task else "已实现"
            return AgentResult(changed=True, summary=summary)

    class _StubWorkspace:
        def ensure(self, *, issue_number, branch):
            return tmp_path / f"wt-{issue_number}"

        def commit_and_push(self, *, worktree, branch, message):
            pass

        def changed_rfc_path(self, *, worktree, base):
            # RFC-0013：implement 转正前实跑 e2e 需先定位本分支 RFC；本用例只验放行链路，
            # 返回 None 让脚本定位降级为 skipped（不起子进程）。
            return None

    state = State(path=tmp_path / ".openagents" / "state.json")
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="u/pull/5"),
        status=STATUS_RFC_REVIEW,
    )
    state.increment_rounds(issue_number=3)  # 预置一回合，验证 implement 会清零
    orch = Orchestrator(backend=_StubBackend(), state=state, work_dir=tmp_path, agent_id=agent_id)
    orch._workspace = _StubWorkspace()
    msgs = Messages(orchestrator=orch, state=state, agent_id=agent_id)

    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: False)
    added = []
    monkeypatch.setattr(
        messages_module.github, "add_label", lambda *, pr_number, name: added.append(name)
    )
    monkeypatch.setattr("openagents.orchestrator.github.mark_ready", lambda *, pr_number: None)
    # RFC-0013：implement 旁路实跑 e2e 后发签名评论；本用例只验放行链路，桩掉评论发送避免真打 gh。
    monkeypatch.setattr(
        "openagents.orchestrator.identity.post_signed_comment",
        lambda *, pr_number, body, agent_id: None,
    )

    events = msgs.poll()

    assert any(e["reason"] == "rfc-pass" for e in events)
    assert APPROVAL_LABEL in added
    run = state.all_runs()[0]
    assert run.status == STATUS_PR_OPEN
    assert run.rounds == 0  # implement 清零


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
