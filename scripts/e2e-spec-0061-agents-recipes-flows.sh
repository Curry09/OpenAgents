#!/usr/bin/env bash
# Spec-0061/T1-T4 端到端测试启动脚本：批次二立起 vigil/poll_comments/fleet 三条循环型 recipe +
# triager/replier 两个新 agent + utils 完整稳定 import 面，全程 additive（旧栈与其 11 个测试桩不动）。
#
# 证明架构契约在离线确定性链路上成立（intent，见 spec e2e 块）：
#   - vigil recipe 只按 triager 的**结构化裁决**路由（actionable→dispatch / 否→_park 挂 needs-human），
#     去重三闸（本地 run / 远端分支 / needs-human 标签）确定性滤「新」、自身零业务判断；
#   - poll_comments recipe 只做「拉游标后新人类评论 → 派 replier → 盖签名回帖 → 推进游标」纯控制流，
#     单 PR 失败错误隔离不拖垮整轮；
#   - fleet recipe 复用旧 Fleet 监管器（注入新栈 spawn），一 plan 一子进程跑新栈 vigil；
#   - triager/replier 确无逻辑（零 def、零 subprocess）；三条 recipe 不直接碰 gh/git（只经 utils/engine）。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯后端编排**，无 product-facing 前端可导航；已自检
# 工具列表：无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，改用离线确定性测法（契约路由
# 单测 + 零逻辑/零 IO grep 锚点）。真实多仓守夜冒烟（`oa vigil-new` / `oa fleet` 跑通 + PR CI 全绿）
# 作为成果验收在 Phase-3 人验/runbook 记录，不塞进本离线脚本。
#
# 用法：
#   bash scripts/e2e-spec-0061-agents-recipes-flows.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/3] 批次二契约路由 + 各层针对性单测"
uv run --extra dev pytest -q \
  tests/test_agents_triager_replier.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_poll_comments.py \
  tests/test_recipe_fleet.py \
  tests/test_cli_new_stack.py

echo
echo "==> [3/3] 零逻辑 / 零 IO grep 锚点"

fail() {
  echo "✗ 锚点失败：$1" >&2
  exit 1
}

# 3a. 两个新 agent 模块：确含 Template( + OUTPUT_SCHEMA（提示词层的正向形态）。
for a in triager replier; do
  f="openagents/agents/${a}.py"
  grep -q "Template(" "$f" || fail "$f 缺 Template("
  grep -q "OUTPUT_SCHEMA" "$f" || fail "$f 缺 OUTPUT_SCHEMA"
done

# 3b. 两个新 agent 模块：零逻辑（无函数定义）、零 IO（无 subprocess）。
#     prompt 字符串里出现 git/gh 字样是**文案**（交付协议），非 Python 调用——只锚定真正的
#     逻辑/IO 标志（def / subprocess），不误伤 prompt 文本。
for a in triager replier; do
  f="openagents/agents/${a}.py"
  grep -nE '^\s*(async\s+)?def ' "$f" && fail "$f 含函数定义（agent 应零逻辑）"
  grep -nE 'import subprocess|subprocess\.' "$f" && fail "$f 含 subprocess（agent 应零 IO）"
done

# 3c. 三条 recipe：无 subprocess、不直接 import 原始 openagents.github / openagents.workspace
#     （只经 utils 稳定面 + runtime.engine/context 路由，版本控制/gh 机械操作全在 utils）。
for r in vigil poll_comments fleet; do
  f="openagents/recipes/${r}.py"
  grep -nE 'import subprocess|subprocess\.' "$f" && fail "$f 含 subprocess 直接调用"
  grep -nE 'openagents\.github|openagents\.workspace' "$f" && fail "$f 直接 import 原始 github/workspace（应走 utils）"
done

# 3d. 循环型 recipe vigil / poll_comments：无 gh/git 字面量 shell 调用（fleet 复用旧监管器、
#     其 docstring 述及 gh 属文案，故不纳入本条字面量锚点，由 3c 的 subprocess 锚点兜底）。
for r in vigil poll_comments; do
  f="openagents/recipes/${r}.py"
  grep -nE '"gh"|"git"|`gh |`git ' "$f" && fail "$f 含 gh/git 字面量调用"
done

echo "✓ grep 锚点全部通过：triager/replier 零逻辑零 IO、三 recipe 零原始 gh/git 直调"
echo
echo "✅ Spec-0061 离线 e2e 全绿"
