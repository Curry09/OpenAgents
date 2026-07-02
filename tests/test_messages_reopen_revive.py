"""Spec-0042/T3：closed→reopen 复活窗口守卫 + 复活 reconcile 的单元测试。

用真实 State（tmp_path 上 hermetic 落盘）+ monkeypatch messages.github 的只读函数，不触网、
不调真实 gh/LLM。覆盖：
- open→closed 转移时置 closed + 打 closed_at 时间戳（仅这一次转移打戳）；
- 已 closed 且 PR 仍 closed（is_open=False）→ 被扫描但 return None、不重打戳、不复活；
- reopen（is_open=True）：draft→复活 rfc-review、转正→复活 pr-open，清 closed_at + 清回合预算 +
  清 block_gate 残留，返回 reopened 事件；
- 超窗口 / 无 closed_at 的 closed run 不进 _process_run（不发任何 gh）、不复活（成本有界）；
- is_merged 恒 done 不复活（merge 不可逆）。
"""

from datetime import UTC, datetime, timedelta

from openagents import messages as messages_module
from openagents.github import PR
from openagents.messages import REOPEN_REVIVE_WINDOW_SECONDS, Messages
from openagents.state import (
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    State,
)

_AGENT_ID = "agent-self"
_ISSUE = 108
_PR = 105


class _NoOrch:
    """复活/关闭/合并路径不触碰 orchestrator——任何调用都是回归。"""

    def __getattr__(self, name):
        raise AssertionError(f"复活/终态路径不应调用 orchestrator.{name}")


def _iso_ago(*, seconds):
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def _state_with_run(tmp_path, *, status, closed_at=""):
    """构造真实 State，落一条 issue=_ISSUE / pr=_PR 的 run，设置 status + closed_at。"""
    state = State(path=tmp_path / ".openagents" / "state.json")
    state.record_run(
        issue_number=_ISSUE,
        branch=f"openagents/issue-{_ISSUE}",
        pr=PR(number=_PR, url=f"u/pull/{_PR}"),
        status=STATUS_PR_OPEN,
    )
    if status != STATUS_PR_OPEN:
        state.update_status(issue_number=_ISSUE, status=status)
    if closed_at:
        state.set_closed_at(issue_number=_ISSUE, when=closed_at)
    return state


def _messages(state):
    return Messages(orchestrator=_NoOrch(), state=state, agent_id=_AGENT_ID)


def _patch_gh(monkeypatch, *, is_merged=False, is_closed=False, is_open=None, is_draft=None):
    """monkeypatch messages.github 的只读判定；未指定的 is_open/is_draft 调用即视为回归。"""
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: is_merged)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: is_closed)

    def _is_open(*, pr_number):
        assert is_open is not None, "本用例不应调用 is_open"
        return is_open

    def _is_draft(*, pr_number):
        assert is_draft is not None, "本用例不应调用 is_draft"
        return is_draft

    monkeypatch.setattr(messages_module.github, "is_open", _is_open)
    monkeypatch.setattr(messages_module.github, "is_draft", _is_draft)


# --------------------------------------------------------------------------- #
# open→closed：置 closed + 打 closed_at 时间戳
# --------------------------------------------------------------------------- #


def test_close_sets_closed_at_stamp(tmp_path, monkeypatch):
    state = _state_with_run(tmp_path, status=STATUS_PR_OPEN)
    _patch_gh(monkeypatch, is_merged=False, is_closed=True)

    events = _messages(state).poll()

    assert events == [{"pr_number": _PR, "reason": "closed"}]
    rec = state.find_by_issue(issue_number=_ISSUE)
    assert rec.status == STATUS_CLOSED
    assert rec.closed_at  # 打了时间戳（复活窗口起点）


# --------------------------------------------------------------------------- #
# 已 closed 且仍 closed：被扫描但不复活、不重打戳
# --------------------------------------------------------------------------- #


def test_still_closed_scanned_but_not_revived_no_restamp(tmp_path, monkeypatch):
    stamp = _iso_ago(seconds=3600)  # 1 小时前 close，在窗口内 → 被扫描
    state = _state_with_run(tmp_path, status=STATUS_CLOSED, closed_at=stamp)
    _patch_gh(monkeypatch, is_merged=False, is_open=False)  # PR 仍 closed

    events = _messages(state).poll()

    assert events == []  # 无事件（return None）
    rec = state.find_by_issue(issue_number=_ISSUE)
    assert rec.status == STATUS_CLOSED
    assert rec.closed_at == stamp  # 不重打戳（窗口不刷新）


