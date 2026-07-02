"""Spec-0041/T1：hold-merge PASS 后夯住 + merge-hold 解挂路由的单元测试。

github / identity / orchestrator 全部 hermetic 注入（monkeypatch / fake），不触网、不调真实
LLM/gh。覆盖：
- _hold_merge_freeze：贴成功文案（非失败模板）+ blocked + needs-human + gate=merge-hold + 水位线；
- 反震荡（bug 核心回归）：首轮 poll 冻结后，次轮 poll 走 _process_blocked、review_code 不再被调、
  状态仍 blocked、无新评论、rounds 不增；
- 三出口：is_merged→done / merge-hold 新评论→iterate(reason=human) / 撕标签→resume 回 pr-open；
- 非 hold（自动合并）路径逐字节不变（merge_pr 被调、done、无成功文案评论）。
"""

import pytest

from openagents import blocknote
from openagents import messages as messages_module
from openagents.github import CheckStatus, Comment, Mergeability
from openagents.hold import NONE as NO_HOLD
from openagents.hold import Hold
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    RunRecord,
)

_AGENT_ID = "agent-self"
_HOLD_MERGE = Hold(at_merge=True)


class _FakeOrchestrator:
    """记录 review_code / iterate / implement 调用次数；review_code 恒返回可配置裁决。"""

    def __init__(self, *, decision):
        self._decision = decision
        self.review_code_calls = 0
        self.iterate_calls = []
        self.implement_calls = []

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return self._decision

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})
        return "已据人类指导迭代代码摘要"

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)

    def review_rfc(self, *, pr_number):
        raise AssertionError("coding 路径不应调 review_rfc")

    def refine_rfc(self, *, pr_number, detail, announce=True):
        raise AssertionError("coding 路径不应调 refine_rfc")


