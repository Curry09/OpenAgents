#!/usr/bin/env bash
# Spec-0039 端到端测试启动脚本：说明书驱动 + 独立执行 + 证据评审门控（Phase 1 骨架）hermetic 闭环。
#
# 本组把 e2e 从「实现者顺手写脚本、implement 里一次性跑、贴条不门控」升级为一条 merge 前的门控流水线：
# spec 声明 e2e 意图 → 代码写完定稿 runbook → 独立 executor 按形态（cli/api/backend）真跑系统产出证据
# → 证据闸 reviewer 拿 RFC 意图对照证据门控合并（PASS 放行、FAIL 走 iterate(reason=e2e)、攒满 K 挂起）。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端**：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 spec e2e 字段/validate
#      （test_spec_*）、executor（test_executor）、证据闸（test_evidence_gate）、reviewer 职责收口
#      （test_reviewer）、编排接线（test_orchestrator / test_messages）的单测。
#   2) 离线闭环演练（默认执行）—— 用 fake backend 驱动真实 executor + evidence_gate 管线，dogfood 本组
#      自身 e2e 粗规划的三条验收行为：① cli runbook→executor 真跑并把证据落进 docs/e2e-results/<pr>/；
#      ② 「意图未达成」证据→证据闸判 FAIL；③ 「达成」证据→证据闸判 PASS。
#
# 用法：
#   bash scripts/e2e-spec-0039-runbook-driven-evidence-gate.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闭环演练：executor 真跑 + 证据闸门控（fake backend，真实管线）"
uv run --extra dev python - <<'PY'
# Spec-0039/T5：hermetic 演练——不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端。
import tempfile
from pathlib import Path

from openagents import evidence_gate, executor
from openagents.backends.base import AgentResult


class _Backend:
    """fake backend：按预设 summary 回应（executor / 证据闸都从 summary 解析裁决）。"""

    name = "fake"

    def __init__(self, *, summary):
        self._summary = summary

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=False, summary=self._summary)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    pr = 12
    evidence_dir = root / evidence_gate.evidence_dir_for(pr_number=pr)
    runbook = root / "runbook.md"
    runbook.write_text("执行形态：cli\n跑 init，看退出码。", encoding="utf-8")
    intent = "意图：init 无 origin 必须显式失败\n验收行为：\n- 非零退出 + 提示"

    # --- 验收行为①：cli runbook → executor 真跑并把证据落进 docs/e2e-results/<pr>/ ------------ #
    assert str(evidence_gate.evidence_dir_for(pr_number=pr)) == "docs/e2e-results/12", (
        "evidence_dir_for 路径约定应为 docs/e2e-results/<pr>/"
    )
    result = executor.run_executor(
        backend=_Backend(summary="跑了 init，退出码 0，符合预期。\nOUTCOME: PASSED"),
        work_dir=root,
        runbook_path=runbook,
        evidence_dir=evidence_dir,
        pr_number=pr,
    )
    assert result.outcome == "passed" and result.form == "cli", result
    assert (evidence_dir / executor.RESULT_FILENAME).is_file(), "证据 result.md 未落盘"
    print("  ✓ 行为①：cli runbook → executor 真跑（fake），证据固化到 docs/e2e-results/12/result.md")

    # --- 验收行为②：「意图未达成」证据 → 证据闸判 FAIL（挡住合并）------------------------------ #
    fail = evidence_gate.review_evidence(
        backend=_Backend(summary="VERDICT: FAIL\n验收行为①未达成：只跑了 --help，避重就轻。"),
        work_dir=root,
        intent=intent,
        evidence_dir=evidence_dir,
        pr_number=pr,
    )
    assert fail.passed is False and fail.feedback, fail
    print("  ✓ 行为②：意图未达成的证据 → 证据闸 FAIL（feedback 非空，链路将走 iterate(reason=e2e) 不 merge）")

    # --- 验收行为③：「达成」证据 → 证据闸判 PASS（放行合并）------------------------------------ #
    ok = evidence_gate.review_evidence(
        backend=_Backend(summary="VERDICT: PASS\n证据逐条对上意图。"),
        work_dir=root,
        intent=intent,
        evidence_dir=evidence_dir,
        pr_number=pr,
    )
    assert ok.passed is True and ok.feedback == "", ok
    print("  ✓ 行为③：达成意图的证据 → 证据闸 PASS（feedback 空，放行 merge）")

    # --- 证据缺失 = 未达成：无 result.md 硬判 FAIL（tautology guard 防线③）--------------------- #
    missing = evidence_gate.review_evidence(
        backend=_Backend(summary="不该被调用"),
        work_dir=root,
        intent=intent,
        evidence_dir=root / "no-such-dir",
        pr_number=pr,
    )
    assert missing.passed is False, missing
    print("  ✓ 兜底：证据缺失（无 result.md）→ 硬判 FAIL，无证据即未达成")

print()
print("✓ Spec-0039 hermetic 演练通过：executor 真跑固化证据 → 证据闸拿 RFC 意图对照证据门控合并，")
print("  证据 FAIL 挡合并 / 证据 PASS 放行 / 证据缺失硬 FAIL，全程不触网/无 LLM/无 gh/无真实 git 远端。")
PY

echo
echo "✓ Spec-0039 端到端脚本完成（离线确定性 + 闭环演练两段全过）。"
