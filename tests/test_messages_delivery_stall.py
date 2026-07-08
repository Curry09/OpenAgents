"""Spec-0056（PR #141 review 必修）：交付硬闸挂起的 sticky 收口 + 跨-poll 重入防护单元测试。

背景缺陷：orchestrator 有 record 的交付路径（refine/implement/iterate/run_e2e）在 head 前移硬闸
拦下时抛 DeliveryStalled；messages 必须在 poll 里 catch 它、用既有 `_block` 收口置 STATUS_BLOCKED——
否则只打 needs-human 标签而不置 status，下一轮 poll 仍进 coding **又派一次 executor 真跑 + 又贴一条
一模一样的 needs-human 评论**（有声但同样无界的重烧 + 刷屏）。

覆盖：
1. 交付硬闸抛 DeliveryStalled（coding 路径 run_e2e）→ _process_run catch → _block(gate="delivery")：
   置 STATUS_BLOCKED + gate="delivery" + 一条结构化签名评论 + 水位线 + 标签，事件 reason="blocked"。
2. **跨-poll 重入防护**（本 spec 初衷的正面证明）：blocked 后第二轮 poll **不再派 executor、不再贴新评论**。
3. 回评论解挂：block_gate="delivery" 走 iterate(reason="human")（与 code 闸同款）。
"""

from openagents import messages as messages_module
from openagents.messages import Messages
from openagents.orchestrator import DeliveryStalled
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_PR_OPEN,
    RunRecord,
)

_AGENT_ID = "agent-self"


