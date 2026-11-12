#!/usr/bin/env bash
# Spec-0066/T1 -T3 End-to-end test start-up script: Phase Time - Wall clock per-case time extension (append-only event stream + multi-wheel reconstruction).
#
# Proof that the "wall clock phase timed the side road site + the inter-wheel time-long reconstruction" was set up on the offline definitive chain (incent, see spec e2e):
#   - T1 Timing Module: record append 5 is valid JSON + UTC ISO8601; injecting open/write drop abnormal  → record silent swallowing
#     No raise (incorrect); load_events jump-default line; Timelines multi-wheel recreate each case duration (case recurrence)
#     The end of the terminal 0; phase_stats exits the field at the limit of 0 for each verse p50/p90+ maximum end + interval precision.
#   - T2 vigil sidewalk site: timing.jsonl after tick Zonce produces dispatch/waiting-*/merging paragraphs;
#     _phase_of 4 values vedidididect x facts
#     The burial site is equal (fp by-pass, self-destructing without touching the fence); the merged section WAIT-ci (CI-wait) can be distinguished from the review-or-fix.
#   - T3 CLI: aa report for the constructed timing.jsonl output list subject time line + cross subject p50/p90 + "Accuracy Lower ="
#     Interval "; empty/missing file friendly hint, exit code 0.
#
# Form description (evidence stratification, philosophy 8): This group is ** pure backend burial point + polymer + CLI report**, no produd-facing frontend to navigate;
# List of Self-checked Tools: Playwright / Crope DevTools MCP, therefore, does not have browser e2e, following previous batch offline certainty (targeting)
# Single + grep anchor. Real, autonomous smoke-smoke (after `oa vigil --once` and `oa report` report) is recorded as a result acceptance in Runbook.
#
# Usage:
#   bash scripts/e2e-spec-0066-phase-timing-wall-clock.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] Offline certainty verification (%2)lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] timing Modules + vigil Put some bypass. + CLI report Targeted singles"
uv run --extra dev pytest -q \
  tests/test_runtime_timing.py \
  tests/test_recipe_vigil_timing.py \
  tests/test_recipe_vigil.py \
  tests/test_cli_timing.py \
  tests/test_cli.py

echo
echo "==> [3/4] spec Verify + Generating without drift"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/4] grep anchor:timing nil vigil Dependence (no cycle) import）/ There’s only two places to bury. / record I’m not gonna let you go."

fail() {
  echo "✗ Organisation$1" >&2
  exit 1
}

# 4a. Timing module recipes.vigil** zero dependency** (case is pure string, logic is left) - uncycled report.
grep -qE 'recipes|vigil' openagents/runtime/timing.py \
  && fail "runtime/timing.py I quote. recipes/vigil(Count on zero, otherwise circular import）"

# 4b. Timeline Writing Point**Only** vigil.py I'm going to get a new one._consider Producers / _reconcile worker）The long term _record_timing
# The next step is to get the rest of the world to get the rest of the world, and to get the rest of the world to get the rest of the world.
grep -q "def _record_timing" openagents/recipes/vigil.py \
  || fail "vigil Missing _record_timing By-pass. helper"
uv run --extra dev python -c "
import inspect
from openagents.recipes import vigil
assert '_record_timing(' in inspect.getsource(vigil._consider), 'Producers _consider No road cover phase'
assert '_record_timing(' in inspect.getsource(vigil._reconcile), 'worker _reconcile No road cover phase'
" || fail "Two of them found their throats hanging. _record_timing Bury it."

# 4c. record is in position for error - failure to write is a single time, and never turns the Vigil.
uv run --extra dev python -c "
import inspect
from openagents.runtime import timing
src = inspect.getsource(timing.record)
assert 'except' in src and 'return' in src, 'timing.record None except ”The wrong side of the wall.”'
" || fail "timing.record I’m not in the right place."

# 4d. Event stream file and status file** file level zero-coup** (idea 10): Timing down timing.jsonl without touching runtime-state.json.
grep -q 'timing.jsonl' openagents/runtime/timing.py \
  || fail "timing Unset timing.jsonl"
grep -q 'runtime-state.json' openagents/runtime/timing.py \
  && fail "timing.py Touched. runtime-state.json(to be Zero-Coded)"

echo "✓ grep All anchor points pass:timing nil vigil   Dependence, burying just   _consider/_reconcile Two places.record ”And the wrong side,"
echo "  timing.jsonl with runtime-state.json File-level zero-collation"
echo
echo "✅ Spec-0066 Offline e2e All green."
