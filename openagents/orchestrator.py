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

from openagents import e2e, github, identity, reviewer
from openagents.backends.base import AgentBackend
from openagents.reviewer import ReviewDecision
from openagents.spec import signpost
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

# RFC-0003 决策 2：分支基线默认锁定到最新 origin/<base>。
# RFC-0012 决策 2：由 main 改为长期 test 分支——PR 的 worktree 基线与 PR base 都锁 test，
# issue→PR 全程在 test 上自动闭环；main 只被 promote 快进，不参与日常流转。
DEFAULT_BASE = "test"

# RFC-0005 + Spec-0014（issue #53 运行时切换）：各原子操作喂给后端的任务模板（prompt）。
# 后端为 cli-agent（如 Claude Code），自带 spec-driven-development skill（取代 rfc-driven-
# development），故任务只需指明意图与约束，细节交由其遵循该 skill。设计产物从「docs/rfcs/
# 单个 RFC.md」改为「docs/specs/ 下的 spec 活快照组」，用 `spec` CLI 创作（见 #53）。
_DRAFT_RFC_TASK = (
    "为 issue #{number}「{title}」起草一份 spec，遵循 spec-driven-development skill 的 Phase 2：\n"
    "用 `spec new <slug> --issue {number} --title ...` 建组，再用 `spec add-task` 逐个加子任务"
    "（含文件清单、依赖、范围、验收），并填写各 Task 的设计 prose；最后 `spec validate` + `spec render`。\n"
    "只产出 spec（docs/specs/ 下），不要写实现代码。\n\nissue 正文：\n{body}"
)
_REFINE_RFC_TASK = (
    "本 issue 的 spec 收到了评审意见，请据此更新 docs/specs/ 下对应的 spec 组"
    "（用 `spec amend` 改 Task，只改 spec、不写实现代码），改完 `spec validate` + `spec render`。"
    "再用一两句话概述你做了哪些调整。\n\n评审意见：\n{detail}"
)
_IMPLEMENT_TASK = (
    "issue #{number} 的 spec 已获批准（rfc-approved）。请阅读 docs/specs/ 下对应 spec 组，"
    "按其 Task 实现代码并自测（ruff + pytest），代码注释引用对应 `# Spec-NNNN/Tn`。"
)
# refine 后回贴到 PR 的评论模板，明确告知人类「已据评审更新 spec」（决策 6）。
_REFINE_COMMENT = "🤖 已根据评审意见更新 spec：\n\n{summary}"


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
            message=f"docs: draft spec for issue #{issue.number}",
        )

        # RFC-0008：开 PR 前，从本分支新增的 RFC 抽取「端到端验证」指路牌拼进正文。
        # 定位失败 / 渲染为 None 时正文回退为原样、不抛错（决策 5，验收标准 2）。
        spec_group = self._workspace.changed_spec_group(worktree=worktree, base=base)
        e2e_section = signpost.signpost_for_group(group_dir=spec_group) if spec_group else None

        self._progress(message="▶ 开 draft PR …")
        pr = github.create_pr(
            branch=branch,
            base=base,  # RFC-0012 决策 2：PR base 锁定到 test（与 worktree 基线同源）。
            title=f"docs: spec for issue #{issue.number} {issue.title}".strip(),
            body=self._pr_body(
                issue_number=issue.number,
                summary="spec 草稿待评审。",
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
        # RFC-0011 决策 4：走 identity.post_signed_comment 给回贴盖本实例签名，用于评论溯源/审计
        # （RFC-0019：评论驱动读侧已退役，poll 不读评论；自动流转由 reviewer 闸驱动，无自循环）。
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
        # RFC-0013：转正前实跑本分支 RFC 的 e2e 脚本，把「合否 + 日志末尾」作为签名评论发出
        # （指路牌 → 实跑结果，理念 8）。整段尽力而为、绝不阻断转正（决策 6）。
        self._post_e2e_result(worktree=worktree, pr_number=pr_number)
        self._progress(message="▶ 取消 draft，PR 转正 …")
        github.mark_ready(pr_number=pr_number)
        self._state.update_status(issue_number=record.issue_number, status=STATUS_PR_OPEN)
        # RFC-0012 决策 6：进入代码闸前清零回合数，使 K 对 RFC 闸 / 代码闸独立计
        # （RFC 闸耗掉的回合不挤占代码闸的预算）。
        self._state.reset_rounds(issue_number=record.issue_number)

    # --- 评审闸：调 reviewer agent 给 RFC / 代码裁决（RFC-0012 决策 5）------ #
    def review_rfc(self, *, pr_number: int) -> ReviewDecision:
        """RFC-0012 决策 5：在 PR 的 worktree 内调 reviewer 评审 RFC 文档，返回聚合裁决。

        reviewer.review 需要 worktree + backend，而二者只有 Orchestrator 持有；故由本方法
        ensure worktree 后转调，messages 只拿 ReviewDecision 决策（保持 messages 薄路由层）。
        N（reviewer 并发数）从 env 读（reviewer.configured_reviewers，决策 6）。
        """
        return self._review(pr_number=pr_number, kind="rfc")

    def review_code(self, *, pr_number: int) -> ReviewDecision:
        """RFC-0012 决策 5：在 PR 的 worktree 内调 reviewer 评审代码 diff，返回聚合裁决。"""
        return self._review(pr_number=pr_number, kind="code")

    def _review(self, *, pr_number: int, kind: str) -> ReviewDecision:
        """review_rfc / review_code 的共用骨架：ensure worktree → reviewer.review。

        RFC-0018：拿到裁决后、返回前，把裁决作为签名评论旁路回贴 PR（best-effort）——
        裁决产生地即回贴地，单点收口，不污染 messages 路由层。
        """
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)
        self._progress(message=f"▶ 调 reviewer 评审 PR #{pr_number}（{kind}）…")
        decision = reviewer.review(
            backend=self._backend,
            work_dir=worktree,
            kind=kind,
            pr_number=pr_number,
            n=reviewer.configured_reviewers(),
        )
        # RFC-0018：把裁决回贴 PR（恢复人对评审闸的可观测性，理念 8），旁路尽力而为。
        self._post_review_decision(pr_number=pr_number, kind=kind, decision=decision)
        return decision

    def _post_review_decision(self, *, pr_number: int, kind: str, decision: ReviewDecision) -> None:
        """RFC-0018：渲染裁决 → RFC-0011 盖章发评论（尽力而为）。失败仅 _progress、不抛出。

        结构镜像 RFC-0013 的 `_post_e2e_result`（决策 1/2）：渲染由 reviewer.render_decision
        负责（票数语义属 reviewer 领域知识），盖章复用 identity.post_signed_comment（RFC-0011
        唯一出口）；任何 gh 故障都不得阻断评审闸与下游 refine/iterate/merge（决策 2）。

        Spec-0022/T3：发评论前按「同 kind 同结论」去重——最近一条同类裁决评论结论与本轮相同
        则跳过重发，止住「PR 长期 open、裁决不变」刷屏（实例 PR #61 的 33 条相同 PASS）。去重
        是尽力而为旁路：查询/比对的任何异常都 fail-open 降级为照常发送（决策 2：宁可多发一条，
        也不因查询抖动漏发裁决、损害可观测性）。
        """
        body = reviewer.render_decision(decision=decision, kind=kind)
        try:
            if self._decision_already_posted(pr_number=pr_number, rendered=body):
                self._progress(message=f"↩ PR #{pr_number} 同结论裁决评论已存在，跳过重发")
                return
        except Exception as error:  # noqa: BLE001 — 去重尽力而为，查询抖动不得漏发裁决
            self._progress(message=f"⚠ 裁决去重查询失败（降级为照发）：{error}")
        try:
            identity.post_signed_comment(
                pr_number=pr_number,
                body=body,
                agent_id=self._agent_id,
            )
        except Exception as error:  # noqa: BLE001 — 旁路尽力而为，任何 gh 故障都不得阻断评审闸
            self._progress(message=f"⚠ 裁决评论发送失败（已忽略）：{error}")

    def _decision_already_posted(self, *, pr_number: int, rendered: str) -> bool:
        """Spec-0022/T3：本轮裁决是否与 PR 上最近一条同 kind 裁决评论结论相同。

        从 rendered（reviewer.render_decision 输出）自身抽取「抬头 / 类型 / 裁决」三行作为匹配
        特征——不重复 reviewer 文案、随其措辞自动同步（理念 10）。去重粒度 = 裁决结论（PASS /
        非 PASS）：只比对类型行 + 裁决行，**不逐字节比对**票数/反馈措辞（它们每轮可能微变，逐字节
        会判「不同」而继续刷屏）。只读 github.list_comments，不改任何状态。
        """
        lines = rendered.splitlines()
        header_line = lines[0]  # "## 评审闸裁决"——reviewer 渲染的稳定抬头
        kind_line = next(line for line in lines if line.startswith("- 类型："))
        verdict_line = next(line for line in lines if line.startswith("- 裁决："))
        # 同 kind 裁决评论：评论正文含抬头行 + 同类型行（区分 rfc / code 两道闸，互不抑制）。
        same_kind = [
            comment
            for comment in github.list_comments(pr_number=pr_number)
            if header_line in comment.body.splitlines() and kind_line in comment.body.splitlines()
        ]
        if not same_kind:
            return False
        # 取最近一条（created_at 为 ISO 8601，可按字典序比较）比对结论：含同一裁决行即重复。
        latest = max(same_kind, key=lambda comment: comment.created_at)
        return verdict_line in latest.body.splitlines()

    def _post_e2e_result(self, *, worktree: Path, pr_number: int) -> None:
        """RFC-0013：定位本分支 spec 的 e2e 脚本 → 实跑 → 渲染 → 签名评论发出（尽力而为）。

        脚本定位单一来源于 spec（issue #53：changed_spec_group + signpost.script_path_for_group）；
        run_e2e_script 契约上绝不抛错；渲染/发评论一步若因 gh 故障抛错，只记进度并吞掉，
        绝不把整条 implement 流程拖崩或拦住 mark_ready（决策 6）。
        """
        self._progress(message="▶ 转正前实跑端到端脚本（ruff + pytest）…")
        # 1. 单一来源定位脚本：本分支改动的 spec 组 → 各 Task tests 里的脚本路径（None 即 skipped）。
        spec_group = self._workspace.changed_spec_group(worktree=worktree, base=DEFAULT_BASE)
        script_path = signpost.script_path_for_group(group_dir=spec_group) if spec_group else None
        # 2. 实跑离线段并截退出码与日志末尾（绝不抛错）。
        result = e2e.run_e2e_script(
            worktree=worktree,
            script_path=script_path,
            timeout_seconds=e2e.DEFAULT_TIMEOUT_SECONDS,
            tail_lines=e2e.DEFAULT_TAIL_LINES,
        )
        # 3. 渲染 + RFC-0011 盖章发评论；发评论失败仅记进度并吞掉，不拖垮主流程。
        try:
            identity.post_signed_comment(
                pr_number=pr_number,
                body=e2e.render_result(result=result, tail_lines=e2e.DEFAULT_TAIL_LINES),
                agent_id=self._agent_id,
            )
        except Exception as error:  # noqa: BLE001 — 旁路尽力而为，任何 gh 故障都不得阻断转正
            self._progress(message=f"⚠ 端到端结果评论发送失败（已忽略）：{error}")

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
