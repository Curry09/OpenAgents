#!/usr/bin/env bash
# Spec-0014 端到端测试启动脚本：在沙箱里串起 spec 全链路——
# new（建组）→ add-task（加子任务）→ validate → render（四块）→ amend（历史 +1 / OVERVIEW
# 重写）→ 再 validate/render 幂等。全程 hermetic（用临时目录，不动仓库 docs/specs）。
#
# issue #53：原步骤 1 用 migrate-rfc-to-spec 从 docs/rfcs 迁移；docs/rfcs 退役后改为用
# `spec new` + `spec add-task` 直接创作（取代迁移），演练真实的 spec 作者流程。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套。
#   2) spec 链路演练（默认也执行，纯本地，无需 gh/网络）。
#
# 用法：
#   bash scripts/e2e-spec-0014-spec-driven.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

echo
echo "==> [2/2] spec 链路演练（new → add-task → validate → render → amend → 幂等复核）"

sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT
specs="$sandbox/specs"

echo "--> 步骤 1：spec new 建组 + spec add-task 加两个子任务（${specs}）"
uv run spec new mvp-issue-to-pr-loop --issue 1 --title "MVP 自举闭环" --specs-root "$specs"
uv run spec add-task 0001 --id T1 --title "包骨架" --priority P0 \
  --files openagents/cli.py --specs-root "$specs"
uv run spec add-task 0001 --id T2 --title "GitHub 集成" --priority P1 \
  --files openagents/github.py --depends-on T1 --specs-root "$specs"

echo "--> 步骤 2：spec validate 全绿（无 error）"
uv run spec validate --specs-root "$specs"

echo "--> 步骤 3：spec render 生成 OVERVIEW.md 并断言四块齐全"
uv run spec render --specs-root "$specs"
for heading in "## 全局看板" "## 跨 feature 关系图" "## 文件冲突报告" "## 各 feature 详情"; do
  grep -qF "$heading" "$specs/OVERVIEW.md" || { echo "缺少区块：$heading"; exit 1; }
done

echo "--> 步骤 4：amend 一个 Task（断言 history +1、tasks 升版、OVERVIEW 重写）"
[[ -f "$specs/0001-mvp-issue-to-pr-loop/history/T1.yaml" ]] && { echo "新建产物不应有 history"; exit 1; }
uv run spec amend 0001 T1 --reason "e2e 演练：拆分子任务" --specs-root "$specs"
[[ -f "$specs/0001-mvp-issue-to-pr-loop/history/T1.yaml" ]] || { echo "amend 未生成 history"; exit 1; }
grep -q "version: 2" "$specs/0001-mvp-issue-to-pr-loop/tasks/T1.yaml" || { echo "tasks 未升到 v2"; exit 1; }

echo "--> 步骤 5：再次 render 断言幂等（无 diff）+ validate 仍全绿"
cp "$specs/OVERVIEW.md" "$sandbox/overview-before.md"
uv run spec render --specs-root "$specs"
diff -q "$sandbox/overview-before.md" "$specs/OVERVIEW.md" >/dev/null || { echo "render 非幂等"; exit 1; }
uv run spec validate --specs-root "$specs"

echo
echo "✓ Spec-0014 端到端链路全部通过。"
