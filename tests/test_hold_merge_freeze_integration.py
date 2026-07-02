"""Spec-0041/T4：hold-merge 夯住的端到端集成测试（离线确定性，全程 mock，不触网/不调真实 LLM/gh）。

用**真实 State**（tmp_path 落盘）+ 真实 Messages / identity + 内存 GitHub 世界（labels/comments）+
桩 orchestrator（review_code 恒 PASS 且计数），驱动 poll 多轮，断言：

1. 反震荡（bug 核心回归）：首轮 poll 冻结（blocked + needs-human + 成功文案 + block_gate=merge-hold）；
   次轮 poll reviewer 桩**未再被调**、状态仍 blocked、无新评论、rounds 不增。
2. 三出口：is_merged→done / merge-hold 新评论→iterate(reason=human) / 撕标签→resume 回 pr-open。
3. scratchpad 净化子断言（T3）：含内心独白的 reviewer summary 聚合后 feedback 不含独白、保留可操作反馈。
4. 成果看板「冻结后稳定」（理念 8）：两轮 poll 后各渲染的 board.html 里该 PR 行状态=blocked 且两份
   完全一致——浏览器 MCP 缺席时降级为 HTML 文本比对（不跳过成果验证，见 T4 spec）。
5. e2e 脚本被 PR 指路牌拾取。
"""

from pathlib import Path

import pytest

from openagents import blocknote, results
from openagents import messages as messages_module
from openagents.backends.base import AgentResult
from openagents.github import PR, CheckStatus, Comment, Mergeability
from openagents.hold import Hold
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision, review
from openagents.spec import signpost
from openagents.state import BLOCKED_LABEL, STATUS_BLOCKED, STATUS_DONE, STATUS_PR_OPEN, State

_AGENT_ID = "agent-e2e-0041"
_HOLD_MERGE = Hold(at_merge=True)
_ISSUE = 106
_PR = 5


class _CountingOrchestrator:
    """review_code 恒返回 PASS 并计数（反震荡断言的核心）；iterate 记录调用。"""

    def __init__(self):
        self.review_code_calls = 0
        self.iterate_calls = []

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return ReviewDecision(passed=True, feedback="", verdicts=("PASS",))

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})
        return "已据人类指导迭代代码摘要"


class _World:
    """内存 GitHub 世界：PR 标签集合 + 评论列表 + merge/close 开关，供 monkeypatch 接管。"""

    def __init__(self):
        self.labels = set()
        self.comments = []
        self.merged = False
        self.closed_issues = []
        self.merge_pr_calls = []

    def add_human_comment(self, *, body, created_at):
        self.comments.append(
            Comment(id=f"h{len(self.comments)}", author="alice", body=body, created_at=created_at)
        )


def _wire(monkeypatch, *, world):
    """把内存世界接到 github/identity 模块函数上（真实 identity.sign/new_human_comments 保留）。"""
    g = messages_module.github
    monkeypatch.setattr(g, "is_merged", lambda *, pr_number: world.merged)
    monkeypatch.setattr(g, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        g,
        "mergeability",
        lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN"),
    )
    monkeypatch.setattr(
        g, "check_status", lambda *, pr_number: CheckStatus(state="pass", failed_logs=[])
    )
    monkeypatch.setattr(g, "list_comments", lambda *, pr_number: list(world.comments))
    monkeypatch.setattr(g, "has_label", lambda *, pr_number, name: name in world.labels)
    monkeypatch.setattr(g, "add_label", lambda *, pr_number, name: world.labels.add(name))
    monkeypatch.setattr(g, "remove_label", lambda *, pr_number, name: world.labels.discard(name))
    monkeypatch.setattr(g, "merge_pr", lambda *, pr_number: world.merge_pr_calls.append(pr_number))
    monkeypatch.setattr(g, "close_issue", lambda *, number: world.closed_issues.append(number))

    # post_signed_comment：真实 identity.sign 盖签名后入库（created_at 单调递增模拟时序）。
    def _post_signed(*, pr_number, body, agent_id):
        stamp = f"2026-07-02T1{len(world.comments)}:00:00Z"
        signed = messages_module.identity.sign(body=body, agent_id=agent_id)
        world.comments.append(
            Comment(id=f"m{len(world.comments)}", author="bot", body=signed, created_at=stamp)
        )

    monkeypatch.setattr(messages_module.identity, "post_signed_comment", _post_signed)


def _setup(monkeypatch, tmp_path, *, status=STATUS_PR_OPEN):
    world = _World()
    _wire(monkeypatch, world=world)
    state = State(path=tmp_path / "state.json")
    state.record_run(
        issue_number=_ISSUE,
        branch=f"openagents/issue-{_ISSUE}",
        pr=PR(number=_PR, url=f"https://example/pull/{_PR}"),
        status=status,
    )
    orch = _CountingOrchestrator()
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)
    return msgs, orch, state, world


def _board_row(*, state, marker):
    """渲染看板并抽出含指定标记（如 '#5'）的那一行 <tr>（generated_at 每次不同，故只比行）。"""
    html = results.render(runs=state.all_runs())
    rows = [line for line in html.splitlines() if marker in line and "<tr>" in line]
    assert len(rows) == 1, f"看板应恰有一行含 {marker}，实际 {len(rows)}"
    return rows[0]


# --------------------------------------------------------------------------- #
# 1. 反震荡 + 成果看板「冻结后稳定」
# --------------------------------------------------------------------------- #


