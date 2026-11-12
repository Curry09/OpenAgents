#!/usr/bin/env bash
# Spec-0030 End-to-end test start-up script: init front end e2e environmental medical examination (test browser MCP+ permissions released, unblocked)
# + Conditional Browner-e2e method paper in (issue #85).
#
# Hermetic - no true claude / GitHub. Three paragraphs:
#   1) Offline certainty validation (ruff lint/format + pytest, round).
#   2) Medical examination of two states: ~/. claude.json + OPENAGENTS_PERMISSION_MODE under a HOME stake,
#      The "miss" report is supposed to contain installation commands / not all release warnings / report settings, unblocked (render not drop);
#      "Satisfaction" contains two gills and does not contain an installation order.
#   3) Methodology paper: grep orchestrator.py/ reviewer.py confirmation condition "Absent Browser Tool  →  Priority Browser
#      The words "e2e" have been inserted into two templates.
#
# Usage:
#   bash scripts/e2e-spec-0030-init-env-check.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/3] Medical examination of two states: missing / Satisfactory Report Claim (Playing HOME + Permissions env）"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- Missing state: ~. claude.json without mcpServers + Default permissions (acceptEdits) ---
MISSING_HOME="$TMP/missing"
mkdir -p "$MISSING_HOME"
echo '{"mcpServers": {}}' > "$MISSING_HOME/.claude.json"
MISSING_OUT="$(HOME="$MISSING_HOME" OPENAGENTS_PERMISSION_MODE= \
  uv run python -c 'from openagents import envcheck; print(envcheck.check().text)')"
echo "$MISSING_OUT"
grep -qF "claude mcp add playwright" <<<"$MISSING_OUT" \
  || { echo "✗ Missing State Report Missing playwright Install command"; exit 1; }
grep -qF "export OPENAGENTS_PERMISSION_MODE=bypassPermissions" <<<"$MISSING_OUT" \
  || { echo "✗ Missing State Report Missing export Settings"; exit 1; }
grep -qF "Not All Release" <<<"$MISSING_OUT" \
  || { echo "✗ Missing state report missing full release warning"; exit 1; }
echo "  ✓ Missing state: contains installation orders + Unfull Release Warning + export Settings"

# --- content: ~. claude.json with playwright + chrome-devtools + Release All ---
OK_HOME="$TMP/ok"
mkdir -p "$OK_HOME"
echo '{"mcpServers": {"playwright": {}, "chrome-devtools": {}}}' > "$OK_HOME/.claude.json"
OK_OUT="$(HOME="$OK_HOME" OPENAGENTS_PERMISSION_MODE=bypassPermissions \
  uv run python -c 'from openagents import envcheck; print(envcheck.check().text)')"
echo "$OK_OUT"
[ "$(grep -cF "✓" <<<"$OK_OUT")" -eq 2 ] \
  || { echo "✗ Two articles should be included in the compliance report ✓"; exit 1; }
grep -qF "claude mcp add" <<<"$OK_OUT" \
  && { echo "✗ The satisfaction report should not contain an installation order"; exit 1; }
echo "  ✓ Satisfaction: two ✓, without installation orders"

# --- Non-blocking: medical examination all_ok Boolean,check() No drop (miss exit code) 0） ---
HOME="$MISSING_HOME" OPENAGENTS_PERMISSION_MODE= \
  uv run python -c 'from openagents import envcheck; r = envcheck.check(); assert r.all_ok is False'
echo "  ✓ Non-blocking: missing state check() No, no, no, no, no, no, no, no, no.all_ok=FalseQuit Code 0"

echo
echo "==> [3/3] Injection of methodological papers:grep orchestrator.py / reviewer.py"
grep -qF "Browser Tool" openagents/orchestrator.py \
  || { echo "✗ orchestrator.py Missing browser-e2e Conditional Guidance"; exit 1; }
grep -qF "Frontend e2e" openagents/orchestrator.py \
  || { echo "✗ orchestrator.py Missing Frontend e2e』Guide"; exit 1; }
grep -qF "Browser Tool" openagents/reviewer.py \
  || { echo "✗ reviewer.py rubric Missing browser-e2e Conditional Guidance"; exit 1; }
echo "  ✓ orchestrator.py(draft) + Reverse Completion) with reviewer.py rubric Both Conditional browser-e2e Guide"

echo
echo "✓ Spec-0030 End-to-end through:init Environmental checkup. + Unblocked + The methodology paper is available in the closed ring."
