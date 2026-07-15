#!/usr/bin/env bash
# Spec-0069 端到端测试启动脚本：为 openagents CLI 接入 argcomplete Shell Tab 补全。
#
# 形态为纯 CLI/后端接线（无 product-facing 前端可导航），故不设浏览器 e2e，改用离线确定性测法：
#   1) 离线确定性验证 —— ruff lint/format + tests/test_cli.py（argcomplete 全 mock，不触真实 shell/gh）。
#   2) 补全冒烟 —— 真跑 argcomplete 的 shell 补全握手（设 _ARGCOMPLETE 环境变量），断言 `openagents <Tab>`
#      能吐出全部子命令、`openagents vigil --<Tab>` 能吐出全部选项。
#   3) grep 锚点 —— cli.py 的优雅降级 import + autocomplete(parser) 调用、pyproject 的 argcomplete 依赖就位。
#
# 用法：
#   bash scripts/e2e-spec-0069-argcomplete-shell-tab-completion.sh
set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$(pwd)"

echo "==> [1/3] 离线确定性验证（lint + format + CLI 单元测试）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/test_cli.py

echo
echo "==> [2/3] 补全冒烟：模拟 shell 补全握手，断言子命令/选项候选"

# argcomplete 通过环境变量与 shell 补全器握手：
#   _ARGCOMPLETE=1                触发补全分支
#   COMP_LINE / COMP_POINT        当前命令行与光标位置
#   补全结果写到 fd 8（_ARGCOMPLETE_STDOUT_FILENAME 指定的文件），并 exit。
run_complete() {
  local line="$1"
  local out
  out="$(mktemp)"
  _ARGCOMPLETE=1 \
  _ARGCOMPLETE_STDOUT_FILENAME="$out" \
  COMP_LINE="$line" \
  COMP_POINT="${#line}" \
    uv run --project "$repo_root" openagents 8>"$out" >/dev/null 2>&1 || true
  tr '\v\t ' '\n' < "$out"
  rm -f "$out"
}

subs="$(run_complete 'openagents ')"
for cmd in init vigil backfill-rfc issue release board report; do
  echo "$subs" | grep -qx "$cmd" || { echo "✗ 子命令补全缺 $cmd"; echo "实际：$subs"; exit 1; }
done
echo "✓ ①openagents <Tab> 补全全部子命令"

opts="$(run_complete 'openagents vigil --')"
for opt in --interval --label --base --once --parallel --hold --skip --config; do
  echo "$opts" | grep -qx "$opt" || { echo "✗ vigil 选项补全缺 $opt"; echo "实际：$opts"; exit 1; }
done
echo "✓ ②openagents vigil --<Tab> 补全全部选项"

echo
echo "==> [3/3] grep 锚点：接线与依赖就位"
grep -q "import argcomplete" openagents/cli.py || { echo "✗ cli.py 缺 argcomplete 导入"; exit 1; }
grep -q "argcomplete.autocomplete(parser)" openagents/cli.py || { echo "✗ cli.py 缺 autocomplete 调用"; exit 1; }
grep -q "argcomplete" pyproject.toml || { echo "✗ pyproject.toml 缺 argcomplete 依赖"; exit 1; }
echo "✓ ③接线与依赖锚点就位"

echo
echo "✓ Spec-0069 端到端验证全部通过。"
