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
from dataclasses import dataclass
from pathlib import Path

from openagents import backfill, evidence_gate, github, identity, reviewer
from openagents.backends.base import AgentBackend
from openagents.reviewer import ReviewDecision
from openagents.spec import model, signpost, validate
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

# Spec-0025/T2：brownfield 反向补全的分支/worktree 前缀——输入是代码 path（无 issue 号），
# 故用 backfill.slug_for 派生的 path slug 取代 issue 号定址（与 _BRANCH_PREFIX 同构、互不撞名）。
_BACKFILL_BRANCH_PREFIX = "openagents/backfill-"

# RFC-0003 决策 2：分支基线默认锁定到最新 origin/<base>。
# Spec-0023/T2：test 分支门控退役，由 test 改回 main——PR 的 worktree 基线与 PR base 都锁
# main，issue→PR 全程经 reviewer 闸+CI 全绿自动合回 main，main 由此成为持续推进的日常分支；
# 发版另走 release/vX.Y.Z 分支（见 `openagents release`），main 不再需要 test 这层体验服中介。
DEFAULT_BASE = "main"

# RFC-0005 + Spec-0014（issue #53 运行时切换）：各原子操作喂给后端的任务模板（prompt）。
# 后端为 cli-agent（如 Claude Code），自带 spec-driven-development skill（取代 rfc-driven-
# development），故任务只需指明意图与约束，细节交由其遵循该 skill。设计产物从「docs/rfcs/
# 单个 RFC.md」改为「docs/specs/ 下的 spec 活快照组」，用 `spec` CLI 创作（见 #53）。
# Spec-0030/T4：条件式 browser-e2e 方法论引导（由 agent 自检自己的工具列表决定是否适用）。
# 落 in-code 方法论面而非后端适配器/编排核心（理念 10 解耦；且全局硬约束禁写 .claude/）：
# 不检测 MCP、不替 agent 宣告「你有浏览器」，措辞为条件式——agent 本就知道自己有哪些工具。
_BROWSER_E2E_GUIDANCE = (
    "设计成果测试（理念 8）时，如果你具备浏览器工具（如 Playwright / Chrome DevTools MCP），"
    "就优先设计基于浏览器的前端 e2e（导航 / 交互 / 截图 / 断言 / console·network 检查），"
    "而不是仅声明 shell 脚本或跳过；是否具备由你自检自己的工具列表决定。"
)
_DRAFT_RFC_TASK = (
    "为 issue #{number}「{title}」起草一份 spec，遵循 spec-driven-development skill 的 Phase 2"
    "（rust-RFC 形态，总览先行）：\n"
    '1) 用 `spec new <slug> --issue {number} --title ... --summary "<一句话 TL;DR>"` 建组'
    "（已铺好 9 段脚手架）;\n"
    "2) **先写组级 rust-RFC 9 段总览**（编辑组 markdown 正文）：Summary / Motivation（现状+"
    "为什么，**背景就地复述，禁止靠「见 Spec-NNNN」承载必要信息——单 spec 自包含**）/ "
    "Guide-level / Reference-level（技术方案 + DAG + 文件分配 + e2e 脚本路径）/ Drawbacks / "
    "Rationale and alternatives（≥1 备选）/ Prior art / Unresolved questions / Future possibilities;\n"
    "3) **再**用 `spec add-task` 逐个加工作分解行（必填 `--files` 互斥 + `--acceptance`，含依赖、范围）;\n"
    "4) 最后 `spec validate`（必填段空/缺 acceptance/files 重叠 = error）+ `spec render` + `spec graph`。\n"
    "只产出 spec（docs/specs/ 下），不要写实现代码。\n"
    + _BROWSER_E2E_GUIDANCE
    + "\n\nissue 正文：\n{body}"
)
_REFINE_RFC_TASK = (
    "本 issue 的 spec 收到了评审意见，请据此更新 docs/specs/ 下对应的 spec 组"
    "（直接编辑组 markdown：改组级 9 段总览或 frontmatter tasks，保持单 spec 自包含、总览先行，"
    "只改 spec、不写实现代码），改完 `spec validate` + `spec render`。"
    "再用一两句话概述你做了哪些调整。\n\n评审意见：\n{detail}"
)
_IMPLEMENT_TASK = (
    "issue #{number} 的 spec 已获批准（rfc-approved）。请阅读 docs/specs/ 下对应 spec 组，"
    "按其 Task 实现代码并自测（ruff + pytest），代码注释引用对应 `# Spec-NNNN/Tn`。"
    # 收尾前先对齐最新 main，把机械冲突就地解掉，别留给 merge 闸机械式报错（issue #48 indexheal 同源）。
    "\n收尾前先确认本分支能与最新 `origin/main` 干净合并：取最新 main 并入/变基，若有冲突就地解决"
    "——`docs/specs/OVERVIEW.md` 这类生成式索引直接 `spec render` 重渲消解、其余语义解决——"
    "确保 PR 处于可干净合并状态，不要把机械冲突留给 merge 闸。"
)
# refine 后回贴到 PR 的评论模板，明确告知人类「已据评审更新 spec」（决策 6）。
_REFINE_COMMENT = "🤖 已根据评审意见更新 spec：\n\n{summary}"

