"""Spec-0040/T3: 证据固化落点约定 + 证据闸 reviewer（拿 RFC 意图对照证据门控合并）。

重设计 e2e 的第⑤⑥步（见 docs/specs/0040-e2e-runbook-driven-evidence-gate.md）：executor（T2）把真跑
系统的证据固化进 `docs/e2e-results/<pr>/`；本模块给出**该目录的路径约定单一来源**（`evidence_dir_for`）
并实现**证据闸** `review_evidence`——一个独立 reviewer agent 拿「**RFC 批准的意图**」对照「**实际证据**」，
判是否**真达成 / 避重就轻**，产出 `{passed, feedback}` 门控合并（PASS 放行、FAIL 走 iterate 回去改）。

tautology guard 防线③落此（Spec-0040 Reference-level）：runbook 即便被实现者写宽松，只要证据对不上
RFC 意图，证据闸仍判 FAIL——「意图在 RFC 锁死 + executor 独立跑 + 证据 reviewer 独立核对」三道防线
共同防「自定说明书自己过」。**证据缺失 = 未达成**：无 result.md 即硬判 FAIL（无需派 agent）。

角色结构镜像 `reviewer.review` / `ReviewDecision`（决策 4：同 backend、不引第二套运行机制）：以证据闸
任务模板调 `AgentBackend.run`，从 `AgentResult.summary` 解析裁决。解耦（理念 10）：只依赖 `AgentBackend`
+ 文件系统，不 import executor / orchestrator / github；evidence_dir 路径由 orchestrator 计算后透传。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openagents.backends.base import AgentBackend

# 证据落点约定（单一来源）：docs/e2e-results/<pr>/。orchestrator 计算 worktree/<此路径> 后透传给
# executor（写证据）与本模块（读证据），二者不互相 import（理念 10 解耦）。
_EVIDENCE_ROOT = Path("docs") / "e2e-results"

# evidence_dir 内结构化证据文件名——executor 写、证据闸读。二者不互相 import，各持这个字面量
# （filename 级重复优于模块耦合，理念 10；与 executor.RESULT_FILENAME 保持一致）。
RESULT_FILENAME = "result.md"

# 证据缺失时的硬 FAIL 反馈（无 result.md = executor 没产出证据 = 未达成，tautology guard 防线③）。
_MISSING_EVIDENCE_FEEDBACK = f"证据缺失：{RESULT_FILENAME} 不存在或不可读，无从证明 RFC 意图达成 → 判 FAIL（无证据即未达成）。"
# 裁决无法解析时的兜底反馈（疑罪从严：解析不出 PASS 即 FAIL）。
_UNPARSED_FEEDBACK = "证据闸未给出可解析的裁决（疑罪从严视为未达成，请重跑或补齐证据）。"

# 从证据闸 agent summary 解析裁决：显式 `VERDICT: PASS|FAIL` 优先，裸 token 回退；无法解析 → FAIL。
_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL)\b", re.IGNORECASE)
_BARE_VERDICT_RE = re.compile(r"\b(PASS|FAIL)\b", re.IGNORECASE)

# 证据闸任务模板：独立 reviewer 拿 RFC 批准意图对照 evidence_dir 的证据判达成与否（tautology guard
# 防线③）。裁决前置（仿 reviewer）：第一行 VERDICT，长回复被截断丢的是尾部论证而非裁决。
_EVIDENCE_REVIEW_TASK = (
    "你是独立的证据审核员（证据闸），负责给 PR #{pr_number} 判「e2e 是否真达成 RFC 意图」。\n"
    "【RFC 批准的意图（不可偷换）】\n{intent}\n\n"
    "【实际证据】读证据目录里的 `{result_path}`（executor 真跑系统固化的观察/输出），"
    "如有随附 *.log / 截图一并核对。\n"
    "判定：证据是否**真达成**上述每一条意图 / 验收行为？警惕**避重就轻**——runbook 或证据把强意图"
    "偷换成更弱的检查（如把「无 origin 报错」换成「跑 --help 不崩」）一律判未达成。证据缺失、与意图"
    "不符、只覆盖了部分验收行为 → 都判 FAIL。\n"
    "【硬性格式】回复第一行必须是 `VERDICT: PASS`（证据真达成全部意图）或 `VERDICT: FAIL`"
    "（未达成 / 避重就轻 / 证据不足），在此之前不写别的；FAIL 时在裁决行之后逐条列出**哪条验收行为"
    "没达成 / 哪里避重就轻**（这段会喂回 iterate 让作者改）。"
)


@dataclass(frozen=True)
class EvidenceDecision:
    """Spec-0040/T3：证据闸裁决（结构镜像 reviewer.ReviewDecision）。

    passed: 证据是否真达成 RFC 意图（门控合并：True 放行、False 走 iterate 回去改）。
    feedback: passed=False 时汇总「哪条验收行为没达成 / 避重就轻」，喂给 iterate(reason="e2e")；
        passed=True 时为空串。
    """

    passed: bool
    feedback: str


# Spec-0050/T2：判决回执抬头（render_decision 渲染的稳定锚点）——messages 收口点据此标题行去重。
_DECISION_HEADER = "## 证据闸判决"


def render_decision(*, decision: EvidenceDecision) -> str:
    """Spec-0050/T2：把证据闸裁决渲染成 PR 回执 Markdown 正文（纯函数，不含签名）。

    仿 `reviewer.render_decision`：以稳定抬头 `## 证据闸判决` 开头，渲 `decision.passed`（✅/❌）+
    `decision.feedback`（FAIL 且非空时附代码块，喂人看清「哪条验收行为没达成」）。PASS 时不含
    feedback 块（render 恒不产反馈块 → 天然与 reviewer PASS 同构）。纯字符串、无副作用、不 import
    identity/github——保持 evidence_gate「只依赖 AgentBackend + 文件系统、只返结构化结果」（理念 10）。
    """
    verdict = "✅ PASS" if decision.passed else "❌ FAIL"
    lines = [_DECISION_HEADER, f"- 裁决：{verdict}"]
    if not decision.passed and decision.feedback.strip():
        lines.append("- 反馈：")
        lines.append("```")
        lines.append(decision.feedback)
        lines.append("```")
    return "\n".join(lines)


def evidence_dir_for(*, pr_number: int) -> Path:
    """Spec-0040/T3：给出 PR 的证据落点相对路径 `docs/e2e-results/<pr>/`（路径约定单一来源）。

    返回相对路径——由 orchestrator 拼到 worktree 下透传给 executor / 证据闸（二者不互相 import，
    保持解耦，理念 10）。例：pr=12 → docs/e2e-results/12。
    """
    return _EVIDENCE_ROOT / str(pr_number)


def review_evidence(
    *,
    backend: AgentBackend,
    work_dir: Path,
    intent: str,
    evidence_dir: Path,
    pr_number: int,
) -> EvidenceDecision:
    """Spec-0040/T3：拿 RFC 意图对照 evidence_dir 的证据判 PASS/FAIL（门控合并）。

    证据缺失（无 result.md）→ 直接 FAIL（无需派 agent，无证据即未达成，tautology guard 防线③）；
    证据在 → 派独立证据闸 agent 核对意图与证据，解析裁决。绝不抛错：任何异常映射成 FAIL（+ feedback），
    与 reviewer / executor 的「旁路绝不阻断」契约一致——门控不因抖动误放行。
    """
    try:
        result_file = evidence_dir / RESULT_FILENAME
        if not result_file.is_file():
            return EvidenceDecision(passed=False, feedback=_MISSING_EVIDENCE_FEEDBACK)
        task = _EVIDENCE_REVIEW_TASK.format(
            pr_number=pr_number, intent=intent, result_path=result_file
        )
        summary = backend.run(work_dir=work_dir, task=task, context="").summary
        return _decide(summary=summary)
    except Exception as error:  # noqa: BLE001 — 门控绝不因异常误放行：任何异常判 FAIL
        return EvidenceDecision(passed=False, feedback=f"证据闸运行异常，判 FAIL：{error}")


def _decide(*, summary: str) -> EvidenceDecision:
    """从证据闸 agent summary 解析裁决：PASS→passed；FAIL/无法解析→passed=False + feedback。"""
    verdict = _parse_verdict(summary=summary)
    if verdict == "PASS":
        return EvidenceDecision(passed=True, feedback="")
    # FAIL / 无法解析：feedback 取 agent 正文（含「哪条没达成」），空则给兜底提示。
    feedback = (summary or "").strip() or _UNPARSED_FEEDBACK
    return EvidenceDecision(passed=False, feedback=feedback)


def _parse_verdict(*, summary: str) -> str | None:
    """解析裁决 token；`VERDICT: PASS|FAIL` 优先，裸 token 回退；无法解析返回 None（→ FAIL）。"""
    text = summary or ""
    match = _VERDICT_RE.search(text) or _BARE_VERDICT_RE.search(text)
    return match.group(1).upper() if match else None
