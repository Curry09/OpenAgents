"""RFC-0004 T2: Vigil 守夜人循环的契约测试。

外部副作用（github.list_issues、git ls-remote 子进程、time.sleep）与业务对象
（Orchestrator / Messages / State）一律 mock/桩，不真实派单或轮询。
"""

import subprocess
from pathlib import Path

from openagents import github, vigil
from openagents.github import Issue
from openagents.orchestrator import OrchestratorError
from openagents.state import RunRecord
from openagents.vigil import Vigil


class _StubOrchestrator:
    """记录 start_rfc 调用（RFC-0005：派单只起草 RFC）；可配置对某些 issue 抛错。"""

    def __init__(self, *, fail_on=()):
        self.started = []
        self._fail_on = set(fail_on)

    def start_rfc(self, *, issue_number, base):
        self.started.append((issue_number, base))
        if issue_number in self._fail_on:
            raise OrchestratorError(f"boom #{issue_number}")
        return None


class _StubMessages:
    def __init__(self):
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1
        return []


class _StubState:
    """find_by_issue 命中预置的 issue 编号集合。"""

    def __init__(self, *, known=()):
        self._known = set(known)

    def find_by_issue(self, *, issue_number):
        if issue_number in self._known:
            return RunRecord(
                issue_number=issue_number,
                branch=f"openagents/issue-{issue_number}",
                pr_number=1,
                pr_url="u",
                status="pr-open",
                summary="",
            )
        return None


def _vigil(*, orchestrator=None, messages=None, state=None, work_dir=Path("/repo")):
    return Vigil(
        orchestrator=orchestrator or _StubOrchestrator(),
        messages=messages or _StubMessages(),
        state=state or _StubState(),
        work_dir=work_dir,
    )


def _no_remote_branches(monkeypatch):
    """git ls-remote 一律返回空（远端无任何分支）。"""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout=""))


class _Proc:
    def __init__(self, *, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# --------------------------------------------------------------------------- #
# discover_and_dispatch：三道闸 + 错误隔离
# --------------------------------------------------------------------------- #


def test_discovers_and_dispatches_fresh_issue(monkeypatch):
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [Issue(9, "t", "b")])
    orch = _StubOrchestrator()

    dispatched = _vigil(orchestrator=orch).discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == [9]
    assert orch.started == [(9, "main")]


def test_skips_issue_with_existing_state_run(monkeypatch):
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [Issue(9, "t", "b")])
    orch = _StubOrchestrator()

    dispatched = _vigil(orchestrator=orch, state=_StubState(known={9})).discover_and_dispatch(
        labels=["openagents"], base="main"
    )

    assert dispatched == []
    assert orch.started == []


def test_skips_issue_with_existing_remote_branch(monkeypatch):
    # git ls-remote 对 issue-9 的分支返回非空 → 视为在途，跳过。
    def fake_run(args, **kwargs):
        if "openagents/issue-9" in args:
            return _Proc(stdout="abc123\trefs/heads/openagents/issue-9\n")
        return _Proc(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [Issue(9, "t", "b")])
    orch = _StubOrchestrator()

    dispatched = _vigil(orchestrator=orch).discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == []
    assert orch.started == []


def test_dispatch_failure_is_isolated(monkeypatch, capsys):
    # issue 9 的 start_rfc 抛错应被跳过，不影响 issue 10 的派单。
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(
        github, "list_issues", lambda *, labels: [Issue(9, "a", ""), Issue(10, "b", "")]
    )
    orch = _StubOrchestrator(fail_on={9})

    dispatched = _vigil(orchestrator=orch).discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == [10]
    assert (9, "main") in orch.started and (10, "main") in orch.started


def test_base_is_passed_through(monkeypatch):
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [Issue(9, "t", "b")])
    orch = _StubOrchestrator()

    _vigil(orchestrator=orch).discover_and_dispatch(labels=["x"], base="dev")

    assert orch.started == [(9, "dev")]


# --------------------------------------------------------------------------- #
# run：循环控制
# --------------------------------------------------------------------------- #


def test_run_once_does_not_sleep(monkeypatch):
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [])
    slept = []
    monkeypatch.setattr(vigil.time, "sleep", lambda s: slept.append(s))
    msgs = _StubMessages()

    _vigil(messages=msgs).run(interval=60, labels=["openagents"], base="main", once=True)

    assert msgs.poll_count == 1  # 守候段被调用一次
    assert slept == []  # once 模式不 sleep


def test_run_loops_until_keyboard_interrupt(monkeypatch):
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [])
    calls = {"n": 0}

    def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(vigil.time, "sleep", fake_sleep)
    msgs = _StubMessages()

    # 不带 once：循环到第 3 次 sleep 时被 Ctrl-C 干净打断，不抛出。
    _vigil(messages=msgs).run(interval=5, labels=["openagents"], base="main", once=False)

    assert calls["n"] == 3
    assert msgs.poll_count == 3  # 每轮一次 poll


def test_run_keyboard_interrupt_during_work_is_clean(monkeypatch):
    # 发现段就被 Ctrl-C 也应干净退出（不抛 KeyboardInterrupt）。
    def boom(*, labels):
        raise KeyboardInterrupt

    monkeypatch.setattr(github, "list_issues", boom)

    _vigil().run(interval=5, labels=["openagents"], base="main", once=False)