# Spec-0036/T4：iterate(reason="human") 的人类解挂专属任务 prompt（提示落点放方法论层，不在
# messages 硬编码——理念 10 解耦 + #85 编排不耦合具体生态）。把 detail 框定为「人类回复了你的挂起
# 评论」，并要求 agent 在摘要里正面回应——回应正文（summary）随后由 messages 经 replynote 引用原
# 评论贴回。与普通 comment/ci 反馈（_ITERATE_TASK）区分：那是泛化反馈，这是「对人的正面回应」。
_HUMAN_UNBLOCK_TASK = (
    "人类在 PR #{pr_number} 上回复了你之前的挂起评论：\n{detail}\n\n"
    "请据此继续修改代码，并在最后用一两句话**正面回应这条评论**："
    "回答其追问 / 说明你做了什么 / 若仍解不了就讲清原因（你的这段回应会被引用原评论后贴回 PR）。"
)
# 普通 comment / ci 反馈的迭代任务模板（沿用原内联文案，抽常量与 _HUMAN_UNBLOCK_TASK 并列）。
# 收尾前同 _IMPLEMENT_TASK：先对齐最新 main、就地解机械冲突，别留给 merge 闸（issue #48 indexheal 同源）。
_ITERATE_TASK = (
    "针对 PR #{pr_number} 的{reason}反馈，请继续修改：\n{detail}\n"
    "改完收尾前先确认本分支能与最新 `origin/main` 干净合并：若有冲突就地解决"
    "（`docs/specs/OVERVIEW.md` 这类生成索引用 `spec render` 重渲、其余语义解决），别把机械冲突留给 merge 闸。"
)

# Spec-0025/T2：反向补全任务模板（prompt）。与 _DRAFT_RFC_TASK 镜像，但输入端从「issue 编号」
# 换成「代码路径 + 盘点摘要」，任务端从「据 issue 起草」换成「据代码反推」。关键约束（见
# Spec-0025 Guide-level / Drawbacks）：**必填四段据实写满**、**难反推段标待补**，再过 spec
# validate 才放行——这两条直接喂进 prompt，是「待补占位不滥用」与「草稿可过质量门槛」的根。
_BACKFILL_RFC_TASK = (
    "为存量代码路径 `{path}` 反向补全一份 spec，遵循 spec-driven-development skill 的 Phase 2"
    "（rust-RFC 形态，总览先行）——这是**实现先行**（代码已存在，反推设计），不是设计先行：\n"
    "1) 先读 `{path}` 下的存量代码（下方盘点已圈定范围，但你必须真正读代码、据实反推，"
    "不得凭空编造——理念 8 证据驱动）;\n"
    '2) 用 `spec new <slug> --title ... --summary "<一句话 TL;DR>"` 建组（已铺好 9 段脚手架）;\n'
    "3) **先写组级 rust-RFC 9 段总览**（编辑组 markdown 正文），据实回填已实现部分："
    "Summary / Motivation（这块代码现在做什么、为何存在，**背景就地复述、单 spec 自包含**）/ "
    "Guide-level / Reference-level（实际技术结构 + DAG + 文件分配 + e2e 脚本路径）/ Drawbacks / "
    "Rationale and alternatives（≥1 备选）/ Prior art / Unresolved questions / Future possibilities;\n"
    "4) **必填四段（Summary / Motivation / Reference-level / Rationale and alternatives）必须据实"
    "写满**；对存量代码确实难以反推的非必填段（典型 Drawbacks / Rationale 备选 / Prior art），"
    "允许显式写 `> 待人工补全（brownfield 反推困难）` 占位，但**不得滥用**——能反推的段不许标待补;\n"
    "5) **再**用 `spec add-task` 逐个加工作分解行（必填 `--files` 互斥 + `--acceptance`）;\n"
    "6) 最后 `spec validate`（必填段空 / 缺 acceptance / files 重叠 = error）+ `spec render` + "
    "`spec graph`。只产出 spec（docs/specs/ 下），不要改实现代码。\n"
    + _BROWSER_E2E_GUIDANCE
    + "\n\n代码盘点：\n{inventory}"
)


