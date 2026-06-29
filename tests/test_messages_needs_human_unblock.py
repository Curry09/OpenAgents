"""Spec-0032/T5：_block enrich（结构化评论 + 水位线）+ 回评论解挂路由的单元测试。

github / identity / orchestrator 全部 hermetic 注入（monkeypatch / fake），不触网、不调真实
LLM/gh。覆盖：
- _block 任意 gate 贴一条四段结构化签名评论 + 落 block_watermark（取最新评论 createdAt）；
- 回评论解挂：block 之后的新人类评论 → remove_label + reset_rounds + 按 block_gate 喂 detail
  到对应 orchestrator 路径 + 返回 resumed（rfc/code/*-unparseable/merge/"" 各路由）；
- 机器签名评论 / 历史评论不触发解挂（退回手动摘标签兜底，零回归）；
- 手动摘标签兜底路径行为不变。
"""

import pytest

from openagents import blocknote
from openagents import messages as messages_module
from openagents.github import Comment
from openagents.messages import Messages
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
)

_AGENT_ID = "agent-self"


class _FakeOrchestrator:
    """记录 refine_rfc / iterate 调用（含 detail/reason）；review_* 不该在解挂/挂起路径被调。"""

    def __init__(self):
        self.refine_calls = []
        self.iterate_calls = []

    def refine_rfc(self, *, pr_number, detail):
        self.refine_calls.append({"pr_number": pr_number, "detail": detail})

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})

    def review_rfc(self, *, pr_number):
        raise AssertionError("解挂/挂起路径不应调 review_rfc")

    def review_code(self, *, pr_number):
        raise AssertionError("解挂/挂起路径不应调 review_code")


