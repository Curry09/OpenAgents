"""Spec-0061/T3: recipes.vigil 发现→分诊→派单 控制流单测——假 backend 喂 triager 裁决。

证明架构契约：vigil 只按 triager 的结构化裁决路由（actionable→dispatch / 否→_park 挂 needs-human）、
自身零业务判断；去重三闸（本地 run 记录 / 远端分支 / needs-human 标签）确定性滤「新」。全程假
backend + 打桩 github/git，不触真实 LLM/网络/仓库；派单动作走注入的假 dispatch（不建真 worktree）。
"""

from __future__ import annotations

import json

from openagents.backends.base import AgentResult
from openagents.github import Issue
from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import Vigil
from openagents.runtime.state import RuntimeState


class _TriagerBackend:
    """假 backend：按 triager 的 task 文本回 canned 末行 JSON。

    task 是 triager.PROMPT 填好占位符后的串，含 issue 正文；正文里带 "PARK" → 判不可派单
    （actionable=false），否则可派单（actionable=true）。据此在单测里逐 issue 驱动两条路由。
    """

    name = "triager-fake"

    def __init__(self) -> None:
        self.tasks: list[str] = []

    def run(self, *, work_dir, task, context):
        self.tasks.append(task)
        actionable = "PARK" not in task
        return AgentResult(
            changed=False,
            summary=json.dumps({"actionable": actionable, "reason": "分诊理由R"}),
        )


class _GithubRecorder:
    """记录 vigil 对 github 写侧（打标签 / 贴评论）的调用，供 _park 路由断言。"""

    def __init__(self) -> None:
        self.added_labels: list[tuple[int, str]] = []
        self.comments: list[tuple[int, str]] = []

    def issue_add_label(self, *, number, name):
        self.added_labels.append((number, name))

    def issue_comment(self, *, number, body):
        self.comments.append((number, body))


def _patch(monkeypatch, *, issues, remote_exists=False):
    """打桩 vigil 依赖的 github.list_issues / git.remote_branch_exists，返回 github 写侧记录器。"""
    monkeypatch.setattr(vigil_module.github, "list_issues", lambda *, labels: list(issues))
    monkeypatch.setattr(
        vigil_module.git, "remote_branch_exists", lambda *, work_dir, branch: remote_exists
    )
    recorder = _GithubRecorder()
    monkeypatch.setattr(vigil_module.github, "issue_add_label", recorder.issue_add_label)
    monkeypatch.setattr(vigil_module.github, "issue_comment", recorder.issue_comment)
    return recorder


def _vigil(tmp_path, *, backend=None, dispatch_calls=None):
    """构造一个 Vigil：真 RuntimeState（tmp 文件）+ 注入假 dispatch（记录派单、不建真 worktree）。"""
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    calls = dispatch_calls if dispatch_calls is not None else []

    def _fake_dispatch(*, issue_number, base, backend, state, work_dir):
        calls.append({"issue_number": issue_number, "base": base})
        return {"delivered": True}

    vigil = Vigil(
        backend=backend or _TriagerBackend(),
        state=state,
        work_dir=tmp_path,
        dispatch=_fake_dispatch,
    )
    return vigil, state, calls


def test_actionable_issue_is_dispatched(monkeypatch, tmp_path):
    issue = Issue(number=145, title="重构", body="正文明确无矛盾")
    _patch(monkeypatch, issues=[issue])
    vigil, _state, calls = _vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == [145]
    assert calls == [{"issue_number": 145, "base": "main"}]


def test_non_actionable_issue_is_parked(monkeypatch, tmp_path):
    issue = Issue(number=145, title="含糊", body="修法自相矛盾 PARK")
    recorder = _patch(monkeypatch, issues=[issue])
    vigil, state, calls = _vigil(tmp_path)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    # 不可派单：不 dispatch，改为 _park —— 打 needs-human + 贴对齐评论 + 记 blocked run。
    assert dispatched == []
    assert calls == []
    assert recorder.added_labels == [(145, vigil_module.github.BLOCKED_LABEL)]
    assert len(recorder.comments) == 1
    assert "分诊理由R" in recorder.comments[0][1]
    run = state.get_run(issue_number=145)
    assert run["status"] == "blocked"


def test_dedup_gate_local_run_record(monkeypatch, tmp_path):
    # 闸①：本地已有 run 记录 → 判非新，triager 不被调、不派单。
    issue = Issue(number=145, title="t", body="b")
    _patch(monkeypatch, issues=[issue])
    backend = _TriagerBackend()
    vigil, state, calls = _vigil(tmp_path, backend=backend)
    state.set_run(issue_number=145, status="solving", branch="openagents/issue-145", pr_number=None)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == []
    assert calls == []
    assert backend.tasks == []  # triager 从未被派


def test_dedup_gate_remote_branch_exists(monkeypatch, tmp_path):
    # 闸②：远端已有该 issue 分支 → 判非新，不派单。
    issue = Issue(number=145, title="t", body="b")
    _patch(monkeypatch, issues=[issue], remote_exists=True)
    backend = _TriagerBackend()
    vigil, _state, calls = _vigil(tmp_path, backend=backend)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == []
    assert calls == []
    assert backend.tasks == []


def test_dedup_gate_blocked_label(monkeypatch, tmp_path):
    # 闸③：issue 已挂 needs-human → 判非新（人摘标签前不重判），不派单。
    issue = Issue(number=145, title="t", body="b", labels=(vigil_module.github.BLOCKED_LABEL,))
    _patch(monkeypatch, issues=[issue])
    backend = _TriagerBackend()
    vigil, _state, calls = _vigil(tmp_path, backend=backend)

    dispatched = vigil.discover_and_dispatch(labels=["openagents"], base="main")

    assert dispatched == []
    assert calls == []
    assert backend.tasks == []


def test_run_once_invokes_discover_then_poll(monkeypatch, tmp_path):
    # Vigil.run(once=True) 跑一轮发现段后调一次注入的守候段 poll，即返回。
    issue = Issue(number=145, title="t", body="b 正常")
    _patch(monkeypatch, issues=[issue])
    vigil, _state, calls = _vigil(tmp_path)
    poll_calls = {"n": 0}

    def _poll():
        poll_calls["n"] += 1

    vigil.run(interval=1, labels=["openagents"], base="main", once=True, poll=_poll)

    assert calls == [{"issue_number": 145, "base": "main"}]
    assert poll_calls["n"] == 1


def test_run_once_none_poll_only_discovers(monkeypatch, tmp_path):
    # poll=None 时只跑发现段，不因缺守候段报错。
    issue = Issue(number=145, title="t", body="b")
    _patch(monkeypatch, issues=[issue])
    vigil, _state, calls = _vigil(tmp_path)

    vigil.run(interval=1, labels=["openagents"], base="main", once=True, poll=None)

    assert calls == [{"issue_number": 145, "base": "main"}]