# Spec-0040/T5：定稿说明书文件名（③ 定稿说明书的落点，与 evidence_gate 的 result.md 同目录）。
_RUNBOOK_FILENAME = "runbook.md"
# 定稿 runbook 的任务模板（派实现者 backend）：把 RFC 阶段的 e2e 粗规划落成【具体可执行说明书】。
# tautology guard 防线①支点：runbook 必须落在 RFC 批准意图内，不得把强意图偷换成更弱的检查。
_FINALIZE_RUNBOOK_TASK = (
    "代码已实现完毕，请把本 PR #{pr_number} 的 e2e 粗规划**定稿**成一份具体可执行的说明书 runbook，"
    "写到文件 `{runbook_path}`（若目录不存在请创建）。\n"
    "【RFC 批准的意图（不可偷换、不得弱化）】\n{intent}\n\n"
    "runbook 内容要求（prose 说明书，给独立 executor 照做）：\n"
    "1) 声明执行形态 form={form}（executor 据此选工具真跑）;\n"
    "2) 列出**具体命令 / 请求 / 操作**、期望输出、判定点（怎么起、跑什么、看什么算过），"
    "每一条都要对得上上面的意图与验收行为——不得把「无 origin 报错」偷换成「跑 --help 不崩」式弱化;\n"
    "3) 只写 runbook 这一个文件，不要改实现代码。"
)


@dataclass(frozen=True)
class RunbookHandle:
    """Spec-0040/T5：finalize_runbook 的产物——供 messages 接 executor / 证据闸的定位信息。

    worktree: PR 的隔离 worktree（executor / 证据闸 backend.run 的 cwd）。
    runbook_path: 定稿说明书路径（executor 读它按形态真跑）。
    evidence_dir: 证据落点 `worktree/docs/e2e-results/<pr>/`（executor 写、证据闸读）。
    intent: RFC 批准的意图 + 验收行为文本（证据闸拿它对照证据判达成，tautology guard 防线①/③）。
    """

    worktree: Path
    runbook_path: Path
    evidence_dir: Path
    intent: str


