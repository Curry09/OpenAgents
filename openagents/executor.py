"""Spec-0040/T2: executor —— 独立的运行时验证 agent（cli/api/backend 形态，Phase 1 骨架）。

重设计 e2e 的第④步（见 docs/specs/0040-e2e-runbook-driven-evidence-gate.md）：一个**独立** agent
（跑的人 ≠ 写代码的人，tautology guard 防线②）读一份定稿说明书 runbook，按其**声明的执行形态**
选工具**真起系统走真实路径**，把每步观察/输出固化进 evidence_dir，返回结构化 {outcome, form,
notes}。角色结构仿 `reviewer.review`（决策 4：与解题 agent 同 backend，不引第二套运行机制）：
以一段 executor 任务模板调既有 `AgentBackend.run`，从 `AgentResult.summary` 解析 outcome。

两条正交轴（Spec-0040 Summary）：**A 执行形态可变**——form 由 runbook 声明，executor 据此选工具；
本组（Phase 1）只落非浏览器形态 `cli`/`api`/`backend`，`ui` 浏览器形态返回 `skipped` 留 Phase 2。
**B 独立执行不变**——无论何形态都由独立 agent 真跑。

契约上**绝不抛错**（仿 `e2e.run_e2e_script`）：runbook 缺失 / 形态无法识别 / backend 抛错 一律映射
成 `failed`（+ notes 说明），并把结构化结果固化到 `evidence_dir/result.md`（⑤ 证据固化的落点，供
证据闸 `evidence_gate.review_evidence` 读；二者不互相 import，路径由 orchestrator 透传，理念 10 解耦）。

解耦：本模块只依赖 `AgentBackend` 协议 + 文件系统，不碰 git / GitHub / 编排（便于 hermetic 单测打桩
backend）。form 枚举单一真源在 `openagents.spec.schema.E2E_FORM_VALUES`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openagents.backends.base import AgentBackend
from openagents.spec.schema import E2E_FORM_VALUES

# Spec-0040/T2：三种 outcome——真跑通 / 真跑挂或无法验证 / 形态本组不支持（ui 留 Phase 2）。
OUTCOME_PASSED = "passed"
OUTCOME_FAILED = "failed"
OUTCOME_SKIPPED = "skipped"

# 本组（Phase 1）落地的非浏览器运行时形态；ui 单列走 skipped。
_RUNTIME_FORMS = ("cli", "api", "backend")
_UI_FORM = "ui"

# ui 形态跳过时的 notes——明确标注留 Phase 2（见 Spec-0040 Future possibilities：接 browser MCP）。
_UI_PHASE2_NOTE = (
    "ui 浏览器形态本组（Phase 1）不实现，留待 Phase 2 接 browser MCP"
    "（Playwright / Chrome DevTools）后支持前端 e2e。"
)
_NO_RUNBOOK_NOTE = "runbook 缺失或不可读，无法据其真跑系统 → 判 failed（无证据即未达成）。"
_NO_FORM_NOTE = "runbook 未声明可识别的执行形态（应为 ui/api/cli/backend 之一）→ 判 failed（形态未知无从选工具）。"

# runbook 里执行形态的声明模式：匹配「执行形态：cli」/「form: cli」/「形态 cli」等，取首个命中。
# form 关键字大小写无关；四种形态词直接来自 E2E_FORM_VALUES（单一真源）。
_FORM_RE = re.compile(
    r"(?:形态|form)\s*[:：]?\s*`?\s*(" + "|".join(E2E_FORM_VALUES) + r")\b",
    re.IGNORECASE,
)
# 从 agent summary 解析运行结论：显式 `OUTCOME: PASSED|FAILED` 优先，裸 token 回退。
# 无法解析 → 疑罪从严判 failed（没确认跑通就不算通过，仿 reviewer 对无法解析裁决的处理）。
_OUTCOME_RE = re.compile(r"OUTCOME:\s*(PASSED|FAILED)\b", re.IGNORECASE)
_BARE_OUTCOME_RE = re.compile(r"\b(PASSED|FAILED)\b", re.IGNORECASE)

# evidence_dir 内结构化证据文件名（⑤ 证据固化的落点）。executor 写、证据闸读——二者不互相 import，
# 各自持有这个文件名字面量（filename 级重复优于模块耦合，理念 10）。
RESULT_FILENAME = "result.md"

# executor 任务模板：要求独立 agent 读 runbook、按形态真跑系统、把观察写进 evidence_dir、
# 末行给出 `OUTCOME: PASSED|FAILED`（结构化输出便于解析，仿 reviewer 的裁决前置约定）。
_EXECUTOR_TASK = (
    "你是独立的运行时验证 executor（与写这份代码的人不共享上下文），负责给 PR #{pr_number} 真跑系统。\n"
    "读说明书 runbook：`{runbook_path}`（它声明了执行形态 form={form}）。\n"
    "按形态 **{form}** 选工具，在工作目录内**真起系统、走真实路径**照 runbook 逐步执行、交互并断言：\n"
    "- cli：在 worktree 里真执行命令，核对退出码 / stdout / stderr 是否符合 runbook 的判定点；\n"
    "- api：对起好的服务真发 HTTP 请求，核对状态码 / body；\n"
    "- backend：跑真实集成路径（非 mock 打桩自证）。\n"
    "把**每一步的命令、观察、输出**写进证据目录：`{evidence_dir}`（日志文件等，durable 可被证据闸读）。\n"
    "禁止把 runbook 的意图偷换成更弱的检查（如把「无 origin 报错」换成「跑 --help 不崩」）。\n"
    "【硬性格式】回复最后一行必须是 `OUTCOME: PASSED`（系统按 runbook 真跑通、验收行为达成）"
    "或 `OUTCOME: FAILED`（跑不通 / 验收行为未达成 / 无法真跑），在此之前写清你跑了什么、看到了什么。"
)


@dataclass(frozen=True)
class ExecutorResult:
    """Spec-0040/T2：一次 executor 运行的结构化结果。

    outcome: "passed" | "failed" | "skipped"（ui 形态本组跳过）。
    form: runbook 声明的执行形态（无法识别时为 ""）。
    notes: agent 的运行说明 / 降级原因（喂给证据闸和人看）。
    """

    outcome: str
    form: str
    notes: str


def run_executor(
    *,
    backend: AgentBackend,
    work_dir: Path,
    runbook_path: Path,
    evidence_dir: Path,
    pr_number: int,
) -> ExecutorResult:
    """Spec-0040/T2：读 runbook → 按形态派独立 agent 真跑系统 → 固化证据 → 返回结构化结果。

    绝不抛错（契约，仿 e2e.run_e2e_script）：runbook 缺失 / 形态无法识别 / backend 抛错 都映射成
    `failed`（+ notes）。无论何 outcome 都把结构化结果写进 `evidence_dir/result.md`（⑤ 证据固化的
    落点，证据闸据此判 PASS/FAIL）。form=ui 返回 `skipped`（Phase 2 留白，不派 agent）。
    """
    form = ""
    try:
        runbook = _read_runbook(runbook_path=runbook_path)
        if runbook is None:
            result = ExecutorResult(outcome=OUTCOME_FAILED, form="", notes=_NO_RUNBOOK_NOTE)
        else:
            form = _parse_form(runbook=runbook)
            result = _run_by_form(
                backend=backend,
                work_dir=work_dir,
                runbook_path=runbook_path,
                evidence_dir=evidence_dir,
                pr_number=pr_number,
                form=form,
            )
    except Exception as error:  # noqa: BLE001 — 契约绝不抛错：任何异常映射成 failed（仿 run_e2e_script）
        result = ExecutorResult(
            outcome=OUTCOME_FAILED, form=form, notes=f"executor 运行异常，判 failed：{error}"
        )
    _write_evidence(evidence_dir=evidence_dir, result=result, pr_number=pr_number)
    return result


def _run_by_form(
    *,
    backend: AgentBackend,
    work_dir: Path,
    runbook_path: Path,
    evidence_dir: Path,
    pr_number: int,
    form: str,
) -> ExecutorResult:
    """按 form 分派：ui→skipped（Phase 2）；cli/api/backend→派 agent 真跑；未知→failed。"""
    if form == _UI_FORM:
        return ExecutorResult(outcome=OUTCOME_SKIPPED, form=form, notes=_UI_PHASE2_NOTE)
    if form not in _RUNTIME_FORMS:
        return ExecutorResult(outcome=OUTCOME_FAILED, form=form, notes=_NO_FORM_NOTE)
    task = _EXECUTOR_TASK.format(
        pr_number=pr_number,
        runbook_path=runbook_path,
        evidence_dir=evidence_dir,
        form=form,
    )
    summary = backend.run(work_dir=work_dir, task=task, context="").summary
    return ExecutorResult(outcome=_parse_outcome(summary=summary), form=form, notes=summary or "")


def _read_runbook(*, runbook_path: Path) -> str | None:
    """读 runbook 文本；不是常规文件 / 读失败 → None（映射成 failed，不抛）。"""
    if not runbook_path.is_file():
        return None
    try:
        return runbook_path.read_text(encoding="utf-8")
    except OSError:
        return None


def _parse_form(*, runbook: str) -> str:
    """从 runbook 文本解析声明的执行形态（小写）；无法识别返回 ""（映射成 failed）。"""
    match = _FORM_RE.search(runbook)
    return match.group(1).lower() if match else ""


def _parse_outcome(*, summary: str) -> str:
    """从 agent summary 解析运行结论；PASSED→passed，其余（含无法解析）→failed（疑罪从严）。"""
    text = summary or ""
    match = _OUTCOME_RE.search(text) or _BARE_OUTCOME_RE.search(text)
    if match and match.group(1).upper() == "PASSED":
        return OUTCOME_PASSED
    return OUTCOME_FAILED


def _write_evidence(*, evidence_dir: Path, result: ExecutorResult, pr_number: int) -> None:
    """把结构化结果固化到 evidence_dir/result.md（⑤ 证据固化）；目录不存在则创建。

    尽力而为但**不吞写失败之外的语义**：目录创建 / 写入用标准库，失败会抛 OSError——由上层
    run_executor 的 try 兜住（映射成 failed 前已 return，此处失败极罕见）。这里保持简单直接。
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    body = _render_evidence(result=result, pr_number=pr_number)
    (evidence_dir / RESULT_FILENAME).write_text(body, encoding="utf-8")


def _render_evidence(*, result: ExecutorResult, pr_number: int) -> str:
    """渲染 result.md 正文：PR / 形态 / 结论 + agent notes（证据闸与人都读这份）。"""
    lines = [
        f"# 端到端执行证据（PR #{pr_number}）",
        "",
        f"- 执行形态：{result.form or '（未声明）'}",
        f"- 结论：{result.outcome}",
        "",
        "## executor 运行说明",
        "",
        result.notes or "（无）",
    ]
    return "\n".join(lines) + "\n"
