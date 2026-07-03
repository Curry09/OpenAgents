"""Spec-0039/T4：两后端并发抢同一 issue 的去重集成测试（离线、确定性、可重复）。

不触网、不调真实 gh/LLM：用一个内存版 GitHub 世界（issue 标签 / 远端分支 / 标签时间线）
把 vigil 发现段的三道闸 + orchestrator 的认领打标/清理接起来，复现「A 先领、B 后到即跳过」
的真实竞态，并覆盖过期回收子用例。看板成果断言（A 有 issue#N 行、B 无）也在此离线完成
（results.render 纯本地静态页），是 e2e 脚本浏览器步骤的降级文本断言路径。
"""

from pathlib import Path

import pytest

from openagents import github, results
from openagents.github import DISPATCH_LABEL, PR, Issue
from openagents.state import STATUS_RFC_REVIEW, State
from openagents.vigil import CLAIM_EXPIRY_SECONDS, Vigil

_BRANCH_PREFIX = "openagents/issue-"


class FakeGitHubWorld:
    """内存版跨后端共享事实源：issue 标签 / 远端分支 / 标签「最近 labeled 事件」逻辑时戳。

    A、B 两后端各自的本地 State 互不可见，唯一共享的就是这个世界（对应真实里的 GitHub）。
    clock 是可推进的逻辑时钟（秒），issue_label_age_seconds 据它算认领年龄——确定性、无真实时间。
    """

    def __init__(self, *, issues):
        self._issues = list(issues)  # [(number, title, body)]
        self.issue_labels: dict[int, set[str]] = {n: {"openagents"} for n, _, _ in issues}
        self.branches: set[str] = set()
        self._last_labeled: dict[tuple[int, str], int] = {}
        self.clock = 0

    # --- 对应 github.* 的内存实现（测试里 monkeypatch 上去）--------------------- #
    def list_issues(self, *, labels, state="open"):
        return [
            Issue(number=n, title=t, body=b, labels=tuple(sorted(self.issue_labels.get(n, set()))))
            for n, t, b in self._issues
        ]

    def issue_add_label(self, *, number, name):
        self.issue_labels.setdefault(number, set()).add(name)
        self._last_labeled[(number, name)] = self.clock  # 每次 add 落一个「labeled 事件」时戳

    def issue_remove_label(self, *, number, name):
        self.issue_labels.setdefault(number, set()).discard(name)  # 幂等

    def issue_stamp_label(self, *, number, name):
        # remove-then-add：即便标签已在也刷新时戳（回收僵尸认领后不抖动）。
        self.issue_remove_label(number=number, name=name)
        self.issue_add_label(number=number, name=name)

    def issue_label_age_seconds(self, *, number, name):
        stamped = self._last_labeled.get((number, name))
        return None if stamped is None else self.clock - stamped

    def branch_exists(self, *, branch):
        return branch in self.branches


class RaceOrchestrator:
    """模拟真实 start_rfc 的认领时序：begin_run → 认领打标 → (慢起草窗口) → 推分支 → 摘认领。

    on_draft 钩子在「已认领、尚未推分支」的窗口里被调用——正是把另一后端塞进这个窗口、验证它
    读到认领标签即跳过（把竞态窗口做实）。单后端/无钩子时行为等价于一次正常派单。
    """

    def __init__(self, *, world, state, on_draft=None):
        self._world = world
        self._state = state
        self._on_draft = on_draft
        self.claimed_snapshots = []  # 记录「认领窗口内 issue 的标签」供断言

    def precheck_issue(self, *, issue_number):
        # Spec-0043/T3：认领去重用例的 issue 均自洽 → 放行（不干扰竞态窗口断言）。
        return False

    def start_rfc(self, *, issue_number, base, resume=False):
        branch = f"{_BRANCH_PREFIX}{issue_number}"
        self._state.begin_run(issue_number=issue_number, branch=branch)
        # 认领：begin_run 后、起草前（Spec-0039/T3 的写点）。
        github.issue_stamp_label(number=issue_number, name=DISPATCH_LABEL)
        if self._on_draft is not None:
            # 慢起草窗口：此刻已认领、分支未推——把另一后端塞进来验证它跳过。
            self.claimed_snapshots.append(set(self._world.issue_labels.get(issue_number, set())))
            self._on_draft()
        self._world.branches.add(branch)  # 推分支（此后 gate 2 接管去重）
        self._state.record_run(
            issue_number=issue_number,
            branch=branch,
            pr=PR(number=issue_number, url=f"u/{issue_number}"),
            status=STATUS_RFC_REVIEW,
        )
        github.issue_remove_label(number=issue_number, name=DISPATCH_LABEL)  # PR 开出后清理
        return PR(number=issue_number, url=f"u/{issue_number}")


class RecordingOrchestrator:
    """只记录派单、不动世界——用于过期回收子用例（只关心 _dispatch_kind 的 fresh/None 判定）。"""

    def __init__(self):
        self.started = []

    def precheck_issue(self, *, issue_number):
        # Spec-0043/T3：过期回收子用例只关心 fresh/None 判定，issue 自洽 → 放行。
        return False

    def start_rfc(self, *, issue_number, base, resume=False):
        self.started.append(issue_number)
        return PR(number=issue_number, url=f"u/{issue_number}")


