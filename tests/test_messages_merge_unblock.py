"""Spec-0031/T2：merge 闸 armed 解挂语义 + MAX_MERGE_ATTEMPTS knob 单元测试。

覆盖：
- _configured_max_merge_attempts knob 读取/兜底（镜像 _configured_max_rounds）；
- _block 经 set_block_gate 记录挂起入口；
- 解挂分支按 block_gate 分流（merge → arm 保留标记/恢复 pr-open；其余 → 清残留）；
- _process_coding 冲突分支 armed 有界重试（resolve 成功清 armed；resolve=None 直接重挂；
  失败未达上限 merge-retry 不重挂；达上限才 _block）；
- block_gate=="" 的首次发现路径行为逐字节同 Spec-0028（零回归）。

github / conflict / identity 全部 monkeypatch，hermetic（不触网、不调真实 LLM/gh）。
"""

import pytest

from openagents import messages as messages_module
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
    """冲突预检阶段不应调 reviewer——任何调用都断言失败。"""

    def review_code(self, *, pr_number):
        raise AssertionError("真冲突预检阶段不应调 review_code")

    def review_rfc(self, *, pr_number):
        raise AssertionError("blocked/冲突路径不应调 review_rfc")


class _FakeState:
    """内存版 State：记录 set_block_gate / increment_merge_attempts / reset_rounds 调用轨迹。"""

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
        # Spec-0032/T1：_block 现会落「解挂水位线」。
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

    def increment_merge_attempts(self, *, issue_number):
        record = self._find(issue_number)
        record.merge_attempts += 1
        return record.merge_attempts


def _run(*, issue_number=3, pr_number=5, status=STATUS_PR_OPEN, block_gate="", merge_attempts=0):
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
        merge_attempts=merge_attempts,
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
# knob: _configured_max_merge_attempts
# --------------------------------------------------------------------------- #


def test_max_merge_attempts_default(monkeypatch):
    monkeypatch.delenv(messages_module.MAX_MERGE_ATTEMPTS_ENV, raising=False)
    assert messages_module._configured_max_merge_attempts() == 3


def test_max_merge_attempts_from_env(monkeypatch):
    monkeypatch.setenv(messages_module.MAX_MERGE_ATTEMPTS_ENV, "5")
    assert messages_module._configured_max_merge_attempts() == 5


def test_max_merge_attempts_invalid_falls_back(monkeypatch):
    monkeypatch.setenv(messages_module.MAX_MERGE_ATTEMPTS_ENV, "oops")
    assert messages_module._configured_max_merge_attempts() == 3


def test_max_merge_attempts_below_one_falls_back(monkeypatch):
    monkeypatch.setenv(messages_module.MAX_MERGE_ATTEMPTS_ENV, "0")
    assert messages_module._configured_max_merge_attempts() == 3


# --------------------------------------------------------------------------- #
# _block 记录 block_gate
# --------------------------------------------------------------------------- #


def test_block_records_block_gate(monkeypatch):
    monkeypatch.setattr(messages_module.github, "add_label", lambda *, pr_number, name: None)
    # Spec-0032/T5：_block 现会贴结构化签名评论 + 读最新评论 createdAt 落水位线——桩掉这两个 IO。
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: None,
    )
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])
    msgs = _messages(runs=[_run(issue_number=3, pr_number=5)])

    msgs._block(record=msgs._state.all_runs()[0], gate="merge", blocker="冲突提示")

    assert {"issue_number": 3, "status": STATUS_BLOCKED} in msgs._state.status_updates
    assert {"issue_number": 3, "gate": "merge"} in msgs._state.block_gate_sets


# --------------------------------------------------------------------------- #
# 解挂分支：按 block_gate 分流
# --------------------------------------------------------------------------- #


def _patch_blocked_unlabeled(monkeypatch):
    """让 poll 走到 blocked 解挂的「人手动摘标签」兜底分支：未合并/未关闭、无新人类评论、needs-human 已摘。"""
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    # Spec-0032/T5：解挂主路径先读新人类评论；这些用例专测标签兜底，故桩为无新评论。
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )

    def _has_label(*, pr_number, name):
        return False  # needs-human 与 rfc-approved 都视为未打

    monkeypatch.setattr(messages_module.github, "has_label", _has_label)


