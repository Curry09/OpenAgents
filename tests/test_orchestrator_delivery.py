"""Spec-0056/T2：orchestrator 交付协议 + head 前移硬闸接线 + WorkspaceError 隔离的单元测试。

覆盖 T2 验收四条：
1. **fork 自愈**（真实本地 git）：用「把交付协议真正执行成 git 命令」的 fake backend 驱动 implement，
   分叉场景一轮内 rebase 自愈 + `--force-with-lease` 推上，`git rev-parse origin/<branch>` 前移到
   本地 HEAD（head 前移硬闸 assert_delivered 放行）。
2. **硬闸 mismatch → needs-human + raise**：assert_delivered 抛 WorkspaceError 时，start_rfc（draft，
   复现路径）打 issue_add_label(BLOCKED_LABEL) + 署名评论，并把 WorkspaceError **翻译**成
   OrchestratorError 上抛（不再裸 WorkspaceError 逃逸 vigil 的 except (OrchestratorError, GithubError)）。
3. **交付协议 prompt 契约锁**：四个 task 模板都含 `--force-with-lease`、BASE 取 fetch 前次序、
   禁裸 `--force`、完成判据 origin==HEAD。
4. **不再出现固定 `docs: draft spec` 消息**：协议/模板/常量均无该硬编码 commit 措辞。
"""

import subprocess
from pathlib import Path

import pytest

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Issue
from openagents.orchestrator import Orchestrator, OrchestratorError
from openagents.state import State
from openagents.workspace import WorkspaceError

# --------------------------------------------------------------------------- #
# (3)(4) 交付协议契约锁 + 无固定 draft-spec 消息（纯常量断言，无副作用）
# --------------------------------------------------------------------------- #


def test_delivery_protocol_contract_lock():
    # (3)：协议锁死关键约束，防措辞被无意改坏（对齐 executor producer/consumer 契约锁范式）。
    p = orch_module._GIT_DELIVERY_PROTOCOL
    assert "--force-with-lease" in p
    # BASE 必须取 fetch **之前**（footgun 防线）。
    assert "BASE=$(git rev-parse origin/<branch>)" in p
    assert "fetch" in p and "之前" in p
    # 禁止裸 --force（无 lease）。
    assert "禁止裸" in p and "git push --force" in p
    # 完成判据：origin/<branch> == HEAD。
    assert "git rev-parse origin/<branch>" in p and "HEAD" in p
    # force-with-lease 仅限本工作分支（决策 7 修订：issue-<n> 派单/迭代 + backfill-<slug> 反向补全）。
    assert "仅限本工作分支" in p


def test_all_five_task_templates_embed_delivery_protocol():
    # (3)：draft / refine / implement / iterate + backfill 五个交付 seam 的 task 模板都追加了交付协议。
    for template in (
        orch_module._DRAFT_RFC_TASK,
        orch_module._REFINE_RFC_TASK,
        orch_module._IMPLEMENT_TASK,
        orch_module._ITERATE_TASK,
        orch_module._BACKFILL_RFC_TASK,
    ):
        assert "--force-with-lease" in template
        assert "BASE=$(git rev-parse origin/<branch>)" in template
        assert "禁止裸" in template


def test_no_hardcoded_draft_spec_commit_message():
    # (4)：删除硬编码 `docs: draft spec for issue #<n>`（根因 4，同名 commit 掩盖重试）。
    assert "draft spec for issue" not in orch_module._GIT_DELIVERY_PROTOCOL
    assert "draft spec for issue" not in orch_module._DRAFT_RFC_TASK
    # 起草改用语义化 commit（draft 措辞由 agent 自定），协议明确「别再堆固定的 docs: draft spec 消息」。
    assert "docs: draft spec" in orch_module._GIT_DELIVERY_PROTOCOL  # 作为「别再用」的反面示例出现


# --------------------------------------------------------------------------- #
# (2) 硬闸 mismatch → needs-human + 署名评论 + raise OrchestratorError（隔离修复）
# --------------------------------------------------------------------------- #


