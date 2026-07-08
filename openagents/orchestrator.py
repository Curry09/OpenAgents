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

from openagents import agentcontext, backfill, executor, github, identity, issuecheck, reviewer
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
from openagents.workspace import Workspace, WorkspaceError

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
# Spec-0044/T3：把 Spec-0030 的条件式 browser-e2e 引导加强为完整「取证判断纪律」，注入实现/派单
# prompt。三分类判断（UI 可见→截图 / UI 不可见但改产品行为→运行日志文本 / 纯内部→相称测试）
# + 反测试顶替 + 反「慢/flaky/投入产出比」借口 + 真跑不起来诚实报阻塞，并指路仓库内 skill 原文。
# 措辞条件式、由 agent 自检（不宣告「OpenAgents 检测到你有浏览器」）；落 in-code 方法论面，不写
# .claude/、不耦合具体 MCP 生态（理念 10 解耦；全局硬约束禁写 .claude/）。
_E2E_EVIDENCE_DISCIPLINE = (
    "取证判断纪律：你改的行为若是**产品对外行为**，验证就要真 app 跑出来的证据，自检分三类——"
    "① UI 直接看得到（工具集 / 报错 / 状态 / 页面渲染…）→ 把真 app 跑起来、真操作到那个点、"
    "**截下那个可视化结果**存进 tracked 证据目录（如 docs/evidence/）；"
    "② UI 看不到但确实改变产品对外行为（如某配置真生效）→ 真 app 触发它、提交**真实运行日志文本 + "
    "触发它的真 app 上下文**为证；③ 纯内部实现细节（重构等，不改对外行为）→ 用相称的自动化测试即可。"
    "纪律：自动化测试 / 后端日志**替代不了**真 app 证据；不许拿「LLM 慢 / flaky / 投入产出比差」当"
    "跳过借口；**真跑不起来就诚实报「因 X 未验证」的阻塞项，绝不假称已验证**。"
    "细则（反惰性 rationalization 表 / 通用流程 / 合格证据判据）见仓库内 "
    "docs/skills/end-to-end-ui-screenshots/。是否适用由你自检自己改的是哪一类行为。"
)
# Spec-0056/T2：git 交付协议（软约束）——交付/冲突自愈下放 agent（唯一有语义能力读冲突、判意图、
# 跑自测的一方），追加进 _DRAFT/_REFINE/_IMPLEMENT/_ITERATE 及 _BACKFILL_RFC_TASK。硬性次序：BASE 取
# **fetch 前**的远端基点（否则 fetch 刷新跟踪 ref 会让 lease 保护退化成等价裸 force——社区公认 footgun）；
# 推送用 `--force-with-lease=<branch>:$BASE` 且**仅限本工作分支**（派单/迭代 issue-<n>、反向补全
# backfill-<slug>）、**绝不裸 --force**；完成判据 origin==HEAD。harness 只保留 assert_delivered 一道
# 死代码硬闸兜底（agent 没落地→head 不前移→拦下转人工）。
_GIT_DELIVERY_PROTOCOL = (
    "\n\n【交付协议——你负责把改动真正推上远端本工作分支 <branch>，直到成果落到 PR head】\n"
    '1. `git add -A && git commit -m "<语义化信息>"`——首稿用 draft 措辞、后续迭代用 refine 等'
    "**不同**措辞，别再堆固定的 `docs: draft spec` 消息;\n"
    "2. **先**记下远端基点 `BASE=$(git rev-parse origin/<branch>)`，**再** `git fetch origin "
    "<branch>`（BASE 必须在 fetch **之前**求值，否则 fetch 刷新跟踪 ref 会让 lease 保护退化成等价"
    "裸 force）;\n"
    "3. 与远端分叉就 `git rebase origin/<branch>`：有冲突你自己读 `<<<<<<<` 标记按双方意图语义"
    "解决、`git add -A && git rebase --continue`，直到 rebase 走完（不许中途 abort、不甩 needs-human）;\n"
    "4. `git push --force-with-lease=<branch>:$BASE origin <branch>`;\n"
    "5. **禁止裸** `git push --force`（无 lease）；`--force-with-lease` 仅限本工作分支 <branch>，"
    "绝不作用于 main / 受保护分支 / 他人分支;\n"
    "完成判据：`git rev-parse origin/<branch>` == 你的 `HEAD`，不相等就继续处理直到相等。"
)
# Spec-0056/T2：head 前移硬闸拦下（agent 自判完成却没把成果推上去）时贴到 issue/PR 的署名说明评论。
_DELIVERY_STALL_COMMENT = (
    "🤖 交付未落地：本分支 `{branch}` 的远端 head 未前移到本地 HEAD，疑似自判完成却没把成果推上去"
    "（未 push / rebase 半途放弃 / 漏 `--force-with-lease`）。\n\n"
    "已打 `needs-human` 挂起，待人工介入。诊断：{reason}"
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
    # Spec-0057/T1：起草侧软引导——e2e 块是 run_e2e 唯一读的东西，缺它 RFC 闸会确定性返工（门控在编排层，
    # 不靠 LLM）。这里让起草 agent 一次到位、少一轮返工。
    "**必须在组 frontmatter 声明 `e2e:` 测法块**（含 `intent`=一句话验什么 + `method`=一段 prose 测法步骤）；"
    "**每个 spec 都要声明**——纯文档/重构/无运行时行为的改动也声明，`method` 写「无运行时行为可验」即可。\n"
    "只产出 spec（docs/specs/ 下），不要写实现代码。\n"
    + _BROWSER_E2E_GUIDANCE
    + "\n\nissue 正文：\n{body}"
    # Spec-0056/T2：交付下放 agent——首稿 commit 用 draft 语义化措辞，再按协议 push（禁固定 draft-spec 消息）。
    + _GIT_DELIVERY_PROTOCOL
)
_REFINE_RFC_TASK = (
    # Spec-0052/T3：任务模板补 PR 号（issue #129 缺口一）——原文只说「本 issue 的 spec」，agent
    # 手里有 gh 却不知 PR 号，无从自查 PR 元信息/评论线程；统一约定所有派单入口把 PR 号写进 task。
    "PR #{pr_number} 的 spec 收到了评审意见，请据此更新 docs/specs/ 下对应的 spec 组"
    "（直接编辑组 markdown：改组级 9 段总览或 frontmatter tasks，保持单 spec 自包含、总览先行，"
    "只改 spec、不写实现代码），改完 `spec validate` + `spec render`。"
    "再用一两句话概述你做了哪些调整。\n\n评审意见：\n{detail}" + _GIT_DELIVERY_PROTOCOL
    # Spec-0056/T2：交付下放 agent——commit 用 refine 语义化措辞，再按协议 push。
)
_IMPLEMENT_TASK = (
    # Spec-0052/T3：任务模板由「只带 issue 号」改为**同时**带 PR 号（issue #129 缺口一）——原文
    # 误用 issue 号定位，agent 拿不到 PR 号；保留 issue 号线索、补上 PR #{pr_number}，形成统一约定。
    "issue #{issue_number} 的 spec 已获批准（rfc-approved），对应 PR #{pr_number}。"
    "请阅读 docs/specs/ 下对应 spec 组，"
    "按其 Task 实现代码并自测（ruff + pytest），代码注释引用对应 `# Spec-NNNN/Tn`。\n"
    # Spec-0044/T3：实现阶段注入取证判断纪律（三分类 + 反测试顶替 + 诚实报阻塞 + skill 指路）。
    + _E2E_EVIDENCE_DISCIPLINE
    # 收尾前先对齐最新 main，把机械冲突就地解掉，别留给 merge 闸机械式报错（issue #48 确定性重渲同源）。
    + "\n收尾前先确认本分支能与最新 `origin/main` 干净合并：取最新 main 并入/变基，若有冲突就地解决"
    "——`docs/specs/OVERVIEW.md` 这类生成式索引直接 `spec render` 重渲消解、其余语义解决——"
    "确保 PR 处于可干净合并状态，不要把机械冲突留给 merge 闸。"
    # Spec-0056/T2：交付下放 agent——commit 用语义化措辞，再按协议 push（BASE 取 fetch 前、force-with-lease 仅本分支）。
     + _GIT_DELIVERY_PROTOCOL
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
# 收尾前同 _IMPLEMENT_TASK：先对齐最新 main、就地解机械冲突，别留给 merge 闸（issue #48 确定性重渲同源）。
_ITERATE_TASK = (
    "针对 PR #{pr_number} 的{reason}反馈，请继续修改：\n{detail}\n"
    "改完收尾前先确认本分支能与最新 `origin/main` 干净合并：若有冲突就地解决"
    "（`docs/specs/OVERVIEW.md` 这类生成索引用 `spec render` 重渲、其余语义解决），别把机械冲突留给 merge 闸。"
    # Spec-0056/T2：交付下放 agent——追加 commit 用语义化措辞，再按协议 push。
    + _GIT_DELIVERY_PROTOCOL
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
    # Spec-0056/T2：交付下放 agent——反向补全同样自负交付（commit 用 backfill 语义化措辞，再按协议
    # push；BASE 取 fetch 前、force-with-lease 仅本工作分支 openagents/backfill-<slug>）。先过第 6 步
    # 的 `spec validate` 再交付，避免推出没过校验的稿（见 spec Drawbacks 孤儿分支缓解）。
    + _GIT_DELIVERY_PROTOCOL
)


# Spec-0055/T5：证据落点相对路径约定（executor 写 result.md / 截图，reviewer 读；单一来源在此）。
_EVIDENCE_ROOT = ("docs", "e2e-results")

# Spec-0057/T1：RFC 闸缺 e2e 块时的**确定性**返工文案（不问 LLM 直接 refine_rfc 喂它）。
_E2E_BLOCK_MISSING_MSG = (
    "你的 spec 缺 e2e 测法块：请在组 frontmatter 声明 `e2e:`，含 `intent`（一句话验什么）+ `method`"
    "（一段 prose 测法步骤，怎么测、看什么算过；不含精确命令）。**每个 spec 都要声明**——纯文档/重构/无"
    "运行时行为的改动也声明，`method` 写「无运行时行为可验，纯文档/内部改动」即可。这个块是 run_e2e 唯一"
    "读的东西：缺它，独立 executor 就永远不会真跑、e2e 验证等于没有。补上后再交评审。"
)


@dataclass(frozen=True)
class E2ERunResult:
    """Spec-0055/T5：orchestrator.run_e2e 的产物——供 messages 渲报告 + 判是否复用。

    reused: True = 源码指纹未变、复用上轮证据（executor 未真跑，result=None）；False = 本轮真跑了。
    result: 本轮 executor 的结构化结果（reused=True 时为 None）。
    """

    reused: bool
    result: executor.ExecutorResult | None


class OrchestratorError(Exception):
    """编排过程中无法继续时抛出（如 refine/implement/iterate 找不到对应 PR 的 run）。"""


class ClaimLost(OrchestratorError):
    """Spec-0049/T4：认领二次确认（read-after-write）发现 issue 已被别的 agent 更晚认领。

    本后端**主动退让**本轮起草：start_rfc 捕获后清掉本轮 begin_run 的本地 solving 记录、再把本
    异常上抛，由 vigil 发现段既有的 per-issue `except (OrchestratorError, GithubError)` 兜住
    （只跳过该 issue、下轮重试，不拖垮整轮）。是 OrchestratorError 子类，故无需改动 vigil 的兜底。
    """


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
            # Spec-0049/T4（止血，对应缺陷 2）：resume **不再认领**——认领只在 fresh 首次派单打一次。
            # 一旦本地已在推进（solving），说明认领早已在 fresh 打过，resume 是「断点续跑」、无需也
            # 不应重新认领；删掉这里的 _claim_issue 从根上止住「两个都在 solving 的后端每轮互撕」。
        else:
            self._progress(message=f"▶ 准备隔离 worktree（基线 origin/{base}）…")
            worktree = self._workspace.prepare(issue_number=issue_number, branch=branch, base=base)
            # 进入即记 run（PR 尚未开），崩溃后可据此恢复定位。
            self._state.begin_run(issue_number=issue_number, branch=branch)
            # Spec-0039/T3 + Spec-0049/T4：认领打标 + 署名认领便签——贴近本地 checkpoint（begin_run
            # 后可 resume）、又在耗时起草之前（把跨后端 check-then-claim 窗口从「起草时长」压到「建
            # worktree」）。_claim_issue 做 read-after-write 二次确认，若被他方更晚认领即抛 ClaimLost；
            # 本后端**主动退让**：清掉刚落的 solving 记录（使下一轮回到「看见他方认领→跳过」，而非
            # resume 续跑与赢家双开），再把 ClaimLost 上抛交 vigil per-issue 隔离兜住。
            try:
                self._claim_issue(issue_number=issue_number)
            except ClaimLost:
                self._progress(
                    message=f"↩ issue #{issue_number}：检出他方更晚认领，主动退让、清本地 solving 记录"
                )
                self._state.clear_run(issue_number=issue_number)
                raise

        self._progress(message="▶ 调起后端起草 RFC（可能需要几分钟）…")
        self._backend.run(
            work_dir=worktree,
            task=_DRAFT_RFC_TASK.format(number=issue.number, title=issue.title, body=issue.body),
            context=issue.body,
        )
        # Spec-0056/T2：交付下放 agent——backend 已按 _GIT_DELIVERY_PROTOCOL 语义化 commit + push
        # （删除原硬编码 `docs: draft spec for issue #<n>` 同名消息，根因 4）。harness 只调 head 前移
        # 硬闸断言成果真的推上去；未前移即打 needs-human + raise（不再由 harness 盲推、分叉即静默卡死）。
        self._progress(message=f"▶ 校验分支 {branch} 交付（head 前移硬闸）…")
        self._assert_delivered_or_fail(
            worktree=worktree, branch=branch, issue_number=issue.number, pr_number=None
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
        # Spec-0039/T3（决策 E）：draft PR 开出后摘认领标签——此时远端分支 + draft PR 本身已是
        # 去重信号（vigil 闸 2 接管），摘标签保持 issue 干净。清理尽力而为、不阻断已开出的 PR。
        self._release_claim(issue_number=issue.number)
        return pr

    # --- 原子操作 0：进 RFC 前的自洽性自检（Spec-0043/T3）---------------- #
    def precheck_issue(self, *, issue_number: int) -> bool:
        """Spec-0043/T3：判读 issue 是否有会直接影响修法的内在冲突；命中则冻结并返回 True。

        命中冲突 → 打 needs-human 标签 + 贴一条署名对齐评论（请人取舍），返回 True（表示已拦下、
        调用方 vigil 发现段勿再派单）；自洽 → 返回 False（放行照常起草）。判读**在建 worktree /
        begin_run / 认领之前**——被拦的 issue 全程不落任何本地/远端起草痕迹（无 worktree、无 run
        记录、无 spec、无 draft PR），干净可回溯（spec 决策 C）。

        orchestrator 是唯一同时持有 backend / agent_id 的位置，判读 + 打标签 + 贴署名评论落在这里；
        「拦下→跳过派单」的控制流决策留在 vigil 发现段（spec 决策 E / 备选 5）。冻结全程复用既有
        原语：backend 判读、issuecheck 渲染、issue_comment + identity.sign 贴署名评论、
        issue_add_label 打 BLOCKED_LABEL（值即 needs-human）——不新增 state 字段、不改起草 prompt。
        """
        self._progress(message=f"▶ 自检 issue #{issue_number} 修法方向是否自洽 …")
        issue = github.get_issue(number=issue_number)
        verdict = issuecheck.check(
            draft=issuecheck.IssueDraft(title=issue.title, body=issue.body),
            backend=self._backend,
        )
        if not verdict.has_conflict:
            return False
        self._progress(
            message=f"⏸ issue #{issue_number}：检出修法方向冲突，打 {github.BLOCKED_LABEL} 待对齐 …"
        )
        body = issuecheck.build_alignment_comment(verdict=verdict)
        github.issue_comment(
            number=issue_number,
            body=identity.sign(body=body, agent_id=self._agent_id),
        )
        github.issue_add_label(number=issue_number, name=github.BLOCKED_LABEL)
        return True

    def _claim_issue(self, *, issue_number: int) -> None:
        """Spec-0049/T4：认领 issue = 幂等 add 固定标签 + 追加署名认领便签 + read-after-write 二次确认。

        写点在 fresh 分支 begin_run 之后、backend.run 之前（见 start_rfc；resume 不再认领）。三步：
          1. **幂等 add** DISPATCH_LABEL（便宜的粗信号，随 issue 一起被拉下）——对已带标签的 issue
             再 add 是 no-op、**不产生 labeled/unlabeled 事件**，根除「无差别 remove 撕别人标签」。
          2. 追加一条**署名认领便签**评论（identity.build_claim_note：claim 标记 + 本实例签名）作
             归属凭证 + 刷新新鲜度的新 created_at。**只贴自己的、绝不删别人的**（互撕物理来源移除）。
          3. **read-after-write 二次确认**：重读 issue 评论，若最近认领便签 owner 是**别的 agent**
             （对方更晚贴 / 存在他方认领覆盖）→ 抛 ClaimLost，由 start_rfc 捕获退让（末位 created_at
             定胜负、恰一个赢家）。owner 是自己 / 无有效便签（刚贴的那条至少是自己）→ 认领成立。

        **不吞任何异常**（除 ClaimLost 交调用方处理）：gh 穿透 RFC-0010 重试后仍败即抛 GithubError
        上抛，由 vigil per-issue 隔离兜住——本轮跳过、下轮重试，绝不带着「没认领成功」继续起草。
        """
        self._progress(message=f"▶ 认领 issue #{issue_number}（幂等标签 + 署名认领便签）…")
        github.issue_add_label(number=issue_number, name=github.DISPATCH_LABEL)
        github.issue_comment(
            number=issue_number,
            body=identity.build_claim_note(agent_id=self._agent_id),
        )
        # read-after-write：重读最近认领便签，owner 是他人 → 抢慢了，退让。
        claim = identity.latest_claim(comments=github.list_issue_comments(number=issue_number))
        if claim is not None and claim[0] != self._agent_id:
            raise ClaimLost(
                f"issue #{issue_number} 已被 agent {claim[0]!r} 更晚认领，本后端（{self._agent_id!r}）退让"
            )

    def _release_claim(self, *, issue_number: int) -> None:
        """Spec-0039/T3（决策 E）：draft PR 开出后摘认领标签——尽力而为，绝不阻断已开出的 PR。

        此刻远端分支 + draft PR 已是去重信号（vigil 闸 2 接管），认领标签使命完成。清理是 PR 开出
        之后的收尾：任何 gh 故障只记进度并吞掉（残留标签无害，闸 2 已覆盖去重、过期回收兜底），
        与 _post_e2e_result / _post_review_decision 同一「主交付已完成、旁路尽力而为」风格。只吞
        GithubError（issue_remove_label 自带「标签本不在」幂等），不触碰上层 OrchestratorError 隔离。
        """
        try:
            github.issue_remove_label(number=issue_number, name=github.DISPATCH_LABEL)
        except github.GithubError as error:
            self._progress(message=f"⚠ 摘认领标签失败（已忽略，残留标签无害）：{error}")

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

        # Spec-0056/T2：交付下放 agent（_BACKFILL_RFC_TASK 已含 _GIT_DELIVERY_PROTOCOL：语义化 commit +
        # 记 fetch 前 BASE + rebase 自愈 + force-with-lease 仅本工作分支）。删除原硬编码
        # `docs: backfill spec for <path>` 同名消息（根因 4）。backfill 由 CLI 触发、**无** originating
        # issue/PR 可路由 needs-human（draft PR 在交付后才开），故硬闸失败**不走** _fail_to_human，直接
        # raise OrchestratorError——CLI 顶层转干净一行 + 非零退出即人工介入面（见 spec Reference-level ②）。
        self._progress(message=f"▶ 校验分支 {branch} 交付（head 前移硬闸）…")
        try:
            self._workspace.assert_delivered(worktree=worktree, branch=branch)
        except WorkspaceError as exc:
            raise OrchestratorError(str(exc)) from exc

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
            task=_REFINE_RFC_TASK.format(pr_number=pr_number, detail=detail),
            # Spec-0052/T3：context 统一走 build_agent_context——注入 PR 号 + 本 PR 对话历史
            # （历轮裁决/作者回复/人类评论），extra_detail 为本轮评审意见（issue #129 缺口二）。
            context=agentcontext.build_agent_context(pr_number=pr_number, extra_detail=detail),
        )
        # Spec-0056/T2：交付下放 agent（按 _GIT_DELIVERY_PROTOCOL commit+push）；harness 以 head
        # 前移硬闸兜底（未前移→打 needs-human + raise OrchestratorError，vigil per-issue 兜住）。
        self._assert_delivered_or_fail(
            worktree=worktree,
            branch=record.branch,
            issue_number=record.issue_number,
            pr_number=pr_number,
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
    def implement(self, *, pr_number: int) -> str:
        """RFC-0005：RFC 获批后按其写代码、把 draft PR 转正，状态 pr-open；返回 agent 本轮实现摘要。

        Spec-0051/T4：返回 `result.summary`（与 iterate/refine_rfc 同款返回 str，agent 无摘要时回落
        占位保证非空），使 messages 收口点（_process_rfc_review）拿得到「本轮实现了什么」摘要、渲成
        「## 实现自述」回执贴回 PR（理念 8 可观测性）。其余编排语义逐字节不变（backend.run / commit /
        mark_ready / 状态流转 / 清回合数不动）；既有忽略返回值的 cli 调用（cli.py）零影响。
        """
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)

        self._progress(message=f"▶ RFC 已批准，按 RFC 实现 PR #{pr_number} 的代码 …")
        result = self._backend.run(
            work_dir=worktree,
            # Spec-0052/T3：模板补 PR 号（issue 号 + PR 号并存）；context 走 build_agent_context
            # 注入 PR 号 + 本 PR 对话历史，implement 本轮无额外反馈故 extra_detail=""（缺口一/二）。
            task=_IMPLEMENT_TASK.format(issue_number=record.issue_number, pr_number=pr_number),
            context=agentcontext.build_agent_context(pr_number=pr_number, extra_detail=""),
        )
        # Spec-0056/T2：交付下放 agent（按 _GIT_DELIVERY_PROTOCOL commit+push）；harness 以 head
        # 前移硬闸兜底（未前移→打 needs-human + raise OrchestratorError，vigil per-issue 兜住）。
        self._assert_delivered_or_fail(
            worktree=worktree,
            branch=record.branch,
            issue_number=record.issue_number,
            pr_number=pr_number,
        )
        # Spec-0040/T5 + Spec-0055/T5：implement 内不跑任何 e2e（旧一次性 smoke 早退役）。e2e 改由
        # merge 前的 run_e2e 负责（CI 绿后派独立 executor 真跑 → 证据进 review_code 判，见
        # messages._process_coding），测的是最终要合的集成态、且证据不达成即 REWORK 挡合并。
        self._progress(message="▶ 取消 draft，PR 转正 …")
        github.mark_ready(pr_number=pr_number)
        self._state.update_status(issue_number=record.issue_number, status=STATUS_PR_OPEN)
        # RFC-0012 决策 6：进入代码闸前清零回合数，使 K 对 RFC 闸 / 代码闸独立计
        # （RFC 闸耗掉的回合不挤占代码闸的预算）。
        self._state.reset_rounds(issue_number=record.issue_number)
        # Spec-0051/T4：回 agent 本轮实现摘要（空则占位保证非空），供 messages 渲「## 实现自述」回执。
        return result.summary or "（无摘要）"

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
        # Spec-0052/T3：组好本 PR 对话历史，作为 reviewer.review(history=…) 新参传入——让 reviewer
        # 不再失忆（历轮裁决/作者回复/人类评论可见），配套的落盘产物为准 rubric（Spec-0052/T2）保留
        # 其独立性。历史组装收口在 orchestrator（唯一持有 pr_number + github 读能力），reviewer 只
        # 接收字符串、不 import github/agentcontext（issue #129 缺口二 + 理念 10 解耦）。
        history = agentcontext.build_agent_context(pr_number=pr_number, extra_detail="")
        # Spec-0055/T4：透传固化的 e2e 能力状态量——RFC 闸据它分流截图测法要求（起草/评审同源）；
        # code 闸不用它。读侧收口在 orchestrator（持有 state），reviewer 只接布尔参数（理念 10 解耦）。
        decision = reviewer.review(
            backend=self._backend,
            work_dir=worktree,
            kind=kind,
            pr_number=pr_number,
            n=reviewer.configured_reviewers(),
            history=history,
            ui_capable=self._state.get_ui_capable(),
        )
        # RFC-0018：把裁决回贴 PR（恢复人对评审闸的可观测性，理念 8），旁路尽力而为。
        self._post_review_decision(pr_number=pr_number, kind=kind, decision=decision)
        return decision

    def _post_review_decision(self, *, pr_number: int, kind: str, decision: ReviewDecision) -> None:
        """RFC-0018：渲染裁决 → RFC-0011 盖章发评论（尽力而为）。失败仅 _progress、不抛出。

        结构镜像 RFC-0013 的 `_post_e2e_result`（决策 1/2）：渲染由 reviewer.render_decision
        负责（票数语义属 reviewer 领域知识），盖章复用 identity.post_signed_comment（RFC-0011
        唯一出口）；任何 gh 故障都不得阻断评审闸与下游 refine/iterate/merge（决策 2）。

        Spec-0022/T3 → Spec-0047/T2：发评论前按「同 kind 同结论**且同反馈**」去重——最近一条
        同类裁决评论的结论与反馈都与本轮相同才跳过重发，止住「PR 长期 open、裁决不变」刷屏
        （实例 PR #61 的 33 条相同 PASS），同时让理由各异的连续 REWORK 照发（issue #116）。去重
        是尽力而为旁路：查询/比对的任何异常都 fail-open 降级为照常发送（决策 2：宁可多发一条，
        也不因查询抖动漏发裁决、损害可观测性）。
        """
        body = reviewer.render_decision(decision=decision, kind=kind)
        try:
            if self._decision_already_posted(pr_number=pr_number, rendered=body):
                self._progress(message=f"↩ PR #{pr_number} 同结论同反馈裁决评论已存在，跳过重发")
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
        """Spec-0047/T2：本轮裁决是否与 PR 上最近一条同 kind 裁决评论**结论且反馈都**相同。

        去重身份由 reviewer.extract_decision_content 从 rendered / 评论正文反解出（理念 10：格式
        知识归 reviewer，orchestrator 只消费 DecisionContent）。粒度从 Spec-0022/T3 的「结论」升级为
        「结论 + 规范化反馈」：仅当最近一条同 kind 裁决的 verdict_line 与 feedback_norm 均与本轮相同
        才判重复。这样既保留 PR #61 的防刷屏去重（同 PASS 不重发），又让理由各异的连续 REWORK 照发
        （issue #116：结论同但反馈不同 → 照发）。只读 github.list_comments，不改任何状态。
        """
        cur = reviewer.extract_decision_content(body=rendered)
        if cur is None:
            return False  # 本轮无法解析（不应发生）→ fail-open 照发
        # 同 kind 裁决评论：解析成功且类型行相同（区分 rfc / code 两道闸，互不抑制）。
        same_kind = [
            (comment, content)
            for comment in github.list_comments(pr_number=pr_number)
            if (content := reviewer.extract_decision_content(body=comment.body)) is not None
            and content.kind_line == cur.kind_line
        ]
        if not same_kind:
            return False
        # 取最近一条（created_at 为 ISO 8601，可按字典序比较）：结论**与**反馈都相同才算重复。
        _, prev = max(same_kind, key=lambda pair: pair[0].created_at)
        return prev.verdict_line == cur.verdict_line and prev.feedback_norm == cur.feedback_norm

    # --- e2e v2：说明书直喂 executor 真跑 + 固化证据（Spec-0055/T5）--------- #
    def run_e2e(self, *, pr_number: int) -> E2ERunResult | None:
        """Spec-0055/T5：把本分支 spec 的 prose 测法直接喂独立 executor 真跑、固化证据、幂等短路。

        取代 0040 的 finalize_runbook + commit_evidence + 证据闸三步（说明书直喂、无中间 runbook、无
        独立证据闸——达成判决合并进 review_code，见 Spec-0055）。流程：
        - 读本分支改动的 spec 组的 e2e 测法 {intent, method}——**未声明即返回 None**（非交互 PR 空过，零回归）；
        - 算**源码指纹**（github.code_fingerprint 默认排除 docs/e2e-results/）与 record.e2e_ran_fingerprint
          比对：**一致 → 复用上轮证据、不重跑 executor**（返回 reused=True；证据 commit 不改源码指纹，
          故稳态不自我刷屏）；
        - **不一致（或指纹算不出 fail-open）→ 派独立 executor 真跑**（method + intent 直接入 prompt，
          agent 运行时自检工具选路）→ **executor agent 自己 commit+push 证据**（Spec-0056/T4 交付下放）
          → head 前移硬闸 assert_delivered → 落盘新指纹 → 返回 reused=False + result。
        executor 契约绝不抛；但**交付硬闸**（_assert_delivered_or_fail）在 agent 没把证据推上去时会打
        needs-human + `raise OrchestratorError`——与四条交付路径同款，由 messages poll 的 per-record 错误
        隔离兜住（不掀翻整轮）。故本方法不再宣称「绝不抛错」：交付未落地即上抛转人工，是刻意的兜底面。
        """
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)
        plan = self._e2e_plan(worktree=worktree)
        if plan is None:
            self._progress(message=f"▶ PR #{pr_number} 无 e2e 测法，e2e 空过")
            return None

        fingerprint = github.code_fingerprint(pr_number=pr_number)
        if fingerprint and fingerprint == record.e2e_ran_fingerprint:
            self._progress(
                message=f"▶ PR #{pr_number} 源码指纹未变，复用上轮 e2e 证据（跳过 executor）"
            )
            return E2ERunResult(reused=True, result=None)

        evidence_dir = worktree.joinpath(*_EVIDENCE_ROOT, str(pr_number))
        self._progress(message=f"▶ 派独立 executor 照 spec 测法真跑 PR #{pr_number} 的 e2e…")
        result = executor.run_executor(
            backend=self._backend,
            work_dir=worktree,
            method=plan.method,
            evidence_dir=evidence_dir,
            pr_number=pr_number,
            ui_intent=plan.intent,
            # Spec-0056/T4：证据交付也下放 executor agent（注入 _GIT_DELIVERY_PROTOCOL：commit + 记 fetch
            # 前 BASE + rebase 自愈 + push --force-with-lease 仅本工作分支），harness 不再代 push。
            delivery_protocol=_GIT_DELIVERY_PROTOCOL,
        )
        # Spec-0056/T4：删原硬编码 `test: e2e evidence for PR #<n>` 的 commit_and_push（agent 后 harness
        # 死写 git 的最后一处「漏网」）。改调 head 前移硬闸——executor agent 没把证据推上去→打 needs-human
        # + raise OrchestratorError（messages poll 的 per-record 错误隔离兜住，与四条交付路径同款兜底）。
        self._assert_delivered_or_fail(
            worktree=worktree,
            branch=record.branch,
            issue_number=record.issue_number,
            pr_number=pr_number,
        )
        # 只在指纹算得出时落盘（fail-open：算不出则不落、下轮照跑，sticky 永不基于「算不出」跳过）。
        if fingerprint:
            self._state.set_e2e_ran_fingerprint(
                issue_number=record.issue_number, fingerprint=fingerprint
            )
        return E2ERunResult(reused=False, result=result)

    def _e2e_plan(self, *, worktree: Path) -> model.E2EPlan | None:
        """读本分支改动的 spec 组的组级 e2e 测法 {intent, method}；无改动组 / 组不可读 / 未声明 → None。"""
        spec_group = self._workspace.changed_spec_group(worktree=worktree, base=DEFAULT_BASE)
        if spec_group is None or not spec_group.is_file():
            return None
        try:
            group = model.load_group(path=spec_group)
        except (OSError, ValueError):
            return None
        return group.metadata.e2e

    def e2e_block_missing(self, *, pr_number: int) -> str | None:
        """Spec-0057/T1：确定性检查——本分支改动的 spec 组是否声明了真实 e2e 测法块（intent+method 非空）。

        缺（无 e2e 块 / intent 空 / method 空）→ 返回确定性返工文案 `_E2E_BLOCK_MISSING_MSG`；已声明 → None。
        供 RFC 闸在调 LLM reviewer **之前**先跑这道机器检查——LLM 会被 spec 正文里的 e2e 讨论骗过、把「没声明
        结构化 frontmatter e2e 块」放行（见 wind-palace PR #19），这道确定性检查骗不过，保证 run_e2e 永远有块可读。
        纯读、不改状态（ensure worktree 幂等）。
        """
        record = self._require_run(pr_number=pr_number)
        worktree = self._workspace.ensure(issue_number=record.issue_number, branch=record.branch)
        plan = self._e2e_plan(worktree=worktree)
        if plan is None or not plan.intent.strip() or not plan.method.strip():
            return _E2E_BLOCK_MISSING_MSG
        return None

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
        # Spec-0052/T3：context 统一走 build_agent_context——本轮反馈（CI/评论/人类）作 extra_detail，
        # 叠加 PR 号 + 本 PR 对话历史，让迭代 agent 也能看到历轮记忆（issue #129 缺口二）。
        result = self._backend.run(
            work_dir=worktree,
            task=task,
            context=agentcontext.build_agent_context(pr_number=pr_number, extra_detail=detail),
        )
        # Spec-0056/T2：交付下放 agent（按 _GIT_DELIVERY_PROTOCOL 追加 commit + push）；harness 以
        # head 前移硬闸兜底（未前移→打 needs-human + raise OrchestratorError，vigil per-issue 兜住）。
        self._assert_delivered_or_fail(
            worktree=worktree,
            branch=record.branch,
            issue_number=record.issue_number,
            pr_number=pr_number,
        )
        self._state.update_status(issue_number=record.issue_number, status=STATUS_ITERATING)
        return result.summary

    def _assert_delivered_or_fail(
        self, *, worktree: Path, branch: str, issue_number: int, pr_number: int | None
    ) -> None:
        """Spec-0056/T2：agent 交付后调 head 前移硬闸；未前移→needs-human+署名评论+raise OrchestratorError。

        交付（commit→记 fetch 前 BASE→rebase 解冲突→push --force-with-lease）下放给 agent（prompt
        软约束 _GIT_DELIVERY_PROTOCOL）；本方法是唯一死代码兜底：断言 origin/<branch> == 本地 HEAD。
        断言失败（agent 自判完成却没推上去，正是 issue #140 复现）→ _fail_to_human 打 needs-human +
        署名说明评论，再把 WorkspaceError **翻译**成 OrchestratorError 上抛——根因 2 隔离修复：让 vigil
        的 `except (OrchestratorError, GithubError)`（vigil.py）兜住、不被裸 WorkspaceError 击穿整轮；
        翻译落在 orchestrator 这个已同时持有 workspace/github 两侧的 seam，workspace 不反向依赖
        orchestrator（守解耦理念 10；见 spec 备选 3 否决理由）。
        """
        try:
            self._workspace.assert_delivered(worktree=worktree, branch=branch)
        except WorkspaceError as exc:
            self._fail_to_human(
                issue_number=issue_number, pr_number=pr_number, branch=branch, reason=str(exc)
            )
            raise OrchestratorError(str(exc)) from exc

    def _fail_to_human(
        self, *, issue_number: int, pr_number: int | None, branch: str, reason: str
    ) -> None:
        """Spec-0056/T2：head 前移硬闸拦下 → 打 needs-human 标签 + 一条署名说明评论（复用既有原语）。

        pr_number 已开出（refine/implement/iterate）走 PR 级 post_comment + add_label；尚未开 PR
        （start_rfc draft 段，issue #140 复现路径）走 issue 级 issue_comment + issue_add_label。不新增
        state 字段、复用 identity.sign + 既有 needs-human 原语（BLOCKED_LABEL）；评论附双 SHA 诊断
        （reason 携本地 HEAD / 远端 head 摘要）便于人工定位（理念 8 可观测）。
        """
        self._progress(
            message=f"⏸ 分支 {branch} head 未前移、疑似未交付，打 {github.BLOCKED_LABEL} 待人工 …"
        )
        body = identity.sign(
            body=_DELIVERY_STALL_COMMENT.format(branch=branch, reason=reason),
            agent_id=self._agent_id,
        )
        if pr_number is not None:
            github.post_comment(pr_number=pr_number, body=body)
            github.add_label(pr_number=pr_number, name=github.BLOCKED_LABEL)
        else:
            github.issue_comment(number=issue_number, body=body)
            github.issue_add_label(number=issue_number, name=github.BLOCKED_LABEL)

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
