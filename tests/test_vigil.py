"""RFC-0004 T2: Vigil 守夜人循环的契约测试。

外部副作用（github.list_issues、git ls-remote 子进程、time.sleep）与业务对象
（Orchestrator / Messages / State）一律 mock/桩，不真实派单或轮询。
"""

import subprocess
from pathlib import Path

import pytest

from openagents import github, vigil
from openagents.github import GithubError, Issue
from openagents.orchestrator import OrchestratorError
from openagents.state import STATUS_SOLVING, RunRecord
from openagents.vigil import Vigil


class _StubOrchestrator:
    """记录 start_rfc 调用（RFC-0005：派单只起草 RFC）；可配置对某些 issue 抛错。

    RFC-0007：记录 (issue_number, base, resume)，便于断言 fresh / resume 分流。
    """

    def __init__(self, *, fail_on=()):
        self.started = []
        self._fail_on = set(fail_on)

    def start_rfc(self, *, issue_number, base, resume=False):
        self.started.append((issue_number, base, resume))
        if issue_number in self._fail_on:
            raise OrchestratorError(f"boom #{issue_number}")
        return None


class _StubMessages:
    def __init__(self):
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1
        return []


def _run_record(*, issue_number, status, pr_number):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url="u" if pr_number else "",
        status=status,
        summary="",
    )


class _StubState:
    """find_by_issue 返回预置的 RunRecord（按 issue_number 映射），未命中返回 None。

    RFC-0007：records 形如 {9: RunRecord(...)}，用于覆盖 solving/pr=0 恢复与其它状态跳过。
    """

    def __init__(self, *, records=None):
        self._records = dict(records or {})

    def find_by_issue(self, *, issue_number):
        return self._records.get(issue_number)


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
    # RFC-0007：无 run + 远端无分支 → fresh 派单（resume=False）。
    assert orch.started == [(9, "main", False)]


def test_resumes_solving_orphan_run(monkeypatch):
    # RFC-0007 T3：solving/pr=0 的孤儿 run → resume 派单（resume=True），复用残留 worktree。
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [Issue(9, "t", "b")])
    orch = _StubOrchestrator()
    state = _StubState(records={9: _run_record(issue_number=9, status=STATUS_SOLVING, pr_number=0)})

    dispatched = _vigil(orchestrator=orch, state=state).discover_and_dispatch(
        labels=["openagents"], base="main"
    )

    assert dispatched == [9]
    assert orch.started == [(9, "main", True)]


def test_skips_issue_with_open_pr_record(monkeypatch):
    # RFC-0007 T3：已带 PR（pr-open）的 run 交 poll 推进，发现段跳过、不重复派单。
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [Issue(9, "t", "b")])
    orch = _StubOrchestrator()
    state = _StubState(records={9: _run_record(issue_number=9, status="pr-open", pr_number=1)})

    dispatched = _vigil(orchestrator=orch, state=state).discover_and_dispatch(
        labels=["openagents"], base="main"
    )

    assert dispatched == []
    assert orch.started == []


def test_skips_other_statuses(monkeypatch):
    # RFC-0007 T3：rfc-review / iterating / done / closed 均带 PR，交 poll，不派单。
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [Issue(9, "t", "b")])
    for status in ("rfc-review", "iterating", "done", "closed"):
        orch = _StubOrchestrator()
        state = _StubState(records={9: _run_record(issue_number=9, status=status, pr_number=1)})

        dispatched = _vigil(orchestrator=orch, state=state).discover_and_dispatch(
            labels=["openagents"], base="main"
        )

        assert dispatched == [], f"status={status} 不应派单"
        assert orch.started == []


