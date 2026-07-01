"""Spec-0036/T5：解挂后确定性贴回「引用原评论的签名回应」端到端单元测试。

github / identity / orchestrator / resolve 全部 hermetic 注入（monkeypatch / fake），不触网、
不调真实 LLM/gh。覆盖整条轨迹：
- rfc/code 闸解挂 → refine_rfc(announce=False)/iterate 回传 summary → 恰贴一条引用原评论的签名回应；
- merge 闸解挂当轮 → 存 unblock_detail、不回应；
- merge armed 下一轮 → 评论作 guidance 喂 resolve → 跑完恰贴一条引用原评论结论回应 + 清 unblock_detail；
- 回应均带签名（不自触发：解挂读侧按签名滤除）；
- 手动摘标签解挂（无评论）→ resolve(guidance="")、不回应（零回归）。
"""

import pytest

from openagents import identity as identity_module
from openagents import messages as messages_module
from openagents import replynote
from openagents.github import Comment
from openagents.messages import Messages
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_PR_OPEN,
    RunRecord,
)

_AGENT_ID = "agent-self"


class _FakeOrchestrator:
    """refine_rfc(announce)/iterate 回传 summary；review_* 在解挂路径不该被调。"""

    def __init__(
        self, *, refine_summary="RFC 已据你的意见补全权衡段", iterate_summary="已按你的指导补了测试"
    ):
        self.refine_calls = []
        self.iterate_calls = []
        self._refine_summary = refine_summary
        self._iterate_summary = iterate_summary

    def refine_rfc(self, *, pr_number, detail, announce=True):
        self.refine_calls.append({"pr_number": pr_number, "detail": detail, "announce": announce})
        return self._refine_summary

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})
        return self._iterate_summary

    def review_rfc(self, *, pr_number):
        raise AssertionError("解挂路径不应调 review_rfc")

    def review_code(self, *, pr_number):
        raise AssertionError("解挂路径不应调 review_code")


