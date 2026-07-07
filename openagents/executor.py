"""Spec-0055/T2·T3: executor —— 独立的运行时验证 agent（单一自主 agent，无 form 分派）。

e2e v2（见 docs/specs/0055-e2e-v2-capability-aware.md，取代 Spec-0040 的 form 分派 + runbook 定稿）：
一个**独立** agent（跑的人 ≠ 写代码的人，tautology guard 防线②）拿 spec 的 **prose 测法 `method`**
（+ 一句话 `intent`）直接跑——**运行时自检手里有没有 `browser_*` 工具**：有则真开浏览器导航/交互/截图
存进 evidence_dir；无则用命令行/HTTP 等能用的方式真跑，或如实报「环境不具备、无法真跑」。把观察固化进
evidence_dir，返回结构化 {outcome, notes}。角色结构仿 `reviewer.review`（与解题 agent 同 backend，不引
第二套运行机制）：以一段 executor 任务模板调既有 `AgentBackend.run`，从 `AgentResult.summary` 解析 outcome。

**executor 只跑只报、不做门控判决**：outcome 供 messages 渲报告 + 人看；「达成没达成」的裁决由合并后的
`review_code`（reviewer 亲眼看截图 + 读声明）做（Spec-0055 机制 4/5，无独立证据闸）。

契约上**绝不抛错**：backend 抛错一律映射成 `failed`（+ notes 说明），并把结构化结果固化到
`evidence_dir/result.md`（证据落点，供 reviewer 读；截图等附件由 agent 自己落 evidence_dir）。

解耦：本模块只依赖 `AgentBackend` 协议 + 文件系统，不碰 git / GitHub / 编排（便于 hermetic 单测打桩
backend）。**Spec-0055 删掉了 form 枚举 / _parse_form / _run_by_form / ui-skipped 分支**——形态由 agent
运行时自检工具决定，不再在 Python 侧分派。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openagents.backends.base import AgentBackend

# Spec-0040/T2（Spec-0055 保留）：两种 outcome——真跑通 / 真跑挂或无法验证。ui-skipped 分支已随 form 删除。
OUTCOME_PASSED = "passed"
OUTCOME_FAILED = "failed"

# 从 agent summary 解析运行结论：显式 `OUTCOME: PASSED|FAILED` 优先，裸 token 回退。
# 无法解析 → 疑罪从严判 failed（没确认跑通就不算通过，仿 reviewer 对无法解析裁决的处理）。
_OUTCOME_RE = re.compile(r"OUTCOME:\s*(PASSED|FAILED)\b", re.IGNORECASE)
_BARE_OUTCOME_RE = re.compile(r"\b(PASSED|FAILED)\b", re.IGNORECASE)

# evidence_dir 内结构化证据文件名（证据落点）。executor 写、reviewer 读。
RESULT_FILENAME = "result.md"

# Spec-0051/T1：回执抬头（render_result 渲染的稳定锚点）——messages 收口点据此标题行去重（防刷屏）。
_REPORT_HEADER = "## 证据执行"
# outcome 中文化：给盯 PR 的人一眼看懂真跑结果（仿 reviewer 的 ✅/❌ 视觉）。
_OUTCOME_LABELS = {
    OUTCOME_PASSED: "✅ 通过",
    OUTCOME_FAILED: "❌ 未通过",
}

# Spec-0055/T3：executor 任务模板——把 spec 的 prose 测法 method + 一句话 intent 直接喂给独立 agent，
# 要求它运行时自检工具、真跑系统、把观察/截图写进 evidence_dir、末行给 `OUTCOME: PASSED|FAILED`。
# 不预设执行形态（agent 据自己手里的工具决定开不开浏览器）；不做门控判决（裁决交合并后的 review_code）。
_EXECUTOR_TASK = (
    "你是独立的运行时验证 executor（与写这份代码的人不共享上下文），负责给 PR #{pr_number} 真跑系统验证。\n"
    "\n"
    "【要验的意图（intent，不可偷换、不得弱化）】\n{intent}\n"
    "\n"
    "【怎么测（method，spec 里写的 prose 测法，照它做；精确命令/选择器由你运行时自己定）】\n{method}\n"
    "\n"
    "【运行时自检工具，据此选路】\n"
    "- 若你**有** browser_*（Playwright / Chrome DevTools）工具且 method 涉及前端：**真开浏览器**导航/"
    "交互，用 browser_take_screenshot 把关键页面状态**截图**存进证据目录。\n"
    "- 若你**没有**浏览器工具、或 method 是命令行/接口类：在工作目录里**真执行命令 / 真发 HTTP**，"
    "核对退出码 / stdout / 状态码 / body 是否符合 method 的判定点。\n"
    "- 若环境确实不具备真跑条件（如需浏览器却无工具、依赖起不来）：**如实报告**「无法真跑 + 为什么」，"
    "不要伪造证据、不要把意图偷换成更弱的检查（如把「筛选生效」换成「页面不崩」）。\n"
    "\n"
    "把**每一步的命令/操作、观察、输出、截图**写进证据目录：`{evidence_dir}`（durable，供 reviewer 亲眼看）。\n"
    "\n"
    "【硬性格式】回复最后一行必须是 `OUTCOME: PASSED`（照 method 真跑通、意图达成）或 `OUTCOME: FAILED`"
    "（跑不通 / 意图未达成 / 环境不具备无法真跑），在此之前写清你跑了什么、看到了什么、截图叫什么名。\n"
    "你只负责真跑并如实固化证据；**是否达成的最终裁决由 code review 看你的证据来判，你不做判决。**"
)


@dataclass(frozen=True)
class ExecutorResult:
    """Spec-0055/T3：一次 executor 运行的结构化结果。

    outcome: "passed" | "failed"（agent 自报的真跑结论，供 messages 渲报告；非门控判决）。
    notes: agent 的运行说明 / 降级原因（喂给 reviewer 和人看）。
    """

    outcome: str
    notes: str


def run_executor(
    *,
    backend: AgentBackend,
    work_dir: Path,
    method: str,
    evidence_dir: Path,
    pr_number: int,
    ui_intent: str,
) -> ExecutorResult:
    """Spec-0055/T3：把 spec 的 prose 测法直接喂独立 agent 真跑系统 → 固化证据 → 返回结构化结果。

    绝不抛错（契约）：backend 抛错映射成 `failed`（+ notes）。无论何 outcome 都把结构化结果写进
    `evidence_dir/result.md`（证据落点，reviewer 据此 + 截图判达成）。agent 运行时自检工具选路
    （有 browser_* 就开前端截图、没有就命令行/HTTP、都不行就如实降级），executor 不在 Python 侧分派形态。
    """
    try:
        task = _EXECUTOR_TASK.format(
            pr_number=pr_number,
            intent=ui_intent,
            method=method,
            evidence_dir=evidence_dir,
        )
        summary = backend.run(work_dir=work_dir, task=task, context="").summary
        result = ExecutorResult(outcome=_parse_outcome(summary=summary), notes=summary or "")
    except Exception as error:  # noqa: BLE001 — 契约绝不抛错：任何异常映射成 failed
        result = ExecutorResult(
            outcome=OUTCOME_FAILED, notes=f"executor 运行异常，判 failed：{error}"
        )
    _write_evidence(evidence_dir=evidence_dir, result=result, pr_number=pr_number)
    return result


def _parse_outcome(*, summary: str) -> str:
    """从 agent summary 解析运行结论；PASSED→passed，其余（含无法解析）→failed（疑罪从严）。"""
    text = summary or ""
    match = _OUTCOME_RE.search(text) or _BARE_OUTCOME_RE.search(text)
    if match and match.group(1).upper() == "PASSED":
        return OUTCOME_PASSED
    return OUTCOME_FAILED


def render_result(*, result: ExecutorResult) -> str:
    """Spec-0051/T1（Spec-0055 去 form）：把一次 executor 真跑结果渲染成 PR 回执 Markdown 正文。

    以稳定抬头 `## 证据执行` 开头，渲 `result.outcome`（中文化）/ `result.notes`（非空时附代码块）。
    纯字符串函数、无副作用、不 import github/identity——保持 executor 解耦定位（理念 10）；发评论收口在
    messages（Spec-0051/T5）。
    """
    outcome = _OUTCOME_LABELS.get(result.outcome, result.outcome)
    lines = [
        _REPORT_HEADER,
        f"- 结论：{outcome}",
    ]
    if result.notes.strip():
        lines.append("- 运行说明：")
        lines.append("```")
        lines.append(result.notes)
        lines.append("```")
    return "\n".join(lines)


def _render_evidence(*, result: ExecutorResult, pr_number: int) -> str:
    """渲染 result.md 正文：PR / 结论 + agent notes（reviewer 与人都读这份，配 evidence_dir 里的截图）。"""
    lines = [
        f"# 端到端执行证据（PR #{pr_number}）",
        "",
        f"- 结论：{result.outcome}",
        "",
        "## executor 运行说明",
        "",
        result.notes or "（无）",
    ]
    return "\n".join(lines) + "\n"


def _write_evidence(*, evidence_dir: Path, result: ExecutorResult, pr_number: int) -> None:
    """把结构化结果固化到 evidence_dir/result.md（证据落点）；目录不存在则创建。

    在 run_executor 的 try/except **之外**被调用（好让正常路径与异常路径的 result 都尽力固化），
    因此本函数**自身绝不抛错**（契约「run_executor 绝不抛错」的一部分）：mkdir / write_text 失败一律吞掉。
    outcome 已在返回值里，reviewer 读不到文件时按缺证据处理，无需靠异常传播。
    """
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        body = _render_evidence(result=result, pr_number=pr_number)
        (evidence_dir / RESULT_FILENAME).write_text(body, encoding="utf-8")
    except OSError:  # 尽力而为：写失败不破坏「run_executor 绝不抛错」契约
        pass
