#!/usr/bin/env bash
# RFC-0005 端到端测试启动脚本：solve 原子化 + RFC-first 评审循环。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh。
#   2) 真实演练（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 且给定 OPENAGENTS_E2E_ISSUE=<n>，
#      在当前已绑定且 gh 已登录的仓库走完整 RFC-first 链路：
#        rfc <issue> → 模拟评审评论 → refine-rfc <pr> → 打 rfc-approved 标签 → implement <pr> → poll
#
# 用法：
#   bash scripts/e2e-rfc-0005-rfc-first.sh                                    # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 OPENAGENTS_E2E_ISSUE=42 \
#     bash scripts/e2e-rfc-0005-rfc-first.sh                                  # 含真实演练
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ 离线验证通过。真实演练已跳过（设 OPENAGENTS_E2E_REAL=1 且 OPENAGENTS_E2E_ISSUE=<n> 开启）。"
  exit 0
fi

echo
echo "==> [2/2] 真实演练：rfc → 评论 → refine-rfc → 打标签 → implement → poll"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh 未登录，请先 gh auth login"; exit 1; }
issue="${OPENAGENTS_E2E_ISSUE:-}"
[[ -n "$issue" ]] || { echo "请设置 OPENAGENTS_E2E_ISSUE=<issue 编号>"; exit 1; }

echo "--> 步骤 1：为 issue #$issue 起草 RFC 并开 draft PR"
uv run openagents rfc "$issue"

# 定位刚为该 issue 开的 draft PR 编号（分支命名前缀来自 orchestrator）。
branch="openagents/issue-$issue"
pr="$(gh pr list --head "$branch" --state open --json number --jq '.[0].number')"
[[ -n "${pr:-}" && "$pr" != "null" ]] || { echo "未能定位 issue #$issue 的 PR"; exit 1; }
echo "    draft PR = #$pr"

echo "--> 步骤 2：模拟人类评审，在 PR #$pr 上留一条评论"
gh pr comment "$pr" --body "[e2e] 请在 RFC 中补充权衡取舍章节。"

echo "--> 步骤 3：按评审评论精炼 RFC（agent 会回贴改动说明评论）"
uv run openagents refine-rfc "$pr"

echo "--> 步骤 4：人类批准——打 rfc-approved 标签"
gh pr edit "$pr" --add-label "rfc-approved"

echo "--> 步骤 5：RFC 获批，按 RFC 实现代码并把 draft PR 转正"
uv run openagents implement "$pr"

echo "--> 步骤 6：poll 一轮（coding 阶段的 CI/comment 路由验证）"
uv run openagents poll

echo
echo "✓ 真实演练完成：issue #$issue 已走完 RFC-first → 代码 全链路（PR #$pr）。"
echo "  注意：本脚本不会自动关闭 PR / 删标签，请按需在 GitHub 上清理。"
