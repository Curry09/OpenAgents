#!/usr/bin/env bash
# Spec-0024 端到端测试启动脚本：spec 转 rust-RFC 形态（总览先行 + 单 spec 自包含，issue #69）。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest（全程 mock，不触达 gh/git），
#      覆盖 spec 数据模型（组级 Overview 9 段 round-trip、Task 瘦身）、校验质量门槛
#      （必填段非空 = error、跨 spec 裸引用 = warning、files/acceptance required）、
#      spec new 9 段脚手架、signpost 从组级 Overview 抽 e2e 脚本。
#   2) 流程演练（默认执行，全在临时目录）—— 用 `spec` CLI 实跑「新建组 → 写 9 段总览 →
#      add-task → validate/render/graph 全绿」，证明 rust-RFC 形态闭环可用。
#
# 用法：
#   bash scripts/e2e-spec-0024-rfc-form.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 流程演练：spec new → 写 9 段总览 → add-task → validate/render/graph"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ROOT="$TMP/specs"
mkdir -p "$ROOT"

# 1) 新建组（自动铺 9 段脚手架）。
uv run spec new demo-feature --issue 999 --title "演示 feature" \
  --summary "一句话 TL;DR：演示 rust-RFC 形态。" --specs-root "$ROOT"
GROUP="$ROOT/0001-demo-feature.md"
test -f "$GROUP"

# 断言脚手架含 9 段 rust 标题。
for h in "## Summary" "## Motivation" "## Guide-level explanation" \
         "## Reference-level explanation" "## Drawbacks" \
         "## Rationale and alternatives" "## Prior art" \
         "## Unresolved questions" "## Future possibilities"; do
  grep -qF "$h" "$GROUP" || { echo "✗ 脚手架缺段：$h"; exit 1; }
done
echo "  ✓ spec new 产出 9 段脚手架"

# 2) 填满必填四段（总览先行：feature 自包含地讲一遍）。
uv run python - "$GROUP" <<'PY'
import sys
from pathlib import Path
from openagents.spec import model
p = Path(sys.argv[1])
g = model.load_group(path=p)
g = model.Group(
    number=g.number, metadata=g.metadata, tasks=g.tasks, history={},
    overview=model.Overview(
        summary="把示例 feature 自包含地讲清楚。",
        motivation="现状缺 X，因此需要 Y（背景就地复述，不靠跨 spec 引用）。",
        guide_level="当它已存在，这样向人讲解：示例……",
        reference_level="技术方案 + DAG。bash scripts/e2e-spec-0024-rfc-form.sh 作 e2e。\nT1 改 a.py。",
        rationale_alternatives="备选 A 被否决，因为……",
    ),
)
p.write_text(model.render_group(group=g), encoding="utf-8")
print("  ✓ 已填 9 段必填总览")
PY

# 3) add-task（工作分解行：files 互斥 + acceptance 必填）。
uv run spec add-task 0001 --id T1 --title "实现 a" --priority P1 \
  --files demo/a.py --scope "改 a.py" --acceptance "a 的单测通过" --specs-root "$ROOT"

# 4) validate / render / graph 全绿。
uv run spec validate --specs-root "$ROOT"
uv run spec render --specs-root "$ROOT"
test -f "$ROOT/OVERVIEW.md"
echo
echo "✓ Spec-0024 端到端通过：rust-RFC 9 段总览 + DAG 工作分解闭环可用。"