def _intent_text(*, plan: model.E2EPlan) -> str:
    """把组级 e2e 粗规划渲成给 runbook / 证据闸的意图文本（意图 + 逐条验收行为）。"""
    lines = [f"意图：{plan.intent}", "验收行为："]
    lines.extend(f"- {behavior}" for behavior in plan.acceptance)
    return "\n".join(lines)


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
        e2e_section = signpost.signpost_for_group(group_path=spec_group) if spec_group else None
        # Spec-0028/T1：复用同一 spec_group 抽组级总览三段摘要，内嵌进 PR 正文（None 即跳过，零回归）。
        digest_section = (
            signpost.overview_digest_for_group(group_path=spec_group) if spec_group else None
        )

        self._progress(message="▶ 开 draft PR …")
        pr = github.create_pr(
            branch=branch,
            base=base,  # RFC-0012 决策 2：PR base 锁定到 test（与 worktree 基线同源）。
            title=f"docs: spec for issue #{issue.number} {issue.title}".strip(),
            body=self._pr_body(
                issue_number=issue.number,
                summary="spec 草稿待评审。",
                digest_section=digest_section,
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

    # --- 原子操作 1bis：brownfield 反向补全 RFC（Spec-0025/T2）----------- #
    def backfill_rfc(self, *, path: str, base: str = DEFAULT_BASE) -> github.PR:
        """Spec-0025/T2：扫存量代码 → 派后端反推 9 段 spec → validate 门控 → 开 draft PR。

        与 start_rfc 同构（复用 workspace/backend/github/signpost 骨架），只替换两端：
        输入端把「拉 issue」换成「盘点代码路径」，任务端把「据 issue 起草」换成「据代码反推」。
        path 无 issue 号，故分支/worktree 用 backfill.slug_for 派生的 slug 定址（_BACKFILL_BRANCH_PREFIX）。

        **validate 门控**（Spec-0025 Guide-level 第 3 步）：后端产出草稿后先跑 `spec validate`，
        有 error（必填四段空 / 缺 acceptance / files 重叠）则**不 commit、不开 PR**，抛
        OrchestratorError——保证开出的 draft PR 必然已过既有质量门槛（不新增 validate 规则）。
        校验通过才提交并开 draft PR（不自动 merge，交人评审、补全「待补」段——理念 5）。
        """
        target = Path(path)
        self._progress(message=f"▶ 盘点存量代码 {target} …")
        # 盘点既校验路径存在（不存在 / 无 .py 即抛 BackfillError），也为 agent 圈定阅读范围。
        report_inventory = backfill.inventory(path=target)
        slug = backfill.slug_for(path=target)
        branch = f"{_BACKFILL_BRANCH_PREFIX}{slug}"

        self._progress(message=f"▶ 准备隔离 worktree（基线 origin/{base}）…")
        worktree = self._workspace.prepare(issue_number=slug, branch=branch, base=base)

        self._progress(message="▶ 调起后端反推 9 段 spec（可能需要几分钟）…")
        self._backend.run(
            work_dir=worktree,
            task=_BACKFILL_RFC_TASK.format(path=path, inventory=report_inventory.render()),
            context=report_inventory.render(),
        )

        # validate 门控：有 error 则不 commit、不开 PR（Spec-0025 Reference-level：把 spec
        # validate 当作开 PR 前的硬门控）。复用既有 validate.validate，不新增任何规则。
        self._progress(message="▶ spec validate 门控（必填四段据实写满才放行）…")
        result = validate.validate(specs_root=worktree / "docs" / "specs")
        if not result.ok:
            errors = [issue for issue in result.issues if issue.level == "error"]
            raise OrchestratorError(
                f"反推草稿未过 spec validate（{len(errors)} 个 error），不开 PR；"
                f"首个：{errors[0].where} {errors[0].message}"
                if errors
                else "反推草稿未过 spec validate，不开 PR"
            )

        self._progress(message=f"▶ 提交并推送分支 {branch} …")
        self._workspace.commit_and_push(
            worktree=worktree,
            branch=branch,
            message=f"docs: backfill spec for {path}",
        )

        # 复用 start_rfc 的指路牌抽取：从反推出的 spec 组抽 e2e 指路牌拼进 PR 正文（None 即回退）。
        spec_group = self._workspace.changed_spec_group(worktree=worktree, base=base)
        e2e_section = signpost.signpost_for_group(group_path=spec_group) if spec_group else None
        # Spec-0028/T1：同 start_rfc，复用 spec_group 抽总览三段摘要内嵌进 PR 正文（None 即跳过）。
        digest_section = (
            signpost.overview_digest_for_group(group_path=spec_group) if spec_group else None
        )

        self._progress(message="▶ 开 draft PR …")
        return github.create_pr(
            branch=branch,
            base=base,
            title=f"docs: backfill spec for {path}",
            body=self._backfill_pr_body(
                path=path, digest_section=digest_section, e2e_section=e2e_section
            ),
            draft=True,
        )

    def _backfill_pr_body(
        self, *, path: str, digest_section: str | None, e2e_section: str | None
    ) -> str:
        """Spec-0025/T2：组装反向补全 PR 正文——说明来源 + 提示评审补「待补」段（+ e2e 指路牌）。

        无关联 issue（path 驱动），故不含 `Closes #N`；正文回退/追加逻辑同 _pr_body。
        Spec-0028/T1：digest_section 非 None 时夹在说明之后、e2e_section 之前（None 即跳过，零回归）。
        """
        body = (
            f"🤖 反向补全：扫 `{path}` 反推出的 spec 草稿，待评审。\n\n"
            "必填四段据实回填；标「待人工补全」的段请在评审中补全后再转正（不自动 merge）。"
        )
        if digest_section is not None:
            body += f"\n\n{digest_section}"
        if e2e_section is not None:
            body += f"\n\n{e2e_section}"
        return body

    # --- 原子操作 2：按评审精炼 RFC -------------------------------------- #
    def refine_rfc(self, *, pr_number: int, detail: str, announce: bool = True) -> str:
        """RFC-0005：按评审评论精炼 RFC，状态维持 rfc-review；返回 agent 本轮动作的 summary。

        Spec-0036/T4：返回 `result.summary`（供 messages 在人类解挂路径作回应文本）；返回值是新增
        信息，既有忽略返回值的调用方（reviewer 驱动的 refine 路径）零影响。`announce` 控制是否回贴
        泛化的 `_REFINE_COMMENT` 广播：reviewer 驱动路径 `announce=True`（保持现状，回贴「已据评审
        更新 spec」）；人类解挂路径 `announce=False`——抑制广播，使该交互恰产生一条评论 = messages
        随后贴的「引用原评论的回应」（奥卡姆：一轮人类解挂 → 一条针对性回应，不叠加泛化广播）。
        """
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
        # 决策 6：reviewer 驱动路径回贴评论说明改动，让人类知道 RFC 已据评审更新。
        # RFC-0011 决策 4：走 identity.post_signed_comment 给回贴盖本实例签名，用于评论溯源/审计。
        # Spec-0036/T4：announce=False（人类解挂路径）抑制此泛化广播——回应由 messages 经 replynote
        # 引用原评论统一贴出，不在此叠加第二条评论。
        if announce:
            identity.post_signed_comment(
                pr_number=pr_number,
                body=_REFINE_COMMENT.format(summary=result.summary or "（无摘要）"),
                agent_id=self._agent_id,
            )
        self._state.update_status(issue_number=record.issue_number, status=STATUS_RFC_REVIEW)
        return result.summary

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
        # Spec-0040/T5：退役 implement 内的一次性 smoke（旧 _post_e2e_result，病灶：测过期版本 + 没牙 +
        # 结果没人消费）。e2e 改由 merge 前的证据闸负责（finalize_runbook → executor → 证据闸门控合并，
        # 见 messages._process_coding），测的是最终要合的集成态、且 FAIL 挡合并。
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

    # --- 证据闸：定稿 runbook + 固化证据（Spec-0040/T5）------------------ #
    def finalize_runbook(self, *, pr_number: int) -> RunbookHandle | None:
        """Spec-0040/T5（③）：把本分支 spec 的 e2e 粗规划定稿成可执行 runbook 并 commit。

        代码在了才定稿（具体命令/判定点这时才定得下来）：读本分支改动的 spec 组的组级 e2e 粗规划
        （form/intent/acceptance，Spec-0040/T1）——**未声明即返回 None**（非交互 PR，证据闸空过，
        零回归）。声明则派**实现者 backend**（它最懂代码）把粗规划落成 `docs/e2e-results/<pr>/runbook.md`
        （声明形态、列出「怎么起、跑什么、看什么算过」），受 tautology guard 约束：runbook 必须落在 RFC
        批准的意图内、不得偷换。写完 commit+push 进 PR。返回 RunbookHandle 供 messages 接 executor/证据闸。
        """
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)
        plan = self._e2e_plan(worktree=worktree)
        if plan is None:
            self._progress(message=f"▶ PR #{pr_number} 无 e2e 粗规划，证据闸空过")
            return None

        evidence_dir = worktree / evidence_gate.evidence_dir_for(pr_number=pr_number)
        runbook_path = evidence_dir / _RUNBOOK_FILENAME
        intent = _intent_text(plan=plan)

        self._progress(message=f"▶ 定稿 PR #{pr_number} 的 e2e 说明书 runbook（形态 {plan.form}）…")
        self._backend.run(
            work_dir=worktree,
            task=_FINALIZE_RUNBOOK_TASK.format(
                pr_number=pr_number,
                form=plan.form,
                intent=intent,
                runbook_path=runbook_path,
            ),
            context=intent,
        )
        self._workspace.commit_and_push(
            worktree=worktree,
            branch=record.branch,
            message=f"test: finalize e2e runbook for PR #{pr_number}",
        )
        return RunbookHandle(
            worktree=worktree,
            runbook_path=runbook_path,
            evidence_dir=evidence_dir,
            intent=intent,
        )

    def commit_evidence(self, *, pr_number: int) -> None:
        """Spec-0040/T5（⑤）：把 executor 写进 evidence_dir 的证据 commit+push 进 PR（durable）。

        executor.run_executor 已把 result.md / 日志写进 worktree 的 `docs/e2e-results/<pr>/`；这里统一
        提交（无改动时 commit_and_push 内部幂等无操作）。让证据 durable、可被证据闸读、也给人看成果
        （理念 8）。ensure worktree 幂等（复用 finalize 已建的）。
        """
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)
        self._workspace.commit_and_push(
            worktree=worktree,
            branch=record.branch,
            message=f"test: e2e evidence for PR #{pr_number}",
        )

    def _e2e_plan(self, *, worktree: Path) -> model.E2EPlan | None:
        """读本分支改动的 spec 组的组级 e2e 粗规划；无改动组 / 组不可读 / 未声明 → None。"""
        spec_group = self._workspace.changed_spec_group(worktree=worktree, base=DEFAULT_BASE)
        if spec_group is None or not spec_group.is_file():
            return None
        try:
            group = model.load_group(path=spec_group)
        except (OSError, ValueError):
            return None
        return group.metadata.e2e

    # --- 原子操作 4：coding 阶段迭代（CI/comment 反馈）------------------ #
    def iterate(self, *, pr_number: int, reason: str, detail: str) -> str:
        """RFC-0001（决策 7）+ RFC-0005：在 issue 的 worktree 内续写并**追加 commit**；返回 agent summary。

        reason ∈ {"comment", "ci", "review", "human", "e2e"}：决定喂回上下文的来源与任务 prompt 文案。
        Spec-0040/T5：新增 "e2e"——证据闸 FAIL 时把「哪条验收行为没达成/避重就轻」喂回改代码，走
        泛化反馈模板（与 ci/review 同款，逐字节文案：把 reason 填进 _ITERATE_TASK 的「{reason}反馈」）。
        不 force-push，仅 add/commit/push 追加一个新 commit；状态置 iterating。

        Spec-0036/T4：reason="human"（Spec-0032 已引入该取值，人解挂 code 闸）走人类解挂专属任务
        prompt（_HUMAN_UNBLOCK_TASK），把 detail 框定为「人类回复了你的挂起评论，请正面回应」；其余
        reason 沿用泛化反馈模板（_ITERATE_TASK，逐字节同今天）。返回 `result.summary` 供 messages 在
        人类解挂路径作回应文本——返回值是新增信息，既有忽略返回值的调用方（ci/review 闸）零影响。
        """
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)

        if reason == "human":
            task = _HUMAN_UNBLOCK_TASK.format(pr_number=pr_number, detail=detail)
        else:
            task = _ITERATE_TASK.format(pr_number=pr_number, reason=reason, detail=detail)
        result = self._backend.run(work_dir=worktree, task=task, context=detail)
        self._workspace.commit_and_push(
            worktree=worktree,
            branch=record.branch,
            message=f"fix: address {reason} feedback on PR #{pr_number}",
        )
        self._state.update_status(issue_number=record.issue_number, status=STATUS_ITERATING)
        return result.summary

    def _require_run(self, *, pr_number: int) -> RunRecord:
        """按 PR number 定位 run；找不到则抛 OrchestratorError（refine/implement/iterate 复用）。"""
        record = self._state.find_run(pr_number=pr_number)
        if record is None:
            raise OrchestratorError(f"找不到 PR #{pr_number} 对应的 run")
        return record

    def _progress(self, *, message: str) -> None:
        """RFC-0003 决策 6：把各阶段进度打到 stderr，保证用户全程有反馈。"""
        print(message, file=sys.stderr, flush=True)

    def _pr_body(
        self,
        *,
        issue_number: int,
        summary: str,
        digest_section: str | None,
        e2e_section: str | None,
    ) -> str:
        """组装 PR 正文：关联 issue + 摘要（+ Spec-0028 总览摘要 + RFC-0008 端到端验证指路牌）。

        RFC-0008：e2e_section 非 None 时追加到摘要之后，否则正文回退为原有 Closes + 摘要。
        Spec-0028/T1：digest_section 非 None 时夹在 summary 之后、e2e_section 之前（None 即跳过，
        零回归——digest/e2e 皆 None 时正文逐字节同今天）。私有函数，参数无默认值——调用方必须显式传。
        """
        body = f"Closes #{issue_number}\n\n"
        body += summary or "（无摘要）"
        if digest_section is not None:
            body += f"\n\n{digest_section}"
        if e2e_section is not None:
            body += f"\n\n{e2e_section}"
        return body
