"""RFC-0001 T4: 单 issue → 单 agent 编排（决策 7/8）。

solve：拉 issue → 建分支 → 调后端改码 → add/commit/push → 开 PR → 写 State。
iterate：把新 comment 或 CI 失败日志作为上下文喂回后端，**追加 commit**
（决策 7：不 force-push，保留 reviewer 可见的逐条 diff）后 push，状态置 iterating。

依赖注入：backend（满足 AgentBackend 协议）、state（State）、work_dir（repo 根）
都由构造传入；GitHub 操作以模块函数方式调用（测试里 monkeypatch github.*）。
所有 git 操作走 subprocess。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from openagents import github
from openagents.backends.base import AgentBackend
from openagents.state import STATUS_ITERATING, State

# 分支命名前缀：单 issue → 单分支（RFC-0001 概述数据流）。
_BRANCH_PREFIX = "openagents/issue-"


class OrchestratorError(Exception):
    """编排过程中无法继续时抛出（如 iterate 找不到对应 PR 的 run）。"""


class Orchestrator:
    """RFC-0001 T4：单 issue → 单 agent 的编排器。"""

    def __init__(self, *, backend: AgentBackend, state: State, work_dir: Path) -> None:
        self._backend = backend
        self._state = state
        self._work_dir = Path(work_dir)

    def solve(self, *, issue_number: int) -> github.PR:
        """RFC-0001 T4：执行「拉 issue → 建分支 → 调后端 → 开 PR → 写 State」。

        状态流转：进入时该 issue 视为 solving；开 PR 并 record_run 后置 pr-open。
        返回新建的 PR。
        """
        issue = github.get_issue(number=issue_number)
        branch = f"{_BRANCH_PREFIX}{issue_number}"

        self._create_branch(branch=branch)

        task = f"{issue.title}\n\n{issue.body}"
        result = self._backend.run(work_dir=self._work_dir, task=task, context=issue.body)

        commit_message = f"feat: resolve issue #{issue_number} {issue.title}".strip()
        self._commit_and_push(branch=branch, message=commit_message)

        pr = github.create_pr(
            branch=branch,
            title=f"feat: resolve issue #{issue_number} {issue.title}".strip(),
            body=self._pr_body(issue_number=issue_number, summary=result.summary),
        )
        # record_run 内部将状态登记为 pr-open（决策 8 的初始态）。
        self._state.record_run(issue_number=issue_number, branch=branch, pr=pr)
        return pr

    def iterate(self, *, pr_number: int, reason: str, detail: str) -> None:
        """RFC-0001 T4（决策 7）：把 comment/CI 日志喂回后端并**追加 commit**。

        reason ∈ {"comment", "ci"}：决定喂回上下文的来源（评论正文或 CI 失败日志）。
        不 force-push，仅 git add/commit/push 追加一个新 commit；状态置 iterating。
        """
        record = self._state.find_run(pr_number=pr_number)
        if record is None:
            raise OrchestratorError(f"找不到 PR #{pr_number} 对应的 run，无法 iterate")

        branch = record.branch
        self._checkout(branch=branch)

        task = f"针对 PR #{pr_number} 的{reason}反馈，请继续修改：\n{detail}"
        self._backend.run(work_dir=self._work_dir, task=task, context=detail)

        commit_message = f"fix: address {reason} feedback on PR #{pr_number}"
        self._commit_and_push(branch=branch, message=commit_message)

        self._state.update_status(issue_number=record.issue_number, status=STATUS_ITERATING)

    def _create_branch(self, *, branch: str) -> None:
        """从当前 HEAD 新建并切换到 branch。"""
        self._git(["checkout", "-b", branch])

    def _checkout(self, *, branch: str) -> None:
        """切换到已存在的 branch（iterate 续写时用）。"""
        self._git(["checkout", branch])

    def _commit_and_push(self, *, branch: str, message: str) -> None:
        """git add -A → commit → push（决策 7：普通 push，绝不 force-push）。"""
        self._git(["add", "-A"])
        self._git(["commit", "-m", message])
        self._git(["push", "-u", "origin", branch])

    def _git(self, args: list[str]) -> None:
        """在 work_dir 内运行一条 git 子命令；非零退出抛 OrchestratorError。"""
        result = subprocess.run(
            ["git", "-C", str(self._work_dir), *args],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            reason = result.stderr.strip() or f"git {' '.join(args)} 返回码 {result.returncode}"
            raise OrchestratorError(reason)

    def _pr_body(self, *, issue_number: int, summary: str) -> str:
        """组装 PR 正文：关联 issue + agent 改动摘要。"""
        body = f"Closes #{issue_number}\n\n"
        body += summary or "（无摘要）"
        return body
