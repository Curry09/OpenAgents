#!/usr/bin/env bash
# Spec-0073: Desktop app end-to-end validation (form=cli, run offline, door-to-door results).
# From daemon to a sighted fake work_queue  → curl /board assert that JSON  → curl-N/stream/<subject>
# The SSE is supposed to push the line round butler round the front end vitest (Board/Detail/pending single-scale)
# Visual interaction of desktop windows (clicking on a big window, Tab loop view) is classified as a manual step (heatherless without browser MCP cannot run true GUI).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== 1) Backend:daemon /board + /stream SSE（Python Single-covered end-to-end contract)=="
uv run pytest tests/test_streams.py tests/test_desktop_daemon.py -q

echo "== 2) Frontend:Board/Detail/pending vitest”If you’re loaded, node Tool Chain)=="
if command -v npm >/dev/null 2>&1 && [ -d apps/desktop/node_modules ]; then
  (cd apps/desktop && npm run test)
else
  echo "  [skip] Not installed node_modules —— Frontend vitest Skip (Left door only back-end contract green)"
fi

echo "== 3) Manual validation steps (on-line door control)=="
echo "  a. Another openagents vigil --parallel 3"
echo "  b. openagents desktop Pull up the window, confirm. 3 A small window result card refreshed"
echo "  c. ”Show a little window into the big window and see a real-time flow.” ▶」Cut it.Tab   Clock to the window  "

echo "== e2e-desktop OK =="
