#!/usr/bin/env bash
# RFC-0011 端到端测试启动脚本：本地 agent 身份 + 评论签名（区分自评论 vs 真人评论）。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh。
#      覆盖 identity 往返签名/解析、state agent_id 持久化、messages 自评论过滤 + 游标简化、
#      orchestrator/rebase 回贴盖章、cli 接线一致性，以及 current_login 已下线。
#   2) 真实签名往返演练（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 时，在一个真实 PR 上
#      用 identity.post_signed_comment 发一条带隐藏签名的评论，再经 `gh pr view --json comments`
#      把原始 body 取回，断言 parse_agent_id 能解析出本实例 agent_id（证明签名能穿过 gh 往返、
#      GitHub 渲染不可见但机读可解析）。
#
# 用法：
#   bash scripts/e2e-rfc-0011-agent-identity-signature.sh                       # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 E2E_PR=<PR编号> bash scripts/e2e-rfc-0011-agent-identity-signature.sh
#
# 可选环境变量（真实演练段）：
#   E2E_PR              目标 open PR 编号（真实演练必填）。
#   OPENAGENTS_AGENT_ID 显式指定本实例 agent_id（缺省由 resolve_agent_id 解析/生成）。
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv sync --extra dev   # 确保 ruff / pytest 已就位（与 .github/workflows/ci.yml 同步策略一致）
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ 离线验证通过。真实签名往返演练已跳过（设 OPENAGENTS_E2E_REAL=1 开启）。"
  exit 0
fi

echo
echo "==> [2/2] 真实签名往返演练：post_signed_comment → gh 取回 → parse_agent_id 解析"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh 未登录，请先 gh auth login"; exit 1; }
pr="${E2E_PR:?请设置 E2E_PR=<目标 open PR 编号>}"

# 在目标 PR 上发一条带签名的评论，并断言 gh 取回的原始 body 可被 parse_agent_id 解析回同一 id。
uv run python - "$pr" <<'PY'
import sys

from openagents import github, identity
from openagents.state import State

pr_number = int(sys.argv[1])

# 解析本实例 agent_id（env > state > 生成落盘），与 CLI 接线同源。
state = State(path=__import__("pathlib").Path(".openagents/state.json"))
agent_id = identity.resolve_agent_id(state=state)
print(f"--> 本实例 agent_id = {agent_id!r}")

marker = "e2e-0011 签名往返验证"
identity.post_signed_comment(pr_number=pr_number, body=marker, agent_id=agent_id)
print(f"--> 已向 PR #{pr_number} 发出带签名评论")

# 经 gh 取回原始 body，找回刚发的那条，断言签名可解析且等于本实例 id。
comments = github.list_comments(pr_number=pr_number)
mine = [c for c in comments if marker in c.body and identity.parse_agent_id(body=c.body) is not None]
if not mine:
    print("✗ 未在 PR 上找到带签名的回贴")
    sys.exit(1)
latest = max(mine, key=lambda c: c.created_at)
parsed = identity.parse_agent_id(body=latest.body)
if parsed != agent_id:
    print(f"✗ 签名解析不一致：取回 {parsed!r} != 本实例 {agent_id!r}")
    sys.exit(1)
print(f"    ✓ 签名穿过 gh 往返：parse_agent_id = {parsed!r}（== 本实例 agent_id）")
print(f"    ✓ 该评论将被下一轮 poll 据签名剔除，不触发自循环")
PY

echo
echo "✓ 真实签名往返演练完成：自评论签名可经 gh 往返机读解析，poll 据此区分自/非自。"
echo "  注意：本脚本会在 PR #$pr 上留下一条测试评论，请按需清理。"
