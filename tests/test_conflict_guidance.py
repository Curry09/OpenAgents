"""Spec-0036/T3：conflict.resolve_branch / resolve 的 guidance 入参单元测试。

git 与 backend 全部注入桩，保持 hermetic（不触达真实 git / 真实 LLM）。覆盖：
- guidance=""（缺省）时喂给 backend 的 task 不拼「人类对本次解冲突的指导」段（拉式同步语义解冲突的默认口径）；
- guidance 非空时该文本出现在喂给 backend 的 task 里（拼进「人类对本次解冲突的指导」段）；
- resolve_branch / make_resolver 的 resolve 返回 ResolveOutcome（resolved + reply，__bool__ 兼容）；
- make_resolver 的 resolve 把 guidance 透传给 resolve_branch。
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
    """按命令分发的伪 git（与 test_conflict 同款）：记录调用、按预设回应 merge / diff / rev-parse / fetch。

    Spec-0056/T5：建模 head 与 origin/<branch>——交付下放 agent 后 resolve_branch 据 head 前移 +
    推送落地做只读校验；伪 backend 的 on_run 交付时前移 head + 写 remote 模拟 agent commit+push。
    """

    def __init__(self, *, merge_rc, conflicts):
        self._merge_rc = merge_rc
        self.conflicts = list(conflicts)
        self.calls = []
        self.head = "PRE"
        self.remote = {}

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
            return _cp(returncode=128, stdout="")
        return _cp(returncode=0)


class _FakeBackend:
    """伪 coding 后端：记录喂入的 task；on_run 解冲突（清干净文件 + 清 unmerged）。"""

    name = "fake"

    def __init__(self, *, on_run):
        self._on_run = on_run
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        self._on_run(work_dir)
        return AgentResult(changed=True, summary="resolved")


def _resolve_clean(git):
    def _inner(work_dir):
        # Spec-0056/T5：解干净 + 模拟 agent 自己交付（commit 前移 head + push 写 remote）。
        (work_dir / "a.py").write_text("clean content\n", encoding="utf-8")
        git.conflicts = []
        git.head = "POST"
        git.remote[_BRANCH] = "POST"

    return _inner


# --------------------------------------------------------------------------- #
# resolve_branch：guidance 入参
# --------------------------------------------------------------------------- #


def test_guidance_empty_task_matches_today(tmp_path):
    # guidance=""（缺省）：喂给 backend 的 task 不含「人类对本次解冲突的指导」段（零回归）。
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])
    backend = _FakeBackend(on_run=_resolve_clean(git))

    ok = resolve_branch(worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git)

    assert ok.resolved is True
    task = backend.calls[0]["task"]
    assert "人类对本次解冲突的指导" not in task
    # 缺省 task 逐字节等于不带 guidance 形参的旧行为（基础模板 + 冲突文件清单 + 目标分支）。
    assert task == conflict._RESOLVE_TASK.format(files="a.py", branch=_BRANCH)


def test_guidance_empty_explicit_same_as_default(tmp_path):
    # 显式传 guidance="" 与缺省一致（都不拼指导段）。
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])
    backend = _FakeBackend(on_run=_resolve_clean(git))

    resolve_branch(
        worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git, guidance=""
    )

    assert "人类对本次解冲突的指导" not in backend.calls[0]["task"]


def test_guidance_nonempty_appears_in_task(tmp_path):
    # guidance 非空：该文本出现在喂给 backend 的 task 里（拼进指导段）。
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])
    backend = _FakeBackend(on_run=_resolve_clean(git))

    ok = resolve_branch(
        worktree=tmp_path,
        base="main",
        branch=_BRANCH,
        backend=backend,
        run=git,
        guidance="先解 OVERVIEW.md 的冲突，再动 state.py",
    )

    assert ok.resolved is True  # 返回类型仍为 bool
    task = backend.calls[0]["task"]
    assert "人类对本次解冲突的指导" in task
    assert "先解 OVERVIEW.md 的冲突，再动 state.py" in task
    # 冲突文件清单仍在（指导段是追加，不替换）。
    assert "a.py" in task


def test_guidance_blank_treated_as_empty(tmp_path):
    # 仅空白的 guidance（strip 后为空）不拼指导段。
    git = _FakeGit(merge_rc=1, conflicts=["a.py"])
    backend = _FakeBackend(on_run=_resolve_clean(git))

    resolve_branch(
        worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git, guidance="   \n "
    )

    assert "人类对本次解冲突的指导" not in backend.calls[0]["task"]


def test_returns_resolve_outcome_type(tmp_path):
    # resolve_branch 返回 ResolveOutcome（resolved + reply）；__bool__ 兼容旧真值判断。
    git = _FakeGit(merge_rc=0, conflicts=[])
    backend = _FakeBackend(on_run=lambda wt: None)
    result = resolve_branch(
        worktree=tmp_path, base="main", branch=_BRANCH, backend=backend, run=git, guidance="x"
    )
    assert isinstance(result, conflict.ResolveOutcome)
    assert result.resolved is True
    assert bool(result) is True  # __bool__ 兼容 `if resolve(...)`


# --------------------------------------------------------------------------- #
# make_resolver：resolve 透传 guidance
# --------------------------------------------------------------------------- #


def test_resolve_passes_guidance_to_resolve_branch(monkeypatch, tmp_path):
    # make_resolver 返回的 resolve(guidance=…) 把 guidance 透传给 resolve_branch。
    captured = {}

    def _fake_resolve_branch(*, worktree, base, branch, backend, run, guidance="", pr_number=None):
        captured["guidance"] = guidance
        captured["pr_number"] = pr_number
        return conflict.ResolveOutcome(resolved=True)

    monkeypatch.setattr(conflict, "resolve_branch", _fake_resolve_branch)
    monkeypatch.setattr(conflict.github, "pr_head_branch", lambda *, pr_number: "feat/x")
    # 桩掉真实 git IO（fetch / worktree add / push / cleanup 都返回成功）。
    monkeypatch.setattr(conflict, "_git", lambda *, args, cwd, check: _cp())
    monkeypatch.setattr(conflict, "_cleanup", lambda *, root, path: None)

    backend = _FakeBackend(on_run=lambda wt: None)
    resolve = conflict.make_resolver(
        work_dir=tmp_path, base="main", backend=backend, agent_id="agent-x"
    )

    assert resolve(pr_number=7, guidance="人类指导").resolved is True
    assert captured["guidance"] == "人类指导"


def test_resolve_guidance_defaults_empty(monkeypatch, tmp_path):
    # 不传 guidance（如 auto-rebase 路径）→ resolve_branch 收到 guidance=""（零回归）。
    captured = {}

    def _fake_resolve_branch(*, worktree, base, branch, backend, run, guidance="", pr_number=None):
        captured["guidance"] = guidance
        captured["pr_number"] = pr_number
        return conflict.ResolveOutcome(resolved=True)

    monkeypatch.setattr(conflict, "resolve_branch", _fake_resolve_branch)
    monkeypatch.setattr(conflict.github, "pr_head_branch", lambda *, pr_number: "feat/x")
    monkeypatch.setattr(conflict, "_git", lambda *, args, cwd, check: _cp())
    monkeypatch.setattr(conflict, "_cleanup", lambda *, root, path: None)

    backend = _FakeBackend(on_run=lambda wt: None)
    resolve = conflict.make_resolver(
        work_dir=tmp_path, base="main", backend=backend, agent_id="agent-x"
    )

    assert resolve(pr_number=7).resolved is True
    assert captured["guidance"] == ""


# --------------------------------------------------------------------------- #
# 回评论工具段：guidance + pr_number 时要求 agent 用 reply-comment 命令亲自回评论
# --------------------------------------------------------------------------- #


def test_reply_tool_section_present_with_guidance_and_pr_number():
    task = conflict._resolve_task(conflicts=["a.py"], guidance="回我", branch=_BRANCH, pr_number=5)
    assert "openagents reply-comment --pr 5" in task  # 指向带签名的工具命令 + 具体 PR 号
    assert "无 OpenAgents 签名" in task  # 人类判定条件
    assert "gh pr comment" in task  # 明确禁止裸命令（会自循环）


def test_reply_tool_section_absent_without_pr_number():
    # 只有 guidance、无 pr_number（如非 merge 路径）→ 只拼指导段，不拼回评论工具段。
    task = conflict._resolve_task(conflicts=["a.py"], guidance="回我", branch=_BRANCH)
    assert "人类对本次解冲突的指导" in task
    assert "reply-comment" not in task


def test_reply_tool_section_absent_without_guidance():
    # 无 guidance → 既不拼指导段也不拼工具段（哪怕给了 pr_number）。
    task = conflict._resolve_task(conflicts=["a.py"], guidance="", branch=_BRANCH, pr_number=5)
    assert "reply-comment" not in task
    assert "人类对本次解冲突的指导" not in task


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