class _FakeState:
    """内存单 run，支持 _block（update_status/set_block_gate/set_block_watermark）+ 解挂（reset_rounds）。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []
        self.block_gate_sets = []
        self.watermark_sets = []
        self.reset_calls = []
        self.increment_calls = 0

    def all_runs(self):
        return list(self._runs)

    def _find(self, issue_number):
        for record in self._runs:
            if record.issue_number == issue_number:
                return record
        return None

    def update_status(self, *, issue_number, status):
        self.status_updates.append(status)
        record = self._find(issue_number)
        if record is not None:
            record.status = status

    def set_block_gate(self, *, issue_number, gate):
        self.block_gate_sets.append(gate)
        record = self._find(issue_number)
        if record is not None:
            record.block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        self.watermark_sets.append(watermark)
        record = self._find(issue_number)
        if record is not None:
            record.block_watermark = watermark

    def reset_rounds(self, *, issue_number):
        self.reset_calls.append(issue_number)
        record = self._find(issue_number)
        if record is not None:
            record.rounds = 0

    def increment_rounds(self, *, issue_number):
        self.increment_calls += 1
        return 1


class _StallingOrchestrator:
    """run_e2e 恒抛 DeliveryStalled（模拟 executor 自判完成却没把证据推上去）；记 run_e2e/iterate 调用数。"""

    def __init__(self, *, branch, pr_number):
        self._branch = branch
        self._pr_number = pr_number
        self.run_e2e_calls = 0
        self.iterate_calls = []

    def run_e2e(self, *, pr_number):
        self.run_e2e_calls += 1
        raise DeliveryStalled(
            branch=self._branch,
            reason=f"分支 {self._branch} head 未前移、疑似未交付：origin=aaaaaa ≠ 本地 HEAD=bbbbbb",
            pr_number=pr_number,
        )

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})
        return "已据人类指导重新交付摘要"


class _MergeState:
    merge_state_status = "CLEAN"
    mergeable = "MERGEABLE"


class _CiPass:
    state = "pass"
    failed_logs: list[str] = []


def _coding_record():
    return RunRecord(
        issue_number=3,
        branch="openagents/issue-3",
        pr_number=5,
        pr_url="u/pull/5",
        status=STATUS_PR_OPEN,
        summary="",
    )


def _stub_github_reach_e2e(monkeypatch, *, posted, labels, has_blocked_label):
    """打桩 coding 流水线读到 run_e2e：CLEAN + CI 绿；并记录 _block 的评论/标签副作用。"""
    gh = messages_module.github
    defaults = {
        "is_merged": lambda *, pr_number: False,
        "is_closed": lambda *, pr_number: False,
        "mergeability": lambda *, pr_number: _MergeState(),
        "check_status": lambda *, pr_number: _CiPass(),
        "code_fingerprint": lambda *, pr_number: "",
        "add_label": lambda *, pr_number, name: labels.append(name),
        "remove_label": lambda *, pr_number, name: None,
        # _block 落水位线要读最新评论 createdAt。
        "list_comments": lambda *, pr_number: [],
        # 第二轮 blocked 分支：needs-human 是否仍在（True → 保持挂起）。
        "has_label": lambda *, pr_number, name: has_blocked_label(),
    }
    for name, fn in defaults.items():
        monkeypatch.setattr(gh, name, fn)
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(body),
    )
    # 第二轮 blocked 解挂读侧：默认无新人类评论（不解挂）。
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )


def test_delivery_stall_blocks_sticky_and_no_reentry_second_poll(monkeypatch):
    # (1)+(2)：交付硬闸抛 DeliveryStalled → 第一轮 _block(gate="delivery") 置 STATUS_BLOCKED + 一条评论；
    # 第二轮 poll 不再派 executor、不再贴新评论（sticky，杀掉无界重烧 + 刷屏）。
    posted: list[str] = []
    labels: list[str] = []
    orch = _StallingOrchestrator(branch="openagents/issue-3", pr_number=5)
    state = _FakeState(runs=[_coding_record()])
    _stub_github_reach_e2e(
        monkeypatch,
        posted=posted,
        labels=labels,
        # 第一轮 _block 之后 needs-human 视为已在（第二轮 blocked 分支据此保持挂起）。
        has_blocked_label=lambda: True,
    )
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)

    # --- 第一轮：交付硬闸拦下 → _block(delivery) 收口 ---
    events1 = msgs.poll()

    assert orch.run_e2e_calls == 1  # 派了一次 executor（真跑）
    assert events1 == [{"pr_number": 5, "reason": "blocked", "gate": "delivery"}]
    assert STATUS_BLOCKED in state.status_updates  # 置 BLOCKED（关键：status 才是 sticky 那半）
    assert state.block_gate_sets[-1] == "delivery"
    assert BLOCKED_LABEL in labels
    assert len(posted) == 1  # 恰一条结构化挂起评论
    assert "gate=delivery" in posted[0]
    assert state.increment_calls == 0  # run_e2e 在 increment_rounds 之前抛，未记轮

    # --- 第二轮：record 已 BLOCKED → _process_blocked，不再重入 coding ---
    events2 = msgs.poll()

    assert orch.run_e2e_calls == 1, "第二轮不该再派 executor（sticky，杀掉无界重烧）"
    assert len(posted) == 1, "第二轮不该再贴新评论（杀掉刷屏）"
    assert events2 == [], "blocked + needs-human 仍在 + 无新人类评论 → 保持挂起、无事件"


def test_delivery_unblock_by_comment_feeds_iterate_human(monkeypatch):
    # (3)：block_gate="delivery" 的回评论解挂与 code 闸同款——iterate(reason="human", detail)。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "remove_label", lambda *, pr_number, name: None)

    from openagents.github import Comment

    monkeypatch.setattr(
        messages_module.identity,
        "new_human_comments",
        lambda *, pr_number, since: [
            Comment(id="c1", author="alice", body="重新 push 一下你的改动", created_at="t2")
        ],
    )
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: None,
    )
    orch = _StallingOrchestrator(branch="openagents/issue-3", pr_number=5)
    record = _coding_record()
    record.status = STATUS_BLOCKED
    record.block_gate = "delivery"
    record.block_watermark = "t1"
    state = _FakeState(runs=[record])
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)

    events = msgs.poll()

    assert events == [{"pr_number": 5, "reason": "resumed"}]
    assert orch.iterate_calls == [
        {"pr_number": 5, "reason": "human", "detail": "重新 push 一下你的改动"}
    ]
    assert 3 in state.reset_calls


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-q"])
