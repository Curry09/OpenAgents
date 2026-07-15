#!/usr/bin/env bash
# Spec-0035 端到端测试启动脚本：裸 git 网络调用统一硬超时（fail-open）+ 发现段慢检查进度日志。
#
# 纯内部可靠性改动、无 UI，故 e2e 为 hermetic 离线脚本——全程打桩 subprocess.run 抛 TimeoutExpired，
# 断言三类 fail-open 分支 + 两行发现段进度日志落 stderr，不触真实 git / 网络：
#   1) 去重探针超时 → 保守返回 True（「可能在途」→ 本轮跳过、下轮重试，绝不重复派单）：
#      git.remote_branch_exists / Workspace.remote_branch_exists。
#   2) fetch 超时 → 抛既有 WorkspaceError（prepare/ensure/assert_delivered），落既有 per-issue 隔离。
#   3) push 超时 → 抛既有 RuntimeError（release，携 action 语境），CLI 层转干净一行提示。
#   4) 发现段两行进度日志（_intake 拉 issue 前 / _admit 调 LLM 前）落 stderr。
#   5) 网络正常路径行为逐字节不变：返回值 / 退出码不改；_git 均带 timeout=_GIT_NET_TIMEOUT_SECONDS。
#
# 用法：
#   bash scripts/e2e-spec-0035-git-net-timeout.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 定向验证 Spec-0035 四个 Task（打桩 subprocess.run 抛 TimeoutExpired，hermetic 离线）"
uv run --extra dev pytest -q \
  tests/test_utils_git.py \
  tests/test_workspace.py \
  tests/test_release.py \
  tests/test_recipe_vigil_discovery.py

echo
echo "==> [2/2] 全量 lint + format + 单元/集成测试（确认零回归）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "✓ Spec-0035 离线验证通过：网络 git 超时 fail-open 有牙、发现段进度日志落 stderr、默认路径不变。"
