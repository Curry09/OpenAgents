#!/usr/bin/env bash
# Spec-0030 端到端测试启动脚本：init 前端 e2e 环境体检（检测 browser MCP + 权限放行，非阻塞）
# + 条件式 browser-e2e 方法论文案注入（issue #85）。
#
# hermetic——不调真实 claude / GitHub。三段：
#   1) 离线确定性验证（ruff lint/format + pytest，全程 mock）。
#   2) 体检两态：打桩 HOME 下的 ~/.claude.json + OPENAGENTS_PERMISSION_MODE，
#      断言「缺失态」报告含安装命令 / 非全放行警告 / export 设置方式、非阻塞（render 不抛）；
#      「满足态」含两条 ✓ 且不含安装命令。
#   3) 方法论文案：grep orchestrator.py / reviewer.py 确认条件式「具备浏览器工具 → 优先浏览器
#      前端 e2e」字样已注入两处模板。
#
# 用法：
#   bash scripts/e2e-spec-0030-init-env-check.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/3] 体检两态：缺失态 / 满足态报告断言（打桩 HOME + 权限 env）"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- 缺失态：~/.claude.json 无 mcpServers + 默认权限（acceptEdits） ---
MISSING_HOME="$TMP/missing"
mkdir -p "$MISSING_HOME"
echo '{"mcpServers": {}}' > "$MISSING_HOME/.claude.json"
MISSING_OUT="$(HOME="$MISSING_HOME" OPENAGENTS_PERMISSION_MODE= \
  uv run python -c 'from openagents import envcheck; print(envcheck.check().text)')"
echo "$MISSING_OUT"
grep -qF "claude mcp add playwright" <<<"$MISSING_OUT" \
  || { echo "✗ 缺失态报告缺 playwright 安装命令"; exit 1; }
grep -qF "export OPENAGENTS_PERMISSION_MODE=bypassPermissions" <<<"$MISSING_OUT" \
  || { echo "✗ 缺失态报告缺 export 设置方式"; exit 1; }
grep -qF "非全放行" <<<"$MISSING_OUT" \
  || { echo "✗ 缺失态报告缺非全放行警告"; exit 1; }
echo "  ✓ 缺失态：含安装命令 + 非全放行警告 + export 设置方式"

# --- 满足态：~/.claude.json 含 playwright + chrome-devtools + 全放行 ---
OK_HOME="$TMP/ok"
mkdir -p "$OK_HOME"
echo '{"mcpServers": {"playwright": {}, "chrome-devtools": {}}}' > "$OK_HOME/.claude.json"
OK_OUT="$(HOME="$OK_HOME" OPENAGENTS_PERMISSION_MODE=bypassPermissions \
  uv run python -c 'from openagents import envcheck; print(envcheck.check().text)')"
echo "$OK_OUT"
[ "$(grep -cF "✓" <<<"$OK_OUT")" -eq 2 ] \
  || { echo "✗ 满足态报告应含两条 ✓"; exit 1; }
grep -qF "claude mcp add" <<<"$OK_OUT" \
  && { echo "✗ 满足态报告不应含安装命令"; exit 1; }
echo "  ✓ 满足态：两条 ✓、不含安装命令"

# --- 非阻塞：体检 all_ok 布尔可取、check() 不抛（缺失态退出码 0） ---
HOME="$MISSING_HOME" OPENAGENTS_PERMISSION_MODE= \
  uv run python -c 'from openagents import envcheck; r = envcheck.check(); assert r.all_ok is False'
echo "  ✓ 非阻塞：缺失态 check() 不抛、all_ok=False、退出码 0"

echo
echo "==> [3/3] 方法论文案注入：grep orchestrator.py / reviewer.py"
grep -qF "浏览器工具" openagents/orchestrator.py \
  || { echo "✗ orchestrator.py 缺 browser-e2e 条件式引导"; exit 1; }
grep -qF "前端 e2e" openagents/orchestrator.py \
  || { echo "✗ orchestrator.py 缺『前端 e2e』引导"; exit 1; }
grep -qF "浏览器工具" openagents/reviewer.py \
  || { echo "✗ reviewer.py rubric 缺 browser-e2e 条件式引导"; exit 1; }
echo "  ✓ orchestrator.py（起草 + 反向补全）与 reviewer.py rubric 均含条件式 browser-e2e 引导"

echo
echo "✓ Spec-0030 端到端通过：init 环境体检两态 + 非阻塞 + 方法论文案注入闭环可用。"
