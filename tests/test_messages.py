"""RFC-0001 T5 + RFC-0005 + RFC-0011: Messages 按阶段路由 GitHub 事件的单元测试。

外部副作用全部 mock/注入：
- orchestrator：注入记录 implement / refine_rfc / iterate 调用的伪 Orchestrator。
- state：注入控制 all_runs / cursor 的伪 State。
- github.*：monkeypatch（is_merged / has_label / check_status / list_comments）。
- time.sleep：watch 循环测试中 monkeypatch，避免真实阻塞。

覆盖：merged→done（优先级最高）；rfc-review 阶段 标签→implement、新评论→refine_rfc
并把游标推进到**触发评论本身**、自评论（带本实例签名）被剔除不触发（RFC-0011 防自循环：
含 post 后未推游标即崩溃、其他 agent 签名照常处理、干活期间真人评论下一轮被处理）；
coding 阶段 CI→iterate(ci)、新评论→iterate(comment)；仅 open 状态（含 rfc-review）
被轮询；watch 循环。
"""

import time

import pytest

from openagents import identity
from openagents import messages as messages_module
from openagents.github import PR, CheckStatus, Comment
from openagents.messages import APPROVAL_LABEL, Messages
from openagents.state import (
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
)

# RFC-0011：本实例（被测 Messages）的身份；自评论用它签名，应被 poll 剔除。
_AGENT_ID = "agent-self"
# 另一个 agent 的身份；其签名评论应被当作外部反馈照常处理。
_OTHER_AGENT_ID = "agent-other"


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


def _make(*, runs, agent_id=_AGENT_ID):
    orch = _FakeOrchestrator()
    state = _FakeState(runs=runs)
    # RFC-0011 T3：Messages 新增必填 agent_id（自评论签名过滤用）。
    msgs = Messages(orchestrator=orch, state=state, agent_id=agent_id)
    return msgs, orch, state


def _patch_github(
    monkeypatch,
    *,
    merged=False,
    closed=False,
    has_label=False,
    check=None,
    comments=None,
):
    """统一 monkeypatch github 模块函数，返回固定值。"""
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: merged)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: closed)
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: has_label)
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: check or CheckStatus(state="pass", failed_logs=[]),
    )
    monkeypatch.setattr(
        messages_module.github, "list_comments", lambda *, pr_number: list(comments or [])
    )
    # RFC-0009 T3：合并分支会扇出 rebase.rebase_open_prs；默认桩为 no-op，保持 hermetic
    # （不触达真实 gh）。RFC-0011：扇出新增 agent_id 形参，桩需接受它。
    monkeypatch.setattr(
        messages_module.rebase,
        "rebase_open_prs",
        lambda *, merged_pr_number=None, agent_id=None: [],
    )


def _human(*, body, created_at):
    # 真人评论：无签名（author 字段已与判定无关，RFC-0011 不再按作者过滤）。
    return Comment(id="IC", author="alice", body=body, created_at=created_at)


def _own(*, body, created_at):
    # 本实例自评论：盖 _AGENT_ID 签名，应被 _latest_new_comment 剔除。
    return Comment(
        id="IC",
        author="alice",
        body=identity.sign(body=body, agent_id=_AGENT_ID),
        created_at=created_at,
    )


def _other_agent(*, body, created_at):
    # 其他 agent 的评论：带别人的签名，应被当作外部反馈照常处理。
    return Comment(
        id="IC",
        author="alice",
        body=identity.sign(body=body, agent_id=_OTHER_AGENT_ID),
        created_at=created_at,
    )


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
# closed 终止（RFC-0006：关闭但未合并的 PR 不再处理）
# --------------------------------------------------------------------------- #


def test_closed_pr_set_closed_and_not_routed(monkeypatch):
    # RFC-0006：人关掉一个仍带 rfc-approved 标签的 draft PR → 置 closed，不再 implement。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, closed=True, has_label=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_CLOSED}]
    assert orch.implement_calls == []
    assert orch.refine_calls == []
    assert any(e["pr_number"] == 5 and e["reason"] == "closed" for e in events)


def test_closed_coding_pr_not_iterated(monkeypatch):
    # RFC-0006：coding 阶段被关闭的 PR，即便有新评论也不再 iterate。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(
        monkeypatch,
        closed=True,
        comments=[_human(body="please fix", created_at="2026-06-03T02:00:00Z")],
    )

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_CLOSED}]
    assert orch.iterate_calls == []
    assert any(e["reason"] == "closed" for e in events)


def test_merged_takes_precedence_over_closed(monkeypatch):
    # MERGED 与 CLOSED 互斥，但若两者判定同真，merged 优先（决策 3/8）。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, merged=True, closed=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert any(e["reason"] == "merged" for e in events)


def test_closed_status_run_not_polled(monkeypatch):
    # closed 不在 _OPEN_STATUSES，已关闭的 run 后续轮询被跳过。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_CLOSED)])
    seen = []
    monkeypatch.setattr(
        messages_module.github, "is_merged", lambda *, pr_number: seen.append(pr_number) or False
    )
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)

    events = msgs.poll()

    assert seen == []
    assert events == []


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


