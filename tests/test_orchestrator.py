"""RFC-0005: Orchestrator 四个原子操作的单元测试。

外部副作用全部 mock/注入：
- backend：注入记录 run 调用的伪 AgentBackend。
- github.*：monkeypatch 模块函数（get_issue / create_pr / post_comment / mark_ready）。
- git subprocess：monkeypatch subprocess.run（Workspace 借此操作 git），记录命令。

覆盖：start_rfc（建 worktree + 起草 RFC + 开 draft PR + 状态 rfc-review）、
refine_rfc（精炼 + 回贴评论 + 维持 rfc-review）、implement（写码 + mark_ready + pr-open）、
iterate（喂回反馈 + 追加 commit + iterating），以及未知 PR 抛错。
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


class _FakeWorkspace:
    """记录 prepare / ensure / commit_and_push 调用的伪 Workspace（RFC-0007 T2）。

    用于断言 fresh 走 prepare、resume 走 ensure，二者都不走对方的路径。
    """

    def __init__(self, *, root):
        self.prepare_calls = []
        self.ensure_calls = []
        self._root = root

    def prepare(self, *, issue_number, branch, base):
        self.prepare_calls.append({"issue_number": issue_number, "branch": branch, "base": base})
        return self._root / f"issue-{issue_number}"

    def ensure(self, *, issue_number, branch):
        self.ensure_calls.append({"issue_number": issue_number, "branch": branch})
        return self._root / f"issue-{issue_number}"

    def commit_and_push(self, *, worktree, branch, message):
        pass


def _make(tmp_path, *, backend=None):
    backend = backend or _FakeBackend()
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = Orchestrator(backend=backend, state=state, work_dir=tmp_path)
    return orch, backend, state


def _patch_get_issue(monkeypatch, *, title="fix bug", body="details"):
    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title=title, body=body),
    )


# --------------------------------------------------------------------------- #
# start_rfc
# --------------------------------------------------------------------------- #


def test_start_rfc_opens_draft_pr_and_sets_rfc_review(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _patch_get_issue(monkeypatch)
    captured = {}
    created = PR(number=5, url="https://github.com/acme/widget/pull/5")

    def _create_pr(*, branch, title, body, draft):
        captured.update(branch=branch, draft=draft)
        return created

    monkeypatch.setattr(orch_module.github, "create_pr", _create_pr)

    pr = orch.start_rfc(issue_number=3)

    assert pr == created
    assert captured["draft"] is True
    runs = state.all_runs()
    assert len(runs) == 1
    assert runs[0].issue_number == 3
    assert runs[0].status == "rfc-review"
    assert runs[0].pr_number == 5


def test_start_rfc_invokes_backend_with_rfc_task_in_worktree(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _patch_get_issue(monkeypatch, title="add feature", body="the body")
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body, draft: PR(number=5, url="u/pull/5"),
    )

    orch.start_rfc(issue_number=3)

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert "RFC" in call["task"]
    assert "add feature" in call["task"]
    # 在每 issue 独立 worktree 内起草，而非主工作树。
    assert call["work_dir"] == tmp_path / ".openagents" / "worktrees" / "issue-3"


def test_start_rfc_drafts_from_origin_base_and_commits_docs(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    _patch_get_issue(monkeypatch)
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body, draft: PR(number=5, url="u/pull/5"),
    )

    orch.start_rfc(issue_number=3, base="main")

    joined = [" ".join(c) for c in recorder.commands]
    assert any("fetch origin main" in c for c in joined)
    assert any("worktree add -b openagents/issue-3" in c and "origin/main" in c for c in joined)
    commit_cmds = [c for c in recorder.commands if "commit" in c]
    assert commit_cmds and "docs" in " ".join(commit_cmds[0])


def test_start_rfc_writes_rfc_review_in_single_record_run(tmp_path, monkeypatch):
    # RFC-0007 T2/决策 4：末态一次写成 rfc-review（带 pr），不再有随后的 update_status，
    # 故全程不出现瞬态 pr-open。
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _patch_get_issue(monkeypatch)
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body, draft: PR(number=5, url="u/pull/5"),
    )
    statuses = []
    orig_record = state.record_run
    orig_update = state.update_status

    def _spy_record(**kwargs):
        statuses.append(("record_run", kwargs.get("status")))
        return orig_record(**kwargs)

    def _spy_update(**kwargs):
        statuses.append(("update_status", kwargs.get("status")))
        return orig_update(**kwargs)

    monkeypatch.setattr(state, "record_run", _spy_record)
    monkeypatch.setattr(state, "update_status", _spy_update)

    orch.start_rfc(issue_number=3)

    # 唯一一次状态写入是 record_run(status=rfc-review)；没有任何 update_status 调用。
    assert statuses == [("record_run", "rfc-review")]
    assert state.all_runs()[0].status == "rfc-review"


def test_start_rfc_fresh_uses_prepare_and_begin_run(tmp_path, monkeypatch):
    # RFC-0007 T2：resume=False 走 prepare（建全新 worktree）并 begin_run（落 solving/pr=0）。
    orch, backend, state = _make(tmp_path)
    fake_ws = _FakeWorkspace(root=tmp_path)
    orch._workspace = fake_ws
    _patch_get_issue(monkeypatch)
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body, draft: PR(number=5, url="u/pull/5"),
    )
    begin_calls = []
    monkeypatch.setattr(
        state, "begin_run", lambda *, issue_number, branch: begin_calls.append(issue_number)
    )

    orch.start_rfc(issue_number=3, resume=False)

    assert fake_ws.prepare_calls == [
        {"issue_number": 3, "branch": "openagents/issue-3", "base": "main"}
    ]
    assert fake_ws.ensure_calls == []
    assert begin_calls == [3]


def test_start_rfc_resume_uses_ensure_and_skips_prepare_and_begin_run(tmp_path, monkeypatch):
    # RFC-0007 T2/决策 2：resume=True 走 ensure（复用残留 worktree），不调 prepare、不调 begin_run。
    orch, backend, state = _make(tmp_path)
    fake_ws = _FakeWorkspace(root=tmp_path)
    orch._workspace = fake_ws
    _patch_get_issue(monkeypatch)
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body, draft: PR(number=5, url="u/pull/5"),
    )
    begin_calls = []
    monkeypatch.setattr(
        state, "begin_run", lambda *, issue_number, branch: begin_calls.append(issue_number)
    )

    pr = orch.start_rfc(issue_number=3, resume=True)

    assert fake_ws.ensure_calls == [{"issue_number": 3, "branch": "openagents/issue-3"}]
    assert fake_ws.prepare_calls == []
    assert begin_calls == []
    # 恢复路径同样以一次写成的 rfc-review（带 pr）收尾。
    assert pr.number == 5
    assert state.all_runs()[0].status == "rfc-review"
    assert state.all_runs()[0].pr_number == 5


# --------------------------------------------------------------------------- #
# refine_rfc
# --------------------------------------------------------------------------- #


def test_refine_rfc_feeds_detail_posts_comment_and_keeps_rfc_review(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )
    state.update_status(issue_number=3, status="rfc-review")
    posted = {}
    monkeypatch.setattr(
        orch_module.github,
        "post_comment",
        lambda *, pr_number, body: posted.update(pr_number=pr_number, body=body),
    )

    orch.refine_rfc(pr_number=5, detail="请补充权衡章节")

    assert backend.calls[0]["context"] == "请补充权衡章节"
    assert "请补充权衡章节" in backend.calls[0]["task"]
    assert posted["pr_number"] == 5
    assert "done" in posted["body"]  # 回贴评论含后端摘要
    assert state.all_runs()[0].status == "rfc-review"


def test_refine_rfc_commit_message_is_docs(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    monkeypatch.setattr(orch_module.github, "post_comment", lambda *, pr_number, body: None)

    orch.refine_rfc(pr_number=5, detail="x")

    commit_cmds = [c for c in recorder.commands if "commit" in c]
    assert commit_cmds and "docs" in " ".join(commit_cmds[0])


def test_refine_rfc_unknown_pr_raises(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    with pytest.raises(OrchestratorError):
        orch.refine_rfc(pr_number=999, detail="x")


# --------------------------------------------------------------------------- #
# implement
# --------------------------------------------------------------------------- #


def test_implement_marks_ready_and_sets_pr_open(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.update_status(issue_number=3, status="rfc-review")
    ready = {}
    monkeypatch.setattr(
        orch_module.github, "mark_ready", lambda *, pr_number: ready.update(pr=pr_number)
    )

    orch.implement(pr_number=5)

    assert len(backend.calls) == 1
    assert ready["pr"] == 5
    assert state.all_runs()[0].status == "pr-open"


def test_implement_commit_message_is_feat(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    monkeypatch.setattr(orch_module.github, "mark_ready", lambda *, pr_number: None)

    orch.implement(pr_number=5)

    commit_cmds = [c for c in recorder.commands if "commit" in c]
    assert commit_cmds and "feat" in " ".join(commit_cmds[0])


def test_implement_unknown_pr_raises(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    with pytest.raises(OrchestratorError):
        orch.implement(pr_number=999)


# --------------------------------------------------------------------------- #
# iterate
# --------------------------------------------------------------------------- #


def test_iterate_feeds_detail_to_backend_and_appends_commit(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )

    orch.iterate(pr_number=5, reason="comment", detail="please fix the typo")

    assert backend.calls[0]["context"] == "please fix the typo"
    joined = [" ".join(c) for c in recorder.commands]
    assert any("commit" in c for c in joined)
    assert any("push" in c for c in joined)
    assert not any("--force" in c or "-f" in c.split() for c in joined)


def test_iterate_sets_status_iterating(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    orch.iterate(pr_number=5, reason="ci", detail="CI failed: lint error")

    assert state.all_runs()[0].status == "iterating"


def test_iterate_unknown_pr_raises(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    with pytest.raises(OrchestratorError):
        orch.iterate(pr_number=999, reason="comment", detail="x")


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
