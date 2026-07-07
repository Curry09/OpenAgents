"""RFC-0012 T1: reviewer 编排模块 —— N 并行评审 + 裁决聚合。

把人类从「逐个审 PR diff / 评审 RFC」中抽离出来，质量闸的「人眼看代码」一侧换成
reviewer agent 的全票裁决（RFC-0012 决策 1）。reviewer 是一个纯「输入 RFC/diff →
输出裁决」的无状态函数：以一段 review 任务模板调既有 `AgentBackend.run`（决策 4：
reviewer 与解题 agent 同 backend，不新引入第二套 agent 运行机制——奥卡姆剃刀），
线程池并行派 N 个，从每个 `AgentResult.summary` 解析裁决 token（PASS/REWORK/RETHINK，
移植自 `vigil:vigil-reviewer` 的 rubric），聚合成「全票 PASS」（决策 1）。

解耦设计（CLAUDE.md 理念 10）：本模块只依赖 `AgentBackend` 协议，不碰 git/state/
github/编排——便于单测打桩 backend，保持 hermetic。N（reviewer 并发数）从环境变量
`OPENAGENTS_REVIEWERS` 读取（默认 1，决策 6），缺省即退化为单票。
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from openagents.backends.base import AgentBackend

# RFC-0012 决策 6：reviewer 并发数旋钮——env 缺省取默认值（最小可配集，不引入配置文件）。
REVIEWERS_ENV = "OPENAGENTS_REVIEWERS"
DEFAULT_REVIEWERS = 1

# 裁决 token（移植 vigil-reviewer rubric）：仅 PASS 视为通过，REWORK/RETHINK 均为非 PASS。
# 解析鲁棒：大小写无关、允许 `VERDICT:` 前缀或裸 token，正文里第一处命中即采信。
_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|REWORK|RETHINK)\b", re.IGNORECASE)
_BARE_VERDICT_RE = re.compile(r"\b(PASS|REWORK|RETHINK)\b", re.IGNORECASE)

# review 任务模板：要求 reviewer 独立读 RFC/diff，按 rubric 给出首行裁决 token（决策 1 缺点
# 缓解：强约束输出格式 + 单测覆盖解析）。kind 选择评 RFC 文档 vs 评代码 diff。
# Spec-0021/T1：裁决前置——把「以 VERDICT 开头」升级为硬性「第一行必须是 VERDICT: <token>，
# 在任何 REASON/ISSUES/论证之前」。论证写在裁决之后，长回复被截断时丢的是论证尾部而非裁决头部
# （命中 issue #63 根因 1：裁决与论证分离，避免 VERDICT 拖到末尾被截）。
_RUBRIC_TAIL = (
    "你只读不写，禁止任何写操作（commit/push/改文件）。\n"
    "疑罪从严：任一验证标准不确定是否满足 → 判 REWORK，把疑虑写进 ISSUES。\n"
    "【硬性格式】你的回复第一行必须就是 `VERDICT: <token>`（token ∈ PASS/REWORK/RETHINK），"
    "在任何 REASON/ISSUES/论证之前。所有理由、证据、问题列表一律写在裁决行之后——"
    "这样即便回复被长度截断，丢的也是尾部论证而非裁决本身。\n"
    # Spec-0050/T1：语言/长度硬化——把「理由用简短中文」从「示例偏置」升级为并列于裁决前置的硬性
    # 输出规约。落在 _RUBRIC_TAIL（code/rfc 两闸共享）改一处即两闸同时生效（DRY，奥卡姆，理念 1）。
    # 只约束「裁决行之后的理由正文」，与裁决前置正交、互不削弱；不改任何解析/聚合/渲染逻辑。
    "【硬性语言/长度】面向人类的裁决理由（REASON / ISSUES / NEXT，即裁决行之后的正文）必须用"
    "一段简短的中文书写：直击要害、只讲结论与可操作的下一步，避免长篇英文、避免逐行英文堆砌、"
    "避免照搬内部推理原文。无论你内部以什么语言推理，最终给人看的理由一律译成中文。这段话是给"
    "盯 PR 的人在 GitHub 评论里直接读懂并处理用的，不是给你自己看的过程记录。\n"
    "PASS 示例：\n  VERDICT: PASS\n  REASON: <一句话中文说明核对的关键验证标准>\n"
    "REWORK 示例：\n  VERDICT: REWORK\n  ISSUES:\n  - <文件:行号 + 一句话中文点出问题>\n"
    "  NEXT: <一句话中文说明修复方向>\n"
)
# Spec-0055/T4：「要不要有 e2e」在 RFC 闸把关，且**标准据本机 e2e 能力（ui_capable）确定性分流**——
# 起草与评审读同一个固化状态量（Spec-0055/T1），杜绝两头标准漂移。e2e 块从 0040 的 {form,intent,
# acceptance} 瘦身为 {intent,method}（prose 测法，见 Spec-0055/T2）。ui_capable 由 orchestrator 经
# review(ui_capable=...) 透传，reviewer 据此选下面两条规则之一拼进 RFC 任务（保持 reviewer 只依赖
# AgentBackend + 传入参数的解耦，理念 10）。
_RFC_E2E_RUBRIC_CAPABLE = (
    "【e2e 测法硬规则 · 本机具备浏览器能力】若本 PR 属前端/交互类改动（新增/改动用户可见行为、"
    "CLI 交互、HTTP 接口、前端页面等），其 spec 组必须在组级 frontmatter 声明 e2e 块（含 intent="
    "验什么 + method=怎么测的 prose 测法）；**UI 可见改动的 method 必须要求真实导航后的截图为证**。"
    "未声明 e2e、或 UI 改动的 method 避重就轻不要求截图 → 判 REWORK，写进 ISSUES。纯文档/重构/内部"
    "非交互改动可不声明。\n"
)
_RFC_E2E_RUBRIC_INCAPABLE = (
    "【e2e 测法硬规则 · 本机无浏览器能力】若本 PR 属前端/交互类改动，其 spec 组必须在组级 frontmatter "
    "声明 e2e 块（含 intent + method 的 prose 测法）；未声明 → 判 REWORK。但本机不具备浏览器工具，"
    "**不得因 method 没要求真实截图就 REWORK**——UI 改动可用离线断言 / 命令行 / HTTP 等能跑的方式"
    "验，或在 method 里如实注明「本环境无浏览器、UI 截图不可得」即可。纯文档/重构/内部非交互改动可不声明。\n"
)
# Spec-0048/T1：自动化 spec 防过度承诺——若 spec 承诺新增自动化执行链路（executor/agent、e2e/
# evidence gate/runbook、自动 merge·hold gate、GitHub issue·PR 自动化等），其 Reference-level 必须
# 把闭环讲清（触发时机/调用方/artifact 落点/失败路径/正·反例验收），否则只算设计草案。这把「防骨架
# 冒充完整实现」前移到设计闸：设计阶段就逼作者讲清闭环，实现阶段 reviewer 才有对照物。**只挂 rfc 闸、
# 不挂 code 闸**（与 _EVIDENCE_RUBRIC/_AUTOMATION_INTEGRITY_RUBRIC 只挂 code 闸镜像互补，闸别隔离）。
_RFC_AUTOMATION_RUBRIC = (
    "【自动化 spec 防过度承诺】若本 spec 承诺新增自动化执行链路（executor / agent / runtime "
    "validation、e2e / evidence gate / runbook、自动 merge · hold gate、GitHub issue · PR 自动化，"
    "或任何『自动跑 · 自动提交 · 自动门控』的能力），其 Reference-level 必须声明 触发时机 / 调用方 / "
    "artifact 落点 / 失败路径 / 正·反例验收；否则这份 spec 只算设计草案，不应让对应实现 PR 仅凭这份 "
    "spec 过代码闸——判 REWORK，把「缺自动化闭环声明」写进 ISSUES。纯静态 / 重构 / 内部非自动化 spec 不查。\n"
)
# Spec-0052/T2：落盘产物为准 rubric——issue #129 给 reviewer 注入本 PR 对话历史（历轮裁决/作者
# 回复/人类评论）作背景后，配套的独立性守卫。issue #129 要「让 reviewer 知晓历轮意见/人类指导」，
# 又要保留其「独立读仓库真实状态、不被说辞蒙蔽」的价值（这是 PR #128 能**正确**判 FAIL 的原因：
# 作者在评论里说『已把 result.md 改成 PASS』，但文件真实内容仍是 skipped）。故常驻一条硬约束：历史
# 仅供背景，裁决必须以落盘产物为唯一依据。这是 prompt 层软约束（见 Spec-0052 Drawbacks：非结构性
# 保证），与 messages/orchestrator 不共享草稿状态的结构性隔离互补。历史由 orchestrator 组好经
# review(history=…) 传入 backend context，reviewer 本模块不 import github/agentcontext（理念 10 解耦）。
_HISTORY_PRIMACY_RUBRIC = (
    "【落盘产物为准】你会在上下文里看到本 PR 的对话历史（历轮评审裁决 / 作者回复 / 人类评论）作背景，"
    "帮你了解此前发生过什么、别反复挑同一句已澄清的话；但裁决必须以仓库里的**落盘产物**（文件、"
    "git diff、真实运行证据）为**唯一依据**，评论仅供参考——作者在评论里声称『已修复 / 已改成 PASS』"
    "**不构成放行理由**，你必须核对文件的真实内容再裁决。人类在评论里的指导可纳入考量，但同样以落盘"
    "事实为准。\n"
)
# Spec-0055/T4：RFC 任务的头/尾（e2e 测法 rubric 据 ui_capable 在 _rfc_review_task 里选一条插入）。
_RFC_REVIEW_HEAD = (
    "你是独立的 spec 审核员，与起草者不共享上下文。请评审 PR #{pr_number} 的 spec 组。\n"
    "按顺序读：CLAUDE.md（需求/设计理念）→ docs/specs/ 下本 PR 新增/改动的 spec 组"
    "（单文件 NNNN-slug.md：frontmatter 结构化源数据 + 正文各 Task 设计 prose）→ 其引用的来源。"
    "判定：设计是否对齐需求、关键决策是否"
    "有据、Task DAG 是否可独立实现且各 Task 文件清单互不重叠、是否含实现代码（spec 不应含"
    "实现代码）。\n"
)
_RFC_REVIEW_TAIL = _RFC_AUTOMATION_RUBRIC + _HISTORY_PRIMACY_RUBRIC + _RUBRIC_TAIL
# 未格式化的规范 RFC 模板（capable 变体）——保留供别处按 substring 断言常驻 rubric（如
# _HISTORY_PRIMACY_RUBRIC）；实际派单走 _rfc_review_task 按 ui_capable 分流。
_RFC_REVIEW_TASK = _RFC_REVIEW_HEAD + _RFC_E2E_RUBRIC_CAPABLE + _RFC_REVIEW_TAIL


def _rfc_review_task(*, pr_number: int, ui_capable: bool) -> str:
    """Spec-0055/T4：据 ui_capable 选 e2e 测法 rubric 拼成 RFC 评审任务（起草/评审同源分流）。"""
    e2e_rubric = _RFC_E2E_RUBRIC_CAPABLE if ui_capable else _RFC_E2E_RUBRIC_INCAPABLE
    return (_RFC_REVIEW_HEAD + e2e_rubric + _RFC_REVIEW_TAIL).format(pr_number=pr_number)


# Spec-0055/T4：证据/运行时行为 rubric（**反转 Spec-0040/T4**）。0040 曾让代码 reviewer「只判静态、
# 运行时行为交独立证据闸」；Spec-0055 取消独立证据闸，把运行时行为验收**合并回 code review**——
# reviewer 靠亲眼看 executor 产的证据（result.md + 用 Read 打开截图看画面）对照 spec 的 e2e intent 判。
# 统一证据落点为 docs/e2e-results/<pr>/，并入 Spec-0044 原来指向 docs/evidence/** 的「无证据=REWORK」
# （消除两套证据目录）。延伸自 Spec-0048/T1：宣称实现了自动化执行/门控却只交付骨架 → 同样 REWORK。
# 条件式触发（前端/交互类才查），纯内部重构不误伤。只挂 code 闸（rfc 闸的把关在 _RFC_E2E_RUBRIC_*）。
_EVIDENCE_RUBRIC = (
    "【运行时行为：读证据亲眼判】本 PR 若属前端/交互类改动，独立 executor 会照 spec 的 e2e 测法真跑"
    "系统，把证据（result.md + 截图 / 日志）固化在 `docs/e2e-results/{pr_number}/`。请**读这些证据判"
    "运行时行为是否达成 spec 的 e2e intent**：\n"
    "- 用 `Read` 打开 `docs/e2e-results/{pr_number}/` 下的截图（PNG）**亲眼看画面**、读 result.md 声明；\n"
    "- executor 声明达成（OUTCOME: PASSED）但截图/日志与 intent 对不上、或避重就轻（把「筛选生效」"
    "换成「页面不崩」）→ 判 REWORK，写明「证据与意图对不上」；\n"
    "- 证据目录缺 result.md、或 UI 改动却既无截图也无「环境不具备」的诚实说明 → 判 REWORK，写明"
    "「缺运行时证据」；\n"
    "- 若 executor 如实报告「本环境无浏览器工具、无法真跑 UI」→ **软判**：不因缺截图 REWORK，就着"
    "拿得到的证据（离线断言 / 日志 / 代码）判即可。\n"
    "延伸——宣称实现了自动化执行/门控能力（executor 真跑 / 自动提交证据 / UI 截图）却无真实产物或"
    "集成证据 → REWORK：例如声称 executor 真跑却无 result.md、声称自动提交证据却无 commit 证据、"
    "声称支持 UI 截图却无截图也无诚实说明——同样判 REWORK。\n"
)
# Spec-0048/T1：自动化完整性硬规则——专治「架构骨架/模块存在/门控位置对/单测绿」冒充完整实现。仅当
# PR 声称新增/改造自动化执行链路时触发（条件式，与 _EVIDENCE_RUBRIC 同构，纯静态/重构不查、不误伤）；
# 触发时逐条追问闭环（触发点/被调用/artifact 自动产出/正·反例/集成而非局部），任一缺失即 REWORK。
_AUTOMATION_INTEGRITY_RUBRIC = (
    "【自动化完整性硬规则】仅当本 PR 声称新增/改造了自动化执行链路（executor / agent / runtime "
    "validation、e2e / evidence gate / runbook、自动 merge · hold gate、GitHub issue · PR 自动化，"
    "或任何『自动跑 · 自动提交 · 自动门控』的能力）时才触发本检查——纯静态改动 / 库函数 / 重构 / "
    "文档不查、不误伤。触发时逐条核对闭环，任一缺失即判 REWORK：\n"
    "1. 主流程触发点：既有链路从哪个现有函数/状态分支真的会走到这个新能力？"
    "（『有个新模块』≠『主流程会走到它』）\n"
    "2. 被调用证据：新 executor/agent 是否真的被调用，还是只定义了模块却没接线（dead / unwired）？\n"
    "3. artifact 自动产生并 commit：声称生成的产物（result.md / log / screenshot / PR comment）"
    "是否会自动产生并 commit/发送，而不是『假设它存在』？\n"
    "4. 正例·反例：有没有正例证明 PASS 放行、反例证明 FAIL 阻断？\n"
    "5. 集成路径而非局部函数：测试是否覆盖真实集成路径，而不是只测 parser/render/decision 等局部函数？\n"
    "缺完整链路证据 → REWORK，理由：只实现骨架，未证明完整链路。\n"
)
_CODE_REVIEW_TASK = (
    "你是独立的代码审核员，与作者不共享上下文。请评审 PR #{pr_number} 的代码改动。\n"
    "用 `git diff` 查看本分支相对 base 的改动并读涉及文件的完整上下文。判定：是否"
    "真的实现了对应 spec 的 Task 与验收标准、有无 tautological test / 绕过真实路径、"
    "边界与安全盲点（空输入/错误路径/注入/越权）、破坏性改动（删了在用的东西、改接口"
    "未改调用方）。不纠结风格偏好（除非违反 CLAUDE.md 明文规范）。\n"
    "【职责边界】你既判**静态**代码质量/安全/结构，**也判运行时行为**——Spec-0055 取消了独立证据闸，"
    "运行时行为验收合并进本次 code review：靠亲眼看 executor 产的证据（见下条），对照 spec 的 e2e "
    "intent 判系统真跑起来是否达成意图。\n"
    + _EVIDENCE_RUBRIC
    + _AUTOMATION_INTEGRITY_RUBRIC
    + _HISTORY_PRIMACY_RUBRIC
    + _RUBRIC_TAIL
)


# RFC-0018：无法解析裁决 token 时归一化为该占位 token，使 verdicts 与 reviewer 数等长、
# 票数渲染不丢项（疑罪从严：UNPARSED 与 REWORK/RETHINK 同属非 PASS）。
UNPARSED_VERDICT = "UNPARSED"


@dataclass(frozen=True)
class ReviewDecision:
    """RFC-0012 决策 1：N 个 reviewer 的聚合裁决。

    passed: 是否全票 PASS。
    feedback: 聚合的非 PASS 反馈（喂给 refine_rfc / iterate）；passed=True 时为空串。
    verdicts: RFC-0018 决策 3——各 reviewer 解析出的裁决 token 序列（与 N 等长，
        `None` 归一化为 `"UNPARSED"`）。默认 `()` 保证既有构造点向后兼容；编排层据此
        渲染「N 中几票 PASS」的票型回贴 PR（理念 8 可观测性）。
    """

    passed: bool
    feedback: str
    verdicts: tuple[str, ...] = ()
    # Spec-0021/T1：非 PASS 的可操作性。True = 非 PASS 且至少一个解析出的 REWORK/RETHINK
    # 带实质正文（真 REWORK，有东西可改）；False = 要么 passed，要么「评审无效」（裁决全
    # 无法解析 / 无可操作条目）。默认 False 保证既有构造点向后兼容。编排层（Spec-0021/T2）
    # 据 `not passed and not actionable` 判「评审无效」→ 不吃 round、不空转 refine/iterate。
    actionable: bool = False


def configured_reviewers() -> int:
    """RFC-0012 决策 6：从 env 读 reviewer 并发数；缺省/非法回落到 DEFAULT_REVIEWERS。

    下限 1——n<1 没有意义（至少要有一个 reviewer 给出裁决）。供编排层调 review 时传 n。
    """
    raw = os.environ.get(REVIEWERS_ENV)
    if not raw:
        return DEFAULT_REVIEWERS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_REVIEWERS
    return value if value >= 1 else DEFAULT_REVIEWERS


def review(
    *,
    backend: AgentBackend,
    work_dir: Path,
    kind: str,
    pr_number: int,
    n: int,
    history: str = "",
    ui_capable: bool = False,
) -> ReviewDecision:
    """RFC-0012 T1：以 review 任务模板调 backend.run 共 n 次（线程池并行），聚合裁决。

    kind ∈ {"rfc", "code"}：选择评 RFC 文档 vs 评代码 diff 的任务模板。
    聚合规则（决策 1）：全部解析为 PASS → passed=True；否则 passed=False，feedback 汇总
    各非 PASS（含无法解析裁决）的反馈正文。n<1 视为 1（至少一个 reviewer）。

    Spec-0052/T2：`history` = 本 PR 对话历史（历轮裁决/作者回复/人类评论，由 orchestrator 经
    agentcontext.build_agent_context 组好传入），作为每个 reviewer 的 backend.run context 送达，
    让 reviewer 不再失忆（issue #129 缺口二）。默认空串 → 既有调用/测试逐字节零回归。配套的
    `_HISTORY_PRIMACY_RUBRIC`（已拼进两模板）约束「裁决以落盘产物为准、评论仅供参考」，保留
    reviewer 独立读仓库的价值。reviewer 仍只依赖 AgentBackend + 传入字符串，不 import
    github/agentcontext（理念 10 解耦）。
    """
    task = _task_for(kind=kind, pr_number=pr_number, ui_capable=ui_capable)
    summaries = _run_reviewers(
        backend=backend, work_dir=work_dir, task=task, n=max(1, n), history=history
    )
    # RFC-0018 决策 3：把解析出的裁决 token 全程保留（None→UNPARSED），既供聚合判定，
    # 也作为 ReviewDecision.verdicts 暴露给编排层渲染票型（不再聚合后即丢弃）。
    parsed = [_parse_verdict(summary=s) for s in summaries]
    # Spec-0021/T1：对解析为 UNPARSED（None）的 reviewer 单次重跑——截断是随机的，重跑有
    # 相当概率拿到可解析裁决（命中 issue #63 期望 2「可重试一次」）。只重 UNPARSED 项、且仅
    # 一次（不无限）；PASS/REWORK/RETHINK 已是确定裁决不重跑。无限重试属编排层（T2）职责，分层。
    for i, verdict in enumerate(parsed):
        if verdict is None:
            retried = backend.run(work_dir=work_dir, task=task, context=history).summary
            summaries[i] = retried
            parsed[i] = _parse_verdict(summary=retried)
    verdicts = tuple(v or UNPARSED_VERDICT for v in parsed)
    if verdicts and all(v == "PASS" for v in verdicts):
        return ReviewDecision(passed=True, feedback="", verdicts=verdicts, actionable=False)
    # Spec-0021/T1：区分「真 REWORK」与「评审无效」——存在至少一个解析出的 REWORK/RETHINK 且
    # 其对应 summary 有实质正文 → actionable（有东西可改）；否则（全 UNPARSED / 无正文）为评审无效。
    actionable = any(
        verdict in ("REWORK", "RETHINK") and summaries[i].strip()
        for i, verdict in enumerate(verdicts)
    )
    # 非 PASS（含 REWORK/RETHINK/无法解析）的摘要净化后汇总为反馈，喂回 refine/iterate。
    # Spec-0041/T3：喂人前先 _distill_feedback 剥掉 reviewer 内心独白/scratchpad（只作用于展示
    # 用的 feedback，不改 verdicts/actionable 判定）；净化后为空回落既有占位（疑罪从严）。
    parts = [
        (
            _distill_feedback(summary=summary)
            or "（reviewer 未给出可解析的裁决，按疑罪从严视为未通过）"
        )
        for summary, verdict in zip(summaries, verdicts, strict=True)
        if verdict != "PASS"
    ]
    return ReviewDecision(
        passed=False,
        feedback="\n\n---\n\n".join(parts),
        verdicts=verdicts,
        actionable=actionable,
    )


# RFC-0018 决策 4：kind → 评论里的中文展示名（未知 kind 原样回显，不抛错——渲染是旁路）。
# issue #53：kind 内部标识仍沿用 "rfc"（= 设计评审闸的历史名），展示名改为「Spec 文档」。
_KIND_LABELS = {"rfc": "Spec 文档", "code": "代码"}


def render_decision(*, decision: ReviewDecision, kind: str) -> str:
    """RFC-0018 决策 4：把裁决渲染成 PR 评论 Markdown 正文（纯函数，不含签名）。

    含：kind（rfc/code 中文化）、整体 PASS/REWORK、票数（N 中几票 PASS）；`passed=False`
    时附聚合 feedback 摘要。纯字符串函数、无副作用、不依赖 github/identity——保持 reviewer
    模块「只依赖 AgentBackend 协议」的解耦定位（理念 10），与 e2e.render_result 同构。
    """
    label = _KIND_LABELS.get(kind, kind)
    total = len(decision.verdicts)
    pass_count = sum(1 for v in decision.verdicts if v == "PASS")
    # Spec-0021/T1：把「评审无效」与「REWORK」分开渲染，让盯 PR 的人一眼看出是「评审坏了
    # （裁决无法解析，reviewer 输出疑被截断）」而非「代码被打回」（理念 8 可观测性）。
    if decision.passed:
        overall = "✅ PASS"
    elif decision.actionable:
        overall = "❌ REWORK"
    else:
        overall = "⚠️ 评审无效（裁决无法解析，reviewer 输出疑被截断）"
    lines = [
        "## 评审闸裁决",
        f"- 类型：{label}",
        f"- 裁决：{overall}",
        f"- 票数：{total} 票中 {pass_count} 票 PASS",
    ]
    # 暴露逐 reviewer 票型，使 passed=False 时人能看清是 REWORK 还是 RETHINK/UNPARSED。
    if decision.verdicts:
        lines.append(f"- 票型：{' / '.join(decision.verdicts)}")
    # 非 PASS 时附聚合反馈摘要，让人盯 PR 即知卡在哪条验证标准（理念 8）。
    if not decision.passed and decision.feedback:
        lines.append("- 反馈摘要：")
        lines.append("```")
        lines.append(decision.feedback)
        lines.append("```")
    return "\n".join(lines)


# Spec-0047/T1：裁决抬头（render_decision 渲染的稳定锚点）——提取与去重都以它定位裁决块。
_DECISION_HEADER = "## 评审闸裁决"
_KIND_PREFIX = "- 类型："
_VERDICT_PREFIX = "- 裁决："
_FEEDBACK_PREFIX = "- 反馈摘要："
_FENCE = "```"


@dataclass(frozen=True)
class DecisionContent:
    """Spec-0047/T1：一条裁决评论的「去重身份」——结论 + 规范化反馈。

    与 render_decision 互为正逆：render 把 ReviewDecision 渲染成评论 markdown，本类是从
    那段 markdown（可能含 identity 追加的署名尾巴）反解出的匹配特征。orchestrator 只消费
    本 dataclass 做去重，不再自己 splitlines 抠 reviewer 文案（理念 10 解耦）。

    kind_line: `- 类型：代码` / `- 类型：Spec 文档`——区分 rfc / code 两道闸。
    verdict_line: `- 裁决：❌ REWORK` / `✅ PASS` / `⚠️ 评审无效…`——裁决结论。
    feedback_norm: 「反馈摘要」块的规范化正文（逐行 strip、丢空行、\\n 连接）；
        PASS / 无反馈（render 不产「反馈摘要」块）时为 ""。
    """

    kind_line: str
    verdict_line: str
    feedback_norm: str


def extract_decision_content(*, body: str) -> DecisionContent | None:
    """Spec-0047/T1：从一段评论 markdown 里解析出裁决的去重身份，非裁决评论 → None。

    与 render_decision 互为正逆（纯函数、无副作用、不依赖 github/identity）。以稳定抬头
    `## 评审闸裁决` 为锚：抬头缺失 → 非裁决评论 → None。抬头之后取首个 `- 类型：` / `- 裁决：`
    两行；「反馈摘要」= `- 反馈摘要：` 之后 render 外层围栏（首个 ``` 到**最后一个** ```）之间的
    正文，逐行 strip、丢空行、`\\n` 连接归一化（whitespace/换行不敏感，避免仅缩进/空行漂移就误判
    「不同」）。取到最后一个 fence 为止，故 feedback 正文内部的代码围栏被完整纳入（不再被误当闭合
    而截断，见 `_extract_feedback_norm` issue #116 修正），而 identity 追加的无围栏 HTML 注释署名
    天然落在末个 fence 之外被排除；PASS（render 不产「反馈摘要」块）→ feedback_norm == ""。
    缺类型/裁决行 → None。
    """
    lines = body.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if line.strip() == _DECISION_HEADER),
        None,
    )
    if header_idx is None:
        return None
    after = lines[header_idx + 1 :]
    kind_line = next((line for line in after if line.startswith(_KIND_PREFIX)), None)
    verdict_line = next((line for line in after if line.startswith(_VERDICT_PREFIX)), None)
    if kind_line is None or verdict_line is None:
        return None
    return DecisionContent(
        kind_line=kind_line,
        verdict_line=verdict_line,
        feedback_norm=_extract_feedback_norm(lines=after),
    )


def _extract_feedback_norm(*, lines: list[str]) -> str:
    """取「反馈摘要」块（`- 反馈摘要：` 后 render 的**外层**围栏之间）的规范化正文；无块 → ""。

    逐行 strip、丢空行、`\\n` 连接——使措辞未变、仅缩进/空行漂移的两段反馈归一化后相等。

    issue #116 / PR #117 修正：render_decision（reviewer.py:220-222）把 `decision.feedback`
    原样塞进一对围栏，而 feedback 正文本身可能含代码围栏行（`_distill_feedback` 不剥离 ``` 行，
    reviewer 输出的裸 ``` 会原样保留）。旧实现「首个 ``` 到**第一个**闭合 ``` 为止」会把 feedback
    内部的围栏误当成外层闭合围栏，截断甚至清空反馈——两条理由不同但都以 fenced code 开头的 REWORK
    会被误判 feedback_norm 相等而静默抑制，正是 issue #116 要修的失败模式。改为「首个 ``` 到**最后
    一个** ``` 之间」为块体：render 恒把反馈裹在外层围栏里，其后 identity 署名是无围栏的 HTML 注释
    （identity.sign），故末个 ``` 必是 render 的外层闭合围栏，内部围栏被完整纳入正文、不再截断。
    （注：不能改用「剥掉署名尾巴」——多 reviewer 反馈内部以 `\\n\\n---\\n\\n` 连接，按 `---` 截尾
    反会误伤多段反馈；围栏定位法对 `---` 与 HTML 注释署名都免疫。）
    """
    feedback_idx = next(
        (i for i, line in enumerate(lines) if line.startswith(_FEEDBACK_PREFIX)),
        None,
    )
    if feedback_idx is None:
        return ""
    rest = lines[feedback_idx + 1 :]
    fences = [i for i, line in enumerate(rest) if line.strip() == _FENCE]
    if len(fences) < 2:
        return ""
    block = rest[fences[0] + 1 : fences[-1]]
    normalized = [stripped for line in block if (stripped := line.strip())]
    return "\n".join(normalized)


def _task_for(*, kind: str, pr_number: int, ui_capable: bool) -> str:
    """按 kind 选 review 任务模板；未知 kind 抛 ValueError（防静默走错模板）。

    Spec-0055/T4：rfc 闸的 e2e 测法 rubric 据 ui_capable 分流（起草/评审同源）；code 闸不用 ui_capable。
    """
    if kind == "rfc":
        return _rfc_review_task(pr_number=pr_number, ui_capable=ui_capable)
    if kind == "code":
        return _CODE_REVIEW_TASK.format(pr_number=pr_number)
    raise ValueError(f"未知的 review kind：{kind!r}（应为 'rfc' 或 'code'）")


def _run_reviewers(
    *, backend: AgentBackend, work_dir: Path, task: str, n: int, history: str = ""
) -> list[str]:
    """并行派 n 个 reviewer，返回各自 AgentResult.summary（保持入参顺序）。

    n==1 时直接同步调用，避免无谓起线程池；n>1 用 ThreadPoolExecutor 并发——backend.run
    是子进程调用（IO 密集），线程并行即可缩短墙钟（决策 1 缺点缓解：N 默认 1）。

    Spec-0052/T2：`history`（默认空串）作为每个 reviewer 的 backend.run `context` 送达，注入本 PR
    对话历史（issue #129 缺口二）；缺省 "" 时行为逐字节同今天。
    """
    if n == 1:
        return [backend.run(work_dir=work_dir, task=task, context=history).summary]
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [
            pool.submit(backend.run, work_dir=work_dir, task=task, context=history)
            for _ in range(n)
        ]
        return [future.result().summary for future in futures]


# Spec-0041/T3：scratchpad「内心独白」句的保守启发式——第一人称过程叙述前缀。命中即视为
# reviewer 给自己看的过程记录（非给人的可操作反馈）。措辞含中英（backend 输出双语皆可能）。
_SCRATCHPAD_RE = re.compile(
    r"^\s*(?:"
    r"let me\b|let's\b|lets\b"
    r"|i'?ll\b|i will\b|i'?m going to\b|i am going to\b"
    r"|i'?ve\b|i have\b|i now have\b|i need to\b|i should\b|i can\b|i'?m\b|i am\b"
    r"|now i\b|okay\b|ok[,. ]|alright\b"
    r"|all \d+ tests?\b"  # 「All 32 tests pass…」式过程叙述
    r"|好[的，,]|我现在\b|我来\b|让我\b|接下来我\b"
    r")",
    re.IGNORECASE,
)
# 即便命中 scratchpad 前缀，若句中含可操作信号（文件:行号 / 裁决关键词 / 中文祈使）则保留——
# 避免把「Let me note that x.py:10 应改…」这类真反馈误删（保守：宁可漏删不可误删可操作反馈）。
_ACTIONABLE_HINT_RE = re.compile(
    r":\d+|\bVERDICT\b|\bISSUES?\b|\bNEXT\b|\bREASON\b|\bREWORK\b|\bRETHINK\b|\bbug\b"
    r"|应\b|需\b|建议\b|缺\b|错\b|漏\b|未\b",
    re.IGNORECASE,
)
# 句子切分：按换行 + 中英句末标点。保留切分符外的可操作行结构（bullet / 裁决段）不受影响。
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.。!?！？])\s+|\n")


def _distill_feedback(*, summary: str) -> str:
    """Spec-0041/T3：从 reviewer summary 剥离内心独白/scratchpad，保留可操作反馈（纯函数）。

    保守启发式：按行 + 句末标点切成句子，逐句丢弃「第一人称过程叙述」（`_SCRATCHPAD_RE` 命中）
    且不含可操作信号（`_ACTIONABLE_HINT_RE`：文件:行号 / VERDICT|ISSUES|NEXT|REWORK / 中文祈使）
    的句子；其余原样保留、按原分隔重拼。净化后为空（全是独白 / 原本就空）返回空串——由调用方
    回落既有占位。只作用于喂人的 feedback，不影响 verdicts/actionable 判定与 render_decision。
    """
    text = summary or ""
    kept: list[str] = []
    for segment in _SENTENCE_SPLIT_RE.split(text):
        sentence = segment.strip()
        if not sentence:
            continue
        if _SCRATCHPAD_RE.match(sentence) and not _ACTIONABLE_HINT_RE.search(sentence):
            continue
        kept.append(sentence)
    return "\n".join(kept)


def _parse_verdict(*, summary: str) -> str | None:
    """从 summary 解析裁决 token；无法解析返回 None（聚合时按非 PASS 处理，疑罪从严）。

    Spec-0021/T1：解析顺序「首行/首段优先 → 全文回退」。先在首个非空行找 `VERDICT:` token，
    命中即采信——避免正文里偶现的裸 "REWORK" 字样（如引用别人的评审）污染裁决（rubric 已要求
    裁决置于首行）。首段无果再回退到既有全文 `_VERDICT_RE` / 裸 token 匹配（向后兼容老格式 +
    漏写 `VERDICT:` 前缀）。大小写无关，统一大写返回。
    """
    text = summary or ""
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    head_match = _VERDICT_RE.search(first_line)
    if head_match:
        return head_match.group(1).upper()
    match = _VERDICT_RE.search(text) or _BARE_VERDICT_RE.search(text)
    return match.group(1).upper() if match else None
