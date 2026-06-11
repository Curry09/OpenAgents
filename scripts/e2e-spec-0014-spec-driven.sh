#!/usr/bin/env bash
# Spec-0014 端到端测试启动脚本：在沙箱里串起 spec 全链路——
# 迁移（RFC→spec）→ validate → render（四块）→ amend（历史 +1 / OVERVIEW 重写）→ 再
# validate/render 幂等。全程 hermetic（用临时目录，不动仓库 docs/specs）。
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
echo "==> [2/2] spec 链路演练（迁移 → validate → render → amend → 幂等复核）"

sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT
specs="$sandbox/specs"

echo "--> 步骤 1：把 docs/rfcs/ 全量迁移为 spec 组（${specs}）"
uv run python scripts/migrate-rfc-to-spec.py --rfcs-dir docs/rfcs --specs-root "$specs"

echo "--> 步骤 2：spec validate 全绿（无 error）"
uv run spec validate --specs-root "$specs"

echo "--> 步骤 3：spec render 生成 OVERVIEW.md 并断言四块齐全"
uv run spec render --specs-root "$specs"
for heading in "## 全局看板" "## 跨 feature 关系图" "## 文件冲突报告" "## 各 feature 详情"; do
  grep -qF "$heading" "$specs/OVERVIEW.md" || { echo "缺少区块：$heading"; exit 1; }
done

echo "--> 步骤 4：amend 一个 Task（断言 history +1、tasks 升版、OVERVIEW 重写）"
[[ -f "$specs/0001-mvp-issue-to-pr-loop/history/T1.yaml" ]] && { echo "迁移产物不应有 history"; exit 1; }
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
