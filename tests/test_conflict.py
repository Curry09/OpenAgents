"""Spec-0028/T2 · Spec-0056/T5：conflict.resolve_branch / make_resolver 单元测试。

git 与 backend 全部注入桩，保持 hermetic（不触达真实 git / 真实 LLM）。
覆盖 resolve_branch 的分支：干净合并 / agent 解决+自己交付（commit+push）过 / 仍残留冲突 /
agent 解了但没 commit（head 未前移）/ commit 了但没 push（origin≠HEAD）/ 合并非冲突类失败 /
backend 抛异常吞成 False；以及 make_resolver 的安全降级（取 head 分支失败 → False）。

Spec-0056/T5：交付（commit+push）下放 agent 后，_FakeGit 建模 HEAD 与 origin/<branch> 两个 SHA，
伪 backend 的 on_run 回调据此模拟 agent「commit（前移 head）+ push（写 remote[branch]）」；
resolve_branch 只做只读校验（残留标记 + head 前移 + 推送落地），不再 add/commit/push。
"""

import subprocess

import pytest

from openagents import conflict
from openagents.backends.base import AgentResult
from openagents.conflict import resolve_branch

_BRANCH = "openagents/issue-9"


def _cp(*, returncode=0, stdout=""):
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=""
    )


class _FakeGit:
    """按命令分发的伪 git：记录调用、按预设回应 merge / diff / rev-parse / fetch，其余返回成功。

    conflicts 可变——伪 backend 解完冲突后清空它，模拟「unmerged 文件消失」。
    Spec-0056/T5：head 建模本地 HEAD sha、remote 建模 origin/<branch> sha——伪 backend 交付时
    自行前移 head（commit）+ 写 remote[branch]（push），resolve_branch 据此校验 head 前移 + 推送落地。
    """

    def __init__(self, *, merge_rc, conflicts):
        self._merge_rc = merge_rc
        self.conflicts = list(conflicts)
        self.calls = []
        self.head = "PRE"  # 合并前 HEAD（merge 冲突中 HEAD 仍在本分支 tip）
        self.remote = {}  # origin/<branch> -> sha（未 push 前不存在）

    def __call__(self, *, args, cwd, check):
        self.calls.append(args)
        if args[0] == "merge" and args[1] != "--abort":
            return _cp(returncode=self._merge_rc)
        if args[:3] == ["diff", "--name-only", "--diff-filter=U"]:
            return _cp(stdout="\n".join(str(c) for c in self.conflicts))
        if args[:2] == ["rev-parse", "HEAD"]:
            return _cp(stdout=self.head)
        if args[0] == "rev-parse" and str(args[1]).startswith("origin/"):
            branch = str(args[1]).split("/", 1)[1]
            if branch in self.remote:
                return _cp(stdout=self.remote[branch])
            return _cp(returncode=128, stdout="")  # 未 push → 远端无此 ref
        return _cp(returncode=0)


class _FakeBackend:
    """伪 coding 后端：调 on_run（可改 worktree/清 conflicts/前移 head+写 remote 模拟交付），记录调用。"""

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
    ok = resolve_branch(worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git)
    assert ok.resolved is True
    assert ok.delivered is False  # 干净合并无 agent turn，交付留 make_resolver 普通 push
    assert backend.calls == []  # 干净合并不调 agent
    assert ["merge", "origin/main", "--no-edit"] in git.calls
    assert not _abort_called(git)


def test_agent_resolves_and_delivers(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])

    def _resolve(work_dir):
        # agent 解完并**自己交付**：清干净文件（无标记）+ unmerged 消失 + commit（前移 head）+ push（写 remote）。
        (work_dir / "a.py").write_text("clean content\n", encoding="utf-8")
        git.conflicts = []
        git.head = "POST"
        git.remote[_BRANCH] = "POST"

    backend = _FakeBackend(on_run=_resolve)
    ok = resolve_branch(worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git)
    assert ok.resolved is True
    assert ok.delivered is True  # agent 已 commit+push，make_resolver 不再代 push
    assert len(backend.calls) == 1
    # 任务里带上了冲突文件清单与目标分支名。
    assert "a.py" in backend.calls[0]["task"]
    assert _BRANCH in backend.calls[0]["task"]
    # Spec-0056/T5：harness 不再 add/commit——交付全下放 agent。
    assert ["add", "-A"] not in git.calls
    assert ["commit", "--no-edit"] not in git.calls
    # 校验推送落地跑了 fetch + rev-parse origin/<branch>。
    assert ["fetch", "origin", _BRANCH] in git.calls
    assert not _abort_called(git)


def test_agent_resolves_but_no_commit_aborts(tmp_path):
    # agent 清了标记却没 commit（merge 半途）→ head 未前移（post==pre）→ 判未交付、abort 回落人工。
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])

    def _resolve_no_commit(work_dir):
        (work_dir / "a.py").write_text("clean content\n", encoding="utf-8")
        git.conflicts = []  # index 干净、无残留标记，但 head 保持 "PRE"（没 commit）

    backend = _FakeBackend(on_run=_resolve_no_commit)
    ok = resolve_branch(worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git)
    assert ok.resolved is False
    assert ok.delivered is False
    assert _abort_called(git)


def test_agent_commits_but_no_push_degrades(tmp_path):
    # agent commit 了（head 前移）却没 push（正是 issue #140 的冻结类）→ origin/<branch> 缺 → 判未交付。
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])

    def _resolve_no_push(work_dir):
        (work_dir / "a.py").write_text("clean content\n", encoding="utf-8")
        git.conflicts = []
        git.head = "POST"  # 提交了，但 remote 不写 → 没推上去

    backend = _FakeBackend(on_run=_resolve_no_push)
    ok = resolve_branch(worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git)
    assert ok.resolved is False
    assert ok.delivered is False


def test_residual_conflict_marker_aborts(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])

    def _leave_marker(work_dir):
        # agent 自测失败 / 解不动：清了 index（unmerged 空）但文件里仍留冲突标记 → grep 兜住。
        (work_dir / "a.py").write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>>\n", encoding="utf-8")
        git.conflicts = []

    backend = _FakeBackend(on_run=_leave_marker)
    ok = resolve_branch(worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git)
    assert ok.resolved is False
    assert _abort_called(git)
    assert ["commit", "--no-edit"] not in git.calls


def test_still_unmerged_aborts(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])
    # agent 啥也没解，unmerged 文件仍在 → --diff-filter=U 非空 → abort。
    backend = _FakeBackend(on_run=lambda wt: None)
    ok = resolve_branch(worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git)
    assert ok.resolved is False
    assert _abort_called(git)


def test_merge_failure_without_conflicts_aborts(tmp_path):
    # 合并失败但无 unmerged 文件（非冲突类错误）→ 无从下手，abort 交人工，不调 agent。
    git = _FakeGit(merge_rc=1, conflicts=[])
    backend = _FakeBackend(on_run=lambda wt: None)
    ok = resolve_branch(worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git)
    assert ok.resolved is False
    assert backend.calls == []
    assert _abort_called(git)


def test_backend_exception_swallowed_to_false(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])

    def _boom(work_dir):
        raise RuntimeError("后端炸了")

    backend = _FakeBackend(on_run=_boom)
    ok = resolve_branch(worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git)
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
