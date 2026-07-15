#!/usr/bin/env bash
# Spec-0068 端到端测试启动脚本：并行守夜 worktree prepare 共享 .git 锁竞争消除。
#
# 纯内部并发正确性修复、无 product-facing 前端可导航，故按取证纪律「纯内部 → 相称自动化测试」，
# 用 hermetic 离线并发回归测法（不触真实 LLM / GitHub / 网络，只用本地临时 git 仓）：
#   1) T1 单测（tests/test_workspace.py）：prepare / ensure 的整段共享 .git 变更在持
#      _GIT_MUTATION_LOCK 下执行；assert_delivered（纯读）不进锁；锁为模块级 threading.Lock。
#   2) T2 并发回归（tests/test_workspace_concurrency.py）：起 N(≥4) 线程对同一临时 git 仓并发调
#      prepare（各带不同 issue_number/branch），断言全部建成 worktree、零 WorkspaceError、
#      git stderr 不含 'cannot lock ref' / 'could not lock working tree'，且变更段观测最大并发度=1。
#      对照（文档化、不长期跑）：去掉锁则该测试转 flaky/失败——正是本锁要消除的竞态。
#
# 用法：
#   bash scripts/e2e-spec-0068-parallel-worktree-git-lock.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 定向验证 Spec-0068 T1+T2（hermetic 离线并发回归，只用本地临时 git 仓）"
uv run --extra dev pytest -q \
  tests/test_workspace.py \
  tests/test_workspace_concurrency.py

echo
echo "==> [2/2] 全量 lint + format（确认零回归）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "✓ Spec-0068 离线验证通过：K worker 并发建 worktree 零 git 锁竞争，prepare/ensure 变更段串行、纯读路径不进锁。"
