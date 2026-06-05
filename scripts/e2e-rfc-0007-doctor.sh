#!/usr/bin/env bash
# RFC-0007 端到端测试启动脚本：openagents doctor 子命令。
#
# 三段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实环境。
#   2) 真实体检：在当前仓库跑 `openagents doctor`，展示 ✓/✗ 清单与退出码。
#   3) 失败判定演示：在一个临时「非 git 目录」里跑 doctor，验证必需项（git 仓库）失败
#      → 非零退出。用临时目录隔离，不污染主仓库。
#
# 用法：
#   bash scripts/e2e-rfc-0007-doctor.sh
set -euo pipefail

cd "$(dirname "$0")/.."
repo="$PWD"

echo "==> [1/3] 离线确定性验证（lint + format + 单元/集成测试）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

echo
echo "==> [2/3] 真实体检：openagents doctor（当前仓库）"
# doctor 自带退出码：必需项失败时返回非零。这里不让脚本因体检失败而整体中断，
# 仅记录退出码并打印清单，便于人查看当前环境缺什么。
set +e
uv run openagents doctor
doctor_rc=$?
set -e
echo "doctor 退出码：${doctor_rc}（0=环境就绪；1=有必需项失败）"

echo
echo "==> [3/3] 失败判定演示：在非 git 目录跑 doctor → 期望非零退出"
# 临时目录隔离：cd 到一个全新的非 git 目录，必需项「git 仓库」必失败 → doctor 非零退出。
# 用 --project 指回主仓库，使 `uv run` 在临时 cwd 下仍能解析到 openagents 包。
demo_dir="$(mktemp -d)"
trap 'rm -rf "$demo_dir"' EXIT
demo_rc=0
(
  cd "$demo_dir"
  uv run --project "$repo" openagents doctor
) || demo_rc=$?

if [[ "${demo_rc}" -ne 0 ]]; then
  echo "✓ 失败判定符合预期：非 git 目录下 doctor 以非零退出（退出码 ${demo_rc}）。"
else
  echo "✗ 失败判定异常：非 git 目录下 doctor 竟退出 0（应为必需项失败）。"
  exit 1
fi

echo
echo "✓ RFC-0007 e2e 完成。"