def test_rfc_review_refine_advances_cursor_to_trigger_and_signature_kills_self_loop(monkeypatch):
    # RFC-0011 决策 1/5：真人评论触发 refine；游标只推进到**触发评论本身**；refine 回贴的
    # 「已更新 RFC」自评论带本实例签名，下一轮由签名过滤剔除，不再对自己的回贴触发 refine。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    comments = [_human(body="补充权衡章节", created_at="2026-06-03T02:00:00Z")]

    def _refine(*, pr_number, detail):
        orch.refine_calls.append({"pr_number": pr_number, "detail": detail})
        # 模拟 orchestrator.refine_rfc 回贴一条带本实例签名的说明评论（晚于触发评论）。
        comments.append(_own(body="🤖 已更新 RFC", created_at="2026-06-03T02:05:00Z"))

    orch.refine_rfc = _refine
    _patch_github(monkeypatch, has_label=False, comments=comments)

    msgs.poll()

    assert orch.refine_calls == [{"pr_number": 5, "detail": "补充权衡章节"}]
    # 游标推进到触发评论本身（02:00），而非自评论所在的 02:05。
    assert state.get_cursor(pr_number=5) == "2026-06-03T02:00:00Z"

    # 下一轮：自评论虽晚于游标，但带本实例签名 → 被剔除 → 不重复触发。
    orch.refine_calls.clear()
    events = msgs.poll()
    assert orch.refine_calls == []
    assert events == []


def test_rfc_review_self_comment_filtered_even_if_cursor_not_advanced(monkeypatch):
    # RFC-0011 决策 1（崩溃自循环根治）：模拟「post 自评论后、推游标前崩溃」——游标仍停在
    # 触发评论之前。重启重跑 poll，自评论靠签名被剔除，不自循环；不依赖游标是否推进。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    # 游标尚未推进（None）；PR 上只剩 agent 自己的回贴（带本实例签名）。
    _patch_github(
        monkeypatch,
        has_label=False,
        comments=[_own(body="🤖 已更新 RFC", created_at="2026-06-03T02:05:00Z")],
    )

    events = msgs.poll()

    assert orch.refine_calls == []
    assert events == []


def test_rfc_review_other_agent_comment_triggers_refine(monkeypatch):
    # RFC-0011 决策 1：判定粒度是「自己 vs 非自己」——其他 agent 的签名评论是外部反馈，照常触发。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(
        monkeypatch,
        has_label=False,
        comments=[_other_agent(body="另一个 agent 的意见", created_at="2026-06-03T02:00:00Z")],
    )

    events = msgs.poll()

    assert len(orch.refine_calls) == 1
    assert orch.refine_calls[0]["pr_number"] == 5
    assert "另一个 agent 的意见" in orch.refine_calls[0]["detail"]
    assert any(e["reason"] == "refine" for e in events)


def test_rfc_review_human_comment_during_work_processed_next_round(monkeypatch):
    # RFC-0011 决策 1（误跳真人根治）：agent 干活期间真人发了评论（晚于触发评论）。游标只推到
    # 触发评论，真人那条 > cursor 且无签名 → 下一轮被正常处理，不再被「游标推到最新」静默跳过。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    comments = [_human(body="第一条意见", created_at="2026-06-03T02:00:00Z")]

    def _refine(*, pr_number, detail):
        orch.refine_calls.append({"pr_number": pr_number, "detail": detail})
        # agent 回贴自评论；同时一条真人评论在干活期间到达（晚于触发评论与自评论）。
        comments.append(_own(body="🤖 已更新 RFC", created_at="2026-06-03T02:05:00Z"))
        comments.append(_human(body="第二条意见", created_at="2026-06-03T02:06:00Z"))

    orch.refine_rfc = _refine
    _patch_github(monkeypatch, has_label=False, comments=comments)

    msgs.poll()
    assert orch.refine_calls == [{"pr_number": 5, "detail": "第一条意见"}]
    assert state.get_cursor(pr_number=5) == "2026-06-03T02:00:00Z"

    # 下一轮：自评论被签名剔除，但真人「第二条意见」> cursor 且无签名 → 被处理。
    orch.refine_calls.clear()
    msgs.poll()
    assert orch.refine_calls == [{"pr_number": 5, "detail": "第二条意见"}]
    assert state.get_cursor(pr_number=5) == "2026-06-03T02:06:00Z"


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


def test_coding_does_not_retrigger_at_or_below_cursor(monkeypatch):
    # 进入 coding 前游标已越过 rfc-review 阶段 agent 的回贴；不晚于游标的评论不重复触发。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_ITERATING)])
    state.set_cursor(pr_number=5, comment_id="2026-06-03T02:00:00Z")
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
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: False)
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: CheckStatus(state="pass", failed_logs=[]),
    )
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])

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


# --------------------------------------------------------------------------- #
# RFC-0009 T3：合并后扇出 rebase_open_prs
# --------------------------------------------------------------------------- #


