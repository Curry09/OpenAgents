#!/usr/bin/env bash
# Spec-0070 端到端测试启动脚本：openagents 自更新预检（每次命令前检测并拉取最新版：快照重装 + 重执行）。
#
# 形态为纯 CLI/后端接线（无 product-facing 前端可导航），故不设浏览器 e2e，改用离线确定性测法：
#   1) 离线确定性验证 —— ruff lint/format + 针对性 pytest（selfupdate 注入 fake run/execvp，全程不触真实
#      git/uv/网络/shell；cli 接线测 precheck 打桩为 no-op 时正常行为不变）。
#   2) 守卫冒烟 —— 真跑 `OPENAGENTS_NO_SELF_UPDATE=1 openagents`（硬开关关闭整段预检），断言 CLI 照常起、
#      无命令仍打印帮助并退 2，且绝不触网自更新（离线安全）。
#   3) grep 锚点 —— cli.py 的 precheck 调用；selfupdate.py 的三把守卫/ff-only/execvp；conftest 的硬开关。
#
# 用法：
#   bash scripts/e2e-spec-0070-self-update-precheck.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] 离线确定性验证（lint + format + 针对性 pytest）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/test_selfupdate.py tests/test_cli.py

echo
echo "==> [2/3] 守卫冒烟：硬开关关闭预检，CLI 照常起、不触网自更新"
# OPENAGENTS_NO_SELF_UPDATE=1 → precheck 一进来即短路；无命令仍走 build_parser → 打印帮助 → 退 2。
set +e
OPENAGENTS_NO_SELF_UPDATE=1 uv run openagents >/dev/null 2>&1
code=$?
set -e
[ "$code" -eq 2 ] || { echo "✗ 硬开关下 openagents 无命令应退 2，实得 $code"; exit 1; }
echo "✓ ①OPENAGENTS_NO_SELF_UPDATE=1 下 CLI 照常起（无命令退 2）、预检整段短路"

echo
echo "==> [3/3] grep 锚点：接线 / 守卫 / 硬开关就位"
grep -q "selfupdate.precheck(argv=sys.argv)" openagents/cli.py || { echo "✗ cli.py 缺 precheck 接线"; exit 1; }
grep -q "OPENAGENTS_NO_SELF_UPDATE" openagents/utils/selfupdate.py || { echo "✗ selfupdate 缺硬开关"; exit 1; }
grep -q "OPENAGENTS_SELFUPDATE_DONE" openagents/utils/selfupdate.py || { echo "✗ selfupdate 缺重执行守卫"; exit 1; }
grep -q -- "--ff-only" openagents/utils/selfupdate.py || { echo "✗ selfupdate 缺 pull --ff-only"; exit 1; }
grep -q "execvp" openagents/utils/selfupdate.py || { echo "✗ selfupdate 缺 execvp 重执行"; exit 1; }
grep -q "OPENAGENTS_NO_SELF_UPDATE" tests/conftest.py || { echo "✗ conftest 缺全局硬开关"; exit 1; }
echo "✓ ②接线 / 守卫 / 硬开关锚点就位"

echo
echo "✓ Spec-0070 端到端验证全部通过。"
