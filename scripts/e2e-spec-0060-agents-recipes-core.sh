#!/usr/bin/env bash
# Spec-0060/T6 端到端测试启动脚本：核心收敛为 agents（提示词）+ recipes（编排）+ runtime 最小硬闸。
#
# 证明架构契约在离线确定性链路上成立（intent，见 spec e2e 块）：
#   - solve_issue recipe 只按 agent 的**结构化裁决**路由（PASS→next / REWORK→loop）、自身零业务判断；
#   - 最小硬闸真能兜底（head 未前移 / 超轮次 → raise）；
#   - agents/* 确无逻辑、recipes/solve_issue.py 确无版本控制/gh/subprocess 直接调用。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯后端编排**，无 product-facing 前端可导航；已自检
# 工具列表：无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，改用离线确定性测法（契约路由
# 单测 + 零逻辑/零 IO grep 锚点）。真实 issue 冒烟（`oa solve <issue>` 走新栈跑通 + PR CI 全绿）是
# issue 第 5 条验收，作为成果验收在 Phase-3 人验/runbook 记录，不塞进本离线脚本（见 spec method 3）。
#
# 用法：
#   bash scripts/e2e-spec-0060-agents-recipes-core.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/3] 契约路由 + 各层针对性单测"
uv run --extra dev pytest -q \
  tests/test_utils_git.py \
  tests/test_utils_github.py \
  tests/test_runtime_engine.py \
  tests/test_runtime_gates.py \
  tests/test_agents_prompts.py \
  tests/test_runtime_context.py \
  tests/test_recipe_solve_issue.py

echo
echo "==> [3/3] 零逻辑 / 零 IO grep 锚点"

fail() {
  echo "✗ 锚点失败：$1" >&2
  exit 1
}

AGENTS=(planner implementer reviewer deliver tester)

# 3a. 5 个 agent 模块：确含 Template( + OUTPUT_SCHEMA（提示词层的正向形态）。
for a in "${AGENTS[@]}"; do
  f="openagents/agents/${a}.py"
  grep -q "Template(" "$f" || fail "$f 缺 Template("
  grep -q "OUTPUT_SCHEMA" "$f" || fail "$f 缺 OUTPUT_SCHEMA"
done

# 3b. 5 个 agent 模块：零逻辑（无函数定义）、零 IO（无 subprocess）。
#     prompt 字符串里出现 git/gh 字样是**文案**（交付协议），非 Python 调用——故只锚定
#     真正的逻辑/IO 标志（def / subprocess），不误伤 prompt 文本。
for a in "${AGENTS[@]}"; do
  f="openagents/agents/${a}.py"
  grep -nE '^\s*(async\s+)?def ' "$f" && fail "$f 含函数定义（agent 应零逻辑）"
  grep -nE 'import subprocess|subprocess\.' "$f" && fail "$f 含 subprocess（agent 应零 IO）"
done

# 3c. recipes/solve_issue.py：无 subprocess / 无 "gh"·"git" 字面量调用 / 不直接 import github·workspace
#     （只经 runtime.run_agent + gates 路由，业务判断/版本控制操作全在 agent 或 utils）。
R="openagents/recipes/solve_issue.py"
grep -nE 'subprocess' "$R" && fail "$R 含 subprocess 直接调用"
grep -nE '"gh"|"git"|`gh |`git ' "$R" && fail "$R 含 gh/git 字面量调用"
grep -nE 'import .*(github|workspace)' "$R" && fail "$R 直接 import github/workspace"

echo "✓ grep 锚点全部通过：agents 零逻辑/零 IO、recipe 零版本控制调用"
echo
echo "✅ Spec-0060 离线 e2e 全绿"
