"""Spec-0043/T3：vigil 发现段 precheck 接线的单元测试。

github.list_issues / git ls-remote 子进程一律 mock，orchestrator/state 用桩。覆盖：
- fresh 冲突 issue：precheck 返回 True → start_rfc 不被调、continue；
- 带 needs-human 的 issue：_dispatch_kind 返回 None、precheck 不被调（判读只跑一次，防震荡）；
- 自洽 issue：precheck 返回 False → start_rfc 正常派单（零回归）；
- 摘掉 needs-human 后：重判为 fresh、precheck 被重新调用（人触发的一次重判）。
"""

import subprocess
from pathlib import Path

from openagents import github
from openagents.vigil import Vigil


class _StubOrchestrator:
    """记录 precheck_issue / start_rfc 调用；precheck 对预置 issue 返回冲突（True）。"""

    def __init__(self, *, conflict_on=()):
        self.precheck_calls: list[int] = []
        self.started: list[tuple[int, str, bool]] = []
        self._conflict_on = set(conflict_on)

    def precheck_issue(self, *, issue_number):
        self.precheck_calls.append(issue_number)
        return issue_number in self._conflict_on

    def start_rfc(self, *, issue_number, base, resume=False):
        self.started.append((issue_number, base, resume))
        return None


class _StubState:
    """find_by_issue 恒返回 None（无 run 记录，走 fresh 路径判定）。"""

    def find_by_issue(self, *, issue_number):
        return None


class _Proc:
    def __init__(self, *, stdout=""):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


def _no_remote_branches(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout=""))


def _patch_issues(monkeypatch, issues):
    monkeypatch.setattr(github, "list_issues", lambda *, labels, state="open": list(issues))


def _vigil(orch):
    return Vigil(orchestrator=orch, messages=None, state=_StubState(), work_dir=Path("/repo"))


def test_conflicting_fresh_issue_is_frozen_not_dispatched(monkeypatch):
    _no_remote_branches(monkeypatch)
    issue = github.Issue(number=106, title="标题主张 A", body="正文主张 B", labels=("openagents",))
    _patch_issues(monkeypatch, [issue])
    orch = _StubOrchestrator(conflict_on={106})

    dispatched = _vigil(orch).discover_and_dispatch(labels=["openagents"], base="main")

    # precheck 被调、判为冲突 → start_rfc 未被调、未派单。
    assert orch.precheck_calls == [106]
    assert orch.started == []
    assert dispatched == []


def test_needs_human_issue_skips_precheck_and_dispatch(monkeypatch):
    # 已冻结（带 needs-human）→ _dispatch_kind 返回 None → precheck 不被调（防复审震荡）。
    _no_remote_branches(monkeypatch)
    issue = github.Issue(
        number=106, title="t", body="b", labels=("openagents", github.BLOCKED_LABEL)
    )
    _patch_issues(monkeypatch, [issue])
    orch = _StubOrchestrator(conflict_on={106})

    dispatched = _vigil(orch).discover_and_dispatch(labels=["openagents"], base="main")

    assert orch.precheck_calls == [], "带 needs-human 的 issue 不得重跑判读"
    assert orch.started == []
    assert dispatched == []


def test_self_consistent_issue_dispatches_normally(monkeypatch):
    _no_remote_branches(monkeypatch)
    issue = github.Issue(number=200, title="清晰", body="一致", labels=("openagents",))
    _patch_issues(monkeypatch, [issue])
    orch = _StubOrchestrator(conflict_on=set())  # precheck 放行

    dispatched = _vigil(orch).discover_and_dispatch(labels=["openagents"], base="main")

    # 自洽 → precheck 放行 → 正常 fresh 派单（零回归）。
    assert orch.precheck_calls == [200]
    assert orch.started == [(200, "main", False)]
    assert dispatched == [200]


def test_unfreezing_by_removing_label_re_triggers_precheck(monkeypatch):
    # 摘掉 needs-human → 重新成 fresh → precheck 被重新调用（人触发的一次重判，有界）。
    _no_remote_branches(monkeypatch)
    orch = _StubOrchestrator(conflict_on=set())

    frozen = github.Issue(
        number=106, title="t", body="b", labels=("openagents", github.BLOCKED_LABEL)
    )
    _patch_issues(monkeypatch, [frozen])
    _vigil(orch).discover_and_dispatch(labels=["openagents"], base="main")
    assert orch.precheck_calls == []  # 冻结时不判

    unfrozen = github.Issue(number=106, title="t", body="b（已澄清）", labels=("openagents",))
    _patch_issues(monkeypatch, [unfrozen])
    _vigil(orch).discover_and_dispatch(labels=["openagents"], base="main")
    assert orch.precheck_calls == [106]  # 解冻后重判一次
    assert orch.started == [(106, "main", False)]  # 已自洽 → 正常派单