class _StubBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=True, summary="done")


class _StallWorkspace:
    """assert_delivered 恒抛 WorkspaceError 的 Workspace 替身（模拟 agent 自判完成却没推上去）。"""

    def __init__(self, *, root):
        self._root = Path(root)

    def prepare(self, *, issue_number, branch, base):
        return self._root / f"issue-{issue_number}"

    def ensure(self, *, issue_number, branch):
        return self._root / f"issue-{issue_number}"

    def changed_spec_group(self, *, worktree, base):
        return None

    def assert_delivered(self, *, worktree, branch):
        raise WorkspaceError(
            f"分支 {branch} head 未前移、疑似未交付：origin/{branch}=aaaaaaaaaaaa ≠ 本地 HEAD=bbbbbbbbbbbb"
        )


def test_start_rfc_hard_gate_mismatch_blocks_to_human_and_raises_orchestrator_error(
    tmp_path, monkeypatch
):
    # (2)：draft 段硬闸 mismatch → issue_add_label(needs-human) + 署名评论 + raise OrchestratorError。
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = Orchestrator(backend=_StubBackend(), state=state, work_dir=tmp_path, agent_id="agent-x")
    orch._workspace = _StallWorkspace(root=tmp_path)

    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="t", body="b"),
    )
    # 认领链路 mock（本用例只验硬闸拦截，不验认领竞态）。
    monkeypatch.setattr(orch_module.github, "list_issue_comments", lambda *, number: [])
    monkeypatch.setattr(orch_module.github, "issue_remove_label", lambda *, number, name: None)

    labels: list[tuple[int, str]] = []
    comments: list[tuple[int, str]] = []
    monkeypatch.setattr(
        orch_module.github,
        "issue_add_label",
        lambda *, number, name: labels.append((number, name)),
    )
    monkeypatch.setattr(
        orch_module.github,
        "issue_comment",
        lambda *, number, body: comments.append((number, body)),
    )

    with pytest.raises(OrchestratorError):
        orch.start_rfc(issue_number=79)

    # needs-human 标签打在 issue 上（draft 段 PR 尚未开，走 issue 级出口）。
    assert (79, orch_module.github.BLOCKED_LABEL) in labels
    # 贴了一条署名说明评论，携双 SHA 诊断（理念 8 可观测）。
    assert comments and comments[-1][0] == 79
    from openagents.identity import parse_agent_id

    assert parse_agent_id(body=comments[-1][1]) == "agent-x"
    assert "未前移" in comments[-1][1]


def test_hard_gate_raises_orchestrator_error_not_bare_workspace_error(tmp_path, monkeypatch):
    # (2) 隔离修复（根因 2）：抛的是 OrchestratorError（vigil except 元组能兜住），不是裸 WorkspaceError。
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = Orchestrator(backend=_StubBackend(), state=state, work_dir=tmp_path, agent_id="agent-x")
    orch._workspace = _StallWorkspace(root=tmp_path)
    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="t", body="b"),
    )
    monkeypatch.setattr(orch_module.github, "list_issue_comments", lambda *, number: [])
    monkeypatch.setattr(orch_module.github, "issue_remove_label", lambda *, number, name: None)
    monkeypatch.setattr(orch_module.github, "issue_add_label", lambda *, number, name: None)
    monkeypatch.setattr(orch_module.github, "issue_comment", lambda *, number, body: None)

    with pytest.raises(OrchestratorError) as excinfo:
        orch.start_rfc(issue_number=79)
    # 是 OrchestratorError（含子类判定）、不是裸 WorkspaceError；且 from exc 保留根因链。
    assert not isinstance(excinfo.value, WorkspaceError)
    assert isinstance(excinfo.value.__cause__, WorkspaceError)


