#!/usr/bin/env bash
# RFC-0004 端到端测试启动脚本：openagents vigil 守夜人模式。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh/claude。
#   2) 真实冒烟（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 时，在当前已绑定且 gh 已登录的
#      仓库里：建一个带门控标签的 issue → 跑 `openagents vigil --once` 让守夜人自主发现并
#      派单（真实调起 claude 开 PR）→ 打印结果。需要 Claude Code CLI 可用。
#
# 用法：
#   bash scripts/e2e-rfc-0004-vigil.sh                          # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-rfc-0004-vigil.sh    # 含真实冒烟（会真实开 PR）
#
# 可选环境变量（真实冒烟段）：
#   VIGIL_LABEL   门控标签，默认 openagents
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ 离线验证通过。真实冒烟已跳过（设 OPENAGENTS_E2E_REAL=1 开启）。"
  exit 0
fi

echo
echo "==> [2/2] 真实冒烟：建带标签 issue → openagents vigil --once 自主发现并派单"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh 未登录，请先 gh auth login"; exit 1; }
command -v claude >/dev/null || { echo "需要可用的 Claude Code CLI（claude）"; exit 1; }

label="${VIGIL_LABEL:-openagents}"
# 确保门控标签存在（已存在则忽略错误）。
gh label create "$label" --description "openagents vigil 守夜人自动认领" >/dev/null 2>&1 || true

title="[e2e] RFC-0004 vigil 冒烟 $(date -u +%Y%m%dT%H%M%SZ)"
echo "创建带标签 issue：$title（label=$label）"
uv run openagents issue "$title" \
  --body "由 e2e-rfc-0004 脚本创建：请在 README 末尾追加一行 'vigil e2e ok'。" \
  --label "$label"

echo "运行守夜人单轮（--once）：自主发现该 issue 并派单 solve 开 PR …"
uv run openagents vigil --once --label "$label"

echo
echo "✓ 真实冒烟完成。请到 GitHub 检查：守夜人是否为上述 issue 自主开出了 PR。"
echo "  （PR 审核与合并由人工完成——这正是 vigil 设计中人类唯一的介入点。）"
