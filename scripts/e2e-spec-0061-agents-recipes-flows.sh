#!/usr/bin/env bash
# Spec-0061/T1 -T4 End-to-end test start-up script: batch double-ups vigil/poll_comments/fleet 3 circular recipe +
# triager/replier 2 new agent + utils complete stable Import side, complete journey (the old stack is not moving with its 11 test stakes).
#
# Proof that the architecture contract was set up on the offline certainty chain (incent, see block spec e2e):
#   - vigil review only uses ** structured decision** by actionable  → dispatch / No_park hang needs-human,
#     The #3Rs (local run/ remote branch/ needs-human tag) confirm "new" and self-zero business judgement.
#   poll_comments review is a pure control stream of "post-galler review of new human beings" and "shows to sign back and push the traveler"
#     (a) The single PR failure error segregation does not drag the entire wheel;
#   - Fleet recipe reuse old Fleet controller (injecting new spahn), one plan one-street process to run new spasves, vigil;
#   - triager/replier does not have a logic (zero dev, zero subproces); three recipes do not touch gh/git (only via utils/engine).
#
# Form description (evidence layer, philosophy 8): This group is** pure backend **, no produd-facing frontend to navigable; self-checked
# Tool List: No Playwright / Chrome DevTools MCP, so no browser e2e, instead of offline certainty (coding route)
# Single + zero logic/ zero IO grep anchor point. Real multi-gauge smoke (`oa vigil-new` / `oa fleet` run through + PRCI All Green)
# As a result of the acceptance, this offline script is not inserted in the Phase-3 human examination/runbook records.
#
# Usage:
#   bash scripts/e2e-spec-0061-agents-recipes-flows.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] Offline certainty verification (%2)lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/3] Batch 2 contractual route + Targeted and single-scale measurements"
uv run --extra dev pytest -q \
  tests/test_agents_triager_replier.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_poll_comments.py \
  tests/test_recipe_fleet.py \
  tests/test_cli_new_stack.py

echo
echo "==> [3/3] Zero Logic / nil IO grep anchor"

fail() {
  echo "✗ Organisation$1" >&2
  exit 1
}

# 3a. Two new agent modules: Contain Template (+ OUTPUT_SCHEMA) (reverse form of the hint layer).
for a in triager replier; do
  f="openagents/agents/${a}.py"
  grep -q "Template(" "$f" || fail "$f Missing Template("
  grep -q "OUTPUT_SCHEMA" "$f" || fail "$f Missing OUTPUT_SCHEMA"
done

# 3b. Two new agent modules: zero logic (no function definition), zero IO (no subprocess).
#     The git/gh word in the propt string is** (delivery protocol)**, not Python call - anchor real
#     Logical/IO sign(def / subprocess), without prejudice to prompt text.
for a in triager replier; do
  f="openagents/agents/${a}.py"
  grep -nE '^\s*(async\s+)?def ' "$f" && fail "$f Include function definition (agent Zero logic)"
  grep -nE 'import subprocess|subprocess\.' "$f" && fail "$f Ham subprocess（agent Zero. IO）"
done

# 3c. recide: no subproces, no direct import original openagents.github/ openagents.workspace
#     (Users only stable face + runtime.engine/context route, version control/gh machine operation is all at utils).
for r in vigil poll_comments fleet; do
  f="openagents/recipes/${r}.py"
  grep -nE 'import subprocess|subprocess\.' "$f" && fail "$f Ham subprocess Direct Call"
  grep -nE 'openagents\.github|openagents\.workspace' "$f" && fail "$f Direct import Original github/workspace(Let’s go. utils）"
done

# 3d. Cycle / poll_comments: no gh/git font shell call (fleet reuse old controller,
#     It doescstring refers to gh text, so it does not include the word-volume anchor, which is covered by the subprocess anchor in 3c).
for r in vigil poll_comments; do
  f="openagents/recipes/${r}.py"
  grep -nE '"gh"|"git"|`gh |`git ' "$f" && fail "$f Ham gh/git Font Call"
done

echo "✓ grep All anchor points pass:triager/replier Zero logic zero. IOThree. recipe Zero Original gh/git Straight"
echo
echo "✅ Spec-0061 Offline e2e All green."
