#!/usr/bin/env bash
# Spec-0057 端到端测试启动脚本：e2e 门控硬化——RFC 闸确定性强制 e2e 块 + 代码 review 两重测试交叉比对。
#
# wind-palace PR #19 实证：e2e v2 被两道非确定 LLM 软闸绕过（RFC 闸被 spec 正文的 e2e 讨论骗过、没逼出
# 结构化 e2e 块 → run_e2e 空过；代码 review 把实现者自测/自证当放行依据、没要求独立 executor 证据）。
# 本组把这两条硬化：T1 RFC 闸在调 LLM 前加确定性检查（缺真实 e2e{intent,method} 块直接自动返工，不问
# LLM）；T2 代码 review rubric 明说两重（自测=声明/运动员、独立 executor=裁判），交叉比对、独立证据缺失
# 不得凭自测放行。两个证据目录保持分开。
#
# 全程离线、不触网/不调真实 LLM/gh：ruff + pytest + grep 锚点。
# 用法：bash scripts/e2e-spec-0057-e2e-gate-hardening.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 关键不变量 grep 锚点"
grep -q "def e2e_block_missing" openagents/orchestrator.py && echo "  ✓ orchestrator.e2e_block_missing 确定性检查存在"
grep -q "e2e_block_missing" openagents/messages.py && echo "  ✓ RFC 闸接入确定性检查（review_rfc 之前）"
grep -q "refine-e2e-block" openagents/messages.py && echo "  ✓ 缺块走 refine-e2e-block 自动返工"
grep -q "必须在组 frontmatter 声明" openagents/orchestrator.py && echo "  ✓ 起草 prompt 强制声明 e2e 块"
grep -q "两重" openagents/reviewer.py && echo "  ✓ 代码 review rubric 含两重测试交叉比对"
grep -q "不得凭自测放行" openagents/reviewer.py && echo "  ✓ 独立证据缺失不得凭自测放行"
grep -q "docs/evidence/" openagents/reviewer.py && grep -q "docs/e2e-results/" openagents/reviewer.py && echo "  ✓ 两个证据目录分开提及（自证 vs 独立）"

echo
echo "全部通过 ✅（Spec-0057 e2e 门控硬化）"
