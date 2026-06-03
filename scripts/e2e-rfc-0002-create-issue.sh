#!/usr/bin/env bash
# RFC-0002 端到端测试启动脚本：openagents issue 子命令。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh。
#   2) 真实冒烟（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 时，在当前已绑定且 gh 已登录的
#      仓库真实创建一个 issue，再用 gh 把它关闭（避免遗留）。
#
# 用法：
#   bash scripts/e2e-rfc-0002-create-issue.sh                 # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-rfc-0002-create-issue.sh   # 含真实冒烟
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
echo "==> [2/2] 真实冒烟：openagents issue → gh 关闭"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh 未登录，请先 gh auth login"; exit 1; }

title="[e2e] RFC-0002 冒烟 $(date -u +%Y%m%dT%H%M%SZ)"
echo "创建 issue：$title"
uv run openagents issue "$title" --body "由 e2e-rfc-0002 脚本自动创建，可安全关闭。"

# 从 gh 找回刚创建的 issue 编号并关闭，避免在仓库里留垃圾。
num="$(gh issue list --search "$title in:title" --state open --json number --jq '.[0].number')"
if [[ -n "${num:-}" && "$num" != "null" ]]; then
  echo "关闭冒烟 issue #$num"
  gh issue close "$num" --comment "e2e 冒烟完成，自动关闭。"
  echo "✓ 真实冒烟通过：已创建并关闭 issue #$num"
else
  echo "⚠ 未能定位刚创建的 issue（标题搜索为空），请手动到 GitHub 检查并关闭：$title"
  exit 1
fi
