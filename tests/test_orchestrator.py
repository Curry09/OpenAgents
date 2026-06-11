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

    def changed_rfc_path(self, *, worktree, base):
        # RFC-0008：start_rfc 开 PR 前会查本分支新增的 RFC 以拼端到端指路牌。
        # 这两个用例只断言 prepare/ensure/begin_run 路径，返回 None 让正文回退即可。
        return None


def _make(tmp_path, *, backend=None, agent_id="agent-x"):
    backend = backend or _FakeBackend()
    state = State(path=tmp_path / ".openagents" / "state.json")
    # RFC-0011 T4：Orchestrator 新增必填 agent_id（回贴评论盖章用）。
    orch = Orchestrator(backend=backend, state=state, work_dir=tmp_path, agent_id=agent_id)
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

    def _create_pr(*, branch, title, body, base, draft):
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
        lambda *, branch, title, body, base, draft: PR(number=5, url="u/pull/5"),
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
        lambda *, branch, title, body, base, draft: PR(number=5, url="u/pull/5"),
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
        lambda *, branch, title, body, base, draft: PR(number=5, url="u/pull/5"),
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
        lambda *, branch, title, body, base, draft: PR(number=5, url="u/pull/5"),
    )
    begin_calls = []
    monkeypatch.setattr(
        state, "begin_run", lambda *, issue_number, branch: begin_calls.append(issue_number)
    )

    orch.start_rfc(issue_number=3, resume=False)

    # RFC-0012 决策 2：默认基线由 main 改为 test。
    assert fake_ws.prepare_calls == [
        {"issue_number": 3, "branch": "openagents/issue-3", "base": "test"}
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
        lambda *, branch, title, body, base, draft: PR(number=5, url="u/pull/5"),
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


# RFC-0008 T3: PR 正文端到端验证指路牌

_RFC_WITH_E2E = """# RFC-0008: 示例

### 集成测试

- `scripts/e2e-rfc-0008-pr-e2e-signpost.sh`：默认离线跑 ruff + pytest。

### 手动验证

1. `openagents rfc <issue>` → 检查生成的 draft PR 正文含「## 端到端验证」段。
"""


def test_start_rfc_pr_body_includes_e2e_signpost(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _patch_get_issue(monkeypatch)
    # 造一份带测试方案的 RFC，并让 changed_rfc_path 指向它。
    rfc_file = tmp_path / "0008-pr-e2e-signpost.md"
    rfc_file.write_text(_RFC_WITH_E2E, encoding="utf-8")
    monkeypatch.setattr(orch._workspace, "changed_rfc_path", lambda *, worktree, base: rfc_file)
    captured = {}

    def _create_pr(*, branch, title, body, base, draft):
        captured.update(body=body)
        return PR(number=5, url="u/pull/5")

    monkeypatch.setattr(orch_module.github, "create_pr", _create_pr)

    orch.start_rfc(issue_number=3)

    body = captured["body"]
    assert "## 端到端验证" in body
    assert "`bash scripts/e2e-rfc-0008-pr-e2e-signpost.sh`" in body
    assert "RFC-0008「手动验证」" in body
    # 指路牌追加在原有 Closes + 摘要之后，不替换它们。
    assert body.startswith("Closes #3")


def test_start_rfc_pr_body_omits_e2e_when_no_rfc(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _patch_get_issue(monkeypatch)
    # changed_rfc_path 取不到 RFC 文件时正文回退为原样、不抛错。
    monkeypatch.setattr(orch._workspace, "changed_rfc_path", lambda *, worktree, base: None)
    captured = {}

    def _create_pr(*, branch, title, body, base, draft):
        captured.update(body=body)
        return PR(number=5, url="u/pull/5")

    monkeypatch.setattr(orch_module.github, "create_pr", _create_pr)

    orch.start_rfc(issue_number=3)

    assert "## 端到端验证" not in captured["body"]
    assert captured["body"].startswith("Closes #3")


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
    # RFC-0011 T4：回贴评论盖本实例签名，用于溯源/审计（RFC-0019：poll 不读评论，
    # 自动流转由 reviewer 闸驱动）。
    from openagents.identity import parse_agent_id

    assert parse_agent_id(body=posted["body"]) == "agent-x"
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
# RFC-0013: implement 转正前实跑 e2e + 签名结果评论
# --------------------------------------------------------------------------- #


def _arm_implement(orch, state, monkeypatch, *, e2e_outcome="passed", rfc_path="/tmp/0013.md"):
    """给 implement 接好 RFC-0013 旁路所需的全部替身，返回事件记录器。

    monkeypatch：changed_rfc_path / rfc.script_path_for / e2e.run_e2e_script /
    e2e.render_result / identity.post_signed_comment / github.mark_ready，并记录调用顺序。
    """
    from openagents.e2e import E2EResult

    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    events = {"order": [], "comment": None, "run_e2e": [], "mark_ready": None}

    monkeypatch.setattr(orch._workspace, "changed_rfc_path", lambda *, worktree, base: rfc_path)
    monkeypatch.setattr(orch_module.rfc, "script_path_for", lambda *, rfc_path: "scripts/x.sh")

    def _run_e2e(*, worktree, script_path, timeout_seconds, tail_lines):
        events["order"].append("run_e2e")
        events["run_e2e"].append({"script_path": script_path})
        return E2EResult(
            outcome=e2e_outcome,
            exit_code=0 if e2e_outcome == "passed" else 1,
            script_path=script_path,
            log_tail="log",
            timed_out=False,
        )

    monkeypatch.setattr(orch_module.e2e, "run_e2e_script", _run_e2e)
    monkeypatch.setattr(
        orch_module.e2e, "render_result", lambda *, result, tail_lines: "## 端到端测试结果\nbody"
    )

    def _post(*, pr_number, body, agent_id):
        events["order"].append("post_comment")
        events["comment"] = {"pr_number": pr_number, "body": body, "agent_id": agent_id}

    monkeypatch.setattr(orch_module.identity, "post_signed_comment", _post)

    def _mark_ready(*, pr_number):
        events["order"].append("mark_ready")
        events["mark_ready"] = pr_number

    monkeypatch.setattr(orch_module.github, "mark_ready", _mark_ready)
    return events


def test_implement_runs_e2e_and_posts_signed_comment_before_mark_ready(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path, agent_id="agent-007")
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    events = _arm_implement(orch, state, monkeypatch)

    orch.implement(pr_number=5)

    # 实跑 → 发结果评论 → 转正，严格按此序（评论在 mark_ready 前）。
    assert events["order"] == ["run_e2e", "post_comment", "mark_ready"]
    assert events["run_e2e"][0]["script_path"] == "scripts/x.sh"
    assert events["comment"]["pr_number"] == 5
    assert events["comment"]["agent_id"] == "agent-007"
    assert "端到端测试结果" in events["comment"]["body"]
    assert events["mark_ready"] == 5


def test_implement_e2e_failed_still_marks_ready(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    events = _arm_implement(orch, state, monkeypatch, e2e_outcome="failed")

    orch.implement(pr_number=5)

    # e2e 失败仅发评论、不阻断转正（决策 6）。
    assert events["mark_ready"] == 5
    assert events["comment"] is not None
    assert state.all_runs()[0].status == "pr-open"


def test_implement_no_rfc_runs_skipped_still_posts_and_marks_ready(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    events = _arm_implement(orch, state, monkeypatch, rfc_path=None)

    orch.implement(pr_number=5)

    # changed_rfc_path 为 None → script_path=None 传入 run_e2e_script，仍发评论且转正。
    assert events["run_e2e"][0]["script_path"] is None
    assert events["comment"] is not None
    assert events["mark_ready"] == 5


def test_implement_comment_failure_does_not_block_mark_ready(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    events = _arm_implement(orch, state, monkeypatch)

    def _boom(*, pr_number, body, agent_id):
        events["order"].append("post_comment")
        raise RuntimeError("gh 故障")

    monkeypatch.setattr(orch_module.identity, "post_signed_comment", _boom)

    orch.implement(pr_number=5)

    # 发评论抛错被吞掉，mark_ready 仍执行、流程不崩（决策 6）。
    assert events["mark_ready"] == 5
    assert state.all_runs()[0].status == "pr-open"


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


# --------------------------------------------------------------------------- #
# RFC-0012 T5：implement 清零 rounds + review_rfc / review_code 评审闸
# --------------------------------------------------------------------------- #


def test_implement_resets_rounds(tmp_path, monkeypatch):
    # RFC-0012 决策 6：进入代码闸前清零回合数（K 对每个闸独立计）。
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.increment_rounds(issue_number=3)
    state.increment_rounds(issue_number=3)
    monkeypatch.setattr(orch_module.github, "mark_ready", lambda *, pr_number: None)

    orch.implement(pr_number=5)

    assert state.all_runs()[0].rounds == 0


def test_review_rfc_pass_returns_decision(tmp_path, monkeypatch):
    # reviewer backend 返回 PASS → review_rfc 聚合为 passed=True。
    backend = _FakeBackend(summary="VERDICT: PASS\nREASON: 对齐需求")
    orch, _, state = _make(tmp_path, backend=backend)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    decision = orch.review_rfc(pr_number=5)

    assert decision.passed is True
    # reviewer 在 PR 的 worktree 内、用 rfc 模板评审。
    assert "RFC" in backend.calls[0]["task"]


def test_review_code_non_pass_carries_feedback(tmp_path, monkeypatch):
    backend = _FakeBackend(summary="VERDICT: REWORK\nISSUES:\n- foo.py:1 缺测试\nNEXT: 补单测")
    orch, _, state = _make(tmp_path, backend=backend)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    decision = orch.review_code(pr_number=5)

    assert decision.passed is False
    assert "缺测试" in decision.feedback
    assert "git diff" in backend.calls[0]["task"]


def test_review_unknown_pr_raises(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    with pytest.raises(OrchestratorError):
        orch.review_rfc(pr_number=999)


# --------------------------------------------------------------------------- #
# RFC-0018：评审闸裁决回贴签名评论（旁路）
# --------------------------------------------------------------------------- #


def _spy_post_comment(monkeypatch):
    """monkeypatch identity.post_signed_comment，记录回贴入参，返回记录器。"""
    posted = {}

    def _post(*, pr_number, body, agent_id):
        posted.update({"pr_number": pr_number, "body": body, "agent_id": agent_id})

    monkeypatch.setattr(orch_module.identity, "post_signed_comment", _post)
    return posted


def test_review_rfc_posts_signed_decision_comment(tmp_path, monkeypatch):
    # RFC-0018 验收标准 1：返回裁决前回贴一条签名评论，正文含整体裁决与票数。
    backend = _FakeBackend(summary="VERDICT: PASS\nREASON: 对齐需求")
    orch, _, state = _make(tmp_path, backend=backend, agent_id="agent-018")
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    posted = _spy_post_comment(monkeypatch)

    decision = orch.review_rfc(pr_number=5)

    assert decision.passed is True
    assert posted["pr_number"] == 5
    assert posted["agent_id"] == "agent-018"
    assert "评审闸裁决" in posted["body"]
    assert "PASS" in posted["body"]
    assert "1 票中 1 票 PASS" in posted["body"]


def test_review_code_rework_comment_carries_votes_and_feedback(tmp_path, monkeypatch):
    backend = _FakeBackend(summary="VERDICT: REWORK\nISSUES:\n- foo.py:1 缺测试\nNEXT: 补单测")
    orch, _, state = _make(tmp_path, backend=backend)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    posted = _spy_post_comment(monkeypatch)

    decision = orch.review_code(pr_number=5)

    assert decision.passed is False
    assert "REWORK" in posted["body"]
    assert "缺测试" in posted["body"]


def test_review_comment_failure_does_not_block_decision(tmp_path, monkeypatch):
    # RFC-0018 验收标准 2：post_signed_comment 抛错时 _review 仍返回原裁决、不抛出。
    backend = _FakeBackend(summary="VERDICT: PASS")
    orch, _, state = _make(tmp_path, backend=backend)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    def _boom(*, pr_number, body, agent_id):
        raise RuntimeError("gh 故障")

    monkeypatch.setattr(orch_module.identity, "post_signed_comment", _boom)

    decision = orch.review_rfc(pr_number=5)

    # 回贴抛错被吞掉，裁决照常返回（不阻断下游 refine/iterate/merge）。
    assert decision.passed is True


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
