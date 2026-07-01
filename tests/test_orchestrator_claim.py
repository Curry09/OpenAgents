"""Spec-0039/T3：start_rfc 认领打标与清理的单元测试。

github.* 与 git 子进程（Workspace 借此操作 git）一律 mock/注入；聚焦认领标签的
「何时打、何时摘、失败如何传播」，不真实联网。既有 start_rfc 主流程回归由
test_orchestrator.py 覆盖。
"""

import subprocess

import pytest

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, GithubError, Issue
from openagents.state import State


class _FakeBackend:
    name = "fake"

    def __init__(self, *, events):
        self._events = events
        self._result = AgentResult(changed=True, summary="done")

    def run(self, *, work_dir, task, context):
        self._events.append("backend.run")
        return self._result


class _GitRecorder:
    def __call__(self, args, **kwargs):
        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Proc()


def _make(tmp_path, *, events):
    backend = _FakeBackend(events=events)
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = orch_module.Orchestrator(
        backend=backend, state=state, work_dir=tmp_path, agent_id="agent-x"
    )
    return orch, state


def _patch_common(monkeypatch, *, events, stamp=None, remove=None):
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="t", body="b"),
    )
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body, base, draft: PR(number=5, url="u/pull/5"),
    )

    def _default_stamp(*, number, name):
        events.append("stamp")

    def _default_remove(*, number, name):
        events.append("remove")

    monkeypatch.setattr(orch_module.github, "issue_stamp_label", stamp or _default_stamp)
    monkeypatch.setattr(orch_module.github, "issue_remove_label", remove or _default_remove)


# --------------------------------------------------------------------------- #
# 打标时机：fresh 路径 begin_run 后、backend.run 前
# --------------------------------------------------------------------------- #


def test_fresh_stamps_after_begin_run_and_before_backend_run(tmp_path, monkeypatch):
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)
    _patch_common(monkeypatch, events=events)
    orig_begin = state.begin_run
    monkeypatch.setattr(
        state,
        "begin_run",
        lambda *, issue_number, branch: (
            events.append("begin_run"),
            orig_begin(issue_number=issue_number, branch=branch),
        )[1],
    )

    orch.start_rfc(issue_number=3, resume=False)

    # 顺序：begin_run → 认领打标 → 后端起草。
    assert events.index("begin_run") < events.index("stamp") < events.index("backend.run")
    assert orch_module.github.DISPATCH_LABEL == "openagents-dispatching"


def test_pr_opened_then_claim_removed(tmp_path, monkeypatch):
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)
    _patch_common(monkeypatch, events=events)

    pr = orch.start_rfc(issue_number=3, resume=False)

    assert pr.number == 5
    # 认领标签在起草前打上、在 PR 开出后摘掉（remove 发生在 backend.run 之后）。
    assert events.index("remove") > events.index("backend.run")
    assert events.count("remove") == 1


# --------------------------------------------------------------------------- #
# resume 路径：ensure 认领在位（重打标签刷新时戳）
# --------------------------------------------------------------------------- #


def test_resume_ensures_claim_in_place(tmp_path, monkeypatch):
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)
    _patch_common(monkeypatch, events=events)
    # resume 前置：已有 solving/pr=0 的孤儿 run。
    state.begin_run(issue_number=3, branch="openagents/issue-3")

    orch.start_rfc(issue_number=3, resume=True)

    # resume 也 stamp（刷新认领年龄，避免被跨后端过期回收误抢），且在起草之前。
    assert "stamp" in events
    assert events.index("stamp") < events.index("backend.run")


# --------------------------------------------------------------------------- #
# 失败传播：stamp 失败上抛（不吞噬隔离语义）；remove 失败被吞（PR 已开出）
# --------------------------------------------------------------------------- #


def test_stamp_failure_propagates_as_github_error(tmp_path, monkeypatch):
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)

    def _boom_stamp(*, number, name):
        raise GithubError("HTTP 401 must authenticate")

    _patch_common(monkeypatch, events=events, stamp=_boom_stamp)

    # 认领打标失败 → GithubError 上抛，交给 vigil 的 per-issue 隔离；不在本层吞噬。
    with pytest.raises(GithubError):
        orch.start_rfc(issue_number=3, resume=False)
    # 起草未发生（打标先于起草，打标失败即中止本轮）。
    assert "backend.run" not in events


def test_remove_failure_is_swallowed_after_pr_open(tmp_path, monkeypatch):
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)

    def _boom_remove(*, number, name):
        raise GithubError("HTTP 502 bad gateway")

    _patch_common(monkeypatch, events=events, remove=_boom_remove)

    # 摘标签失败发生在 PR 开出之后 → 尽力而为吞掉，start_rfc 照常返回 PR、状态落 rfc-review。
    pr = orch.start_rfc(issue_number=3, resume=False)
    assert pr.number == 5
    assert state.all_runs()[0].status == "rfc-review"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