def test_implement_hard_gate_mismatch_blocks_pr_and_raises(tmp_path, monkeypatch):
    # (2)：已开 PR 的 implement 段 mismatch → PR 级 add_label + post_comment + raise。
    state = State(path=tmp_path / ".openagents" / "state.json")
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    orch = Orchestrator(backend=_StubBackend(), state=state, work_dir=tmp_path, agent_id="agent-x")
    orch._workspace = _StallWorkspace(root=tmp_path)

    pr_labels: list[tuple[int, str]] = []
    pr_comments: list[int] = []
    monkeypatch.setattr(
        orch_module.github,
        "add_label",
        lambda *, pr_number, name: pr_labels.append((pr_number, name)),
    )
    monkeypatch.setattr(
        orch_module.github, "post_comment", lambda *, pr_number, body: pr_comments.append(pr_number)
    )
    ready = []
    monkeypatch.setattr(
        orch_module.github, "mark_ready", lambda *, pr_number: ready.append(pr_number)
    )

    with pytest.raises(OrchestratorError):
        orch.implement(pr_number=5)

    # 走 PR 级出口（post_comment + add_label），且拦在 mark_ready 之前（PR 不转正）。
    assert (5, orch_module.github.BLOCKED_LABEL) in pr_labels
    assert pr_comments == [5]
    assert ready == []


# --------------------------------------------------------------------------- #
# (5) backfill 反向补全：交付下放 agent + 硬闸失败直接 raise（无 issue/PR 可路由 → 不打 github 标签）
# --------------------------------------------------------------------------- #


class _StubInventory:
    def render(self):
        return "module: x.py"


def test_no_hardcoded_backfill_spec_commit_message():
    # (5)/根因 4：删除硬编码 `docs: backfill spec for <path>`（backfill 交付亦下放 agent 语义化 commit）。
    import inspect

    # backfill_rfc 源码不再有 commit_and_push 硬编码的 backfill 提交消息（PR 标题仍可保留同措辞）。
    src = inspect.getsource(Orchestrator.backfill_rfc)
    assert "commit_and_push" not in src
    assert 'message=f"docs: backfill spec' not in src


def _mock_backfill_deps(*, monkeypatch, validate_ok):
    """公用 mock：inventory / slug_for / validate（backfill 三处外部依赖），返回 spy 记录容器。"""
    monkeypatch.setattr(orch_module.backfill, "inventory", lambda *, path: _StubInventory())
    monkeypatch.setattr(orch_module.backfill, "slug_for", lambda *, path: "code")
    from types import SimpleNamespace

    issues = (
        []
        if validate_ok
        else [SimpleNamespace(level="error", where="0056/overview", message="必填段空")]
    )
    monkeypatch.setattr(
        orch_module.validate,
        "validate",
        lambda *, specs_root: SimpleNamespace(ok=validate_ok, issues=issues),
    )
    # backfill 无 issue/PR 路由——断言这些 github 出口一个都不该被调（否则说明误走 _fail_to_human）。
    calls: dict[str, int] = {
        "issue_add_label": 0,
        "issue_comment": 0,
        "add_label": 0,
        "post_comment": 0,
    }
    for hook in calls:
        monkeypatch.setattr(
            orch_module.github, hook, lambda *a, _h=hook, **k: calls.__setitem__(_h, calls[_h] + 1)
        )
    return calls


def test_backfill_hard_gate_mismatch_raises_without_github_routing(tmp_path, monkeypatch):
    # (5)：backfill 交付硬闸 mismatch → raise OrchestratorError（from WorkspaceError），且**不**打任何
    # github 标签/评论（无 originating issue/PR，人工介入面是 CLI 顶层的干净报错，非 needs-human 标签）。
    calls = _mock_backfill_deps(monkeypatch=monkeypatch, validate_ok=True)
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = Orchestrator(backend=_StubBackend(), state=state, work_dir=tmp_path, agent_id="agent-x")
    orch._workspace = _StallWorkspace(root=tmp_path)

    with pytest.raises(OrchestratorError) as excinfo:
        orch.backfill_rfc(path="openagents/foo.py")

    # 是 OrchestratorError（vigil 无关，但仍保 CLI 顶层可捕）、from WorkspaceError 保根因链。
    assert not isinstance(excinfo.value, WorkspaceError)
    assert isinstance(excinfo.value.__cause__, WorkspaceError)
    # 关键路由差异：一个 github 出口都没碰（不走 _fail_to_human）。
    assert sum(calls.values()) == 0


