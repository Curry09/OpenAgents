"""RFC-0001 T5 + RFC-0005: Messages 按阶段路由 GitHub 事件的单元测试。

外部副作用全部 mock/注入：
- orchestrator：注入记录 implement / refine_rfc / iterate 调用的伪 Orchestrator。
- state：注入控制 all_runs / cursor 的伪 State。
- github.*：monkeypatch（is_merged / has_label / check_status / list_comments / current_login）。
- time.sleep：watch 循环测试中 monkeypatch，避免真实阻塞。

覆盖：merged→done（优先级最高）；rfc-review 阶段 标签→implement、人类评论→refine_rfc、
仅 agent 自评论→不触发；coding 阶段 CI→iterate(ci)、人类评论→iterate(comment)；
仅 open 状态（含 rfc-review）被轮询；watch 循环。
"""

import time

import pytest

from openagents import messages as messages_module
from openagents.github import CheckStatus, Comment
from openagents.messages import APPROVAL_LABEL, Messages
from openagents.state import (
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
)

_OWN_LOGIN = "agent-bot"


class _FakeOrchestrator:
    """记录三种原子操作调用参数的伪编排器。"""

    def __init__(self):
        self.implement_calls = []
        self.refine_calls = []
        self.iterate_calls = []

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)

    def refine_rfc(self, *, pr_number, detail):
        self.refine_calls.append({"pr_number": pr_number, "detail": detail})

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})