# --------------------------------------------------------------------------- #
# reopen：draft→rfc-review、转正→pr-open，清 closed_at + 回合预算 + block_gate
# --------------------------------------------------------------------------- #


def test_reopen_draft_revives_rfc_review(tmp_path, monkeypatch):
    stamp = _iso_ago(seconds=3600)
    state = _state_with_run(tmp_path, status=STATUS_CLOSED, closed_at=stamp)
    _patch_gh(monkeypatch, is_merged=False, is_open=True, is_draft=True)

    events = _messages(state).poll()

    assert events == [{"pr_number": _PR, "reason": "reopened", "stage": STATUS_RFC_REVIEW}]
    rec = state.find_by_issue(issue_number=_ISSUE)
    assert rec.status == STATUS_RFC_REVIEW
    assert rec.closed_at == ""  # 清戳（退出复活窗口）


def test_reopen_ready_revives_pr_open_and_clears_residue(tmp_path, monkeypatch):
    stamp = _iso_ago(seconds=3600)
    state = _state_with_run(tmp_path, status=STATUS_CLOSED, closed_at=stamp)
    # reopen 前带上 armed 残留（曾在 merge 闸挂过）+ 攒过回合。
    state.set_block_gate(issue_number=_ISSUE, gate="merge")
    state.increment_rounds(issue_number=_ISSUE)
    _patch_gh(monkeypatch, is_merged=False, is_open=True, is_draft=False)

    events = _messages(state).poll()

    assert events == [{"pr_number": _PR, "reason": "reopened", "stage": STATUS_PR_OPEN}]
    rec = state.find_by_issue(issue_number=_ISSUE)
    assert rec.status == STATUS_PR_OPEN
    assert rec.closed_at == ""
    # reopen = 重来：block_gate 残留清空（避免复活到 pr-open 后被误判为 armed 解冲突）+ rounds 清零。
    assert rec.block_gate == ""
    assert rec.rounds == 0


# --------------------------------------------------------------------------- #
# 成本有界：超窗口 / 无 closed_at 的 closed run 不进 _process_run（不发任何 gh）
# --------------------------------------------------------------------------- #


def test_out_of_window_closed_not_scanned(tmp_path, monkeypatch):
    stamp = _iso_ago(seconds=REOPEN_REVIVE_WINDOW_SECONDS + 3600)  # 超窗口
    state = _state_with_run(tmp_path, status=STATUS_CLOSED, closed_at=stamp)

    def _boom(*, pr_number):
        raise AssertionError("超窗口 closed run 不应发任何 gh")

    monkeypatch.setattr(messages_module.github, "is_merged", _boom)
    monkeypatch.setattr(messages_module.github, "is_closed", _boom)
    monkeypatch.setattr(messages_module.github, "is_open", _boom)

    events = _messages(state).poll()

    assert events == []
    assert state.find_by_issue(issue_number=_ISSUE).status == STATUS_CLOSED  # 真终态


def test_missing_closed_at_closed_not_scanned(tmp_path, monkeypatch):
    # closed 但无 closed_at（如缺该键的旧 closed 记录）→ 非候选、不发 gh。
    state = _state_with_run(tmp_path, status=STATUS_CLOSED, closed_at="")

    def _boom(*, pr_number):
        raise AssertionError("无 closed_at 的 closed run 不应发任何 gh")

    monkeypatch.setattr(messages_module.github, "is_merged", _boom)
    monkeypatch.setattr(messages_module.github, "is_open", _boom)

    assert _messages(state).poll() == []


# --------------------------------------------------------------------------- #
# is_merged 恒 done 不复活（merge 不可逆）
# --------------------------------------------------------------------------- #


def test_merged_wins_over_revive(tmp_path, monkeypatch):
    stamp = _iso_ago(seconds=3600)  # closed 复活候选……
    state = _state_with_run(tmp_path, status=STATUS_CLOSED, closed_at=stamp)
    # ……但 PR 已被 merge（不可逆）→ 走 is_merged→done，不复活。
    _patch_gh(monkeypatch, is_merged=True)
    monkeypatch.setattr(messages_module.github, "close_issue", lambda *, number: None)

    events = _messages(state).poll()

    assert events == [{"pr_number": _PR, "reason": "merged"}]
    assert state.find_by_issue(issue_number=_ISSUE).status == STATUS_DONE