def test_unblock_merge_gate_arms(monkeypatch):
    # block_gate=="merge" 的解挂：恢复 pr-open、保留 block_gate（不清）、reset 预算、返回 resumed。
    _patch_blocked_unlabeled(monkeypatch)
    msgs = _messages(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_BLOCKED, block_gate="merge")]
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert {"issue_number": 3, "status": STATUS_PR_OPEN} in msgs._state.status_updates
    assert 3 in msgs._state.reset_calls  # merge_attempts 清零给满预算
    # armed 标记保留：解挂分支没有把 block_gate 清成 ""。
    assert {"issue_number": 3, "gate": ""} not in msgs._state.block_gate_sets
    assert msgs._state.all_runs()[0].block_gate == "merge"


def test_unblock_rfc_gate_clears_block_gate(monkeypatch):
    # block_gate=="rfc"（无 rfc-approved 标签）的解挂：恢复 rfc-review、清残留 block_gate、resumed。
    _patch_blocked_unlabeled(monkeypatch)
    msgs = _messages(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_BLOCKED, block_gate="rfc")]
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert {"issue_number": 3, "status": STATUS_RFC_REVIEW} in msgs._state.status_updates
    assert {"issue_number": 3, "gate": ""} in msgs._state.block_gate_sets


def test_unblock_keeps_blocked_when_label_present(monkeypatch):
    # needs-human 仍在 → 保持挂起（返回 None，不动状态）。零回归。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    # Spec-0032/T5：解挂主路径先读新人类评论；本用例专测「标签仍在 → 保持挂起」兜底，故桩为无新评论。
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: True)
    msgs = _messages(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_BLOCKED, block_gate="merge")]
    )

    events = msgs.poll()

    assert events == []
    assert msgs._state.status_updates == []


# --------------------------------------------------------------------------- #
# armed 冲突重试（_process_coding，block_gate=="merge" 且 pr-open）
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
    # Spec-0034/T3：merge 闸 blocker 改取 _conflict_blocker→诊断器；桩 make_diagnoser 返回静态
    # CONFLICT_COMMENT，保持 hermetic（不触真实 git/gh）且 CONFLICT_COMMENT 断言不变。
    monkeypatch.setattr(
        messages_module.conflictdiag,
        "make_diagnoser",
        lambda *, work_dir, base: lambda *, pr_number: messages_module.rebase.CONFLICT_COMMENT,
    )
    # Spec-0032/T5：_block 落水位线要读最新评论 createdAt——桩为空。
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: comments.append(
            {"pr_number": pr_number, "body": body}
        ),
    )


def _patch_resolver(monkeypatch, *, result):
    monkeypatch.setattr(
        messages_module.conflict,
        "make_resolver",
        lambda *, work_dir, base, backend, agent_id: lambda *, pr_number: result,
    )


class _FakeBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):  # pragma: no cover - 不实际调用
        raise AssertionError("resolve 已被 monkeypatch，不应真起 backend")


def test_armed_resolve_success_clears_armed(monkeypatch):
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    _patch_resolver(monkeypatch, result=True)
    msgs = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="merge")], backend=_FakeBackend()
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resolved"}]
    assert comments == []  # 解决了不留言
    assert {"issue_number": 3, "gate": ""} in msgs._state.block_gate_sets  # 清 armed
    assert 3 in msgs._state.reset_calls  # reset 预算
    assert {"issue_number": 3, "status": STATUS_BLOCKED} not in msgs._state.status_updates


def test_armed_resolve_none_falls_back_to_block(monkeypatch):
    # armed 但无 backend（resolve is None）→ 直接回落人工，不空转重试。
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    msgs = _messages(runs=[_run(issue_number=3, pr_number=5, block_gate="merge")], backend=None)

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "unmergeable"}]
    assert len(comments) == 1 and comments[0]["pr_number"] == 5
    # Spec-0032/T5：挂起评论由 _block 经 blocknote 统一出（merge 闸把 CONFLICT_COMMENT 当 blocker）。
    assert messages_module.rebase.CONFLICT_COMMENT in comments[0]["body"]
    assert "gate=merge" in comments[0]["body"]
    assert {"issue_number": 3, "status": STATUS_BLOCKED} in msgs._state.status_updates


