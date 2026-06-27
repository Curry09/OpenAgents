#!/usr/bin/env bash
# Spec-0026/T2 端到端测试启动脚本：README「最简用法 / Quickstart」段位置与内容断言。
#
# 纯文档校验——不调用任何真实 CLI / GitHub，无外部依赖,CI 可稳定复跑。
# 断言：
#   1) README.md 含「## 最简用法 / Quickstart」标题；
#   2) 该标题行号在「## 安装」之后、「## 快速上手」之前（按行号顺序）；
#   3) 新段代码块同时含 `openagents init` / `openagents issue` / `openagents vigil` 三行。
#
# 用法：
#   bash scripts/e2e-spec-0026-readme-quickstart.sh
set -euo pipefail

cd "$(dirname "$0")/.."

README="README.md"
test -f "$README" || { echo "✗ 缺 $README"; exit 1; }

# 取某个标题的首次出现行号（无则为空）。
line_of() { grep -nF "$1" "$README" | head -n1 | cut -d: -f1; }

echo "==> [1/2] 断言「## 最简用法 / Quickstart」位于「## 安装」与「## 快速上手」之间"
INSTALL_LN="$(line_of '## 安装')"
QUICKSTART_LN="$(line_of '## 最简用法 / Quickstart')"
WALKTHROUGH_LN="$(line_of '## 快速上手')"

test -n "$INSTALL_LN"     || { echo "✗ 缺「## 安装」"; exit 1; }
test -n "$QUICKSTART_LN"  || { echo "✗ 缺「## 最简用法 / Quickstart」"; exit 1; }
test -n "$WALKTHROUGH_LN" || { echo "✗ 缺「## 快速上手」"; exit 1; }

if ! { [ "$INSTALL_LN" -lt "$QUICKSTART_LN" ] && [ "$QUICKSTART_LN" -lt "$WALKTHROUGH_LN" ]; }; then
  echo "✗ 顺序错误：安装(L$INSTALL_LN) → Quickstart(L$QUICKSTART_LN) → 快速上手(L$WALKTHROUGH_LN)"
  exit 1
fi
echo "  ✓ 顺序正确：安装(L$INSTALL_LN) → Quickstart(L$QUICKSTART_LN) → 快速上手(L$WALKTHROUGH_LN)"

echo
echo "==> [2/2] 断言 Quickstart 段代码块含 init / issue / vigil 三行"
# 截取 Quickstart 标题到「快速上手」之间的段落，仅在该段内校验三行命令。
SECTION="$(sed -n "${QUICKSTART_LN},${WALKTHROUGH_LN}p" "$README")"
for cmd in "openagents init" "openagents issue" "openagents vigil"; do
  grep -qF "$cmd" <<<"$SECTION" || { echo "✗ Quickstart 段缺命令：$cmd"; exit 1; }
  echo "  ✓ Quickstart 段含：$cmd"
done

echo
echo "✓ Spec-0026 端到端通过：README 最简用法/Quickstart 段位置正确、最短路径三行齐备。"