def _wire_world(monkeypatch, world):
    monkeypatch.setattr(github, "list_issues", world.list_issues)
    monkeypatch.setattr(github, "issue_stamp_label", world.issue_stamp_label)
    monkeypatch.setattr(github, "issue_remove_label", world.issue_remove_label)
    monkeypatch.setattr(github, "issue_add_label", world.issue_add_label)
    monkeypatch.setattr(github, "issue_label_age_seconds", world.issue_label_age_seconds)
    # vigil._remote_branch_exists 走 git ls-remote 子进程 → 改判内存世界的分支集合。
    monkeypatch.setattr(
        Vigil,
        "_remote_branch_exists",
        lambda self, *, branch: world.branch_exists(branch=branch),
    )


def _vigil(*, orchestrator, state):
    return Vigil(orchestrator=orchestrator, messages=object(), state=state, work_dir=Path("/repo"))


# --------------------------------------------------------------------------- #
# 主竞态：A 先领、B 在起草窗口内到达 → 恰一个后端派单
# --------------------------------------------------------------------------- #


def test_two_backends_race_dedupes_to_single_dispatch(monkeypatch):
    world = FakeGitHubWorld(issues=[(42, "并发去重", "body")])
    _wire_world(monkeypatch, world)

    state_a = State(path=Path("/tmp/nonexistent-a"))  # 用内存态：下面 monkeypatch _load/_save
    state_b = State(path=Path("/tmp/nonexistent-b"))
    _make_in_memory(monkeypatch, state_a)
    _make_in_memory(monkeypatch, state_b)

    b_dispatched: list[list[int]] = []

    def b_runs_during_a_drafting():
        # A 认领后、推分支前，B 扫描发现段：应读到认领标签 → 跳过。
        vb = _vigil(orchestrator=RecordingOrchestrator(), state=state_b)
        b_dispatched.append(vb.discover_and_dispatch(labels=["openagents"], base="main"))

    orch_a = RaceOrchestrator(world=world, state=state_a, on_draft=b_runs_during_a_drafting)
    va = _vigil(orchestrator=orch_a, state=state_a)

    a_dispatched = va.discover_and_dispatch(labels=["openagents"], base="main")

    # 恰一个后端派单：A 领到、B 跳过。
    assert a_dispatched == [42]
    assert b_dispatched == [[]]
    # 认领窗口内 issue 确曾带认领标签（B 正是据它跳过）。
    assert orch_a.claimed_snapshots == [{"openagents", DISPATCH_LABEL}]
    # 远端恰一个 issue-42 分支；PR 开出后认领标签已摘。
    assert world.branches == {"openagents/issue-42"}
    assert DISPATCH_LABEL not in world.issue_labels.get(42, set())
    # A 的 state 有 issue#42 的 run，B 的 state 无。
    assert [r.issue_number for r in state_a.all_runs()] == [42]
    assert state_b.all_runs() == []


def test_boards_reflect_single_ownership(monkeypatch):
    # 成果可视化（理念 8）降级文本断言：A 看板有 issue#42 行，B 看板无（呈现「暂无成果记录」）。
    world = FakeGitHubWorld(issues=[(42, "并发去重", "body")])
    _wire_world(monkeypatch, world)
    state_a = State(path=Path("/tmp/nonexistent-a2"))
    state_b = State(path=Path("/tmp/nonexistent-b2"))
    _make_in_memory(monkeypatch, state_a)
    _make_in_memory(monkeypatch, state_b)

    def b_runs():
        _vigil(orchestrator=RecordingOrchestrator(), state=state_b).discover_and_dispatch(
            labels=["openagents"], base="main"
        )

    orch_a = RaceOrchestrator(world=world, state=state_a, on_draft=b_runs)
    _vigil(orchestrator=orch_a, state=state_a).discover_and_dispatch(
        labels=["openagents"], base="main"
    )

    board_a = results.render(runs=state_a.all_runs())
    board_b = results.render(runs=state_b.all_runs())
    assert "#42" in board_a
    assert "#42" not in board_b
    assert "暂无成果记录" in board_b


# --------------------------------------------------------------------------- #
# 过期回收子用例：僵尸认领超 T 判 fresh、未超 T 跳过
# --------------------------------------------------------------------------- #


def test_expired_claim_is_recovered_but_fresh_claim_is_skipped(monkeypatch):
    world = FakeGitHubWorld(issues=[(43, "僵尸认领", "body")])
    _wire_world(monkeypatch, world)
    state_b = State(path=Path("/tmp/nonexistent-b3"))
    _make_in_memory(monkeypatch, state_b)

    # 人为造一个认领标签（t=0 打上）、不建分支、B 本地无记录 → 僵尸认领占坑。
    world.clock = 0
    github.issue_stamp_label(number=43, name=DISPATCH_LABEL)

    # 未超 T：B 扫描应跳过（别人可能仍在慢起草）。
    world.clock = CLAIM_EXPIRY_SECONDS - 1
    orch = RecordingOrchestrator()
    dispatched = _vigil(orchestrator=orch, state=state_b).discover_and_dispatch(
        labels=["openagents"], base="main"
    )
    assert dispatched == []

    # 超 T：判僵尸认领 → 回收（视同 fresh 派单）。
    world.clock = CLAIM_EXPIRY_SECONDS + 1
    orch2 = RecordingOrchestrator()
    dispatched2 = _vigil(orchestrator=orch2, state=state_b).discover_and_dispatch(
        labels=["openagents"], base="main"
    )
    assert dispatched2 == [43]


def _make_in_memory(monkeypatch, state):
    """把一个 State 的落盘换成进程内 dict，避免真实文件 IO（确定性、隔离）。"""
    store = {"runs": [], "cursors": {}}
    monkeypatch.setattr(state, "_load", lambda: store)
    monkeypatch.setattr(state, "_save", lambda *, data: store.update(data))


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
