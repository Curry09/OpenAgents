#!/usr/bin/env bash
# RFC-0004 end-to-end test startup script: openagents vigil Vigil mode.
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest, full-scale mock, unattractive to real gh/claude.
#   2) Real smoke (not to be visible opt-in) - currently bound and gh logged when set OPENAGENTS_E2E_REAL = 1
#      In the warehouse: build a door-controlled tag-a-sue-sue run `openagents vigil --once` to make the Night's Watch discover and
#      Plot (real callup for claude) printout results. Claude Code CLI is needed.
#
# Usage:
#   rash scripts/e2e-rfc-0004-vigil.sh# Offline Only
#   OPENAGENTS_E2E_REAL = 1 bash scripts/e2e-rfc-0004-vigil.sh # with real smoke (which will drive real PR)
#
# Optional environment variable (real smoke segment):
#   VIGIL_LABEL door control tag, default optagents
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ Offline check passed. Real smoke has been passed. OPENAGENTS_E2E_REAL=1 Open."
  exit 0
fi

echo
echo "==> [2/2] Real smoke: belt tags issue → openagents vigil --once Self-discovery and handing out orders"
command -v gh >/dev/null || { echo "Require installation and login gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh Not registered, please first. gh auth login"; exit 1; }
command -v claude >/dev/null || { echo "Available Claude Code CLI（claude）"; exit 1; }

label="${VIGIL_LABEL:-openagents}"
# Ensure that door-control labels exist (where they exist, errors are ignored).
gh label create "$label" --description "openagents vigil The Night’s Watch will take it." >/dev/null 2>&1 || true

title="[e2e] RFC-0004 vigil Smoke. $(date -u +%Y%m%dT%H%M%SZ)"
echo "Create Tabs issue：$title（label=$label）"
uv run openagents issue "$title" \
  --body "By e2e-rfc-0004 Script creation: Please in README Add a line at the end 'vigil e2e ok'。" \
  --label "$label"

echo "Run the Vigil single wheel (--once）: Self-discovery of the issue And send a draft. RFCOpen draft PR …"
uv run openagents vigil --once --label "$label"

echo
echo "✓ Real smoke is done. Please come. GitHub Check: Whether the Night’s Watch is the above-mentioned issue It’s all on its own. PR。"
echo "  （PR Audit and consolidation performed manually——That’s exactly what I’m talking about. vigil The only point of human intervention in the design."