def test_backfill_validate_error_blocks_before_delivery(tmp_path, monkeypatch):
    # (5)：validate 硬门控保留——error 时 raise 不开 PR，且**不到**交付硬闸（assert_delivered 不被调）。
    _mock_backfill_deps(monkeypatch=monkeypatch, validate_ok=False)
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = Orchestrator(backend=_StubBackend(), state=state, work_dir=tmp_path, agent_id="agent-x")

    delivered_called = {"n": 0}

    class _SpyWorkspace(_StallWorkspace):
        def assert_delivered(self, *, worktree, branch):
            delivered_called["n"] += 1
            super().assert_delivered(worktree=worktree, branch=branch)

    orch._workspace = _SpyWorkspace(root=tmp_path)

    with pytest.raises(OrchestratorError) as excinfo:
        orch.backfill_rfc(path="openagents/foo.py")

    # validate error 先拦（消息带 validate 语义），交付硬闸未触达。
    assert "validate" in str(excinfo.value)
    assert delivered_called["n"] == 0


# --------------------------------------------------------------------------- #
# (1) fork 自愈闭环（真实本地 git）：执行协议的 fake backend 一轮内 rebase + force-with-lease 推上
# --------------------------------------------------------------------------- #


def _git(*, cwd, args, check=True):
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check
    )


def _init_repo(*, path, is_bare=False):
    path.mkdir(parents=True, exist_ok=True)
    _git(cwd=path, args=["init", "--bare"] if is_bare else ["init"])
    if not is_bare:
        _git(cwd=path, args=["config", "user.email", "a@b.c"])
        _git(cwd=path, args=["config", "user.name", "tester"])
        _git(cwd=path, args=["config", "commit.gpgsign", "false"])


class _ProtocolBackend:
    """把交付协议真正执行成 git 命令的 fake backend：commit → 记 fetch 前 BASE → rebase 解冲突 →
    push --force-with-lease=<branch>:$BASE。记录 push 命令供断言（带 lease + BASE、无裸 --force）。"""

    name = "protocol"

    def __init__(self, *, branch):
        self._branch = branch
        self.push_cmd = None

    def run(self, *, work_dir, task, context):
        wt = Path(work_dir)
        # 1. 语义化 commit（agent 自己写的新草稿）。
        _git(cwd=wt, args=["add", "-A"])
        _git(cwd=wt, args=["commit", "-m", "feat: local draft"], check=False)
        # 2. BASE 取 fetch **之前**的远端基点（footgun 防线）。
        base = _git(cwd=wt, args=["rev-parse", f"origin/{self._branch}"]).stdout.strip()
        _git(cwd=wt, args=["fetch", "origin", self._branch])
        # 3. 分叉 → rebase 解冲突（本 fake 以「取本地版」策略语义解决后 continue）。
        rebase = _git(cwd=wt, args=["rebase", f"origin/{self._branch}"], check=False)
        if rebase.returncode != 0:
            (wt / "spec.txt").write_text("resolved-by-agent\n")
            _git(cwd=wt, args=["add", "-A"])
            env_continue = _git(cwd=wt, args=["rebase", "--continue"], check=False)
            # rebase --continue 无编辑器时可能要 GIT_EDITOR=true；用 -c 兜底重试。
            if env_continue.returncode != 0:
                _git(cwd=wt, args=["-c", "core.editor=true", "rebase", "--continue"], check=False)
        # 4. force-with-lease，lease 期望值 = fetch 前 BASE；仅限本分支，绝不裸 --force。
        self.push_cmd = [
            "push",
            f"--force-with-lease={self._branch}:{base}",
            "origin",
            self._branch,
        ]
        _git(cwd=wt, args=self.push_cmd)
        return AgentResult(changed=True, summary="delivered")