def test_merged_fans_out_rebase_with_merged_pr_number(monkeypatch):
    # 侦测到合并时调用 rebase.rebase_open_prs 且传入正确 merged_pr_number。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(monkeypatch, merged=True)

    seen = {}

    def _fake_rebase(*, merged_pr_number=None, agent_id=None):
        seen["merged_pr_number"] = merged_pr_number
        seen["agent_id"] = agent_id
        return [{"pr_number": 8, "result": "updated"}]

    monkeypatch.setattr(messages_module.rebase, "rebase_open_prs", _fake_rebase)

    events = msgs.poll()

    # RFC-0011 T3：扇出透传本实例 agent_id（rebase 据此给冲突留言盖章）。
    assert seen == {"merged_pr_number": 5, "agent_id": _AGENT_ID}
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    # merged 事件附带本轮同步结果，供日志。
    merged_event = next(e for e in events if e["reason"] == "merged")
    assert merged_event["synced"] == [{"pr_number": 8, "result": "updated"}]


def test_non_merged_does_not_fan_out_rebase(monkeypatch):
    # 未合并的 run（仅有新评论）不触发扇出同步。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(
        monkeypatch, comments=[_human(body="please fix", created_at="2026-06-03T02:00:00Z")]
    )

    called = []
    monkeypatch.setattr(
        messages_module.rebase,
        "rebase_open_prs",
        lambda *, merged_pr_number=None, agent_id=None: called.append(merged_pr_number) or [],
    )

    msgs.poll()

    assert called == []


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


# --------------------------------------------------------------------------- #
# RFC-0011 集成测试：真实 Messages + 真实 Orchestrator 的跨模块自循环防护
# --------------------------------------------------------------------------- #


def test_integration_real_orchestrator_self_reply_does_not_self_loop(monkeypatch, tmp_path):
    """端到端一轮 rfc-review poll（真实 Messages ↔ 真实 Orchestrator）：

    真人评论 → orchestrator.refine_rfc 经 identity.post_signed_comment 回贴带签名的自评论 →
    下一轮 poll 据签名剔除自评论、不再触发 refine；其后追加一条真人评论 → 被正常处理。
    跨 messages → orchestrator → identity → github 边界，验证整条链路的身份/签名一致。
    """
    from openagents import identity as identity_module
    from openagents.orchestrator import Orchestrator
    from openagents.state import State

    agent_id = "agent-integration"

    class _StubBackend:
        name = "stub"

        def run(self, *, work_dir, task, context):
            from openagents.backends.base import AgentResult

            return AgentResult(changed=True, summary="已据评审更新 RFC")

    class _StubWorkspace:
        def ensure(self, *, issue_number, branch):
            return tmp_path / f"wt-{issue_number}"

        def commit_and_push(self, *, worktree, branch, message):
            pass

    # 真实 State + 真实 Orchestrator（桩掉 backend / workspace / git）。
    state = State(path=tmp_path / ".openagents" / "state.json")
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )
    state.update_status(issue_number=3, status=STATUS_RFC_REVIEW)
    orch = Orchestrator(backend=_StubBackend(), state=state, work_dir=tmp_path, agent_id=agent_id)
    orch._workspace = _StubWorkspace()
    msgs = Messages(orchestrator=orch, state=state, agent_id=agent_id)

    # 共享一个内存评论列表：post_signed_comment 往里追加（带签名），list_comments 读它。
    comments: list[Comment] = [_human(body="补充权衡章节", created_at="2026-06-03T02:00:00Z")]
    posted_at = {"n": 4}

    def _post_comment(*, pr_number, body):
        # 模拟 gh 落地：原始 body（含隐藏签名）原样进入评论列表，时间晚于触发评论。
        posted_at["n"] += 1
        comments.append(
            Comment(
                id="IC", author="acct", body=body, created_at=f"2026-06-03T02:0{posted_at['n']}:00Z"
            )
        )

    monkeypatch.setattr(identity_module.github, "post_comment", _post_comment)
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: False)
    monkeypatch.setattr(
        messages_module.github, "list_comments", lambda *, pr_number: list(comments)
    )

    # 第 1 轮：真人评论触发 refine，orchestrator 回贴一条带本实例签名的自评论。
    events = msgs.poll()
    assert any(e["reason"] == "refine" for e in events)
    assert identity.parse_agent_id(body=comments[-1].body) == agent_id  # 自评论确带签名
    assert state.get_cursor(pr_number=5) == "2026-06-03T02:00:00Z"  # 游标只到触发评论

    # 第 2 轮：仅有 agent 自评论晚于游标 → 被签名剔除 → 不自循环。
    events = msgs.poll()
    assert events == []

    # 追加一条真人评论（无签名，晚于游标）→ 第 3 轮被正常处理。
    comments.append(_human(body="再改一处", created_at="2026-06-03T03:00:00Z"))
    events = msgs.poll()
    assert any(e["reason"] == "refine" for e in events)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
