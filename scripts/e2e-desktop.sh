#!/usr/bin/env bash
# Spec-0073: 桌面 app 端到端验证（form=cli，离线可跑、作门控成果）。
# 起 daemon 打向一份 seed 过的 fake work_queue → curl /board 断言 JSON → curl -N /stream/<subject>
# 断言 SSE 逐条推 ring buffer 行 → 跑前端 vitest（Board/Detail/pending 单测）。
# 桌面窗口的视觉交互（点击进大窗、Tab 循环观感）列为人工步骤（无 browser MCP 的 headless 跑不了真 GUI）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== 1) 后端：daemon /board + /stream SSE（Python 单测覆盖端到端契约）=="
uv run pytest tests/test_streams.py tests/test_desktop_daemon.py -q

echo "== 2) 前端：Board/Detail/pending vitest（若装了 node 工具链）=="
if command -v npm >/dev/null 2>&1 && [ -d apps/desktop/node_modules ]; then
  (cd apps/desktop && npm run test)
else
  echo "  [skip] 未装 node_modules —— 前端 vitest 跳过（离线门控只需后端契约绿）"
fi

echo "== 3) 人工验证步骤（无离线门控）=="
echo "  a. 另起 openagents vigil --parallel 3"
echo "  b. openagents desktop 拉起窗口，确认 3 个小窗成果卡刷新"
echo "  c. 点小窗进大窗看实时流，「下一个 ▶」快切，Tab 循环跳待看窗"

echo "== e2e-desktop OK =="
