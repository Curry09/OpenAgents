#!/usr/bin/env bash
# Spec-0023 端到端测试启动脚本：退役 test 分支 —— main 持续推进 + release/vX.Y.Z 版本分支发布。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh/git。
#      覆盖：base=main 透传（github/orchestrator/cli/vigil）、ensure_prerequisites 只预建标签、
#      release 预检（无 BLOCKED/needs-human + main CI 绿）、版本号语义化递增（patch/minor/major、
#      首发 v0.1.0、v0.10.0>v0.9.0）、物化分支+tag、CLI 接线（release/--bump/--base）。
#   2) 真实发布演练（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 时，在当前已绑定且 gh 已
#      登录的仓库里演示 release 预检 + 物化版本：
#        a. `openagents init` → 幂等预建流程标签（test 分支门控退役后不再建任何分支）；
#        b. `openagents release --bump patch` → 预检（无 BLOCKED/needs-human + main CI 绿）通过则
#           把 main 当前 HEAD 物化为 release/vX.Y.Z 分支并打 tag vX.Y.Z。
#           断言：远端存在 release/<版本> 分支与 <版本> tag，且二者 HEAD == main HEAD。
#      注：完整 issue→自动合入 main 的循环需真实后端（claude）驱动，成本高、非确定，本脚本
#      的真实段只演示「预检 + 物化版本」这一确定可断言的链路；完整循环请用
#      `openagents vigil --once` 在真实仓库手动观察。
#
# 用法：
#   bash scripts/e2e-spec-0023-release-flow.sh                          # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0023-release-flow.sh    # 含真实 release 演练
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ 离线验证通过。真实 release 演练已跳过（设 OPENAGENTS_E2E_REAL=1 开启）。"
  exit 0
fi

echo
echo "==> [2/2] 真实发布演练：init 预建标签 → release 预检通过则把 main 物化成版本"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh 未登录，请先 gh auth login"; exit 1; }

# --- 步骤 1：init 预建流程标签（幂等；test 门控退役后不再建任何分支）------------- #
echo "--> 步骤 1：openagents init —— 幂等预建流程标签"
uv run openagents init

git fetch origin main
main_head="$(git rev-parse origin/main)"
echo "    main HEAD = ${main_head:0:8}"

# --- 步骤 2：release —— 预检通过则把 main 物化为 release/vX.Y.Z 分支 + tag ------- #
echo "--> 步骤 2：openagents release --bump patch —— 预检（无 BLOCKED/needs-human + main CI 绿）后发布"
if uv run openagents release --bump patch; then
  git fetch origin --tags
  # 取最新版本 tag（语义化：按版本号排序取末位）。
  version="$(git tag --list 'v*' --sort=version:refname | tail -n1)"
  [[ -n "$version" ]] || { echo "✗ release 报成功但找不到任何版本 tag"; exit 1; }
  git fetch origin "refs/heads/release/${version}:refs/remotes/origin/release/${version}"
  branch_head="$(git rev-parse "origin/release/${version}")"
  tag_head="$(git rev-parse "${version}^{commit}")"
  if [[ "$branch_head" == "$main_head" && "$tag_head" == "$main_head" ]]; then
    echo "    ✓ 已发布 ${version}：release/${version} 分支与 tag 均指向 main HEAD ${main_head:0:8}"
  else
    echo "✗ ${version} 物化的分支(${branch_head:0:8})/tag(${tag_head:0:8}) != main(${main_head:0:8})"
    exit 1
  fi
else
  echo "    ⓘ release 预检未通过（存在 BLOCKED/needs-human，或 main CI 未绿）——这是预期内的"
  echo "      门控行为：有悬而未决的工作时拒绝发布。修完后再跑 release 即可。"
fi

echo
echo "✓ 真实发布演练完成。"
