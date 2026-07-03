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
from openagents.github import PR, Comment, Issue
from openagents.orchestrator import Orchestrator, OrchestratorError
from openagents.reviewer import ReviewDecision
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


def test_draft_and_backfill_templates_have_conditional_browser_e2e_guidance():
    # Spec-0030/T4：起草 / 反向补全两处 prompt 模板均含条件式「具备浏览器工具 → 优先浏览器
    # 前端 e2e」引导，且措辞为条件式（由 agent 自检），不含「检测到你有浏览器」式宣告。
    for template in (orch_module._DRAFT_RFC_TASK, orch_module._BACKFILL_RFC_TASK):
        assert "浏览器工具" in template
        assert "前端 e2e" in template
        assert "自检" in template
        assert "检测到你有浏览器" not in template


def test_implement_task_has_e2e_evidence_discipline():
    # Spec-0044/T3：实现 prompt 含完整取证判断纪律——三分类 + 反测试顶替 + 诚实报阻塞 +
    # docs/skills/end-to-end-ui-screenshots/ 指路；措辞为条件式自检，不含「检测到你有浏览器」式宣告。
    template = orch_module._IMPLEMENT_TASK
    # 三分类判断字样。
    assert "三类" in template or "分三类" in template
    assert "UI 直接看得到" in template and "UI 看不到但确实改变产品对外行为" in template
    assert "纯内部实现细节" in template
    # 反测试顶替 + 反借口。
    assert "替代不了" in template and "跳过借口" in template
    # 诚实报阻塞。
    assert "诚实报" in template and "绝不假称已验证" in template
    # skill 指路 + 条件式自检、不宣告。
    assert "docs/skills/end-to-end-ui-screenshots/" in template
    assert "由你自检" in template
    assert "检测到你有浏览器" not in template


class _GitRecorder:
    """subprocess.run 替身，记录所有 git 命令并返回成功。"""

    def __init__(self):
        self.commands = []

    def __call__(self, args, **kwargs):
        self.commands.append(list(args))

        # Spec-0048/T4：start_rfc fresh 认领会 read-after-write 调 `gh issue view --json comments`
        # （list_issue_comments）；给它回一个空评论 JSON，使 latest_claim 返回 None（无他方认领）→
        # 不抛 ClaimLost，本用例聚焦 worktree/PR/状态路径，不验认领竞态（那由 test_orchestrator_claim）。
        class _Proc:
            returncode = 0
            stdout = '{"comments": []}' if "comments" in args else ""
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

    def changed_spec_group(self, *, worktree, base):
        # issue #53：start_rfc 开 PR 前会查本分支改动的 spec 组以拼端到端指路牌。
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
    assert "spec" in call["task"]
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
    # Spec-0048/T4：fresh 认领 = 幂等 add 标签 + 贴署名认领便签 + read-after-write 重读评论；PR 开出后
    # 摘标签。全 mock 掉避免真实 gh（本用例只验 worktree 路径）；list_issue_comments 回 [] → 无他方认领。
    monkeypatch.setattr(orch_module.github, "issue_add_label", lambda *, number, name: None)
    monkeypatch.setattr(orch_module.github, "issue_comment", lambda *, number, body: None)
    monkeypatch.setattr(orch_module.github, "list_issue_comments", lambda *, number: [])
    monkeypatch.setattr(orch_module.github, "issue_remove_label", lambda *, number, name: None)
    begin_calls = []
    monkeypatch.setattr(
        state, "begin_run", lambda *, issue_number, branch: begin_calls.append(issue_number)
    )

    orch.start_rfc(issue_number=3, resume=False)

    # Spec-0023/T2：默认基线为 main（test 分支门控退役）。
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
        lambda *, branch, title, body, base, draft: PR(number=5, url="u/pull/5"),
    )
    # Spec-0048/T4：resume **不再认领**（止血）——只在 PR 开出后 _release_claim 摘标签，mock issue_remove_label
    # 即可；不会调 issue_add_label / issue_comment / list_issue_comments（下面断言认领便签零调用）。
    claim_calls: list[str] = []
    monkeypatch.setattr(
        orch_module.github, "issue_add_label", lambda *, number, name: claim_calls.append("add")
    )
    monkeypatch.setattr(
        orch_module.github, "issue_comment", lambda *, number, body: claim_calls.append("note")
    )
    monkeypatch.setattr(
        orch_module.github,
        "list_issue_comments",
        lambda *, number: claim_calls.append("read") or [],
    )
    monkeypatch.setattr(orch_module.github, "issue_remove_label", lambda *, number, name: None)
    begin_calls = []
    monkeypatch.setattr(
        state, "begin_run", lambda *, issue_number, branch: begin_calls.append(issue_number)
    )

    pr = orch.start_rfc(issue_number=3, resume=True)

    # resume 路径零认领事件（既不打标、也不贴便签、也不 read-after-write）。
    assert claim_calls == []

    assert fake_ws.ensure_calls == [{"issue_number": 3, "branch": "openagents/issue-3"}]
    assert fake_ws.prepare_calls == []
    assert begin_calls == []
    # 恢复路径同样以一次写成的 rfc-review（带 pr）收尾。
    assert pr.number == 5
    assert state.all_runs()[0].status == "rfc-review"
    assert state.all_runs()[0].pr_number == 5