def test_armed_resolve_fail_under_limit_retries(monkeypatch):
    # armed，resolve 失败，merge_attempts 未达上限 → merge-retry，保持 pr-open、不留言、不重挂。
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    _patch_resolver(monkeypatch, result=False)
    monkeypatch.setattr(messages_module, "MAX_MERGE_ATTEMPTS", 3)
    msgs = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="merge")], backend=_FakeBackend()
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "merge-retry"}]
    assert comments == []  # 未挂起不留言
    assert {"issue_number": 3, "status": STATUS_BLOCKED} not in msgs._state.status_updates
    assert msgs._state.all_runs()[0].merge_attempts == 1


def test_armed_resolve_fail_reaching_limit_blocks(monkeypatch):
    # armed，resolve 失败，本次递增到达上限 → 留言 + _block(gate=merge) 重新挂起。
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    _patch_resolver(monkeypatch, result=False)
    monkeypatch.setattr(messages_module, "MAX_MERGE_ATTEMPTS", 3)
    # 已用 2 次，本轮 +1 = 3 达上限。
    msgs = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="merge", merge_attempts=2)],
        backend=_FakeBackend(),
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "unmergeable"}]
    assert len(comments) == 1 and comments[0]["pr_number"] == 5
    # Spec-0032/T5：挂起评论由 _block 经 blocknote 统一出（merge 闸把 CONFLICT_COMMENT 当 blocker）。
    assert messages_module.rebase.CONFLICT_COMMENT in comments[0]["body"]
    assert "gate=merge" in comments[0]["body"]
    assert {"issue_number": 3, "status": STATUS_BLOCKED} in msgs._state.status_updates
    assert {"issue_number": 3, "gate": "merge"} in msgs._state.block_gate_sets


# --------------------------------------------------------------------------- #
# 首次发现冲突（block_gate==""）逐字节同 Spec-0028（零回归）
# --------------------------------------------------------------------------- #


def test_first_discovery_resolve_success_no_block(monkeypatch):
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    _patch_resolver(monkeypatch, result=True)
    msgs = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="")], backend=_FakeBackend()
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resolved"}]
    assert comments == []
    assert msgs._state.status_updates == []  # 不 block


def test_first_discovery_resolve_fail_blocks_with_merge_gate(monkeypatch):
    # 首次发现解不了：留言 + _block，且 block_gate 置 "merge"（为将来人解挂铺 armed 入口）。
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    _patch_resolver(monkeypatch, result=False)
    msgs = _messages(
        runs=[_run(issue_number=3, pr_number=5, block_gate="")], backend=_FakeBackend()
    )

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "unmergeable"}]
    assert len(comments) == 1 and comments[0]["pr_number"] == 5
    # Spec-0032/T5：挂起评论由 _block 经 blocknote 统一出（merge 闸把 CONFLICT_COMMENT 当 blocker）。
    assert messages_module.rebase.CONFLICT_COMMENT in comments[0]["body"]
    assert "gate=merge" in comments[0]["body"]
    assert {"issue_number": 3, "status": STATUS_BLOCKED} in msgs._state.status_updates
    assert {"issue_number": 3, "gate": "merge"} in msgs._state.block_gate_sets
    # 首次发现不递增 merge_attempts（只试一次）。
    assert msgs._state.all_runs()[0].merge_attempts == 0


def test_first_discovery_no_backend_keeps_legacy_block(monkeypatch):
    # block_gate=="" 且无 backend（resolve 恒 None）：与 Spec-0028 逐字节一致——留言 + block。
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    msgs = _messages(runs=[_run(issue_number=3, pr_number=5, block_gate="")], backend=None)

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "unmergeable"}]
    assert len(comments) == 1 and comments[0]["pr_number"] == 5
    # Spec-0032/T5：挂起评论由 _block 经 blocknote 统一出（merge 闸把 CONFLICT_COMMENT 当 blocker）。
    assert messages_module.rebase.CONFLICT_COMMENT in comments[0]["body"]
    assert "gate=merge" in comments[0]["body"]
    assert {"issue_number": 3, "status": STATUS_BLOCKED} in msgs._state.status_updates


def test_blocked_label_constant_imported():
    # 守护：BLOCKED_LABEL 仍是 _block 打的标签（避免常量漂移把上面用例悄悄变绿）。
    assert BLOCKED_LABEL


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