def test_freeze_then_no_re_review_and_board_stable(monkeypatch, tmp_path):
    msgs, orch, state, world = _setup(monkeypatch, tmp_path)

    # 首轮 poll：冻结。
    events1 = msgs.poll(hold=_HOLD_MERGE)
    assert events1 == [{"pr_number": _PR, "reason": "hold-merge", "gate": "merge-hold"}]
    assert orch.review_code_calls == 1
    rec = state.find_by_issue(issue_number=_ISSUE)
    assert rec.status == STATUS_BLOCKED
    assert rec.block_gate == "merge-hold"
    assert rec.block_watermark  # 落了水位线
    assert BLOCKED_LABEL in world.labels
    # 恰一条成功文案评论（非失败模板）。
    bot_comments = [c for c in world.comments if c.author == "bot"]
    assert len(bot_comments) == 1
    assert blocknote.build_hold_merge_pass() in bot_comments[0].body
    assert "卡住了" not in bot_comments[0].body
    assert world.merge_pr_calls == []  # 未自动合并

    # 看板第一份：该 PR 行状态=blocked。
    row1 = _board_row(state=state, marker=f"#{_PR}")
    assert '<span class="status">blocked</span>' in row1

    # 次轮 poll：无新人类评论（机器成功评论被签名滤掉）+ needs-human 仍在 → 保持挂起。
    events2 = msgs.poll(hold=_HOLD_MERGE)
    assert events2 == []
    # reviewer 桩未再被调（反震荡铁证）、状态仍 blocked、无新评论、rounds 不增。
    assert orch.review_code_calls == 1
    rec2 = state.find_by_issue(issue_number=_ISSUE)
    assert rec2.status == STATUS_BLOCKED
    assert rec2.rounds == 0
    assert len([c for c in world.comments if c.author == "bot"]) == 1

    # 看板第二份：与第一份该行完全一致（冻结后跨轮稳定，无震荡的可见成果）。
    row2 = _board_row(state=state, marker=f"#{_PR}")
    assert row2 == row1
    # 说明：真实浏览器成果验证（Playwright/chrome-devtools MCP navigate board.html + snapshot +
    # 截图 + console/network 无报错）在 e2e 脚本外由 agent 驱动；pytest 环境无浏览器 MCP，
    # 按 T4 spec 降级为此处 HTML 文本比对（不跳过成果验证）。


# --------------------------------------------------------------------------- #
# 2. 三出口
# --------------------------------------------------------------------------- #


def test_exit_human_merges_to_done(monkeypatch, tmp_path):
    msgs, orch, state, world = _setup(monkeypatch, tmp_path)
    msgs.poll(hold=_HOLD_MERGE)  # 冻结
    world.merged = True  # 人在 GitHub 上手动合并

    events = msgs.poll(hold=_HOLD_MERGE)

    assert events == [{"pr_number": _PR, "reason": "merged"}]
    assert state.find_by_issue(issue_number=_ISSUE).status == STATUS_DONE
    assert world.closed_issues == [_ISSUE]
    assert orch.review_code_calls == 1  # 合并出口未重审


def test_exit_new_comment_iterates_human(monkeypatch, tmp_path):
    msgs, orch, state, world = _setup(monkeypatch, tmp_path)
    msgs.poll(hold=_HOLD_MERGE)  # 冻结（水位线落在此刻最新评论）
    world.add_human_comment(body="再补一处空输入的单测", created_at="2026-07-02T20:00:00Z")

    events = msgs.poll(hold=_HOLD_MERGE)

    assert events == [{"pr_number": _PR, "reason": "resumed"}]
    assert orch.iterate_calls == [
        {"pr_number": _PR, "reason": "human", "detail": "再补一处空输入的单测"}
    ]
    assert BLOCKED_LABEL not in world.labels  # 自动摘标签
    assert state.find_by_issue(issue_number=_ISSUE).block_gate == ""  # 清残留 gate


def test_exit_label_torn_resumes_to_pr_open(monkeypatch, tmp_path):
    msgs, orch, state, world = _setup(monkeypatch, tmp_path)
    # 该 PR 已带 rfc-approved（coding 阶段的既有不变式）→ 撕标签 resume 回 pr-open。
    world.labels.add(messages_module.APPROVAL_LABEL)
    msgs.poll(hold=_HOLD_MERGE)  # 冻结
    world.labels.discard(BLOCKED_LABEL)  # 人手动摘 needs-human（无评论）

    events = msgs.poll(hold=_HOLD_MERGE)

    assert events == [{"pr_number": _PR, "reason": "resumed"}]
    rec = state.find_by_issue(issue_number=_ISSUE)
    assert rec.status == STATUS_PR_OPEN
    assert rec.block_gate == ""


# --------------------------------------------------------------------------- #
# 3. scratchpad 净化子断言（T3）
# --------------------------------------------------------------------------- #


class _ScriptedBackend:
    name = "scripted"

    def __init__(self, *, summaries):
        self._summaries = list(summaries)
        self._index = 0

    def run(self, *, work_dir, task, context):
        summary = self._summaries[self._index]
        self._index += 1
        return AgentResult(changed=False, summary=summary)


def test_reviewer_feedback_distilled_in_integration():
    monologue = (
        "VERDICT: REWORK\n"
        "All 32 tests pass. I have enough to finalize. Let me capture my findings.\n"
        "ISSUES:\n- messages.py:430 空操作未夯住"
    )
    backend = _ScriptedBackend(summaries=[monologue])
    decision = review(backend=backend, work_dir=".", kind="code", pr_number=_PR, n=1)
    assert decision.passed is False
    assert "I have enough" not in decision.feedback
    assert "messages.py:430" in decision.feedback


# --------------------------------------------------------------------------- #
# 4. e2e 脚本被 PR 指路牌拾取
# --------------------------------------------------------------------------- #


def test_e2e_script_picked_up_by_signpost():
    group_path = Path("docs/specs/0041-hold-merge-freeze.md")
    script = signpost.script_path_for_group(group_path=group_path)
    assert script == "scripts/e2e-spec-0041-hold-merge-freeze.sh"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