class _FakeState:
    """内存版 State：记录 status/gate/watermark/reset 轨迹并应用到记录。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []
        self.block_gate_sets = []
        self.watermark_sets = []
        self.reset_calls = []
        self.increment_calls = []

    def all_runs(self):
        return list(self._runs)

    def _find(self, issue_number):
        for record in self._runs:
            if record.issue_number == issue_number:
                return record
        return None

    def update_status(self, *, issue_number, status):
        self.status_updates.append({"issue_number": issue_number, "status": status})
        record = self._find(issue_number)
        if record is not None:
            record.status = status

    def set_block_gate(self, *, issue_number, gate):
        self.block_gate_sets.append({"issue_number": issue_number, "gate": gate})
        record = self._find(issue_number)
        if record is not None:
            record.block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        self.watermark_sets.append({"issue_number": issue_number, "watermark": watermark})
        record = self._find(issue_number)
        if record is not None:
            record.block_watermark = watermark

    def reset_rounds(self, *, issue_number):
        self.reset_calls.append(issue_number)
        record = self._find(issue_number)
        if record is not None:
            record.rounds = 0
            record.review_invalid = 0
            record.merge_attempts = 0

    def increment_rounds(self, *, issue_number):
        # 不应在 PASS 冻结路径被调——记录以便断言「rounds 不增」。
        self.increment_calls.append(issue_number)
        record = self._find(issue_number)
        record.rounds += 1
        return record.rounds


def _run(*, issue_number=3, pr_number=5, status=STATUS_PR_OPEN, block_gate="", block_watermark=""):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url=f"u/pull/{pr_number}",
        status=status,
        summary="",
        rounds=0,
        review_invalid=0,
        block_gate=block_gate,
        merge_attempts=0,
        block_watermark=block_watermark,
        unblock_detail="",
    )


def _messages(*, runs, decision=None):
    if decision is None:
        decision = ReviewDecision(passed=True, feedback="", verdicts=("PASS",))
    orch = _FakeOrchestrator(decision=decision)
    state = _FakeState(runs=runs)
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)
    return msgs, orch, state


def _comment(*, created_at, body, author="alice"):
    return Comment(id=f"c-{created_at}", author=author, body=body, created_at=created_at)


def _patch_coding_reads(monkeypatch, *, comments):
    """让 poll 走完 _process_coding 到 PASS：未合并/未关、MERGEABLE/CLEAN、CI 绿。

    捕获 add_label / post_signed_comment / merge_pr / close_issue，返回捕获字典。
    """
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        messages_module.github,
        "mergeability",
        lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN"),
    )
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: CheckStatus(state="pass", failed_logs=[]),
    )
    monkeypatch.setattr(
        messages_module.github, "list_comments", lambda *, pr_number: list(comments)
    )
    labels = []
    monkeypatch.setattr(
        messages_module.github,
        "add_label",
        lambda *, pr_number, name: labels.append({"pr_number": pr_number, "name": name}),
    )
    posted = []
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append({"body": body, "agent_id": agent_id}),
    )
    merged = []
    monkeypatch.setattr(
        messages_module.github, "merge_pr", lambda *, pr_number: merged.append(pr_number)
    )
    closed = []
    monkeypatch.setattr(
        messages_module.github, "close_issue", lambda *, number: closed.append(number)
    )
    return {"labels": labels, "posted": posted, "merged": merged, "closed": closed}


# --------------------------------------------------------------------------- #
# _hold_merge_freeze：成功文案 + blocked + needs-human + gate=merge-hold + 水位线
# --------------------------------------------------------------------------- #


def test_hold_merge_freeze_posts_success_note_and_blocks(monkeypatch):
    captured = _patch_coding_reads(
        monkeypatch, comments=[_comment(created_at="2026-07-02T12:00:00Z", body="成功评论")]
    )
    msgs, orch, state = _messages(runs=[_run(issue_number=3, pr_number=5)])

    events = msgs.poll(hold=_HOLD_MERGE)

    # 冻结事件。
    assert events == [{"pr_number": 5, "reason": "hold-merge", "gate": "merge-hold"}]
    # 恰贴一条成功文案（build_hold_merge_pass）、盖本实例签名。
    assert len(captured["posted"]) == 1
    assert captured["posted"][0]["body"] == blocknote.build_hold_merge_pass()
    assert captured["posted"][0]["agent_id"] == _AGENT_ID
    # 不含失败模板措辞（不贴 blocknote.build 的「🤖 卡住了」）。
    assert "卡住了" not in captured["posted"][0]["body"]
    # needs-human 打上、blocked 落盘、gate=merge-hold、水位线取最新 createdAt。
    assert captured["labels"] == [{"pr_number": 5, "name": BLOCKED_LABEL}]
    assert {"issue_number": 3, "status": STATUS_BLOCKED} in state.status_updates
    assert {"issue_number": 3, "gate": "merge-hold"} in state.block_gate_sets
    assert {"issue_number": 3, "watermark": "2026-07-02T12:00:00Z"} in state.watermark_sets
    # 不自动合并、rounds 不增（PASS 不吃 round）。
    assert captured["merged"] == []
    assert state.increment_calls == []


# --------------------------------------------------------------------------- #
# 反震荡（bug 核心回归）：首轮冻结 → 次轮不重审
# --------------------------------------------------------------------------- #


def test_second_poll_does_not_re_review_after_freeze(monkeypatch):
    captured = _patch_coding_reads(
        monkeypatch, comments=[_comment(created_at="2026-07-02T12:00:00Z", body="成功评论")]
    )
    msgs, orch, state = _messages(runs=[_run(issue_number=3, pr_number=5)])

    msgs.poll(hold=_HOLD_MERGE)
    assert orch.review_code_calls == 1  # 首轮审了一次

    # 次轮：无新人类评论、needs-human 仍在 → _process_blocked 保持挂起。
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: True)
    events2 = msgs.poll(hold=_HOLD_MERGE)

    # reviewer 未再被调（反震荡铁证）、状态仍 blocked、无新评论、rounds 不增。
    assert orch.review_code_calls == 1
    assert events2 == []
    assert state.all_runs()[0].status == STATUS_BLOCKED
    assert len(captured["posted"]) == 1  # 次轮未再贴评论
    assert state.increment_calls == []


# --------------------------------------------------------------------------- #
# 三出口
# --------------------------------------------------------------------------- #


def test_exit_merged_reconciles_to_done(monkeypatch):
    # 人点合并 → is_merged 分支先于 blocked 被检查 → done + 关 issue。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: True)
    closed = []
    monkeypatch.setattr(
        messages_module.github, "close_issue", lambda *, number: closed.append(number)
    )
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_BLOCKED, block_gate="merge-hold")]
    )

    events = msgs.poll(hold=_HOLD_MERGE)

    assert events == [{"pr_number": 5, "reason": "merged"}]
    assert {"issue_number": 3, "status": STATUS_DONE} in state.status_updates
    assert closed == [3]
    assert orch.review_code_calls == 0


def test_exit_new_comment_feeds_iterate_human(monkeypatch):
    # 人回评论 → merge-hold 走 iterate(reason=human) + resume。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        messages_module.identity,
        "new_human_comments",
        lambda *, pr_number, since: [_comment(created_at="t2", body="再改一处")],
    )
    monkeypatch.setattr(messages_module.github, "remove_label", lambda *, pr_number, name: None)
    posted = []
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(body),
    )
    msgs, orch, state = _messages(
        runs=[
            _run(
                issue_number=3,
                pr_number=5,
                status=STATUS_BLOCKED,
                block_gate="merge-hold",
                block_watermark="t1",
            )
        ]
    )

    events = msgs.poll(hold=_HOLD_MERGE)

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert orch.iterate_calls == [{"pr_number": 5, "reason": "human", "detail": "再改一处"}]
    assert {"issue_number": 3, "gate": ""} in state.block_gate_sets  # 清残留 gate
    # 恰贴一条引用原评论的回应。
    assert len(posted) == 1
    assert "> 再改一处" in posted[0]


def test_exit_label_removed_resumes_to_pr_open(monkeypatch):
    # 人撕标签（无评论）→ _unblock_by_label：merge-hold 落 else → resume 回 pr-open。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )
    # 有 rfc-approved（APPROVAL_LABEL）、无 needs-human → resume 回 pr-open。
    monkeypatch.setattr(
        messages_module.github,
        "has_label",
        lambda *, pr_number, name: name == messages_module.APPROVAL_LABEL,
    )
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_BLOCKED, block_gate="merge-hold")]
    )

    events = msgs.poll(hold=_HOLD_MERGE)

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert {"issue_number": 3, "status": STATUS_PR_OPEN} in state.status_updates
    assert {"issue_number": 3, "gate": ""} in state.block_gate_sets
    assert orch.review_code_calls == 0


# --------------------------------------------------------------------------- #
# 非 hold（自动合并）路径逐字节不变
# --------------------------------------------------------------------------- #


def test_non_hold_path_auto_merges_unchanged(monkeypatch):
    captured = _patch_coding_reads(monkeypatch, comments=[])
    msgs, orch, state = _messages(runs=[_run(issue_number=3, pr_number=5)])

    events = msgs.poll(hold=NO_HOLD)

    # 自动合并 → done + 关 issue，无冻结、无成功文案评论、无 needs-human。
    assert events == [{"pr_number": 5, "reason": "merged"}]
    assert captured["merged"] == [5]
    assert {"issue_number": 3, "status": STATUS_DONE} in state.status_updates
    assert captured["closed"] == [3]
    assert captured["posted"] == []
    assert captured["labels"] == []


def test_iterating_status_also_freezes_under_hold(monkeypatch):
    # iterating 状态（也在 _OPEN_STATUSES）PASS + hold → 同样夯住。
    _patch_coding_reads(monkeypatch, comments=[_comment(created_at="t1", body="c")])
    msgs, orch, state = _messages(runs=[_run(issue_number=3, pr_number=5, status=STATUS_ITERATING)])

    events = msgs.poll(hold=_HOLD_MERGE)

    assert events == [{"pr_number": 5, "reason": "hold-merge", "gate": "merge-hold"}]
    assert {"issue_number": 3, "status": STATUS_BLOCKED} in state.status_updates


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
