#!/usr/bin/env bash
# Spec-0025 端到端测试启动脚本：brownfield 反向补全 RFC（扫存量代码 → 反推 9 段 spec 草稿）。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest（全程 mock，不触达 gh/git/LLM），
#      覆盖 T1 盘点助手（单文件/目录形态、公开符号/docstring 抽取、空目录/缺路径抛错）、
#      T2 编排（盘点→后端→validate 门控→draft PR；validate 非 0 不开 PR）、T3 CLI 子命令解析。
#   2) 反向补全闭环演练（默认执行，全在临时目录）—— 对一个**无 spec 的样例代码路径**：
#      a. 实跑 `backfill.inventory` 证明盘点能产出文件清单 + 公开符号（反推 agent 的输入端）；
#      b. 模拟反推 agent 的产物：用 `spec` CLI 写出一份 9 段草稿（必填四段据实写满、难反推段标
#         「待人工补全」），再 `spec validate` 0 error——证明 backfill 的**开 PR 前硬门控**可过。
#      （真实 backend 反推需调 LLM，不可在 CI 内确定性复现，故此处以 spec CLI 复刻其确定性出口。）
#
# 用法：
#   bash scripts/e2e-spec-0025-backfill-rfc.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 反向补全闭环演练：盘点样例代码 → 反推 9 段草稿 → spec validate 0 error"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1) 造一个「无 spec 的 brownfield 样例代码路径」——单个存量模块。
SAMPLE="$TMP/widget.py"
cat >"$SAMPLE" <<'PY'
"""样例存量模块：一个没有对应 spec 的 brownfield widget。"""


def render():
    return "widget"


class Widget:
    pass
PY

# a) 实跑 T1 盘点：断言产出文件清单 + 公开符号（反推 agent 的输入端）。
uv run python - "$SAMPLE" <<'PY'
import sys
from pathlib import Path
from openagents.backfill import inventory, slug_for

inv = inventory(path=Path(sys.argv[1]))
assert inv.single_file is True, inv
assert [m.path for m in inv.modules] == ["widget.py"], inv
assert inv.modules[0].symbols == ("render", "Widget"), inv.modules[0].symbols
assert "widget.py" in inv.render()
assert slug_for(path=Path(sys.argv[1])) == "widget"
print("  ✓ backfill.inventory 盘点样例代码：文件清单 + 公开符号 OK")
PY

# 2) 模拟反推 agent 的确定性出口：写一份 9 段草稿（必填四段写满、难反推段标「待补」）。
ROOT="$TMP/specs"
mkdir -p "$ROOT"
uv run spec new widget-backfill --issue 0 --title "反向补全 widget" \
  --summary "一句话 TL;DR：为存量 widget 模块反推一份 spec。" --specs-root "$ROOT"
GROUP="$ROOT/0001-widget-backfill.md"
test -f "$GROUP"

# 断言脚手架含 9 段 rust 标题。
for h in "## Summary" "## Motivation" "## Guide-level explanation" \
         "## Reference-level explanation" "## Drawbacks" \
         "## Rationale and alternatives" "## Prior art" \
         "## Unresolved questions" "## Future possibilities"; do
  grep -qF "$h" "$GROUP" || { echo "✗ 脚手架缺段：$h"; exit 1; }
done

# 必填四段据实写满；难反推段标「待人工补全」占位（非必填，不触发 validate error）。
uv run python - "$GROUP" <<'PY'
import sys
from pathlib import Path
from openagents.spec import model

p = Path(sys.argv[1])
g = model.load_group(path=p)
g = model.Group(
    number=g.number, metadata=g.metadata, tasks=g.tasks, history={},
    overview=model.Overview(
        summary="为存量 widget 模块反推一份自包含的 spec。",
        motivation="widget.py 已存在却无 spec，无法纳入 RFC 驱动闭环（背景就地复述）。",
        guide_level="当它已存在，这样向人讲解：render() 产出 widget，Widget 是占位类。",
        reference_level="实际技术结构：单模块 widget.py，公开 render / Widget。"
                        "bash scripts/e2e-spec-0025-backfill-rfc.sh 作 e2e。\nT1 改 widget.py。",
        drawbacks="> 待人工补全（brownfield 反推困难）",
        rationale_alternatives="备选：纯静态生成模板，被否决——写不出 Motivation 语义。",
        prior_art="> 待人工补全（brownfield 反推困难）",
    ),
)
p.write_text(model.render_group(group=g), encoding="utf-8")
print("  ✓ 已写 9 段草稿：必填四段据实写满、难反推段标「待人工补全」")
PY

# add-task（工作分解行：files 互斥 + acceptance 必填）。
uv run spec add-task 0001 --id T1 --title "盘点 widget" --priority P1 \
  --files widget.py --scope "盘点 widget.py" --acceptance "render/Widget 被盘点到" \
  --specs-root "$ROOT"

# b) spec validate 0 error——证明反推草稿能过开 PR 前的硬门控。
uv run spec validate --specs-root "$ROOT"
echo "  ✓ spec validate 0 error：反推草稿可过开 draft PR 前的硬门控"

echo
echo "✓ Spec-0025 端到端通过：盘点存量代码 → 反推 9 段草稿 → validate 门控闭环可用。"
