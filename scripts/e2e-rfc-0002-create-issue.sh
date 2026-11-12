#!/usr/bin/env bash
# RFC-0002 end-to-end test start script: a sub-command for openagents issue.
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest, full mock, not touch the true gh.
#   2) Real smoke (not to be visible opt-in) - currently bound and gh logged when set OPENAGENTS_E2E_REAL = 1
#      The warehouse actually creates a problem and then closes it with gh (avoids legacy).
#
# Usage:
#   rash scripts/e2e-rfc-0002-create-issue.sh# Offline Only
#   OPENAGENTS_E2E_REAL = 1 bash scripts/e2e-rfc-0002-create-issue.sh # with real smoke
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
echo "==> [2/2] Real smoke:openagents issue → gh Close"
command -v gh >/dev/null || { echo "Require installation and login gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh Not registered, please first. gh auth login"; exit 1; }

title="[e2e] RFC-0002 Smoke. $(date -u +%Y%m%dT%H%M%SZ)"
echo "Create issue：$title"
uv run openagents issue "$title" --body "By e2e-rfc-0002 Script is created automatically and can be safely closed."

# Finds the newly created issue number from gh and closes it to avoid leaving trash in the warehouse.
num="$(gh issue list --search "$title in:title" --state open --json number --jq '.[0].number')"
if [[ -n "${num:-}" && "$num" != "null" ]]; then
  echo "Shut down the smoke. issue #$num"
  gh issue close "$num" --comment "e2e Smoke finished, automatically off."
  echo "✓ True smoke through: created and closed issue #$num"
else
  echo "⚠ Could not locate the created issue(title search empty), please do so manually. GitHub Check and close:$title"
  exit 1
fi
