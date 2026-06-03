"""RFC-0001 T4 + RFC-0003: 单 issue → 单 agent 编排（决策 7/8）。

solve：fetch 最新 base → 建**每 issue 独立 worktree**（从 `origin/<base>` 拉分支）
→ 在该 worktree 内调后端改码 → add/commit/push → 开 PR → 写 State。
iterate：复用同一 worktree（缺失则重建），把新 comment 或 CI 失败日志作为上下文
喂回后端，**追加 commit**（RFC-0001 决策 7：不 force-push）后 push，状态置 iterating。

RFC-0003：求解工作区从「主工作树原地 checkout -b」改为「每 issue 独立 worktree +
分支基线锁定最新 `origin/<base>`（默认 main）」，杜绝基线随当前 HEAD 漂移，并为
issue 层面并行（CLAUDE.md 理念 5）提供隔离前提。

依赖注入：backend（满足 AgentBackend 协议）、state（State）、work_dir（repo 根）
都由构造传入；GitHub 操作以模块函数方式调用（测试里 monkeypatch github.*）。
所有 git 操作走 subprocess。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from openagents import github
from openagents.backends.base import AgentBackend
from openagents.state import STATUS_DONE, STATUS_ITERATING, RunRecord, State

# 分支命名前缀：单 issue → 单分支（RFC-0001 概述数据流）。
_BRANCH_PREFIX = "openagents/issue-"

# RFC-0003 决策 2：分支基线默认锁定到最新 origin/main。
DEFAULT_BASE = "main"

# RFC-0003 决策 1：每 issue 的隔离 worktree 根目录（.openagents/ 已被 .gitignore 忽略）。
_WORKTREE_SUBDIR = Path(".openagents") / "worktrees"


class OrchestratorError(Exception):
    """编排过程中无法继续时抛出（如 iterate 找不到对应 PR 的 run）。"""


class Orchestrator:
    """RFC-0001 T4 + RFC-0003：单 issue → 单 agent 的编排器（worktree 隔离）。"""

    def __init__(self, *, backend: AgentBackend, state: State, work_dir: Path) -> None:
        self._backend = backend
        self._state = state
        self._work_dir = Path(work_dir)

    def solve(self, *, issue_number: int, base: str = DEFAULT_BASE) -> github.PR:
        """RFC-0001 T4 + RFC-0003：求解一个 issue 并开/续写其唯一绑定的 PR。

        RFC-0003 决策 7/8：按 State 把重跑分流为「全新」或「续写」——
        - 全新：从最新 `origin/<base>` 建隔离 worktree+分支，开新 PR；
        - 续写：复用已有分支/worktree/PR（State 丢失时用 gh 兜底恢复），追加
          commit 推到同一 PR。这样 solve 中途报错后，重跑能从断点继续而非撞墙。
        base：分支基线（默认 main，决策 2/3）。返回该 issue 绑定的 PR。
        """
        issue = github.get_issue(number=issue_number)
        branch = f"{_BRANCH_PREFIX}{issue_number}"
        record = self._state.find_by_issue(issue_number=issue_number)

        if self._should_resume(record=record, branch=branch):
            return self._resume(issue=issue, branch=branch)
        return self._fresh_solve(issue=issue, branch=branch, base=base)

    def _should_resume(self, *, record: RunRecord | None, branch: str) -> bool:
        """RFC-0003 决策 7：该 issue 有进行中的 run，或远端已存在其分支 → 续写。"""
        if record is not None and record.status != STATUS_DONE:
            return True
        return self._remote_branch_exists(branch=branch)

    def _fresh_solve(self, *, issue: github.Issue, branch: str, base: str) -> github.PR:
        """RFC-0003：全新求解——建隔离 worktree（从最新 origin/<base>）、开新 PR。"""
        worktree = self._prepare_worktree(issue_number=issue.number, branch=branch, base=base)
        # 决策 8：进入即记 solving（PR 尚未开），崩溃后可据此恢复。
        self._state.begin_run(issue_number=issue.number, branch=branch)

        result = self._backend.run(
            work_dir=worktree,
            task=f"{issue.title}\n\n{issue.body}",
            context=issue.body,
        )
        message = f"feat: resolve issue #{issue.number} {issue.title}".strip()
        self._commit_and_push(worktree=worktree, branch=branch, message=message)

        pr = github.create_pr(
            branch=branch,
            title=message,
            body=self._pr_body(issue_number=issue.number, summary=result.summary),
        )
        # record_run 将状态登记为 pr-open（决策 8 的初始态）。
        self._state.record_run(issue_number=issue.number, branch=branch, pr=pr)
        return pr

    def _resume(self, *, issue: github.Issue, branch: str) -> github.PR:
        """RFC-0003 决策 7/8：复用已有分支/worktree 续写，追加 commit 推到同一 PR。"""
        worktree = self._ensure_worktree(issue_number=issue.number, branch=branch)

        result = self._backend.run(
            work_dir=worktree,
            task=f"继续解决 issue #{issue.number}（续写已有 PR）：\n{issue.title}\n\n{issue.body}",
            context=issue.body,
        )
        message = f"fix: continue issue #{issue.number} {issue.title}".strip()
        self._commit_and_push(worktree=worktree, branch=branch, message=message)

        pr = self._open_or_reuse_pr(issue=issue, branch=branch, summary=result.summary)
        self._state.record_run(issue_number=issue.number, branch=branch, pr=pr)
        self._state.update_status(issue_number=issue.number, status=STATUS_ITERATING)
        return pr

    def _open_or_reuse_pr(self, *, issue: github.Issue, branch: str, summary: str) -> github.PR:
        """RFC-0003 决策 8：优先复用分支已有的 open PR（gh 兜底）；没有才补开新 PR。"""
        existing = github.find_pr_by_branch(branch=branch)
        if existing is not None:
            return existing
        return github.create_pr(
            branch=branch,
            title=f"feat: resolve issue #{issue.number} {issue.title}".strip(),
            body=self._pr_body(issue_number=issue.number, summary=summary),
        )

    def _remote_branch_exists(self, *, branch: str) -> bool:
        """RFC-0003 决策 7：远端是否已存在该分支（`git ls-remote --heads`）。"""
        result = self._git(
            args=["ls-remote", "--heads", "origin", branch],
            cwd=self._work_dir,
            check=False,
        )
        return bool(result.stdout.strip())

    def iterate(self, *, pr_number: int, reason: str, detail: str) -> None:
        """RFC-0001 T4（决策 7）+ RFC-0003：在 issue 的 worktree 内续写并**追加 commit**。

        reason ∈ {"comment", "ci"}：决定喂回上下文的来源（评论正文或 CI 失败日志）。
        不 force-push，仅 git add/commit/push 追加一个新 commit；状态置 iterating。
        """
        record = self._state.find_run(pr_number=pr_number)
        if record is None:
            raise OrchestratorError(f"找不到 PR #{pr_number} 对应的 run，无法 iterate")

        branch = record.branch
        # RFC-0003：复用 solve 建的 worktree（缺失则从远端分支重建）后续写。
        worktree = self._ensure_worktree(issue_number=record.issue_number, branch=branch)

        task = f"针对 PR #{pr_number} 的{reason}反馈，请继续修改：\n{detail}"
        self._backend.run(work_dir=worktree, task=task, context=detail)

        commit_message = f"fix: address {reason} feedback on PR #{pr_number}"
        self._commit_and_push(worktree=worktree, branch=branch, message=commit_message)

        self._state.update_status(issue_number=record.issue_number, status=STATUS_ITERATING)

    def _worktree_path(self, *, issue_number: int) -> Path:
        """RFC-0003 决策 1：每 issue 的 worktree 确定式派生路径（不持久化）。"""
        return self._work_dir / _WORKTREE_SUBDIR / f"issue-{issue_number}"

    def _prepare_worktree(self, *, issue_number: int, branch: str, base: str) -> Path:
        """RFC-0003 决策 2/4：同步最新基线、幂等清理残留、再从 origin/<base> 拉新 worktree。"""
        path = self._worktree_path(issue_number=issue_number)
        # 决策 2：solve 前先拉最新 base（fetch 不触碰用户当前检出）。
        self._git(args=["fetch", "origin", base], cwd=self._work_dir, check=True)
        # 决策 4：幂等清理同 issue 可能残留的 worktree 与本地分支（失败忽略）。
        self._git(
            args=["worktree", "remove", "--force", str(path)], cwd=self._work_dir, check=False
        )
        self._git(args=["worktree", "prune"], cwd=self._work_dir, check=False)
        self._git(args=["branch", "-D", branch], cwd=self._work_dir, check=False)
        # 一条 worktree add 同时完成「建隔离工作树」+「从最新 origin/<base> 拉分支」。
        self._git(
            args=["worktree", "add", "-b", branch, str(path), f"origin/{base}"],
            cwd=self._work_dir,
            check=True,
        )
        return path

    def _ensure_worktree(self, *, issue_number: int, branch: str) -> Path:
        """RFC-0003 决策 5：iterate 复用 solve 建的 worktree；缺失则从远端分支重建。"""
        path = self._worktree_path(issue_number=issue_number)
        if path.exists():
            return path
        self._git(args=["fetch", "origin", branch], cwd=self._work_dir, check=False)
        self._git(args=["worktree", "add", str(path), branch], cwd=self._work_dir, check=True)
        return path

    def _commit_and_push(self, *, worktree: Path, branch: str, message: str) -> None:
        """git add -A → commit → push（决策 7：普通 push，绝不 force-push），均在 worktree 内。

        RFC-0003：无改动可提交（续写时后端可能未改文件）则跳过 commit（check=False），
        仍执行 push 以补推历史中尚未推送的 commit；远端已最新时 push 为幂等空操作。
        """
        self._git(args=["add", "-A"], cwd=worktree, check=True)
        self._git(args=["commit", "-m", message], cwd=worktree, check=False)
        self._git(args=["push", "-u", "origin", branch], cwd=worktree, check=True)

    def _git(self, *, args: list[str], cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        """在 cwd 内运行一条 git 子命令；check=True 时非零退出抛 OrchestratorError。"""
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            reason = result.stderr.strip() or f"git {' '.join(args)} 返回码 {result.returncode}"
            raise OrchestratorError(reason)
        return result

    def _pr_body(self, *, issue_number: int, summary: str) -> str:
        """组装 PR 正文：关联 issue + agent 改动摘要。"""
        body = f"Closes #{issue_number}\n\n"
        body += summary or "（无摘要）"
        return body
