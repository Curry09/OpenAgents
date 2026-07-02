"""Spec-0042/T4：close→reopen 复活的端到端集成测试（离线确定性，全程 mock，不触网/不调真实 LLM/gh）。

用**真实 State**（tmp_path 落盘）+ 真实 Messages + 内存 GitHub 世界（可变 PR state / draft /
labels / comments）+ 桩 orchestrator（review_code 恒 PASS），驱动 poll 演练完整时间线，断言：

1. 时间线（复活到 pr-open）：
   - 首轮 close → 置 closed + 打 closed_at 时间戳；
   - 次轮仍 closed → 被扫描但 return None、**不重打戳**、不复活；
   - 第三轮 reopen（PR state 翻 OPEN，转正）→ 复活到 pr-open、清 closed_at、返回 reopened；
   - 第四轮正常处理（复活后的 pr-open run 走既有代码闸 → PASS → merge → done）。
2. reopen draft → 复活到 rfc-review。
3. 成本有界：超窗口的 closed run 不进 _process_run（不发任何 gh）、不复活。
4. is_merged 恒 done 不复活（merge 不可逆）。
5. 成果看板：该 PR 行状态随时间线正确翻转（closed → 复活后 pr-open）——浏览器 MCP 缺席时降级为
   board.html HTML 文本断言（不跳过成果验证，见 T4 spec）。
6. e2e 脚本被 PR 指路牌拾取。
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openagents import messages as messages_module
from openagents import results
from openagents.github import PR, CheckStatus, Mergeability
from openagents.messages import REOPEN_REVIVE_WINDOW_SECONDS, Messages
from openagents.reviewer import ReviewDecision
from openagents.spec import signpost
from openagents.state import (
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    State,
)

_AGENT_ID = "agent-e2e-0042"
_ISSUE = 108
_PR = 105


class _CountingOrchestrator:
    """review_code 恒返回 PASS 并计数；其余方法被调即回归。"""

    def __init__(self):
        self.review_code_calls = 0

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return ReviewDecision(passed=True, feedback="", verdicts=("PASS",))

    def __getattr__(self, name):
        raise AssertionError(f"本演练不应调用 orchestrator.{name}")


class _World:
    """内存 GitHub 世界：可变 PR state / draft + labels/comments + merge/close 记录。"""

    def __init__(self):
        self.pr_state = "OPEN"  # OPEN / CLOSED / MERGED
        self.draft = False
        self.labels = set()
        self.comments = []
        self.merge_pr_calls = []
        self.closed_issues = []


def _wire(monkeypatch, *, world):
    g = messages_module.github
    monkeypatch.setattr(g, "is_merged", lambda *, pr_number: world.pr_state == "MERGED")
    monkeypatch.setattr(g, "is_closed", lambda *, pr_number: world.pr_state == "CLOSED")
    monkeypatch.setattr(g, "is_open", lambda *, pr_number: world.pr_state == "OPEN")
    monkeypatch.setattr(g, "is_draft", lambda *, pr_number: world.draft)
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
    """渲染看板并抽出含指定标记（如 '#105'）的那一行 <tr>（generated_at 每次不同，故只比行）。"""
    html = results.render(runs=state.all_runs())
    rows = [line for line in html.splitlines() if marker in line and "<tr>" in line]
    assert len(rows) == 1, f"看板应恰有一行含 {marker}，实际 {len(rows)}"
    return rows[0]


# --------------------------------------------------------------------------- #
# 1. 完整时间线：close → 仍 closed → reopen 复活 pr-open → 正常处理 done（含看板翻转）
# --------------------------------------------------------------------------- #


def test_full_timeline_close_then_reopen_revives_and_completes(monkeypatch, tmp_path):
    msgs, orch, state, world = _setup(monkeypatch, tmp_path)

    # --- 第一轮：人 close 了 PR ---
    world.pr_state = "CLOSED"
    events1 = msgs.poll()
    assert events1 == [{"pr_number": _PR, "reason": "closed"}]
    rec1 = state.find_by_issue(issue_number=_ISSUE)
    assert rec1.status == STATUS_CLOSED
    assert rec1.closed_at  # 打了时间戳
    stamp = rec1.closed_at
    row_closed = _board_row(state=state, marker=f"#{_PR}")
    assert '<span class="status">closed</span>' in row_closed

    # --- 第二轮：PR 仍 closed → 被扫描但不复活、不重打戳 ---
    events2 = msgs.poll()
    assert events2 == []
    rec2 = state.find_by_issue(issue_number=_ISSUE)
    assert rec2.status == STATUS_CLOSED
    assert rec2.closed_at == stamp  # 未重打戳（窗口不刷新，成本有界）
    assert _board_row(state=state, marker=f"#{_PR}") == row_closed  # 看板跨轮稳定

    # --- 第三轮：人 reopen 了 PR（转正、非 draft）→ 复活到 pr-open ---
    world.pr_state = "OPEN"
    world.draft = False
    events3 = msgs.poll()
    assert events3 == [{"pr_number": _PR, "reason": "reopened", "stage": STATUS_PR_OPEN}]
    rec3 = state.find_by_issue(issue_number=_ISSUE)
    assert rec3.status == STATUS_PR_OPEN
    assert rec3.closed_at == ""  # 清戳（退出复活窗口）
    assert orch.review_code_calls == 0  # 复活当轮不续跑闸（只做状态归位）
    row_reopened = _board_row(state=state, marker=f"#{_PR}")
    assert '<span class="status">pr-open</span>' in row_reopened
    assert row_reopened != row_closed  # 看板行随时间线翻转（closed → pr-open）

    # --- 第四轮：复活后的 pr-open run 走既有代码闸，正常处理到底（PASS → merge → done）---
    events4 = msgs.poll()
    assert events4 == [{"pr_number": _PR, "reason": "merged"}]
    assert orch.review_code_calls == 1  # 下一轮才真正跑评审闸
    assert world.merge_pr_calls == [_PR]
    assert world.closed_issues == [_ISSUE]
    assert state.find_by_issue(issue_number=_ISSUE).status == STATUS_DONE


# --------------------------------------------------------------------------- #
# 2. reopen draft → 复活到 rfc-review
# --------------------------------------------------------------------------- #


def test_reopen_draft_revives_to_rfc_review(monkeypatch, tmp_path):
    msgs, orch, state, world = _setup(monkeypatch, tmp_path)
    world.pr_state = "CLOSED"
    msgs.poll()  # close + 打戳

    world.pr_state = "OPEN"
    world.draft = True  # reopen 时仍是 draft（RFC 未批 / 代码未写完）
    events = msgs.poll()

    assert events == [{"pr_number": _PR, "reason": "reopened", "stage": STATUS_RFC_REVIEW}]
    rec = state.find_by_issue(issue_number=_ISSUE)
    assert rec.status == STATUS_RFC_REVIEW
    assert rec.closed_at == ""


# --------------------------------------------------------------------------- #
# 3. 成本有界：超窗口的 closed run 不进 _process_run（不发任何 gh）
# --------------------------------------------------------------------------- #


def test_out_of_window_closed_not_scanned(monkeypatch, tmp_path):
    msgs, orch, state, world = _setup(monkeypatch, tmp_path, status=STATUS_CLOSED)
    # 人为把 closed_at 设成超窗口（8 天前）——硬化成真终态。
    old = (datetime.now(UTC) - timedelta(seconds=REOPEN_REVIVE_WINDOW_SECONDS + 86400)).isoformat()
    state.set_closed_at(issue_number=_ISSUE, when=old)

    def _boom(*, pr_number):
        raise AssertionError("超窗口 closed run 不应发任何 gh")

    monkeypatch.setattr(messages_module.github, "is_merged", _boom)
    monkeypatch.setattr(messages_module.github, "is_open", _boom)

    events = msgs.poll()

    assert events == []
    assert state.find_by_issue(issue_number=_ISSUE).status == STATUS_CLOSED  # 仍真终态


# --------------------------------------------------------------------------- #
# 4. is_merged 恒 done 不复活（merge 不可逆）
# --------------------------------------------------------------------------- #


def test_merged_not_revived(monkeypatch, tmp_path):
    msgs, orch, state, world = _setup(monkeypatch, tmp_path)
    world.pr_state = "CLOSED"
    msgs.poll()  # close + 打戳（closed 复活候选）

    world.pr_state = "MERGED"  # PR 最终被 merge（不可逆）
    events = msgs.poll()

    assert events == [{"pr_number": _PR, "reason": "merged"}]
    assert state.find_by_issue(issue_number=_ISSUE).status == STATUS_DONE
    assert world.closed_issues == [_ISSUE]


# --------------------------------------------------------------------------- #
# 5. e2e 脚本被 PR 指路牌拾取
# --------------------------------------------------------------------------- #


def test_e2e_script_picked_up_by_signpost():
    group_path = Path("docs/specs/0042-reopen-revive-closed-run.md")
    script = signpost.script_path_for_group(group_path=group_path)
    assert script == "scripts/e2e-spec-0042-reopen-revive-closed-run.sh"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