class _FakeState:
    """伪 State：内存维护 runs 与 cursors，记录状态更新。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self._cursors = {}
        self.status_updates = []

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        self.status_updates.append({"issue_number": issue_number, "status": status})
        for record in self._runs:
            if record.issue_number == issue_number:
                record.status = status

    def get_cursor(self, *, pr_number):
        return self._cursors.get(pr_number)

    def set_cursor(self, *, pr_number, comment_id):
        self._cursors[pr_number] = comment_id


def _run(*, issue_number, pr_number, status):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url=f"https://github.com/acme/widget/pull/{pr_number}",
        status=status,
        summary="",
    )


def _make(*, runs):
    orch = _FakeOrchestrator()
    state = _FakeState(runs=runs)
    msgs = Messages(orchestrator=orch, state=state)
    return msgs, orch, state


def _patch_github(
    monkeypatch, *, merged=False, has_label=False, check=None, comments=None, login=_OWN_LOGIN
):
    """统一 monkeypatch github 模块函数，返回固定值。"""
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: merged)
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: has_label)
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: check or CheckStatus(state="pass", failed_logs=[]),
    )
    monkeypatch.setattr(
        messages_module.github, "list_comments", lambda *, pr_number: list(comments or [])
    )
    monkeypatch.setattr(messages_module.github, "current_login", lambda: login)


def _human(*, body, created_at):
    return Comment(id="IC", author="alice", body=body, created_at=created_at)


def _own(*, body, created_at):
    return Comment(id="IC", author=_OWN_LOGIN, body=body, created_at=created_at)


# --------------------------------------------------------------------------- #
# merged 优先
# --------------------------------------------------------------------------- #


def test_merged_pr_set_done_and_not_routed(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, merged=True, has_label=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert orch.implement_calls == []
    assert any(e["reason"] == "merged" for e in events)


# --------------------------------------------------------------------------- #
# rfc-review 阶段
# --------------------------------------------------------------------------- #


def test_rfc_review_label_triggers_implement(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, has_label=True)

    events = msgs.poll()

    assert orch.implement_calls == [5]
    assert orch.refine_calls == []
    assert any(e["pr_number"] == 5 and e["reason"] == "approved" for e in events)


def test_rfc_review_human_comment_triggers_refine_and_advances_cursor(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(
        monkeypatch,
        has_label=False,
        comments=[_human(body="补充权衡章节", created_at="2026-06-03T02:00:00Z")],
    )

    events = msgs.poll()

    assert orch.refine_calls == [{"pr_number": 5, "detail": "补充权衡章节"}]
    assert orch.implement_calls == []
    assert state.get_cursor(pr_number=5) == "2026-06-03T02:00:00Z"
    assert any(e["reason"] == "refine" for e in events)


def test_rfc_review_ignores_agent_own_comment(monkeypatch):
    # agent 自己回贴的「已更新 RFC」评论不应再次触发 refine（决策 6，防自我死循环）。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(
        monkeypatch,
        has_label=False,
        comments=[_own(body="🤖 已根据评审更新 RFC", created_at="2026-06-03T03:00:00Z")],
    )

    events = msgs.poll()

    assert orch.refine_calls == []
    assert events == []


def test_rfc_review_refines_only_newest_human_above_cursor(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    state.set_cursor(pr_number=5, comment_id="2026-06-03T01:00:00Z")
    _patch_github(
        monkeypatch,
        has_label=False,
        comments=[
            _human(body="seen", created_at="2026-06-03T01:00:00Z"),
            _human(body="newest", created_at="2026-06-03T02:00:00Z"),
        ],
    )

    msgs.poll()

    assert orch.refine_calls == [{"pr_number": 5, "detail": "newest"}]


# --------------------------------------------------------------------------- #
# coding 阶段
# --------------------------------------------------------------------------- #


def test_coding_ci_fail_triggers_iterate_ci(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(
        monkeypatch, check=CheckStatus(state="fail", failed_logs=["lint [FAILURE] http://x"])
    )

    events = msgs.poll()

    assert len(orch.iterate_calls) == 1
    assert orch.iterate_calls[0]["reason"] == "ci"
    assert "lint" in orch.iterate_calls[0]["detail"]
    assert any(e["reason"] == "ci" for e in events)


def test_coding_human_comment_triggers_iterate_comment(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(
        monkeypatch, comments=[_human(body="please fix", created_at="2026-06-03T02:00:00Z")]
    )

    events = msgs.poll()

    assert orch.iterate_calls == [{"pr_number": 5, "reason": "comment", "detail": "please fix"}]
    assert state.get_cursor(pr_number=5) == "2026-06-03T02:00:00Z"
    assert any(e["reason"] == "comment" for e in events)


def test_coding_ignores_agent_own_comment(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_ITERATING)])
    _patch_github(monkeypatch, comments=[_own(body="bot note", created_at="2026-06-03T02:00:00Z")])

    events = msgs.poll()

    assert orch.iterate_calls == []
    assert events == []


def test_coding_no_new_comment_ci_green_does_not_trigger(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    state.set_cursor(pr_number=5, comment_id="2026-06-03T05:00:00Z")
    _patch_github(monkeypatch, comments=[_human(body="seen", created_at="2026-06-03T05:00:00Z")])

    events = msgs.poll()

    assert orch.iterate_calls == []
    assert events == []


# --------------------------------------------------------------------------- #
# 轮询范围 / watch
# --------------------------------------------------------------------------- #


def test_only_open_runs_are_polled_including_rfc_review(monkeypatch):
    msgs, orch, state = _make(
        runs=[
            _run(issue_number=1, pr_number=11, status=STATUS_DONE),
            _run(issue_number=2, pr_number=22, status="solving"),
            _run(issue_number=3, pr_number=33, status=STATUS_RFC_REVIEW),
            _run(issue_number=4, pr_number=44, status=STATUS_PR_OPEN),
        ]
    )
    seen = []
    monkeypatch.setattr(
        messages_module.github, "is_merged", lambda *, pr_number: seen.append(pr_number) or False
    )
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: False)
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: CheckStatus(state="pass", failed_logs=[]),
    )
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])
    monkeypatch.setattr(messages_module.github, "current_login", lambda: _OWN_LOGIN)

    msgs.poll()

    assert seen == [33, 44]


def test_merged_takes_precedence_over_label_and_comment(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(
        monkeypatch,
        merged=True,
        has_label=True,
        comments=[_human(body="x", created_at="2026-06-03T09:00:00Z")],
    )

    msgs.poll()

    assert orch.implement_calls == []
    assert orch.refine_calls == []
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]


def test_approval_label_constant():
    assert APPROVAL_LABEL == "rfc-approved"


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


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
