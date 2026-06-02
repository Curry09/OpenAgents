"""RFC-0001 T5: Messages 消息机制 + CI 监控（决策 6/8/11）的单元测试。

外部副作用全部 mock/注入：
- orchestrator：注入记录 iterate 调用的伪 Orchestrator。
- state：注入控制 all_runs / cursor 的伪 State。
- github.*：monkeypatch 模块函数（is_merged / check_status / list_comments）。
- time.sleep：watch 循环测试中 monkeypatch，避免真实阻塞。

覆盖：新 comment→触发 iterate(reason=comment) 并推进游标；CI 失败→触发
iterate(reason=ci)；已 merge→置 done 不迭代；无新 comment 且 CI 绿→不触发；
watch 循环间隔逻辑（sleep 被 mock，若干轮后退出）。
"""

import time

import pytest

from openagents import messages as messages_module
from openagents.github import CheckStatus, Comment
from openagents.messages import Messages
from openagents.state import (
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    RunRecord,
)


class _FakeOrchestrator:
    """记录 iterate 调用参数的伪编排器。"""

    def __init__(self):
        self.iterate_calls = []

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


def _patch_github(monkeypatch, *, merged=False, check=None, comments=None):
    """统一 monkeypatch github 模块函数，返回固定值。"""
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: merged)
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: check or CheckStatus(state="pass", failed_logs=[]),
    )
    monkeypatch.setattr(
        messages_module.github,
        "list_comments",
        lambda *, pr_number: list(comments or []),
    )


def test_merged_pr_set_done_and_not_iterated(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(monkeypatch, merged=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert orch.iterate_calls == []
    assert any(e["pr_number"] == 5 and e["reason"] == "merged" for e in events)


def test_ci_fail_triggers_iterate_ci(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(
        monkeypatch,
        check=CheckStatus(state="fail", failed_logs=["lint [FAILURE] http://x"]),
    )

    events = msgs.poll()

    assert len(orch.iterate_calls) == 1
    call = orch.iterate_calls[0]
    assert call["pr_number"] == 5
    assert call["reason"] == "ci"
    assert "lint" in call["detail"]
    assert any(e["pr_number"] == 5 and e["reason"] == "ci" for e in events)


def test_new_comment_triggers_iterate_and_advances_cursor(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(
        monkeypatch,
        comments=[
            Comment(id=10, author="alice", body="old"),
            Comment(id=20, author="bob", body="please fix this"),
        ],
    )

    events = msgs.poll()

    assert len(orch.iterate_calls) == 1
    call = orch.iterate_calls[0]
    assert call["pr_number"] == 5
    assert call["reason"] == "comment"
    assert call["detail"] == "please fix this"
    # 游标推进到最大 id
    assert state.get_cursor(pr_number=5) == 20
    assert any(e["pr_number"] == 5 and e["reason"] == "comment" for e in events)


def test_only_comments_above_cursor_are_new(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_ITERATING)])
    state.set_cursor(pr_number=5, comment_id=10)
    _patch_github(
        monkeypatch,
        comments=[
            Comment(id=10, author="alice", body="already seen"),
            Comment(id=15, author="bob", body="newest feedback"),
        ],
    )

    msgs.poll()

    assert len(orch.iterate_calls) == 1
    assert orch.iterate_calls[0]["detail"] == "newest feedback"
    assert state.get_cursor(pr_number=5) == 15


def test_no_new_comment_and_ci_green_does_not_trigger(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    state.set_cursor(pr_number=5, comment_id=20)
    _patch_github(
        monkeypatch,
        comments=[Comment(id=20, author="alice", body="seen")],
    )

    events = msgs.poll()

    assert orch.iterate_calls == []
    assert events == []
    assert state.status_updates == []


def test_only_open_runs_are_polled(monkeypatch):
    msgs, orch, state = _make(
        runs=[
            _run(issue_number=1, pr_number=11, status=STATUS_DONE),
            _run(issue_number=2, pr_number=22, status="solving"),
            _run(issue_number=3, pr_number=33, status=STATUS_PR_OPEN),
        ]
    )
    seen_prs = []

    def _is_merged(*, pr_number):
        seen_prs.append(pr_number)
        return False

    monkeypatch.setattr(messages_module.github, "is_merged", _is_merged)
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: CheckStatus(state="pass", failed_logs=[]),
    )
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])

    msgs.poll()

    # 仅 pr-open / iterating 的 PR 被轮询
    assert seen_prs == [33]


def test_merged_takes_precedence_over_ci_and_comment(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(
        monkeypatch,
        merged=True,
        check=CheckStatus(state="fail", failed_logs=["should not be read"]),
        comments=[Comment(id=99, author="x", body="should not be read")],
    )

    msgs.poll()

    assert orch.iterate_calls == []
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]


def test_watch_loops_then_exits_when_no_open_pr(monkeypatch):
    # 第一轮有 open PR（CI 绿、无新 comment，不迭代），随后置 done → 无 open PR 退出。
    runs = [_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)]
    msgs, orch, state = _make(runs=runs)

    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    poll_count = {"n": 0}
    real_poll = msgs.poll

    def _counting_poll():
        poll_count["n"] += 1
        # 第二次 poll 时把 run 置 done，模拟 PR 合并后无 open PR。
        if poll_count["n"] == 2:
            state.update_status(issue_number=3, status=STATUS_DONE)
        return real_poll()

    monkeypatch.setattr(msgs, "poll", _counting_poll)
    _patch_github(monkeypatch)

    msgs.watch(interval=7)

    assert poll_count["n"] >= 1
    # sleep 用传入的 interval
    assert all(s == 7 for s in sleeps)


def test_watch_exits_on_keyboard_interrupt(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    monkeypatch.setattr(time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    _patch_github(monkeypatch)

    # 不应向上抛出 KeyboardInterrupt
    msgs.watch(interval=1)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
