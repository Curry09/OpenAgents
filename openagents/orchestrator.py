"""RFC-0005: issue → RFC-first → 代码 的原子操作编排（取代单体 solve）。

把原 `solve` 拆成四个**可独立触发**的原子操作，每个都是同一骨架的薄组合：
    确保工作区(workspace) → backend.run(任务) → 提交推送(workspace)
    → 一次 GitHub 动作(github) → 一次状态流转(state)

- `start_rfc`：建隔离 worktree、让后端起草 RFC、开 **draft PR**，状态 rfc-review。
- `refine_rfc`：按评审评论精炼 RFC、回贴一条改动说明评论，状态维持 rfc-review。
- `implement`：RFC 获批后按其写代码、把 draft PR 转正（mark_ready），状态 pr-open。
- `iterate`：coding 阶段把 CI/comment 反馈喂回后端、追加 commit，状态 iterating。

跨步骤编排不在本模块——由 messages.poll 依 GitHub 事件（新 issue / 评论 / 标签）
路由（RFC-0005 决策 1/5）。git/worktree 机制下沉到 workspace.Workspace（决策 3）。

依赖注入：backend / state / work_dir 由构造传入；GitHub 操作以模块函数方式调用
（测试里 monkeypatch github.*）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from openagents import github, identity, rfc
from openagents.backends.base import AgentBackend
from openagents.state import (
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
    State,
)
from openagents.workspace import Workspace

# 分支命名前缀：单 issue → 单分支（RFC-0001 概述数据流，RFC-0005 沿用）。
_BRANCH_PREFIX = "openagents/issue-"

# RFC-0003 决策 2：分支基线默认锁定到最新 origin/main。
DEFAULT_BASE = "main"

# RFC-0005：各原子操作喂给后端的任务模板（prompt）。后端为 cli-agent（如 Claude Code），
# 自带 rfc-driven-development skill，故任务只需指明意图与约束，细节交由其遵循该 skill。
_DRAFT_RFC_TASK = (
    "为 issue #{number}「{title}」起草一份 RFC，遵循 rfc-driven-development skill 的 Phase 2：\n"
    "扫描 local 与 open PR 取下一个未占用编号，在 docs/rfcs/ 下创建 NNNN-slug.md，"
    "填写设计、关键决策、接口契约与子任务 DAG（含文件清单）。\n"
    "只产出 RFC 文档，不要写实现代码。\n\nissue 正文：\n{body}"
)
_REFINE_RFC_TASK = (
    "本 issue 的 RFC 收到了评审意见，请据此更新 docs/rfcs/ 下对应的 RFC 文档"
    "（只改 RFC，不写实现代码）。改完用一两句话概述你做了哪些调整。\n\n评审意见：\n{detail}"
)
_IMPLEMENT_TASK = (
    "issue #{number} 的 RFC 已获批准（rfc-approved）。请阅读 docs/rfcs/ 下对应 RFC，"
    "按其子任务实现代码并自测（ruff + pytest），代码注释引用对应 RFC ID。"
)
# refine 后回贴到 PR 的评论模板，明确告知人类「已据评审更新 RFC」（决策 6）。
_REFINE_COMMENT = "🤖 已根据评审意见更新 RFC：\n\n{summary}"


class OrchestratorError(Exception):
    """编排过程中无法继续时抛出（如 refine/implement/iterate 找不到对应 PR 的 run）。"""


class Orchestrator:
    """RFC-0005：四个原子操作的编排器，组合 workspace + backend + github + state。"""

    def __init__(
        self, *, backend: AgentBackend, state: State, work_dir: Path, agent_id: str
    ) -> None:
        self._backend = backend
        self._state = state
        self._work_dir = Path(work_dir)
        self._workspace = Workspace(work_dir=work_dir)
        # RFC-0011 决策 4/7：本实例身份，由 CLI 接线处解析后注入；refine_rfc 的回贴据此盖章。
        self._agent_id = agent_id

    # --- 原子操作 1：起草 RFC（开 draft PR）------------------------------- #
    def start_rfc(
        self, *, issue_number: int, base: str = DEFAULT_BASE, resume: bool = False
    ) -> github.PR:
        """RFC-0005 / RFC-0007：拉 issue → 确保 worktree → 后端起草 RFC → 开 draft PR，状态 rfc-review。

        base：分支基线（默认 main，决策 2/3）。返回该 issue 绑定的 draft PR。

        RFC-0007 决策 2/3：resume 形参把 fresh / 恢复 两种入口收敛到同一尾段。
        - resume=False（fresh）：workspace.prepare 建全新隔离 worktree + begin_run 落 solving/pr=0。
        - resume=True （恢复）：workspace.ensure 复用崩溃残留的 worktree（保留半成品草稿），
          不调 prepare（避免铲掉进度）、不调 begin_run（solving 记录已存在）。
        fresh / resume 的判定下沉到 vigil 发现段；本方法不读 State，只按显式 resume 形参选择路径
        （保持原子操作「无隐藏状态读」的可单测特性）。
        """
        self._progress(message=f"▶ 拉取 issue #{issue_number} …")
        issue = github.get_issue(number=issue_number)
        branch = f"{_BRANCH_PREFIX}{issue_number}"

        if resume:
            # RFC-0007 决策 2：复用崩溃残留 worktree，接着断点继续，不重写 begin_run。
            self._progress(message=f"▶ 恢复孤儿 run：复用 issue #{issue_number} 既有 worktree …")
            worktree = self._workspace.ensure(issue_number=issue_number, branch=branch)
        else:
            self._progress(message=f"▶ 准备隔离 worktree（基线 origin/{base}）…")
            worktree = self._workspace.prepare(issue_number=issue_number, branch=branch, base=base)
            # 进入即记 run（PR 尚未开），崩溃后可据此恢复定位。
            self._state.begin_run(issue_number=issue_number, branch=branch)

        self._progress(message="▶ 调起后端起草 RFC（可能需要几分钟）…")
        self._backend.run(
            work_dir=worktree,
            task=_DRAFT_RFC_TASK.format(number=issue.number, title=issue.title, body=issue.body),
            context=issue.body,
        )
        self._progress(message=f"▶ 提交并推送分支 {branch} …")
        self._workspace.commit_and_push(
            worktree=worktree,
            branch=branch,
            message=f"docs: draft RFC for issue #{issue.number}",
        )

        # RFC-0008：开 PR 前，从本分支新增的 RFC 抽取「端到端验证」指路牌拼进正文。
        # 定位失败 / 渲染为 None 时正文回退为原样、不抛错（决策 5，验收标准 2）。
        rfc_path = self._workspace.changed_rfc_path(worktree=worktree, base=base)
        e2e_section = rfc.signpost_for(rfc_path=rfc_path) if rfc_path else None

        self._progress(message="▶ 开 draft PR …")
        pr = github.create_pr(
            branch=branch,
            title=f"docs: RFC for issue #{issue.number} {issue.title}".strip(),
            body=self._pr_body(
                issue_number=issue.number,
                summary="RFC 草稿待评审。",
                e2e_section=e2e_section,
            ),
            draft=True,
        )
        # RFC-0007 决策 4：一次写成带 pr 的 rfc-review，消除原 record_run(pr-open)→update_status
        # 两次写之间的瞬态 pr-open 窗口（否则恰被 poll 扫到会误当 coding 阶段处理）。
        self._state.record_run(
            issue_number=issue.number, branch=branch, pr=pr, status=STATUS_RFC_REVIEW
        )
        return pr

    # --- 原子操作 2：按评审精炼 RFC -------------------------------------- #
    def refine_rfc(self, *, pr_number: int, detail: str) -> None:
        """RFC-0005：按评审评论精炼 RFC、回贴一条改动说明评论，状态维持 rfc-review。"""
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)

        self._progress(message=f"▶ 按评审意见精炼 PR #{pr_number} 的 RFC …")
        result = self._backend.run(
            work_dir=worktree,
            task=_REFINE_RFC_TASK.format(detail=detail),
            context=detail,
        )
        self._workspace.commit_and_push(
            worktree=worktree,
            branch=record.branch,
            message=f"docs: refine RFC for PR #{pr_number} per review",
        )
        # 决策 6：回贴评论说明改动，让人类知道 RFC 已据评审更新。
        # RFC-0011 决策 4：走 identity.post_signed_comment 给回贴盖本实例签名，
        # 使下一轮 poll 据签名剔除这条自评论，不再对自己的回贴触发 refine（防自循环）。
        identity.post_signed_comment(
            pr_number=pr_number,
            body=_REFINE_COMMENT.format(summary=result.summary or "（无摘要）"),
            agent_id=self._agent_id,
        )
        self._state.update_status(issue_number=record.issue_number, status=STATUS_RFC_REVIEW)

    # --- 原子操作 3：RFC 获批后实现代码 --------------------------------- #
    def implement(self, *, pr_number: int) -> None:
        """RFC-0005：RFC 获批后按其写代码、把 draft PR 转正，状态 pr-open。"""
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)

        self._progress(message=f"▶ RFC 已批准，按 RFC 实现 PR #{pr_number} 的代码 …")
        self._backend.run(
            work_dir=worktree,
            task=_IMPLEMENT_TASK.format(number=record.issue_number),
            context="",
        )
        self._workspace.commit_and_push(
            worktree=worktree,
            branch=record.branch,
            message=f"feat: implement issue #{record.issue_number} per RFC",
        )
        self._progress(message="▶ 取消 draft，PR 转正 …")
        github.mark_ready(pr_number=pr_number)
        self._state.update_status(issue_number=record.issue_number, status=STATUS_PR_OPEN)

    # --- 原子操作 4：coding 阶段迭代（CI/comment 反馈）------------------ #
    def iterate(self, *, pr_number: int, reason: str, detail: str) -> None:
        """RFC-0001（决策 7）+ RFC-0005：在 issue 的 worktree 内续写并**追加 commit**。

        reason ∈ {"comment", "ci"}：决定喂回上下文的来源（评论正文或 CI 失败日志）。
        不 force-push，仅 add/commit/push 追加一个新 commit；状态置 iterating。
        """
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)

        task = f"针对 PR #{pr_number} 的{reason}反馈，请继续修改：\n{detail}"
        self._backend.run(work_dir=worktree, task=task, context=detail)
        self._workspace.commit_and_push(
            worktree=worktree,
            branch=record.branch,
            message=f"fix: address {reason} feedback on PR #{pr_number}",
        )
        self._state.update_status(issue_number=record.issue_number, status=STATUS_ITERATING)

    def _require_run(self, *, pr_number: int) -> RunRecord:
        """按 PR number 定位 run；找不到则抛 OrchestratorError（refine/implement/iterate 复用）。"""
        record = self._state.find_run(pr_number=pr_number)
        if record is None:
            raise OrchestratorError(f"找不到 PR #{pr_number} 对应的 run")
        return record

    def _progress(self, *, message: str) -> None:
        """RFC-0003 决策 6：把各阶段进度打到 stderr，保证用户全程有反馈。"""
        print(message, file=sys.stderr, flush=True)

    def _pr_body(self, *, issue_number: int, summary: str, e2e_section: str | None) -> str:
        """组装 PR 正文：关联 issue + 摘要（+ RFC-0008 端到端验证指路牌）。

        RFC-0008：e2e_section 非 None 时追加到摘要之后，否则正文回退为原有 Closes + 摘要。
        私有函数，参数无默认值——调用方必须显式传 e2e_section。
        """
        body = f"Closes #{issue_number}\n\n"
        body += summary or "（无摘要）"
        if e2e_section is not None:
            body += f"\n\n{e2e_section}"
        return body