class _FakeState:
    """内存版 State：记录状态/标记/水位线/unblock_detail/reset 轨迹。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []
        self.block_gate_sets = []
        self.watermark_sets = []
        self.unblock_detail_sets = []
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

    def set_unblock_detail(self, *, issue_number, detail):
        self.unblock_detail_sets.append({"issue_number": issue_number, "detail": detail})
        record = self._find(issue_number)
        if record is not None:
            record.unblock_detail = detail

    def reset_rounds(self, *, issue_number):
        self.reset_calls.append(issue_number)
        record = self._find(issue_number)
        if record is not None:
            record.rounds = 0
            record.review_invalid = 0
            record.merge_attempts = 0

    def increment_merge_attempts(self, *, issue_number):
        record = self._find(issue_number)
        record.merge_attempts += 1
        return record.merge_attempts


class _FakeBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):  # pragma: no cover - resolve 已被 monkeypatch
        raise AssertionError("resolve 已被 monkeypatch，不应真起 backend")


def _run(*, issue_number=3, pr_number=5, block_gate="", block_watermark="", unblock_detail=""):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url=f"u/pull/{pr_number}",
        status=STATUS_BLOCKED,
        summary="",
        rounds=0,
        review_invalid=0,
        block_gate=block_gate,
        merge_attempts=0,
        block_watermark=block_watermark,
        unblock_detail=unblock_detail,
    )


def _comment(*, created_at, body, author="alice"):
    return Comment(id=f"c-{created_at}", author=author, body=body, created_at=created_at)


def _capture_posts(monkeypatch):
    """桩 identity.post_signed_comment（盖真实签名后记录正文），返回 posted 列表。"""
    posted = []

    def _post(*, pr_number, body, agent_id):
        # 走真实 sign，使「带签名 → 解挂读侧滤除」可被验证。
        posted.append(
            {"pr_number": pr_number, "body": identity_module.sign(body=body, agent_id=agent_id)}
        )

    monkeypatch.setattr(messages_module.identity, "post_signed_comment", _post)
    return posted


# --------------------------------------------------------------------------- #
# rfc / code 闸解挂：恰贴一条引用原评论的签名回应
# --------------------------------------------------------------------------- #


def _arm_unblock_reads(monkeypatch, *, news):
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: list(news)
    )
    monkeypatch.setattr(messages_module.github, "remove_label", lambda *, pr_number, name: None)


def test_rfc_unblock_posts_single_quoted_signed_reply(monkeypatch):
    _arm_unblock_reads(monkeypatch, news=[_comment(created_at="t2", body="补一下权衡章节")])
    posted = _capture_posts(monkeypatch)
    orch = _FakeOrchestrator(refine_summary="RFC 已据你的意见补全权衡段")
    state = _FakeState(runs=[_run(block_gate="rfc", block_watermark="t1")])
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    # refine_rfc 以 announce=False 调用（抑制泛化广播）。
    assert orch.refine_calls == [{"pr_number": 5, "detail": "补一下权衡章节", "announce": False}]
    # 恰一条回应：引用原评论 + agent summary。
    assert len(posted) == 1
    body = posted[0]["body"]
    assert "> 补一下权衡章节" in body
    assert "RFC 已据你的意见补全权衡段" in body
    # 带签名 → 解挂读侧 new_human_comments 会把它滤掉（不自触发）。
    assert identity_module.parse_agent_id(body=body) == _AGENT_ID


def test_code_unblock_posts_single_quoted_signed_reply(monkeypatch):
    _arm_unblock_reads(monkeypatch, news=[_comment(created_at="t2", body="先补测试再说")])
    posted = _capture_posts(monkeypatch)
    orch = _FakeOrchestrator(iterate_summary="已按你的指导补了测试")
    state = _FakeState(runs=[_run(block_gate="code", block_watermark="t1")])
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)

    msgs.poll()

    assert orch.iterate_calls == [{"pr_number": 5, "reason": "human", "detail": "先补测试再说"}]
    assert len(posted) == 1
    body = posted[0]["body"]
    assert "> 先补测试再说" in body
    assert "已按你的指导补了测试" in body
    assert identity_module.parse_agent_id(body=body) == _AGENT_ID


def test_reply_not_re_read_as_new_human_comment(monkeypatch):
    # 防自激（端到端走真实读侧）：解挂用真实 new_human_comments，回应带签名 → 下一轮读不到自己。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "remove_label", lambda *, pr_number, name: None)
    # 解挂当轮 PR 上只有人类评论（无签名）→ 真实 new_human_comments 命中它触发解挂。
    monkeypatch.setattr(
        messages_module.identity.github,
        "list_comments",
        lambda *, pr_number: [_comment(created_at="t2", body="改一下")],
    )
    posted = _capture_posts(monkeypatch)
    orch = _FakeOrchestrator()
    state = _FakeState(runs=[_run(block_gate="rfc", block_watermark="t1")])
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert len(posted) == 1
    reply_body = posted[0]["body"]
    # 下一轮：PR 上多了那条带签名的回应——真实 new_human_comments 按签名把它滤掉，只剩人类评论。
    monkeypatch.setattr(
        messages_module.identity.github,
        "list_comments",
        lambda *, pr_number: [
            _comment(created_at="t2", body="改一下"),
            _comment(created_at="t9", body=reply_body, author="bot"),
        ],
    )
    fresh = identity_module.new_human_comments(pr_number=5, since="t2")
    assert fresh == []  # 自己的签名回应读不到（t9 回应被签名滤除，t2 在水位线内）


# --------------------------------------------------------------------------- #
# merge 闸：当轮存 detail 不回 → 下一轮 armed 喂 guidance + 跑完回应
# --------------------------------------------------------------------------- #


def test_merge_unblock_stores_detail_and_defers_reply(monkeypatch):
    _arm_unblock_reads(monkeypatch, news=[_comment(created_at="t2", body="先解 OVERVIEW.md")])
    posted = _capture_posts(monkeypatch)
    orch = _FakeOrchestrator()
    state = _FakeState(runs=[_run(block_gate="merge", block_watermark="t1")])
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert {"issue_number": 3, "status": STATUS_PR_OPEN} in state.status_updates
    # 当轮存 detail、不回应。
    assert {"issue_number": 3, "detail": "先解 OVERVIEW.md"} in state.unblock_detail_sets
    assert posted == []


def _arm_armed_conflict(monkeypatch, *, resolve_result):
    """让 poll 走到 coding 真冲突预检 → armed 解冲突；返回 resolve 收到的 guidance 记录。"""
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)

    class _MS:
        merge_state_status = "DIRTY"
        mergeable = "CONFLICTING"

    monkeypatch.setattr(messages_module.github, "mergeability", lambda *, pr_number: _MS())
    monkeypatch.setattr(messages_module.github, "add_label", lambda *, pr_number, name: None)
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])
    monkeypatch.setattr(
        messages_module.conflictdiag,
        "make_diagnoser",
        lambda *, work_dir, base: (
            lambda *, pr_number: messages_module.conflictdiag.CONFLICT_COMMENT
        ),
    )
    seen = {"guidance": None}

    def _make(*, work_dir, base, backend, agent_id):
        def _resolve(*, pr_number, guidance=""):
            seen["guidance"] = guidance
            # resolve 现返回 ResolveOutcome；reply="" → 回应退回模板（本组断言不涉 agent reply）。
            return messages_module.conflict.ResolveOutcome(resolved=resolve_result)

        return _resolve

    monkeypatch.setattr(messages_module.conflict, "make_resolver", _make)
    return seen


def _armed_messages(*, orch, state):
    return Messages(
        orchestrator=orch,
        state=state,
        agent_id=_AGENT_ID,
        work_dir="/repo",
        base="main",
        backend=_FakeBackend(),
    )


def test_armed_with_detail_feeds_guidance_and_clears(monkeypatch):
    seen = _arm_armed_conflict(monkeypatch, resolve_result=True)
    posted = _capture_posts(monkeypatch)
    orch = _FakeOrchestrator()
    state = _FakeState(
        runs=[_run(block_gate="merge", unblock_detail="先解 OVERVIEW.md 再动 state.py")]
    )
    # armed 入口要求 status=pr-open。
    state.all_runs()[0].status = STATUS_PR_OPEN
    msgs = _armed_messages(orch=orch, state=state)

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resolved"}]
    # 评论作 guidance 喂解冲突器（解冲突 agent 会自己用 reply-comment 工具回评论）。
    assert seen["guidance"] == "先解 OVERVIEW.md 再动 state.py"
    # 框架**不代发回复**（agent 自己用带签名工具回）。
    assert posted == []
    # 跑完清空 unblock_detail。
    assert {"issue_number": 3, "detail": ""} in state.unblock_detail_sets


def test_armed_without_detail_no_guidance_no_reply(monkeypatch):
    # 手动摘标签解挂（无评论触发）→ unblock_detail 空 → resolve(guidance="")、不回应（零回归）。
    seen = _arm_armed_conflict(monkeypatch, resolve_result=True)
    posted = _capture_posts(monkeypatch)
    orch = _FakeOrchestrator()
    state = _FakeState(runs=[_run(block_gate="merge", unblock_detail="")])
    state.all_runs()[0].status = STATUS_PR_OPEN
    msgs = _armed_messages(orch=orch, state=state)

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resolved"}]
    assert seen["guidance"] == ""
    assert posted == []  # 无评论触发 → 不回应


def test_reply_body_structure_matches_replynote(monkeypatch):
    # 守护：回应正文的「引用 + 回应」结构出自 replynote.build（避免 messages 自造模板漂移）。
    _arm_unblock_reads(monkeypatch, news=[_comment(created_at="t2", body="改这里")])
    posted = _capture_posts(monkeypatch)
    orch = _FakeOrchestrator(refine_summary="改好了")
    state = _FakeState(runs=[_run(block_gate="rfc", block_watermark="t1")])
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)
    msgs.poll()

    expected_core = replynote.build(original="改这里", response="改好了")
    # 回应正文（去签名）应等于 replynote.build 的产出。
    assert expected_core in posted[0]["body"]
    # 守护标签常量仍是 _block 打的（防常量漂移）。
    assert BLOCKED_LABEL


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
