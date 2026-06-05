#!/usr/bin/env bash
# RFC-0008 端到端测试启动脚本：PR 正文「端到端验证」指路牌（从 RFC 自动生成）。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh。
#   2) 真实演练（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 且给定 OPENAGENTS_E2E_ISSUE=<n>，
#      在当前已绑定且 gh 已登录的仓库执行 `openagents rfc <issue>`，断言新开 draft PR
#      的正文包含「## 端到端验证」段。
#
# 用法：
#   bash scripts/e2e-rfc-0008-pr-e2e-signpost.sh                                # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 OPENAGENTS_E2E_ISSUE=42 \
#     bash scripts/e2e-rfc-0008-pr-e2e-signpost.sh                             # 含真实演练
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
echo "==> [2/2] 真实演练：rfc <issue> → 断言 draft PR 正文含「## 端到端验证」段"
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

echo "--> 步骤 2：断言 PR #$pr 正文包含「## 端到端验证」指路牌段"
body="$(gh pr view "$pr" --json body --jq '.body')"
if grep -q "## 端到端验证" <<<"$body"; then
  echo "✓ PR #$pr 正文已含「## 端到端验证」指路牌段。"
else
  echo "✗ PR #$pr 正文缺少「## 端到端验证」段："
  echo "$body"
  exit 1
fi

echo
echo "✓ 真实演练完成：issue #$issue 的 draft PR（#$pr）正文已带端到端验证指路牌。"
echo "  注意：本脚本不会自动关闭 PR，请按需在 GitHub 上清理。"
