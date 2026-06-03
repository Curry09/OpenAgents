"""RFC-0001 T4: Orchestrator 编排（决策 7/8）的单元测试。

外部副作用全部 mock/注入：
- backend：注入一个记录调用的伪 AgentBackend。
- github.*：monkeypatch 模块函数（get_issue / create_pr）。
- git subprocess：monkeypatch subprocess.run，记录每条 git 命令。

覆盖：solve 端到端状态流转（solving→pr-open）、建分支/commit/push 的 git 序列、
iterate 触发 backend 并追加 commit（不 force-push）、状态置 iterating。
"""

import subprocess

import pytest

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Issue
from openagents.orchestrator import Orchestrator, OrchestratorError
from openagents.state import State


class _FakeBackend:
    """记录 run 调用参数的伪后端，满足 AgentBackend 协议。"""

    name = "fake"

    def __init__(self, *, changed=True, summary="done"):
        self.calls = []
        self._result = AgentResult(changed=changed, summary=summary)

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        return self._result


class _GitRecorder:
    """subprocess.run 替身，记录所有 git 命令并返回成功。"""

    def __init__(self):
        self.commands = []

    def __call__(self, args, **kwargs):
        self.commands.append(list(args))

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Proc()


def _make(tmp_path, *, backend=None):
    """构造 Orchestrator + 其依赖。"""
    backend = backend or _FakeBackend()
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = Orchestrator(backend=backend, state=state, work_dir=tmp_path)
    return orch, backend, state


def test_solve_returns_pr_and_records_pr_open(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)

    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="fix bug", body="details"),
    )
    created_pr = PR(number=5, url="https://github.com/acme/widget/pull/5")
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body: created_pr,
    )

    pr = orch.solve(issue_number=3)

    assert pr == created_pr
    runs = state.all_runs()
    assert len(runs) == 1
    assert runs[0].issue_number == 3
    assert runs[0].status == "pr-open"
    assert runs[0].pr_number == 5


def test_solve_invokes_backend_with_issue_content(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="fix bug", body="the body"),
    )
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body: PR(number=5, url="u/pull/5"),
    )

    orch.solve(issue_number=3)

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert "fix bug" in call["task"]
    assert "the body" in call["task"]
    assert call["context"] == "the body"
    assert call["work_dir"] == tmp_path


def test_solve_creates_branch_and_pushes(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="t", body="b"),
    )
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body: PR(number=5, url="u/pull/5"),
    )

    orch.solve(issue_number=3)

    joined = [" ".join(c) for c in recorder.commands]
    # 建分支
    assert any("checkout" in c and "openagents/issue-3" in c for c in joined)
    # commit + push
    assert any("commit" in c for c in joined)
    assert any("push" in c for c in joined)


def test_solve_commit_message_is_conventional(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="t", body="b"),
    )
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body: PR(number=5, url="u/pull/5"),
    )

    orch.solve(issue_number=3)

    commit_cmds = [c for c in recorder.commands if "commit" in c]
    assert commit_cmds
    msg = " ".join(commit_cmds[0])
    # Conventional Commits 前缀
    assert any(t in msg for t in ("feat", "fix", "chore", "refactor"))


def test_iterate_feeds_detail_to_backend_and_appends_commit(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)

    # 先登记一条 run，使 iterate 能定位到对应分支。
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )

    orch.iterate(pr_number=5, reason="comment", detail="please fix the typo")

    assert len(backend.calls) == 1
    assert backend.calls[0]["context"] == "please fix the typo"

    joined = [" ".join(c) for c in recorder.commands]
    assert any("commit" in c for c in joined)
    assert any("push" in c for c in joined)
    # 决策 7：不 force-push
    assert not any("--force" in c or "-f" in c.split() for c in joined)


def test_iterate_sets_status_iterating(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )

    orch.iterate(pr_number=5, reason="ci", detail="CI failed: lint error")

    assert state.all_runs()[0].status == "iterating"


def test_iterate_unknown_pr_raises(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())

    with pytest.raises(OrchestratorError):
        orch.iterate(pr_number=999, reason="comment", detail="x")
