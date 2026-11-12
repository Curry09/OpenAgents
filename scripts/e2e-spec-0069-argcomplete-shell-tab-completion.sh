#!/usr/bin/env bash
# Spec-0069end-to-end test start script: complete for opengents CLI access aagcomplete Shell Tab.
#
# In the form of a pure CLI/backend (no produtt-facing frontend to navigation), no browser e2e is set, instead of offline certainty:
#   1) Offline certainty verification - ruff lint/format + tests/test_cli.py (argcomplete all mock, untouched shell/gh).
#   2) Full smoke - Shell Full Handshake for Run Aggcomplete (set _ARGCOMPLETE environment variable) with the assertion that `openagents <Tab>`
#      You can spit out all sub-commands, `openagents vigil --<Tab>` can spit out all options.
#   3) grep anchor - an elegant downgrade of cli.py by import + autocomplete (parser) call, argcomplete by pyproject depends on position.
#
# Usage:
#   bash scripts/e2e-spec-0069-argcomplete-shell-tab-completion.sh
set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$(pwd)"

echo "==> [1/3] Offline certainty verification (%2)lint + format + CLI (Modular Test)"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/test_cli.py

echo
echo "==> [2/3] Full smoke: simulation shell Shake hands, say sub-orders./Options Candidate"

# Aggcomplete shakes hands with shell patches by environment variable:
#   _ARGCOMPLETE=1 trigger completion branch
#   COMP_LINE / COMP_POINT Current command line and cursor position
#   Completes the completion result to fd8 (_ARGCOMPLETE_STDOUT_FILENAME specified file) and exit.
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
  echo "$subs" | grep -qx "$cmd" || { echo "✗ Suborder Complete $cmd"; echo "Actual:$subs"; exit 1; }
done
echo "✓ ①openagents <Tab> Complete All Subcommands"

opts="$(run_complete 'openagents vigil --')"
for opt in --interval --label --base --once --parallel --hold --skip --config; do
  echo "$opts" | grep -qx "$opt" || { echo "✗ vigil Options to fill the gap $opt"; echo "Actual:$opts"; exit 1; }
done
echo "✓ ②openagents vigil --<Tab> Complete All Options"

echo
echo "==> [3/3] grep Ocupity: Connecting and relying on position"
grep -q "import argcomplete" openagents/cli.py || { echo "✗ cli.py Missing argcomplete Import"; exit 1; }
grep -q "argcomplete.autocomplete(parser)" openagents/cli.py || { echo "✗ cli.py Missing autocomplete Call"; exit 1; }
grep -q "argcomplete" pyproject.toml || { echo "✗ pyproject.toml Missing argcomplete Dependency"; exit 1; }
echo "✓ ③Connect and rely on anchors."

echo
echo "✓ Spec-0069 End-to-end authentication is all passed."
