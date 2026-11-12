#!/usr/bin/env bash
# Spec-0071 End-to-end test start-up script: harden the ownership of a "single Writer" file from the design-period statement to the operational-period security guard
# (Booking on Rust ownership model: liasing XOR mutability).
#
# Proof that the architecture contract was set up on the offline certainty chain (incent, see block spec e2e):
#   - Parsing layer (T1) spec.ownership: construct a single Writer Index (path  →  owner) from a spec group
#     Task) and according to it, "What is written on a masterless file in a changeset" (exceeded), and the creation (spec md /
#     (a) The permanent release of the OWERVIEW / ARCHITECTURE;
#   - Operational face (T2）spec CLI `ownership`: None --check Printing of the table of ownership;--check --group --changed Verify
#     Changeset, exit code 1 (CI/harness available for run-time guard);
#   - Hard-gate (T3) runtime.gates.assert_writes_owned:race hard-gate, harness after delivery, actual change set, ultra vires
#      → GateError (issue #71: Exceeding is rejected in the hierarchy, not by reviewer eye).
#
# Form description (evidence layer, philosophy 8): This group is** pure backend + CLI** modified, no produd-facing frontend navigable; self-checked
# Tool list does not have Playwright / Chrome DevTools MCP, so no browser e2e is set, following Spec-0059 /0060/0064 symmetry
# The measurement method (targeted pytest + CLI run + grep anchor). This is a pure internal mechanism change, and a proportionate automated test is sufficient for evidence.
#
# Usage:
#   bash scripts/e2e-spec-0071-single-writer-ownership-guard.sh
set -euo pipefail

cd "$(dirname "$0")/.."

fail() {
  echo "✗ Organisation$1" >&2
  exit 1
}

echo "==> [1/5] Offline certainty verification (%2)lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/5] Targeted single detector (desolator) + Hardlock. + CLI  Don’t touch the truth   LLM/Network/(In United States dollars)"
uv run --extra dev pytest -q \
  tests/test_spec_ownership.py \
  tests/test_gates_ownership.py \
  tests/test_spec_cli.py

echo
echo "==> [3/5] spec ownership Real run: One in this warehouse writer Tables 0071 Three. Task Attribution"
OWN_TABLE="$(uv run spec ownership)"
echo "$OWN_TABLE" | grep -Eq "0071/T1[[:space:]]+openagents/spec/ownership\.py" \
  || fail "Lack of a table of ownership 0071/T1 → openagents/spec/ownership.py"
echo "$OWN_TABLE" | grep -Eq "0071/T2[[:space:]]+openagents/spec/cli\.py" \
  || fail "Lack of a table of ownership 0071/T2 → openagents/spec/cli.py"
echo "$OWN_TABLE" | grep -Eq "0071/T3[[:space:]]+openagents/runtime/gates\.py" \
  || fail "Lack of a table of ownership 0071/T3 → openagents/runtime/gates.py"

echo
echo "==> [4/5] spec ownership --checkDeclaration file and creation release, no master writing rejected (exit code) 1）"
uv run spec ownership --check --group 0071 \
  --changed "openagents/spec/ownership.py,docs/specs/OVERVIEW.md" \
  || fail "Declaration Document + Generating should be released (exit code) 0）"
if uv run spec ownership --check --group 0071 --changed "openagents/spec/ownership.py,evil.py"; then
  fail "Exceeding authority evil.py Rejection (exit code) 1）, but commands return 0"
fi

echo
echo "==> [5/5] grep Oct.: Each of the three levels. spec-id Trace in position."
head -n 1 openagents/spec/ownership.py | grep -q "^# Spec-0071/T1" \
  || fail "openagents/spec/ownership.py The first line should read '# Spec-0071/T1' Comment"
grep -q "def assert_writes_owned" openagents/runtime/gates.py \
  || fail "openagents/runtime/gates.py We’re short of hard doors. assert_writes_owned"
grep -q '"ownership"' openagents/spec/cli.py \
  || fail "openagents/spec/cli.py Missing ownership Sub-order"

echo
echo "✓ Spec-0071 Offline certainty e2e All Green (T1 Parser + T2 CLI + T3 Hardlock)"