class _FakeState:
    """内存版 State：记录 set_block_gate / set_block_watermark / reset_rounds / update_status 轨迹。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []
        self.block_gate_sets = []
        self.watermark_sets = []
        self.reset_calls = []

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


def _run(*, issue_number=3, pr_number=5, status=STATUS_BLOCKED, block_gate="", block_watermark=""):
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
    )


def _messages(*, runs):
    orch = _FakeOrchestrator()
    state = _FakeState(runs=runs)
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)
    return msgs, orch, state


def _comment(*, created_at, body, author="alice"):
    return Comment(id=f"c-{created_at}", author=author, body=body, created_at=created_at)


# --------------------------------------------------------------------------- #
# _block enrich：结构化评论 + 水位线
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("gate", ["rfc", "code", "merge", "rfc-unparseable", "code-unparseable"])
def test_block_posts_structured_comment_and_sets_watermark(monkeypatch, gate):
    posted = []
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(
            {"pr_number": pr_number, "body": body, "agent_id": agent_id}
        ),
    )
    monkeypatch.setattr(messages_module.github, "add_label", lambda *, pr_number, name: None)
    # _block 贴完评论后读最新 createdAt 落水位线。
    monkeypatch.setattr(
        messages_module.github,
        "list_comments",
        lambda *, pr_number: [
            _comment(created_at="2026-06-29T10:00:00Z", body="旧"),
            _comment(created_at="2026-06-29T12:00:00Z", body="刚贴的挂起评论"),
        ],
    )
    msgs, _orch, state = _messages(runs=[_run(issue_number=3, pr_number=5)])

    event = msgs._block(record=state.all_runs()[0], gate=gate, blocker="reviewer 反馈原文")

    # 恰一条四段结构化签名评论（盖本实例签名）。
    assert len(posted) == 1
    assert posted[0]["agent_id"] == _AGENT_ID
    for section in ("**原因**", "**我试过**", "**卡在哪**", "**你可以怎么做**"):
        assert section in posted[0]["body"]
    assert f"gate={gate}" in posted[0]["body"]
    # blocked + gate 落盘，水位线取最新 createdAt。
    assert {"issue_number": 3, "status": STATUS_BLOCKED} in state.status_updates
    assert {"issue_number": 3, "gate": gate} in state.block_gate_sets
    assert {"issue_number": 3, "watermark": "2026-06-29T12:00:00Z"} in state.watermark_sets
    assert event == {"pr_number": 5, "reason": "blocked", "gate": gate}


def test_block_watermark_empty_when_no_comments(monkeypatch):
    monkeypatch.setattr(
        messages_module.identity, "post_signed_comment", lambda *, pr_number, body, agent_id: None
    )
    monkeypatch.setattr(messages_module.github, "add_label", lambda *, pr_number, name: None)
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])
    msgs, _orch, state = _messages(runs=[_run(issue_number=3, pr_number=5)])

    msgs._block(record=state.all_runs()[0], gate="code", blocker="")

    assert {"issue_number": 3, "watermark": ""} in state.watermark_sets


def test_block_comment_body_matches_blocknote(monkeypatch):
    posted = []
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(body),
    )
    monkeypatch.setattr(messages_module.github, "add_label", lambda *, pr_number, name: None)
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])
    msgs, _orch, state = _messages(runs=[_run(issue_number=3, pr_number=5)])

    msgs._block(record=state.all_runs()[0], gate="code", blocker="补单测")

    # 正文出自 blocknote.build（tried 由 messages 据 gate 选）——卡点原文被嵌入。
    expected = blocknote.build(
        gate="code", tried=messages_module._TRIED_BY_GATE["code"], blocker="补单测"
    )
    assert posted == [expected]
    assert "补单测" in posted[0]


# --------------------------------------------------------------------------- #
# 回评论解挂：按 block_gate 路由
# --------------------------------------------------------------------------- #


def _patch_unblock_reads(monkeypatch, *, news):
    """让 poll 走到 blocked 解挂主路径：未合并/未关闭、有指定的新人类评论。"""
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: list(news)
    )
    removed = []
    monkeypatch.setattr(
        messages_module.github,
        "remove_label",
        lambda *, pr_number, name: removed.append({"pr_number": pr_number, "name": name}),
    )
    return removed


def test_unblock_rfc_feeds_refine_rfc(monkeypatch):
    removed = _patch_unblock_reads(
        monkeypatch, news=[_comment(created_at="t2", body="按这个思路改 RFC")]
    )
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="rfc", block_watermark="t1")]
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert removed == [{"pr_number": 5, "name": BLOCKED_LABEL}]
    assert 3 in state.reset_calls
    assert orch.refine_calls == [{"pr_number": 5, "detail": "按这个思路改 RFC"}]
    assert orch.iterate_calls == []
    assert {"issue_number": 3, "gate": ""} in state.block_gate_sets  # 清残留


def test_unblock_rfc_unparseable_also_feeds_refine_rfc(monkeypatch):
    _patch_unblock_reads(monkeypatch, news=[_comment(created_at="t2", body="人工指导")])
    msgs, orch, _state = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="rfc-unparseable", block_watermark="t1")]
    )

    msgs.poll()

    assert orch.refine_calls == [{"pr_number": 5, "detail": "人工指导"}]


def test_unblock_code_feeds_iterate_reason_human(monkeypatch):
    _patch_unblock_reads(monkeypatch, news=[_comment(created_at="t2", body="别动 messages")])
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="code", block_watermark="t1")]
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert orch.iterate_calls == [{"pr_number": 5, "reason": "human", "detail": "别动 messages"}]
    assert orch.refine_calls == []
    assert {"issue_number": 3, "gate": ""} in state.block_gate_sets


def test_unblock_code_unparseable_also_feeds_iterate(monkeypatch):
    _patch_unblock_reads(monkeypatch, news=[_comment(created_at="t2", body="人工指导")])
    msgs, orch, _state = _messages(
        runs=[
            _run(issue_number=3, pr_number=5, block_gate="code-unparseable", block_watermark="t1")
        ]
    )

    msgs.poll()

    assert orch.iterate_calls == [{"pr_number": 5, "reason": "human", "detail": "人工指导"}]


def test_unblock_merge_arms_without_feeding(monkeypatch):
    # merge 闸解挂：不喂解冲突器，按 armed 语义恢复 pr-open、保留 block_gate="merge"。
    _patch_unblock_reads(monkeypatch, news=[_comment(created_at="t2", body="我已表态，去解冲突")])
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="merge", block_watermark="t1")]
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert orch.refine_calls == [] and orch.iterate_calls == []
    assert {"issue_number": 3, "status": STATUS_PR_OPEN} in state.status_updates
    assert 3 in state.reset_calls
    # armed 标记保留：解挂没把 block_gate 清成 ""。
    assert {"issue_number": 3, "gate": ""} not in state.block_gate_sets
    assert state.all_runs()[0].block_gate == "merge"


def test_unblock_feeds_last_human_comment(monkeypatch):
    # 多条新人类评论 → 取最后一条作 detail（最贴近最新意图）。
    _patch_unblock_reads(
        monkeypatch,
        news=[
            _comment(created_at="t2", body="第一条"),
            _comment(created_at="t3", body="最后一条"),
        ],
    )
    msgs, orch, _state = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="code", block_watermark="t1")]
    )

    msgs.poll()

    assert orch.iterate_calls == [{"pr_number": 5, "reason": "human", "detail": "最后一条"}]


# --------------------------------------------------------------------------- #
# 无新人类评论 → 退回手动摘标签兜底（零回归）
# --------------------------------------------------------------------------- #


def test_no_new_comment_keeps_blocked_when_label_present(monkeypatch):
    # 无新人类评论 + needs-human 仍在 → 保持挂起（不解挂、不动状态）。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: True)
    msgs, _orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="code", block_watermark="t1")]
    )

    events = msgs.poll()

    assert events == []
    assert state.status_updates == []


def test_no_new_comment_label_removed_resumes_via_manual_fallback(monkeypatch):
    # 无新人类评论 + needs-human 已被人手动摘 → 走既有 label 兜底解挂（无 detail 注入）。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: False)
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="rfc", block_watermark="t1")]
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert orch.refine_calls == [] and orch.iterate_calls == []  # 兜底不注入 detail
    assert {"issue_number": 3, "status": STATUS_RFC_REVIEW} in state.status_updates


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
