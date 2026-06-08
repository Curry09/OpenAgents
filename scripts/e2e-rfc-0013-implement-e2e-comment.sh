#!/usr/bin/env bash
# RFC-0013 端到端测试启动脚本：implement 转正前实跑 e2e 脚本并把「合否 + 日志」作为
# 带签名的 PR 评论发出（RFC-0008 指路牌 → 实跑结果延伸）。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh。
#   2) 真实演练（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 且给定 OPENAGENTS_E2E_PR=<n>
#      （一个已 rfc-approved 的 draft PR），在 gh 已登录的仓库执行 `openagents implement <pr>`，
#      断言该 PR 新增一条含「## 端到端测试结果」且带 agent 签名的评论。
#
# 用法：
#   bash scripts/e2e-rfc-0013-implement-e2e-comment.sh                          # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 OPENAGENTS_E2E_PR=42 \
#     bash scripts/e2e-rfc-0013-implement-e2e-comment.sh                        # 含真实演练
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ 离线验证通过。真实演练已跳过（设 OPENAGENTS_E2E_REAL=1 且 OPENAGENTS_E2E_PR=<n> 开启）。"
  exit 0
fi

echo
echo "==> [2/2] 真实演练：implement <pr> → 断言 PR 新增「## 端到端测试结果」签名评论"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh 未登录，请先 gh auth login"; exit 1; }
pr="${OPENAGENTS_E2E_PR:-}"
[[ -n "$pr" ]] || { echo "请设置 OPENAGENTS_E2E_PR=<已 rfc-approved 的 draft PR 编号>"; exit 1; }

echo "--> 步骤 1：对 PR #$pr 跑 openagents implement（写码 + 实跑 e2e + 发结果评论 + 转正）"
uv run openagents implement "$pr"

echo "--> 步骤 2：断言 PR #$pr 新增一条含「## 端到端测试结果」且带 agent 签名的评论"
bodies="$(gh pr view "$pr" --json comments --jq '.comments[].body')"
if grep -q "## 端到端测试结果" <<<"$bodies" \
  && grep -q "openagents:agent=" <<<"$bodies"; then
  echo "✓ PR #$pr 已含带签名的「## 端到端测试结果」评论。"
else
  echo "✗ PR #$pr 缺少带签名的「## 端到端测试结果」评论："
  echo "$bodies"
  exit 1
fi

echo
echo "✓ 真实演练完成：PR #$pr 已带实跑结果评论（带 agent 签名，poll 不会自循环）。"
echo "  注意：本脚本不会自动关闭 PR，请按需在 GitHub 上清理。"
