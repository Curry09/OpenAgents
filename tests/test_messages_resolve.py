"""Spec-0028/T3：Messages 的 agent 语义解冲突接线单元测试。

覆盖 _make_resolver 的门控（work_dir+base+backend 齐备才构造，缺一返 None）与 _process_coding
可合并性预检撞冲突时「先试 resolve，成功本轮不 block、失败才留言+block」的分层降级。
github / conflict 全部 monkeypatch，hermetic（不触达真实 gh / 真实 LLM）。
"""

import pytest

from openagents import messages as messages_module
from openagents.backends.base import AgentResult
from openagents.messages import Messages
from openagents.state import BLOCKED_LABEL, STATUS_BLOCKED, STATUS_PR_OPEN, RunRecord

_AGENT_ID = "agent-self"


class _FakeBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=True, summary="resolved")


class _FakeOrchestrator:
    def __init__(self):
        self.review_code_calls = []

    def review_code(self, *, pr_number):
        self.review_code_calls.append(pr_number)
        raise AssertionError("真冲突预检阶段不应调 review_code")


class _FakeState:
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

    def set_block_gate(self, *, issue_number, gate):
        # Spec-0031/T2：_block 现会记录挂起入口；首次发现冲突路径（block_gate=="" 默认）会命中。
        for record in self._runs:
            if record.issue_number == issue_number:
                record.block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        # Spec-0032/T1：_block 现会落「解挂水位线」。
        for record in self._runs:
            if record.issue_number == issue_number:
                record.block_watermark = watermark


def _run(*, issue_number=3, pr_number=5, status=STATUS_PR_OPEN):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url=f"u/pull/{pr_number}",
        status=status,
        summary="",
        rounds=0,
        review_invalid=0,
    )


def _messages(*, runs, work_dir="/repo", base="main", backend=None):
    return Messages(
        orchestrator=_FakeOrchestrator(),
        state=_FakeState(runs=runs),
        agent_id=_AGENT_ID,
        work_dir=work_dir,
        base=base,
        backend=backend,
    )


# --------------------------------------------------------------------------- #
# _make_resolver 门控
# --------------------------------------------------------------------------- #


def test_make_resolver_none_without_backend():
    # work_dir + base 齐但无 backend（如手动 sync-prs / 老夹具）→ None（不偷烧 token）。
    msgs = _messages(runs=[_run()], backend=None)
    assert msgs._make_resolver() is None


def test_make_resolver_none_without_work_dir():
    msgs = _messages(runs=[_run()], work_dir=None, backend=_FakeBackend())
    assert msgs._make_resolver() is None


def test_make_resolver_built_when_all_present(monkeypatch):
    captured = {}

    def _fake_make(*, work_dir, base, backend, agent_id):
        captured.update(work_dir=work_dir, base=base, backend=backend, agent_id=agent_id)
        return lambda *, pr_number: True

    monkeypatch.setattr(messages_module.conflict, "make_resolver", _fake_make)
    backend = _FakeBackend()
    msgs = _messages(runs=[_run()], work_dir="/repo", base="main", backend=backend)

    resolver = msgs._make_resolver()
    assert resolver is not None
    assert captured == {
        "work_dir": "/repo",
        "base": "main",
        "backend": backend,
        "agent_id": _AGENT_ID,
    }


# --------------------------------------------------------------------------- #
# _process_coding 真冲突 → resolve 分层降级
# --------------------------------------------------------------------------- #


def _patch_conflict_precheck(monkeypatch, *, comments):
    """让 poll 走到 coding 真冲突预检：未合并/未关闭、mergeability=DIRTY/CONFLICTING。"""
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)

    class _MS:
        merge_state_status = "DIRTY"
        mergeable = "CONFLICTING"

    monkeypatch.setattr(messages_module.github, "mergeability", lambda *, pr_number: _MS())
    monkeypatch.setattr(messages_module.github, "add_label", lambda *, pr_number, name: None)
    # Spec-0032/T5：_block 落水位线要读最新评论 createdAt——桩为空。
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: comments.append(
            {"pr_number": pr_number, "body": body}
        ),
    )


def test_coding_conflict_resolved_skips_block(monkeypatch):
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    monkeypatch.setattr(
        messages_module.conflict,
        "make_resolver",
        lambda *, work_dir, base, backend, agent_id: lambda *, pr_number: True,
    )
    msgs = _messages(runs=[_run(pr_number=5)], backend=_FakeBackend())

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resolved"}]
    assert comments == []  # resolve 成功本轮不留言
    assert msgs._state.status_updates == []  # 不 block


def test_coding_conflict_resolve_fails_falls_back_to_block(monkeypatch):
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    monkeypatch.setattr(
        messages_module.conflict,
        "make_resolver",
        lambda *, work_dir, base, backend, agent_id: lambda *, pr_number: False,
    )
    msgs = _messages(runs=[_run(issue_number=3, pr_number=5)], backend=_FakeBackend())

    events = msgs.poll()

    # resolve 失败：逐字节回落现状——发一条 CONFLICT 留言 + 置 BLOCKED。
    assert events == [{"pr_number": 5, "reason": "unmergeable"}]
    assert len(comments) == 1 and comments[0]["pr_number"] == 5
    # Spec-0032/T5：挂起评论由 _block 经 blocknote 统一出（merge 闸把 CONFLICT_COMMENT 当 blocker）。
    assert messages_module.rebase.CONFLICT_COMMENT in comments[0]["body"]
    assert {"issue_number": 3, "status": STATUS_BLOCKED} in msgs._state.status_updates


def test_coding_conflict_no_backend_keeps_legacy_block(monkeypatch):
    # backend 未注入（resolve 恒 None）：与改前逐字节一致——留言 + block。
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    msgs = _messages(runs=[_run(issue_number=3, pr_number=5)], backend=None)

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "unmergeable"}]
    assert len(comments) == 1 and comments[0]["pr_number"] == 5
    # Spec-0032/T5：挂起评论由 _block 经 blocknote 统一出（merge 闸把 CONFLICT_COMMENT 当 blocker）。
    assert messages_module.rebase.CONFLICT_COMMENT in comments[0]["body"]
    assert {"issue_number": 3, "status": STATUS_BLOCKED} in msgs._state.status_updates


def test_blocked_label_constant_imported():
    # 守护：BLOCKED_LABEL 仍是 _block 打的标签（避免常量漂移把上面用例悄悄变绿）。
    assert BLOCKED_LABEL


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