def test_resume_not_repeated_after_rfc_review(monkeypatch):
    # RFC-0007 决策 6(b)：resume 成功落 rfc-review 后，下一轮归入「其它」被跳过，不重复派单。
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [Issue(9, "t", "b")])
    orch = _StubOrchestrator()
    # 第一轮：solving/pr=0 → resume。
    state = _StubState(records={9: _run_record(issue_number=9, status=STATUS_SOLVING, pr_number=0)})
    v = _vigil(orchestrator=orch, state=state)
    assert v.discover_and_dispatch(labels=["openagents"], base="main") == [9]
    # 模拟 resume 成功后状态翻到 rfc-review（带 pr）。
    state._records[9] = _run_record(issue_number=9, status="rfc-review", pr_number=5)
    assert v.discover_and_dispatch(labels=["openagents"], base="main") == []
    assert orch.started == [(9, "main", True)]


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
    assert (9, "main", False) in orch.started and (10, "main", False) in orch.started


def test_base_is_passed_through(monkeypatch):
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [Issue(9, "t", "b")])
    orch = _StubOrchestrator()

    _vigil(orchestrator=orch).discover_and_dispatch(labels=["x"], base="dev")

    assert orch.started == [(9, "dev", False)]


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


# --------------------------------------------------------------------------- #
# RFC-0010 T2：run 单轮 try/except 兜底（长驻吞异常续命 / once 上抛）
# --------------------------------------------------------------------------- #


def test_run_long_running_swallows_round_failure_and_continues(monkeypatch, capsys):
    # 长驻模式：第一轮 list_issues 抛 GithubError → 记日志、不崩、进下一轮；第二轮正常 poll
    # 后在 sleep 时 Ctrl-C 干净退出。
    _no_remote_branches(monkeypatch)
    rounds = {"n": 0}

    def flaky_list(*, labels):
        rounds["n"] += 1
        if rounds["n"] == 1:
            raise GithubError("HTTP 504: 504 Gateway Timeout")
        return []

    monkeypatch.setattr(github, "list_issues", flaky_list)

    # sleep 在第二轮之后才以 Ctrl-C 终止，确保第二轮真的跑到（证明失败后续命）。
    slept = {"n": 0}

    def fake_sleep(_seconds):
        slept["n"] += 1
        if slept["n"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(vigil.time, "sleep", fake_sleep)
    msgs = _StubMessages()

    _vigil(messages=msgs).run(interval=5, labels=["openagents"], base="main", once=False)

    assert rounds["n"] == 2  # 第一轮失败后续到了第二轮
    assert msgs.poll_count == 1  # 第一轮在发现段就抛、未到 poll；第二轮 poll 一次
    err = capsys.readouterr().err
    assert "本轮守夜失败" in err  # 失败被记录到 stderr，可观测


def test_run_long_running_swallows_generic_exception(monkeypatch):
    # 兜底范围比发现段更宽：poll 段抛通用 Exception（非 GithubError）也应被吞、续命。
    _no_remote_branches(monkeypatch)
    monkeypatch.setattr(github, "list_issues", lambda *, labels: [])

    class _BoomMessages:
        def __init__(self):
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            if self.poll_count == 1:
                raise RuntimeError("unexpected boom")
            return []

    slept = {"n": 0}

    def fake_sleep(_seconds):
        slept["n"] += 1
        if slept["n"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(vigil.time, "sleep", fake_sleep)
    msgs = _BoomMessages()

    _vigil(messages=msgs).run(interval=5, labels=["openagents"], base="main", once=False)

    assert msgs.poll_count == 2  # 第一轮 poll 抛错被吞，第二轮 poll 正常 → 续命成功


def test_run_once_propagates_round_failure(monkeypatch):
    # once 模式：单轮异常照旧上抛（不被吞），便于 cron/CI 得到非零退出。
    _no_remote_branches(monkeypatch)

    def boom(*, labels):
        raise GithubError("HTTP 504: 504 Gateway Timeout")

    monkeypatch.setattr(github, "list_issues", boom)

    with pytest.raises(GithubError):
        _vigil().run(interval=5, labels=["openagents"], base="main", once=True)
