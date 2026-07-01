"""Spec-0028/T2：conflict.resolve_branch / make_resolver 单元测试。

git 与 backend 全部注入桩，保持 hermetic（不触达真实 git / 真实 LLM）。
覆盖 resolve_branch 的分支：干净合并 / agent 解决+自测过 / 仍残留冲突 / 合并非冲突类失败 /
backend 抛异常吞成 False；以及 make_resolver 的安全降级（取 head 分支失败 → False）。
"""

import subprocess

import pytest

from openagents import conflict
from openagents.backends.base import AgentResult
from openagents.conflict import resolve_branch


def _cp(*, returncode=0, stdout=""):
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=""
    )


class _FakeGit:
    """按命令分发的伪 git：记录调用、按预设回应 merge / diff，其余返回成功。

    conflicts 可变——伪 backend 解完冲突后清空它，模拟「unmerged 文件消失」。
    """

    def __init__(self, *, merge_rc, conflicts):
        self._merge_rc = merge_rc
        self.conflicts = list(conflicts)
        self.calls = []

    def __call__(self, *, args, cwd, check):
        self.calls.append(args)
        if args[0] == "merge" and args[1] != "--abort":
            return _cp(returncode=self._merge_rc)
        if args[:3] == ["diff", "--name-only", "--diff-filter=U"]:
            return _cp(stdout="\n".join(str(c) for c in self.conflicts))
        return _cp(returncode=0)


class _FakeBackend:
    """伪 coding 后端：调 on_run（可改 worktree/清 conflicts 模拟 agent 解冲突），记录调用。"""

    name = "fake"

    def __init__(self, *, on_run):
        self._on_run = on_run
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        self._on_run(work_dir)
        return AgentResult(changed=True, summary="resolved")


def _abort_called(git):
    return ["merge", "--abort"] in git.calls


def test_clean_merge_returns_true_without_agent(tmp_path):
    git = _FakeGit(merge_rc=0, conflicts=[])
    backend = _FakeBackend(on_run=lambda wt: None)
    ok = resolve_branch(worktree=tmp_path, base="main", backend=backend, run=git)
    assert ok.resolved is True
    assert backend.calls == []  # 干净合并不调 agent
    assert ["merge", "origin/main", "--no-edit"] in git.calls
    assert not _abort_called(git)


def test_agent_resolves_and_commits(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])

    def _resolve(work_dir):
        # agent 解完：清干净文件（无标记）+ unmerged 文件消失。
        (work_dir / "a.py").write_text("clean content\n", encoding="utf-8")
        git.conflicts = []

    backend = _FakeBackend(on_run=_resolve)
    ok = resolve_branch(worktree=tmp_path, base="main", backend=backend, run=git)
    assert ok.resolved is True
    assert len(backend.calls) == 1
    # 任务里带上了冲突文件清单。
    assert "a.py" in backend.calls[0]["task"]
    assert ["add", "-A"] in git.calls
    assert ["commit", "--no-edit"] in git.calls
    assert not _abort_called(git)


def test_residual_conflict_marker_aborts(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])

    def _leave_marker(work_dir):
        # agent 自测失败 / 解不动：清了 index（unmerged 空）但文件里仍留冲突标记 → grep 兜住。
        (work_dir / "a.py").write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>>\n", encoding="utf-8")
        git.conflicts = []

    backend = _FakeBackend(on_run=_leave_marker)
    ok = resolve_branch(worktree=tmp_path, base="main", backend=backend, run=git)
    assert ok.resolved is False
    assert _abort_called(git)
    assert ["commit", "--no-edit"] not in git.calls


def test_still_unmerged_aborts(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])
    # agent 啥也没解，unmerged 文件仍在 → --diff-filter=U 非空 → abort。
    backend = _FakeBackend(on_run=lambda wt: None)
    ok = resolve_branch(worktree=tmp_path, base="main", backend=backend, run=git)
    assert ok.resolved is False
    assert _abort_called(git)


def test_merge_failure_without_conflicts_aborts(tmp_path):
    # 合并失败但无 unmerged 文件（非冲突类错误）→ 无从下手，abort 交人工，不调 agent。
    git = _FakeGit(merge_rc=1, conflicts=[])
    backend = _FakeBackend(on_run=lambda wt: None)
    ok = resolve_branch(worktree=tmp_path, base="main", backend=backend, run=git)
    assert ok.resolved is False
    assert backend.calls == []
    assert _abort_called(git)


def test_backend_exception_swallowed_to_false(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])

    def _boom(work_dir):
        raise RuntimeError("后端炸了")

    backend = _FakeBackend(on_run=_boom)
    ok = resolve_branch(worktree=tmp_path, base="main", backend=backend, run=git)
    assert ok.resolved is False  # 任何异常吞成 resolved=False
    assert _abort_called(git)


def test_make_resolver_degrades_on_github_error(monkeypatch, tmp_path):
    # 取 PR head 分支失败 → resolve 安全降级为 False（回落人工留言路径），绝不抛错。
    def _boom(*, pr_number):
        raise conflict.github.GithubError("gh 失败")

    monkeypatch.setattr(conflict.github, "pr_head_branch", _boom)
    backend = _FakeBackend(on_run=lambda wt: None)
    resolve = conflict.make_resolver(
        work_dir=tmp_path, base="main", backend=backend, agent_id="agent-x"
    )
    assert resolve(pr_number=7).resolved is False


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
