"""Spec-0037/T1：合并扇出两调用点能力对称回归测试。

守夜人 messages.Messages.poll 有两个 rebase.rebase_open_prs 扇出调用点（都把刚进 main 的改动并入
其余 open PR）：① reconcile（下一轮 poll 发现 is_merged）路径；② reviewer-PASS 框架自动合并（同轮立即
扇出）路径。两处本应逐字节能力对称——都注入 heal / resolve / diagnose 三层降级。本测试 monkeypatch
rebase.rebase_open_prs 为捕获器，在 work_dir+base+backend 齐备夹具下分别驱动 poll 走两条扇出路径，断言
两次调用 kwargs 的 heal / resolve / diagnose 均为非 None callable——把「补一处忘补另一处」从靠人自觉变成
测试会失败的结构性红线。github / 三个能力工厂全部 monkeypatch，hermetic（不触真实 git/gh/LLM）。
"""

from openagents import messages as messages_module
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import STATUS_DONE, STATUS_PR_OPEN, RunRecord

_AGENT_ID = "agent-self"

# 三个能力工厂的哨兵返回值（distinct callable），用于断言「扇出确实注入了这一层」而非依赖工厂内部实现。
_HEAL = lambda *, pr_number: True  # noqa: E731 - 测试哨兵
_RESOLVE = lambda *, pr_number: True  # noqa: E731 - 测试哨兵
_DIAGNOSE = lambda *, pr_number: "diag"  # noqa: E731 - 测试哨兵


class _FakeBackend:
    """非 None 的 backend 占位——只为让 _make_resolver 的门控（backend is not None）放行。"""


class _FakeOrchestrator:
    def review_code(self, *, pr_number):
        # 自动合并路径：reviewer 全票 PASS → 框架自合 → 同轮扇出。
        return ReviewDecision(passed=True, feedback="", verdicts=[], actionable=False)


class _FakeState:
    def __init__(self, *, runs):
        self._runs = list(runs)

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        for record in self._runs:
            if record.issue_number == issue_number:
                record.status = status


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


def _messages(*, runs):
    # work_dir + base + backend 三者齐备：三个工厂门控全部放行，扇出本应注入 heal/resolve/diagnose 三层。
    return Messages(
        orchestrator=_FakeOrchestrator(),
        state=_FakeState(runs=runs),
        agent_id=_AGENT_ID,
        work_dir="/repo",
        base="main",
        backend=_FakeBackend(),
    )


def _patch_factories(monkeypatch):
    """把三个能力工厂换成返回哨兵 callable——隔离工厂内部，只验 messages 的注入接线。"""
    monkeypatch.setattr(messages_module.indexheal, "make_healer", lambda *, work_dir, base: _HEAL)
    monkeypatch.setattr(
        messages_module.conflict,
        "make_resolver",
        lambda *, work_dir, base, backend, agent_id: _RESOLVE,
    )
    monkeypatch.setattr(
        messages_module.conflictdiag, "make_diagnoser", lambda *, work_dir, base: _DIAGNOSE
    )


def _patch_fanout_capture(monkeypatch, *, captured):
    """把 rebase.rebase_open_prs 换成捕获器：记录每次调用的 heal/resolve/diagnose kwargs，返回 []。"""

    def _capture(*, merged_pr_number=None, agent_id=None, heal=None, resolve=None, diagnose=None):
        captured.append({"heal": heal, "resolve": resolve, "diagnose": diagnose})
        return []

    monkeypatch.setattr(messages_module.rebase, "rebase_open_prs", _capture)


def _assert_all_three_injected(call):
    """断言一次扇出调用注入的 heal / resolve / diagnose 均为非 None 的 callable。"""
    for layer in ("heal", "resolve", "diagnose"):
        assert call[layer] is not None, f"扇出漏注入 {layer}（应与另一调用点对称）"
        assert callable(call[layer]), f"{layer} 应为 callable"


# --------------------------------------------------------------------------- #
# 第一处 · reconcile（is_merged）扇出
# --------------------------------------------------------------------------- #


def test_reconcile_fanout_injects_heal_resolve_diagnose(monkeypatch):
    _patch_factories(monkeypatch)
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: True)
    monkeypatch.setattr(messages_module.github, "close_issue", lambda *, number: None)
    captured: list[dict] = []
    _patch_fanout_capture(monkeypatch, captured=captured)
    msgs = _messages(runs=[_run(pr_number=5)])

    events = msgs.poll()

    assert any(e["reason"] == "merged" for e in events)
    assert len(captured) == 1
    _assert_all_three_injected(captured[0])


# --------------------------------------------------------------------------- #
# 第二处 · reviewer-PASS 框架自动合并扇出（本组补回 heal/resolve 的那一处）
# --------------------------------------------------------------------------- #


def test_auto_merge_fanout_injects_heal_resolve_diagnose(monkeypatch):
    _patch_factories(monkeypatch)
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)

    class _MS:
        merge_state_status = "CLEAN"
        mergeable = "MERGEABLE"

    monkeypatch.setattr(messages_module.github, "mergeability", lambda *, pr_number: _MS())

    class _CS:
        state = "pass"
        failed_logs: list[str] = []

    monkeypatch.setattr(messages_module.github, "check_status", lambda *, pr_number: _CS())
    monkeypatch.setattr(messages_module.github, "merge_pr", lambda *, pr_number: None)
    monkeypatch.setattr(messages_module.github, "close_issue", lambda *, number: None)
    captured: list[dict] = []
    _patch_fanout_capture(monkeypatch, captured=captured)
    msgs = _messages(runs=[_run(pr_number=5)])

    events = msgs.poll()

    assert any(e["reason"] == "merged" for e in events)
    assert msgs._state.all_runs()[0].status == STATUS_DONE
    assert len(captured) == 1
    _assert_all_three_injected(captured[0])


# --------------------------------------------------------------------------- #
# 两调用点逐字节能力对称（核心防退化断言）
# --------------------------------------------------------------------------- #


def test_both_fanout_call_sites_inject_identical_capabilities(monkeypatch):
    """同一夹具下两条扇出路径注入的 heal/resolve/diagnose 完全一致——任一处漏注入则本测试红。"""
    _patch_factories(monkeypatch)
    monkeypatch.setattr(messages_module.github, "close_issue", lambda *, number: None)
    captured: list[dict] = []
    _patch_fanout_capture(monkeypatch, captured=captured)

    # 轨迹 A：reconcile（is_merged）。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: True)
    _messages(runs=[_run(pr_number=5)]).poll()

    # 轨迹 B：reviewer-PASS 自动合并。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)

    class _MS:
        merge_state_status = "CLEAN"
        mergeable = "MERGEABLE"

    monkeypatch.setattr(messages_module.github, "mergeability", lambda *, pr_number: _MS())

    class _CS:
        state = "pass"
        failed_logs: list[str] = []

    monkeypatch.setattr(messages_module.github, "check_status", lambda *, pr_number: _CS())
    monkeypatch.setattr(messages_module.github, "merge_pr", lambda *, pr_number: None)
    _messages(runs=[_run(pr_number=7)]).poll()

    assert len(captured) == 2
    reconcile_call, auto_merge_call = captured
    _assert_all_three_injected(reconcile_call)
    _assert_all_three_injected(auto_merge_call)
    # 逐键对称：两处注入的能力集逐字节一致（同款工厂哨兵）。
    assert reconcile_call == auto_merge_call
