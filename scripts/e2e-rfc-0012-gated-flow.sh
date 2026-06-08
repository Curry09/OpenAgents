#!/usr/bin/env bash
# RFC-0012 端到端测试启动脚本：test 分支门控流程 —— 人只在「提 issue」与「promote」介入。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh/claude。
#      覆盖：reviewer 闸（全票 PASS 聚合 / 非 PASS 反馈）、rounds/K 边界、STATUS_BLOCKED、
#      base=test 透传、merge 后扇出、promote 预检、CLI 接线（promote/--base/init 兜底）。
#   2) 真实门控演练（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 时，在当前已绑定且 gh 已
#      登录的仓库里演示 test 分支冷启动兜底 + promote 预检：
#        a. `openagents init` → 幂等兜底建 test 分支（决策 8）；
#        b. `openagents promote` → 预检（无 BLOCKED/needs-human + test CI 绿）通过则把 test
#           快进到 main（决策 7）。断言 promote 后 main 的 HEAD == test 的 HEAD。
#      注：reviewer 闸需真实后端（claude）驱动，成本高、非确定，本脚本的真实段只演示
#      「冷启动兜底 + promote 扬升」这一确定可断言的链路；完整 issue→自动合入 test 的循环
#      请用 `openagents vigil --once` 在真实仓库手动观察（见 RFC 测试方案「手动验证」）。
#
# 用法：
#   bash scripts/e2e-rfc-0012-gated-flow.sh                          # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-rfc-0012-gated-flow.sh    # 含真实 promote 演练
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ 离线验证通过。真实 promote 演练已跳过（设 OPENAGENTS_E2E_REAL=1 开启）。"
  exit 0
fi

echo
echo "==> [2/2] 真实门控演练：init 兜底建 test → promote 预检通过则快进 main"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh 未登录，请先 gh auth login"; exit 1; }

# --- 步骤 1：init 兜底建 test 体验服分支（幂等，决策 8）------------------------ #
echo "--> 步骤 1：openagents init —— 幂等兜底建 test 分支"
uv run openagents init

git fetch origin main test
main_head="$(git rev-parse origin/main)"
test_head_before="$(git rev-parse origin/test)"
echo "    main HEAD = ${main_head:0:8}；test HEAD = ${test_head_before:0:8}"

# --- 步骤 2：promote —— 预检通过则把 test 快进到 main（决策 7）----------------- #
echo "--> 步骤 2：openagents promote —— 预检（无 BLOCKED/needs-human + test CI 绿）后快进 main"
if uv run openagents promote; then
  git fetch origin main test
  main_after="$(git rev-parse origin/main)"
  test_after="$(git rev-parse origin/test)"
  if [[ "$main_after" == "$test_after" ]]; then
    echo "    ✓ main 已快进到 test：main HEAD == test HEAD == ${main_after:0:8}"
  else
    echo "✗ promote 报成功但 main(${main_after:0:8}) != test(${test_after:0:8})"
    exit 1
  fi
else
  echo "    ⓘ promote 预检未通过（存在 BLOCKED/needs-human，或 test CI 未绿）——这是预期内的"
  echo "      门控行为：有悬而未决的工作时拒绝扬升 main。修完后再跑 promote 即可。"
fi

echo
echo "✓ 真实门控演练完成。"
