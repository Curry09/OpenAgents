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
    "PASS 示例：\n  VERDICT: PASS\n  REASON: <一句话说明核对的关键验证标准>\n"
    "REWORK 示例：\n  VERDICT: REWORK\n  ISSUES:\n  - <文件:行号 + 具体问题>\n  NEXT: <修复方向>\n"
)
# Spec-0040/T4：「要不要有 e2e」从代码 reviewer 上移到 RFC 闸——加一条更硬的规则：前端/交互类
# 改动的 spec 若没声明 e2e 粗规划（组级 frontmatter 的 e2e{form,intent,acceptance}，见 Spec-0040/
# T1）→ 直接 REWORK。这取代 Spec-0030/T4 挂在代码 reviewer 上的条件式 browser-e2e rubric：把「验不
# 验、验什么」的把关前移到设计闸，代码 reviewer 只管静态质量（职责收口，Spec-0040 Reference-level）。
_RFC_E2E_RUBRIC = (
    "【e2e 粗规划硬规则】若本 PR 属前端/交互类改动（新增/改动用户可见行为、CLI 交互、HTTP 接口、"
    "前端页面等），其 spec 组必须在组级 frontmatter 声明 e2e 粗规划（e2e 块含 form/intent/"
    "acceptance，承载「要不要验、验什么」）；未声明 → 判 REWORK，把「缺 e2e 粗规划」写进 ISSUES。"
    "纯文档/重构/内部非交互改动可不声明。\n"
)
_RFC_REVIEW_TASK = (
    "你是独立的 spec 审核员，与起草者不共享上下文。请评审 PR #{pr_number} 的 spec 组。\n"
    "按顺序读：CLAUDE.md（需求/设计理念）→ docs/specs/ 下本 PR 新增/改动的 spec 组"
    "（单文件 NNNN-slug.md：frontmatter 结构化源数据 + 正文各 Task 设计 prose）→ 其引用的来源。"
    "判定：设计是否对齐需求、关键决策是否"
    "有据、Task DAG 是否可独立实现且各 Task 文件清单互不重叠、是否含实现代码（spec 不应含"
    "实现代码）。\n" + _RFC_E2E_RUBRIC + _RUBRIC_TAIL
)
# Spec-0040/T4：代码 reviewer 职责收口——**只判静态代码质量/安全/结构，显式不判运行时行为**
# （运行时行为由证据闸 evidence_gate 拿证据对照 RFC 意图门控，见 Spec-0040 Reference-level）。删掉了
# Spec-0030/T4 的条件式 browser-e2e rubric（那道「要不要有 e2e」的把关已上移到 _RFC_REVIEW_TASK）。
# Spec-0044/T2：无证据=REWORK 结构化检查项——把 wind-palace PR #14 里 reviewer 手动做过的
# 「宣称验证过某产品对外行为却拿不出 tracked 证据 → 打回」固化为常驻 rubric（软约定硬化）。
# 条件式触发（仅当 PR 出现端到端/e2e/截图/已验证 UI 类措辞才查），避免误伤纯内部重构 PR。
# 与 Spec-0040 的职责收口不冲突：证据闸判「系统真跑起来是否达成意图」（运行时正确性），本 rubric
# 判「作者宣称验证过却拿不出证据」（声明诚信），两者分属不同层，故并存。
_EVIDENCE_RUBRIC = (
    "宣称验证过但无证据 → REWORK：仅当本 PR 正文/评论出现「端到端 / e2e / 截图 / 已验证 UI」"
    "类措辞（声称验证过某个产品对外行为）时才触发本检查——纯内部重构 PR（无此类措辞）不查、"
    "不误伤。触发时核对仓库里有没有对应的 tracked 证据（截图文件如 docs/evidence/** 下的图、"
    "或真实运行日志文本），且 PR 评论里有没有实跑留痕；若既无 tracked 证据、评论也无实跑留痕 → "
    "判 REWORK，理由写明「宣称验证过但无证据」。自动化测试绿 / 后端日志替代不了真 app 证据。\n"
)
_CODE_REVIEW_TASK = (
    "你是独立的代码审核员，与作者不共享上下文。请评审 PR #{pr_number} 的代码改动。\n"
    "用 `git diff` 查看本分支相对 base 的改动并读涉及文件的完整上下文。判定：是否"
    "真的实现了对应 spec 的 Task 与验收标准、有无 tautological test / 绕过真实路径、"
    "边界与安全盲点（空输入/错误路径/注入/越权）、破坏性改动（删了在用的东西、改接口"
    "未改调用方）。不纠结风格偏好（除非违反 CLAUDE.md 明文规范）。\n"
    "【职责边界】你只判**静态**代码质量/安全/结构；**运行时行为（系统真跑起来是否达成意图）"
    "由证据闸负责，你不判**——不必也不应据「有没有真跑过」下裁决。\n"
    + _EVIDENCE_RUBRIC
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
    *, backend: AgentBackend, work_dir: Path, kind: str, pr_number: int, n: int
) -> ReviewDecision:
    """RFC-0012 T1：以 review 任务模板调 backend.run 共 n 次（线程池并行），聚合裁决。

    kind ∈ {"rfc", "code"}：选择评 RFC 文档 vs 评代码 diff 的任务模板。
    聚合规则（决策 1）：全部解析为 PASS → passed=True；否则 passed=False，feedback 汇总
    各非 PASS（含无法解析裁决）的反馈正文。n<1 视为 1（至少一个 reviewer）。
    """
    task = _task_for(kind=kind, pr_number=pr_number)
    summaries = _run_reviewers(backend=backend, work_dir=work_dir, task=task, n=max(1, n))
    # RFC-0018 决策 3：把解析出的裁决 token 全程保留（None→UNPARSED），既供聚合判定，
    # 也作为 ReviewDecision.verdicts 暴露给编排层渲染票型（不再聚合后即丢弃）。
    parsed = [_parse_verdict(summary=s) for s in summaries]
    # Spec-0021/T1：对解析为 UNPARSED（None）的 reviewer 单次重跑——截断是随机的，重跑有
    # 相当概率拿到可解析裁决（命中 issue #63 期望 2「可重试一次」）。只重 UNPARSED 项、且仅
    # 一次（不无限）；PASS/REWORK/RETHINK 已是确定裁决不重跑。无限重试属编排层（T2）职责，分层。
    for i, verdict in enumerate(parsed):
        if verdict is None:
            retried = backend.run(work_dir=work_dir, task=task, context="").summary
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


def _task_for(*, kind: str, pr_number: int) -> str:
    """按 kind 选 review 任务模板；未知 kind 抛 ValueError（防静默走错模板）。"""
    if kind == "rfc":
        return _RFC_REVIEW_TASK.format(pr_number=pr_number)
    if kind == "code":
        return _CODE_REVIEW_TASK.format(pr_number=pr_number)
    raise ValueError(f"未知的 review kind：{kind!r}（应为 'rfc' 或 'code'）")


def _run_reviewers(*, backend: AgentBackend, work_dir: Path, task: str, n: int) -> list[str]:
    """并行派 n 个 reviewer，返回各自 AgentResult.summary（保持入参顺序）。

    n==1 时直接同步调用，避免无谓起线程池；n>1 用 ThreadPoolExecutor 并发——backend.run
    是子进程调用（IO 密集），线程并行即可缩短墙钟（决策 1 缺点缓解：N 默认 1）。
    """
    if n == 1:
        return [backend.run(work_dir=work_dir, task=task, context="").summary]
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [
            pool.submit(backend.run, work_dir=work_dir, task=task, context="") for _ in range(n)
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
