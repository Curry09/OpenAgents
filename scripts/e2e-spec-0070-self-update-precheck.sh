#!/usr/bin/env bash
# Spec-0070 end-to-end test start script: openagents update precheck (test and pull up the latest version before each command: snapshot reload + re-execut).
#
# In the form of a pure CLI/backend (no produtt-facing frontend to navigation), no browser e2e is set, instead of offline certainty:
#   1) Offline certainty verification - ruff lint/format+ Target pytest(selfupdate) injection fake run/execvp, untouched for all
#      git/uv/ network/shell; cli connection precheck to no-op without change in normal behaviour).
#   2) Guard smoke - Run `OPENAGENTS_NO_SELF_UPDATE=1 openagents` (hard switch off whole pre-screen) and assert that CLI is on the same level,
#      Print help and back 2 without command and never touch the net for self-renewal (offline security).
#   3) grep anchor —— cli.py It's... precheck Call;selfupdate.py Three guards./ff-only/execvp；conftest The hard switch.
#
# Usage:
#   bash scripts/e2e-spec-0070-self-update-precheck.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] Offline certainty verification (%2)lint + format + Targeted pytest）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/test_selfupdate.py tests/test_cli.py

echo
echo "==> [2/3] Guard smokes: hard switch off pre-screening,CLI You’re gonna be up to date, you know, you’re gonna be up to date."
# OPENAGENTS_NO_SELF_UPDATE = 1  →  precheck short path as soon as you enter; still without order build_parser  →  print help back 2.
set +e
OPENAGENTS_NO_SELF_UPDATE=1 uv run openagents >/dev/null 2>&1
code=$?
set -e
[ "$code" -eq 2 ] || { echo "✗ Hard switch. openagents No orders to retreat. 2- That’s right. $code"; exit 1; }
echo "✓ ①OPENAGENTS_NO_SELF_UPDATE=1 Down CLI As usual (no order to retreat) 2）Pre-screening the entire short circuit"

echo
echo "==> [3/3] grep Intern: Connect / Guards. / Hard switch in position."
grep -q "selfupdate.precheck(argv=sys.argv)" openagents/cli.py || { echo "✗ cli.py Missing precheck Connect"; exit 1; }
grep -q "OPENAGENTS_NO_SELF_UPDATE" openagents/utils/selfupdate.py || { echo "✗ selfupdate Hard Switch missing"; exit 1; }
grep -q "OPENAGENTS_SELFUPDATE_DONE" openagents/utils/selfupdate.py || { echo "✗ selfupdate We’re short of guards."; exit 1; }
grep -q -- "--ff-only" openagents/utils/selfupdate.py || { echo "✗ selfupdate Missing pull --ff-only"; exit 1; }
grep -q "execvp" openagents/utils/selfupdate.py || { echo "✗ selfupdate Missing execvp Re-enforcement"; exit 1; }
grep -q "OPENAGENTS_NO_SELF_UPDATE" tests/conftest.py || { echo "✗ conftest Lack of global hard switches"; exit 1; }
echo "✓ ②Connect / Guards. / Hard switch anchor in position."

echo
echo "✓ Spec-0070 End-to-end authentication is all passed."