def _setup_diverged_worktree(*, tmp_path, branch):
    """构造复现态：远端裸库 + PR 分支领先 base，本地 worktree 对同一文件重起草导致分叉（冲突）。"""
    remote = tmp_path / "remote.git"
    _init_repo(path=remote, is_bare=True)
    # seed main：一个初始文件。
    seed = tmp_path / "seed"
    _init_repo(path=seed)
    (seed / "spec.txt").write_text("base\n")
    _git(cwd=seed, args=["add", "-A"])
    _git(cwd=seed, args=["commit", "-m", "chore: base"])
    _git(cwd=seed, args=["branch", "-M", "main"])
    _git(cwd=seed, args=["remote", "add", "origin", str(remote)])
    _git(cwd=seed, args=["push", "-u", "origin", "main"])
    # 远端 PR 分支领先 base（改了 spec.txt，与本地将要写的内容冲突）。
    _git(cwd=seed, args=["checkout", "-b", branch, "main"])
    (seed / "spec.txt").write_text("remote-change\n")
    _git(cwd=seed, args=["add", "-A"])
    _git(cwd=seed, args=["commit", "-m", "docs: remote draft"])
    _git(cwd=seed, args=["push", "-u", "origin", branch])
    # 本地 worktree：从 origin/main 起分支（与 origin/<branch> 分叉），带一处冲突改动待 commit。
    wt = tmp_path / ".openagents" / "worktrees" / "issue-3"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(cwd=tmp_path, args=["clone", str(remote), str(wt)], check=True)
    _git(cwd=wt, args=["config", "user.email", "a@b.c"])
    _git(cwd=wt, args=["config", "user.name", "tester"])
    _git(cwd=wt, args=["config", "commit.gpgsign", "false"])
    _git(cwd=wt, args=["checkout", "-b", branch, "origin/main"])
    (wt / "spec.txt").write_text("local-change\n")
    return remote, wt


def test_implement_fork_selfheal_rebase_and_force_with_lease_advances_head(tmp_path, monkeypatch):
    # (1)：真实本地 git 分叉场景，执行协议的 fake backend 一轮内 rebase 自愈 + force-with-lease 推上，
    # implement 的 head 前移硬闸（真实 assert_delivered）放行，origin/<branch> 前移到本地 HEAD。
    branch = "openagents/issue-3"
    remote, wt = _setup_diverged_worktree(tmp_path=tmp_path, branch=branch)

    # 预置分叉证据：本地分支 head 与 origin/<branch> 不是祖先关系（真·分叉）。
    _git(cwd=wt, args=["fetch", "origin", branch])
    ancestor = _git(
        cwd=wt,
        args=["merge-base", "--is-ancestor", f"origin/{branch}", "HEAD"],
        check=False,
    )
    assert ancestor.returncode != 0  # 分叉：远端不是本地 HEAD 的祖先

    state = State(path=tmp_path / ".openagents" / "state.json")
    state.record_run(issue_number=3, branch=branch, pr=PR(number=5, url="u/pull/5"))
    backend = _ProtocolBackend(branch=branch)
    # 真实 Workspace（不替身），work_dir=tmp_path → ensure 返回已存在的 wt。
    orch = Orchestrator(backend=backend, state=state, work_dir=tmp_path, agent_id="agent-x")
    monkeypatch.setattr(orch_module.github, "mark_ready", lambda *, pr_number: None)

    orch.implement(pr_number=5)

    # 成果到达 PR head：origin/<branch> 前移到本地 HEAD（head 前移硬闸已放行、未抛）。
    head = _git(cwd=wt, args=["rev-parse", "HEAD"]).stdout.strip()
    remote_head = _git(cwd=wt, args=["rev-parse", f"origin/{branch}"]).stdout.strip()
    assert head == remote_head
    # 推送带 lease + BASE，仅限本分支，绝不裸 --force。
    assert backend.push_cmd is not None
    joined = " ".join(backend.push_cmd)
    assert f"--force-with-lease={branch}:" in joined
    assert "--force " not in joined and not joined.endswith("--force")


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
