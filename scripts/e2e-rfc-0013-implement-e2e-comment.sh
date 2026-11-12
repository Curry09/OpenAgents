#!/usr/bin/env bash
# RFC-0013 End-to-end Test Start Script: implement Before turning e2e script and using "No + Log"
# A signed PR comment is sent (RFC-0008 sign sign extension).
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest, full mock, not touch the true gh.
#   2) Real Practice (Remarkable) opt-in）—— Set OPENAGENTS_E2E_REAL=1 and give OPENAGENTS_E2E_PR=<n>
#      (a draft PR of refc-approved) execute `openagents implement <pr>` in gh login warehouse,
#      The PR adds a comment with the "#end-to-end test results" and ant sign.
#
# Usage:
#   rash scripts/e2e-rfc-0013-implement-e2e-comment.sh# Offline Only
#   OPENAGENTS_E2E_REAL=1 OPENAGENTS_E2E_PR=42 \
#     lash scripts/e2e-rfc-0013-implement-e2e-comment.sh# with real exercise
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ Offline validation passed. Real exercise has been skipped (set) OPENAGENTS_E2E_REAL=1 and OPENAGENTS_E2E_PR=<n> Open."
  exit 0
fi

echo
echo "==> [2/2] Real exercise:implement <pr> → The assertion. PR Add ’%1 ’## End-to-end test results” Sign comment"
command -v gh >/dev/null || { echo "Require installation and login gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh Not registered, please first. gh auth login"; exit 1; }
pr="${OPENAGENTS_E2E_PR:-}"
[[ -n "$pr" ]] || { echo "Please set OPENAGENTS_E2E_PR=<Already rfc-approved It’s... draft PR Numbering>"; exit 1; }

echo "--> Steps 1: Yes. PR #$pr Run! openagents implement(Celling) + Run! e2e + Comments on the outcome + Turn it back on."
uv run openagents implement "$pr"

echo "--> Steps 2: The assertion PR #$pr Add a new article with ”%1”## End-to-end test results ”and with agent Comments on signatures"
bodies="$(gh pr view "$pr" --json comments --jq '.comments[].body')"
if grep -q "## End-to-end test results" <<<"$bodies" \
  && grep -q "openagents:agent=" <<<"$bodies"; then
  echo "✓ PR #$pr ”with a signature”## The results of the end-to-end test are commented on."
else
  echo "✗ PR #$pr Missing signature## The results of the end-to-end test are commented:"
  echo "$bodies"
  exit 1
fi

echo
echo "✓ Real exercise complete:PR #$pr Comments with results of live run (with agent Signature,poll It’s not self-recycling."
echo "  Note: This script does not automatically close PR, please be in GitHub Up and clean."
