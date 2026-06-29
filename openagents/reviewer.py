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
_RFC_REVIEW_TASK = (
    "你是独立的 spec 审核员，与起草者不共享上下文。请评审 PR #{pr_number} 的 spec 组。\n"
    "按顺序读：CLAUDE.md（需求/设计理念）→ docs/specs/ 下本 PR 新增/改动的 spec 组"
    "（单文件 NNNN-slug.md：frontmatter 结构化源数据 + 正文各 Task 设计 prose）→ 其引用的来源。"
    "判定：设计是否对齐需求、关键决策是否"
    "有据、Task DAG 是否可独立实现且各 Task 文件清单互不重叠、是否含实现代码（spec 不应含"
    "实现代码）。\n" + _RUBRIC_TAIL
)
# Spec-0030/T4：条件式 browser-e2e 方法论 rubric——若被评为前端改动且作者具备浏览器工具，
# 检查是否优先设计了浏览器 e2e 而非仅声明脚本。措辞为条件式（由 reviewer 自检自己的工具），
# 不做「OpenAgents 检测到你有浏览器」式宣告；落 in-code rubric（reviewer.py）而非后端适配器。
_BROWSER_E2E_RUBRIC = (
    "若被评 PR 是前端改动且作者具备浏览器工具（如 Playwright / Chrome DevTools MCP），"
    "检查是否优先设计了基于浏览器的前端 e2e（导航 / 交互 / 截图 / 断言）而非仅声明 shell "
    "脚本或跳过；是否具备由你自检自己的工具列表决定。\n"
)
_CODE_REVIEW_TASK = (
    "你是独立的代码审核员，与作者不共享上下文。请评审 PR #{pr_number} 的代码改动。\n"
    "用 `git diff` 查看本分支相对 base 的改动并读涉及文件的完整上下文。判定：是否"
    "真的实现了对应 spec 的 Task 与验收标准、有无 tautological test / 绕过真实路径、"
    "边界与安全盲点（空输入/错误路径/注入/越权）、破坏性改动（删了在用的东西、改接口"
    "未改调用方）。不纠结风格偏好（除非违反 CLAUDE.md 明文规范）。\n"
    + _BROWSER_E2E_RUBRIC
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
    # 非 PASS（含 REWORK/RETHINK/无法解析）的摘要原文汇总为反馈，喂回 refine/iterate。
    parts = [
        (summary.strip() or "（reviewer 未给出可解析的裁决，按疑罪从严视为未通过）")
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