# RFC-0008 T3: PR 正文端到端验证指路牌


def _spec_group_with_e2e(*, root):
    """造一个带 e2e 脚本（写在组级 Overview 的 Reference-level）的 spec 组，供指路牌抽取。"""
    from openagents.spec import model as spec_model
    from openagents.spec.model import Group, Metadata, Overview, Task

    group = Group(
        number="0008",
        metadata=Metadata(title="示例", issue=8, slug="pr-e2e-signpost", summary="示例 TL;DR"),
        tasks=[Task(id="T1", title="t", status="done", priority="P1")],
        overview=Overview(
            reference_level="离线跑 `scripts/e2e-rfc-0008-pr-e2e-signpost.sh`（ruff + pytest）。"
        ),
    )
    path = spec_model.group_path(specs_root=root, number="0008", slug="pr-e2e-signpost")
    spec_model.dump_group(group=group, path=path)
    return path


def test_start_rfc_pr_body_includes_e2e_signpost(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _patch_get_issue(monkeypatch)
    # 造一份带 e2e 脚本的 spec 组，并让 changed_spec_group 指向它。
    group_dir = _spec_group_with_e2e(root=tmp_path)
    monkeypatch.setattr(orch._workspace, "changed_spec_group", lambda *, worktree, base: group_dir)
    captured = {}

    def _create_pr(*, branch, title, body, base, draft):
        captured.update(body=body)
        return PR(number=5, url="u/pull/5")

    monkeypatch.setattr(orch_module.github, "create_pr", _create_pr)

    orch.start_rfc(issue_number=3)

    body = captured["body"]
    assert "## 端到端验证" in body
    assert "`bash scripts/e2e-rfc-0008-pr-e2e-signpost.sh`" in body
    assert "docs/specs/0008-pr-e2e-signpost" in body
    # 指路牌追加在原有 Closes + 摘要之后，不替换它们。
    assert body.startswith("Closes #3")


def test_start_rfc_pr_body_omits_e2e_when_no_spec(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _patch_get_issue(monkeypatch)
    # changed_spec_group 取不到 spec 组时正文回退为原样、不抛错。
    monkeypatch.setattr(orch._workspace, "changed_spec_group", lambda *, worktree, base: None)
    captured = {}

    def _create_pr(*, branch, title, body, base, draft):
        captured.update(body=body)
        return PR(number=5, url="u/pull/5")

    monkeypatch.setattr(orch_module.github, "create_pr", _create_pr)

    orch.start_rfc(issue_number=3)

    assert "## 端到端验证" not in captured["body"]
    assert captured["body"].startswith("Closes #3")


# --------------------------------------------------------------------------- #
# Spec-0025/T2: backfill_rfc（反向补全：盘点 → 后端反推 → validate 门控 → draft PR）
# --------------------------------------------------------------------------- #


def _fake_inventory():
    from openagents.backfill import Inventory, ModuleInfo

    return Inventory(
        root="release.py",
        single_file=True,
        modules=(ModuleInfo(path="release.py", docstring="发版逻辑。", symbols=("release",)),),
    )


def _report(*, ok):
    from openagents.spec.validate import ValidationIssue, ValidationReport

    issues = [] if ok else [ValidationIssue(level="error", where="0025", message="必填段为空")]
    return ValidationReport(ok=ok, issues=issues)


def _arm_backfill(orch, monkeypatch, *, ok=True):
    """给 backfill_rfc 接好替身：盘点 / validate / create_pr，返回捕获记录。"""
    captured = {"created": False, "create_kwargs": None}
    monkeypatch.setattr(orch_module.backfill, "inventory", lambda *, path: _fake_inventory())
    monkeypatch.setattr(orch_module.validate, "validate", lambda *, specs_root: _report(ok=ok))

    def _create_pr(*, branch, title, body, base, draft):
        captured["created"] = True
        captured["create_kwargs"] = {"branch": branch, "body": body, "draft": draft}
        return PR(number=7, url="u/pull/7")

    monkeypatch.setattr(orch_module.github, "create_pr", _create_pr)
    return captured


def test_backfill_rfc_inventories_then_opens_draft_pr(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    captured = _arm_backfill(orch, monkeypatch, ok=True)

    pr = orch.backfill_rfc(path="openagents/release.py")

    assert pr.number == 7
    assert captured["create_kwargs"]["draft"] is True
    # 无 issue 号 → 分支用 path slug 定址（release.py → release）。
    assert captured["create_kwargs"]["branch"] == "openagents/backfill-release"


def test_backfill_rfc_prompt_carries_path_and_constraints(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _arm_backfill(orch, monkeypatch, ok=True)

    orch.backfill_rfc(path="openagents/release.py")

    task = backend.calls[0]["task"]
    # 反推 prompt 含目标路径、必填四段据实写满、难反推段标待补三项约束。
    assert "openagents/release.py" in task
    assert "必填四段" in task
    assert "待人工补全" in task
    # 盘点摘要拼进 prompt（圈定阅读范围）。
    assert "release.py" in task


def test_backfill_rfc_validate_error_does_not_open_pr(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    captured = _arm_backfill(orch, monkeypatch, ok=False)

    with pytest.raises(OrchestratorError):
        orch.backfill_rfc(path="openagents/release.py")

    # validate 有 error → 不开 PR（门控）。
    assert captured["created"] is False


def test_backfill_rfc_commit_message_is_docs(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    _arm_backfill(orch, monkeypatch, ok=True)

    orch.backfill_rfc(path="openagents/release.py")

    commit_cmds = [c for c in recorder.commands if "commit" in c]
    assert commit_cmds and "docs" in " ".join(commit_cmds[0])


def test_backfill_rfc_validate_error_skips_commit(tmp_path, monkeypatch):
    # validate 门控未过 → 既不 commit 也不 push（在校验后才提交）。
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    _arm_backfill(orch, monkeypatch, ok=False)

    with pytest.raises(OrchestratorError):
        orch.backfill_rfc(path="openagents/release.py")

    assert not any("commit" in c for c in recorder.commands)


def test_backfill_rfc_missing_path_raises_before_backend(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    from openagents.backfill import BackfillError

    def _boom(*, path):
        raise BackfillError("路径不存在")

    monkeypatch.setattr(orch_module.backfill, "inventory", _boom)

    with pytest.raises(BackfillError):
        orch.backfill_rfc(path="nope")
    # 盘点先于建 worktree / 调后端：后端未被触达。
    assert backend.calls == []


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
# Spec-0040/T5: 退役旧 smoke + 证据闸 finalize_runbook / commit_evidence
# --------------------------------------------------------------------------- #


def _write_spec_group(*, path, e2e):
    """写一个 spec 组文件（带/不带 e2e 粗规划），供 finalize_runbook 读组级 e2e 计划。"""
    from openagents.spec import model as spec_model
    from openagents.spec.model import Group, Metadata, Overview, Task

    group = Group(
        number="0040",
        metadata=Metadata(title="e2e", issue=104, slug="e2e-gate", summary="s", e2e=e2e),
        tasks=[Task(id="T1", title="t", status="done", priority="P1")],
        overview=Overview(reference_level="方案。"),
    )
    spec_model.dump_group(group=group, path=path)
    return path


def test_implement_no_longer_posts_e2e_smoke(tmp_path, monkeypatch):
    # Spec-0040/T5：退役 _post_e2e_result——implement 只 mark_ready，不再实跑 smoke / 发端到端评论。
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    posted = []
    monkeypatch.setattr(
        orch_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(body),
    )
    monkeypatch.setattr(orch_module.github, "mark_ready", lambda *, pr_number: None)

    orch.implement(pr_number=5)

    # implement 只调一次 backend（写代码），不再有 e2e 实跑评论，且 _post_e2e_result 已删除。
    assert len(backend.calls) == 1
    assert posted == []
    assert not hasattr(orch, "_post_e2e_result")


def test_finalize_runbook_no_e2e_plan_returns_none(tmp_path, monkeypatch):
    # 无 e2e 粗规划的 spec 组 → finalize_runbook 返回 None（证据闸空过），不派 backend 定稿。
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    group_path = _write_spec_group(path=tmp_path / "0040-e2e-gate.md", e2e=None)
    monkeypatch.setattr(orch._workspace, "changed_spec_group", lambda *, worktree, base: group_path)

    assert orch.finalize_runbook(pr_number=5) is None
    assert backend.calls == []


def test_finalize_runbook_with_e2e_plan_drafts_and_returns_handle(tmp_path, monkeypatch):
    # 有 e2e 粗规划 → 派实现者定稿 runbook、返回 handle（worktree/runbook_path/evidence_dir/intent）。
    from openagents.spec.model import E2EPlan

    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    plan = E2EPlan(
        form="cli", intent="init 无 origin 必须报错", acceptance=["非零退出", "补 origin 成功"]
    )
    group_path = _write_spec_group(path=tmp_path / "0040-e2e-gate.md", e2e=plan)
    monkeypatch.setattr(orch._workspace, "changed_spec_group", lambda *, worktree, base: group_path)

    handle = orch.finalize_runbook(pr_number=5)

    assert handle is not None
    assert handle.runbook_path.name == "runbook.md"
    assert handle.evidence_dir.name == "5"
    assert "e2e-results" in str(handle.evidence_dir)
    assert "init 无 origin 必须报错" in handle.intent
    assert "非零退出" in handle.intent and "补 origin 成功" in handle.intent
    # 派了实现者定稿，任务模板含形态与 runbook 路径。
    assert len(backend.calls) == 1
    assert "cli" in backend.calls[0]["task"]
    assert "runbook.md" in backend.calls[0]["task"]


def test_commit_evidence_commits_and_pushes(tmp_path, monkeypatch):
    orch, backend, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    orch.commit_evidence(pr_number=5)

    commit_cmds = [c for c in recorder.commands if "commit" in c]
    push_cmds = [c for c in recorder.commands if "push" in c]
    assert commit_cmds and "evidence" in " ".join(commit_cmds[0])
    assert push_cmds


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
    # reviewer 在 PR 的 worktree 内、用 spec 模板评审。
    assert "spec" in backend.calls[0]["task"]


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


# --------------------------------------------------------------------------- #
# Spec-0022/T3：裁决评论幂等——同 kind 同结论不每轮重发
# --------------------------------------------------------------------------- #


def _decision_comment(*, kind, passed, feedback, created_at):
    """构造一条「裁决评论」：用 reviewer.render_decision 生成正文，确保与生产抬头/字段一致。

    Spec-0047/T2：显式传 feedback（不再由 passed 隐式决定），以便造「同结论不同反馈」场景。
    """
    verdicts = ("PASS",) if passed else ("REWORK",)
    decision = ReviewDecision(
        passed=passed, feedback=feedback, verdicts=verdicts, actionable=not passed
    )
    body = orch_module.reviewer.render_decision(decision=decision, kind=kind)
    return Comment(id="c", author="bot", body=body, created_at=created_at)


def _patch_list_comments(monkeypatch, comments):
    monkeypatch.setattr(orch_module.github, "list_comments", lambda *, pr_number: list(comments))


def test_decision_same_conclusion_skips_repost(tmp_path, monkeypatch):
    # 既有一条同 kind PASS 裁决 → 本轮 PASS（反馈同为空）不再调 post_signed_comment（PR #61 防刷屏）。
    orch, _, _ = _make(tmp_path)
    prior = _decision_comment(
        kind="code", passed=True, feedback="", created_at="2026-06-18T00:00:00Z"
    )
    _patch_list_comments(monkeypatch, [prior])
    posted = _spy_post_comment(monkeypatch)

    orch._post_review_decision(
        pr_number=5,
        kind="code",
        decision=ReviewDecision(passed=True, feedback="", verdicts=("PASS", "PASS")),
    )

    assert posted == {}


def test_decision_conclusion_flip_reposts(tmp_path, monkeypatch):
    # 既有为 PASS、本轮非 PASS（结论翻转）→ 正常发新评论。
    orch, _, _ = _make(tmp_path)
    prior = _decision_comment(
        kind="code", passed=True, feedback="", created_at="2026-06-18T00:00:00Z"
    )
    _patch_list_comments(monkeypatch, [prior])
    posted = _spy_post_comment(monkeypatch)

    orch._post_review_decision(
        pr_number=5,
        kind="code",
        decision=ReviewDecision(
            passed=False, feedback="补单测", verdicts=("REWORK",), actionable=True
        ),
    )

    assert posted["pr_number"] == 5
    assert "REWORK" in posted["body"]


def test_decision_first_time_posts(tmp_path, monkeypatch):
    # 无既往裁决评论 → 正常发。
    orch, _, _ = _make(tmp_path)
    _patch_list_comments(monkeypatch, [])
    posted = _spy_post_comment(monkeypatch)

    orch._post_review_decision(
        pr_number=5,
        kind="code",
        decision=ReviewDecision(passed=True, feedback="", verdicts=("PASS",)),
    )

    assert posted["pr_number"] == 5


def test_decision_kind_isolation_does_not_suppress(tmp_path, monkeypatch):
    # 既有 rfc 裁决不抑制 code 裁决（两道闸按类型行区分）。
    orch, _, _ = _make(tmp_path)
    prior_rfc = _decision_comment(
        kind="rfc", passed=True, feedback="", created_at="2026-06-18T00:00:00Z"
    )
    _patch_list_comments(monkeypatch, [prior_rfc])
    posted = _spy_post_comment(monkeypatch)

    orch._post_review_decision(
        pr_number=5,
        kind="code",
        decision=ReviewDecision(passed=True, feedback="", verdicts=("PASS",)),
    )

    assert posted["pr_number"] == 5


def test_decision_dedup_query_failure_falls_open_to_post(tmp_path, monkeypatch):
    # list_comments 抛错 → 不抛出、降级为照发（fail-open），评审闸不受影响。
    orch, _, _ = _make(tmp_path)

    def _boom(*, pr_number):
        raise orch_module.github.GithubError("gh 查询抖动")

    monkeypatch.setattr(orch_module.github, "list_comments", _boom)
    posted = _spy_post_comment(monkeypatch)

    orch._post_review_decision(
        pr_number=5,
        kind="code",
        decision=ReviewDecision(passed=True, feedback="", verdicts=("PASS",)),
    )

    assert posted["pr_number"] == 5


# --------------------------------------------------------------------------- #
# Spec-0047/T2：去重按「结论 + 反馈内容」——同结论理由不同照发（issue #116）
# --------------------------------------------------------------------------- #


def test_decision_same_conclusion_different_feedback_reposts(tmp_path, monkeypatch):
    # issue #116 修复：既有 code REWORK（理由 A）后本轮 code REWORK（理由 B ≠ A）→ 照发。
    orch, _, _ = _make(tmp_path)
    prior = _decision_comment(
        kind="code",
        passed=False,
        feedback="EntityWithContent 继承不符 / 章-场 pattern 缺失",
        created_at="2026-06-18T13:18:00Z",
    )
    _patch_list_comments(monkeypatch, [prior])
    posted = _spy_post_comment(monkeypatch)

    orch._post_review_decision(
        pr_number=5,
        kind="code",
        decision=ReviewDecision(
            passed=False,
            feedback="_validate_specs:65 崩溃 bug + 8 个 task 零实现",
            verdicts=("REWORK",),
            actionable=True,
        ),
    )

    assert posted["pr_number"] == 5
    assert "REWORK" in posted["body"]
    assert "8 个 task 零实现" in posted["body"]


def test_decision_same_conclusion_same_feedback_skips(tmp_path, monkeypatch):
    # 同结论且同反馈的 REWORK（真·相同，无新信息）→ 跳过重发。
    orch, _, _ = _make(tmp_path)
    prior = _decision_comment(
        kind="code",
        passed=False,
        feedback="foo.py:1 缺测试",
        created_at="2026-06-18T13:18:00Z",
    )
    _patch_list_comments(monkeypatch, [prior])
    posted = _spy_post_comment(monkeypatch)

    orch._post_review_decision(
        pr_number=5,
        kind="code",
        decision=ReviewDecision(
            passed=False, feedback="foo.py:1 缺测试", verdicts=("REWORK",), actionable=True
        ),
    )

    assert posted == {}


def test_decision_dedup_compares_latest_by_created_at(tmp_path, monkeypatch):
    # 取最近一条同 kind 比对：最近一条是理由 B，本轮理由 B → 跳过（即便更早有理由 A）。
    orch, _, _ = _make(tmp_path)
    older = _decision_comment(
        kind="code", passed=False, feedback="理由 A", created_at="2026-06-18T13:18:00Z"
    )
    newer = _decision_comment(
        kind="code", passed=False, feedback="理由 B", created_at="2026-06-18T13:34:00Z"
    )
    _patch_list_comments(monkeypatch, [older, newer])
    posted = _spy_post_comment(monkeypatch)

    orch._post_review_decision(
        pr_number=5,
        kind="code",
        decision=ReviewDecision(
            passed=False, feedback="理由 B", verdicts=("REWORK",), actionable=True
        ),
    )

    assert posted == {}


def test_decision_fenced_feedback_different_reasons_reposts(tmp_path, monkeypatch):
    # issue #116 / PR #117 回归：两条**理由不同**但都以 fenced code 示例开头的 REWORK，
    # 必须照发第二条——旧实现把 feedback 内部围栏误当外层闭合、把两者归一化为 "" 而误判重复静默抑制。
    orch, _, _ = _make(tmp_path)
    prior = _decision_comment(
        kind="code",
        passed=False,
        feedback="```\nfoo()\n```\n第一轮卡点：缺边界处理",
        created_at="2026-06-18T13:18:00Z",
    )
    _patch_list_comments(monkeypatch, [prior])
    posted = _spy_post_comment(monkeypatch)

    orch._post_review_decision(
        pr_number=5,
        kind="code",
        decision=ReviewDecision(
            passed=False,
            feedback="```\nbar()\n```\n第二轮卡点：越权访问",
            verdicts=("REWORK",),
            actionable=True,
        ),
    )

    assert posted["pr_number"] == 5
    assert "越权访问" in posted["body"]


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
