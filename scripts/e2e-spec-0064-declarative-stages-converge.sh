#!/usr/bin/env bash
# Spec-0064/T1 -T6 End-to-end test start script: curtailes scripts to vigil+issue - declaration forms YamL definition
# agent/human/skip stage is + set up by a tri-state policy route + CI/e2e/review to retort back ring + recipes layer 6  → 3
#
# Proof that the architecture contract was set up on the offline certainty chain (incent, see block spec e2e):
#   - Configure Layer. openagents/openagents.yml as a single source: Validisation of values per gate in 3-state (conflict/merge rejected sskip,
#     rfc only agent/skip, hard-gate access status projects, "No Zero-Clock" guard refused:skip+merge:at,
#     rifc:skip override combined with a silo of override
#   - Layer run_vigil Press the infusion. config The Three-State Claim agent/human/skip Three branches; merging water flow lines conflict→ci→
#     e2e→review→merge (a) Order,conflict I'm reading. CI First sentence. mergeable；CI/e2e/review Failure by Uniting Back to Ring
#     implementer iterative (re-entry from next round); certainty hard-gates (round_cap) are not stages;
#   - I'll take it from here. recipes/ Only left {stages,vigil,backfill,__init__}.py;remoted recipe（solve_issue/merge_pr/
#     poll_comments/rfc_lifecycle/fleet) and agents.planner n n n n n n n n/ n/ n/ n/ n; stages altab functions are visible
#     identity.post_signed_comment leaks edit supplement (not just warn) to close the loop.
#
# Form Description (evidence stratification, philosophy 8): This group is** pure backend configuration + configuration + CLI consolidation**, no produd-facing frontend
# Navigator; list of self-checked tools: no Playwright / Crope DevTools MCP, therefore no browser e2e, following the first four batches of offline certainty
# Surveying (indentary route alone) + grep The anchor. Real auto-smoking.`oa vigil` Use Minimum openagents.yml Run! issue→PR、
# PR CI All Green) as a result acceptance in Phase-3 person/runbook record, without being inserted in this offline script.
#
# Usage:
#   bash scripts/e2e-spec-0064-declarative-stages-converge.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] Offline certainty verification (%2)lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] Configure Layer + Layer + CLI The target-specific test."
uv run --extra dev pytest -q \
  tests/test_agent_config.py \
  tests/test_recipe_stages.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_backfill.py \
  tests/test_cli_new_stack.py \
  tests/test_cli.py \
  tests/test_agents_prompts.py

echo
echo "==> [3/4] spec Verify + Generating without drift"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/4] grep anchor:recipes Layer 6→3 Zero. + Zero nudity. import + Nine-atom visual acceptance + Sign closed circle"

fail() {
  echo "✗ Organisation$1" >&2
  exit 1
}

# 4a. recipes/ {stages,vigil,backfill,__init__}.py (6  → 3 %3 )
present="$(cd openagents/recipes && ls -1 *.py | sort | tr '\n' ' ')"
expected="__init__.py backfill.py stages.py vigil.py "
[ "$present" = "$expected" ] || fail "recipes/ The content should read {__init__,backfill,stages,vigil}.py, is:$present"

# 4b. Full library for ** nudit force** of deleted recide / agents.planner (docstrining/note does not count).
# Sweep only the .py source (--include): Excludes the text references of .pyc caches and scripts.
if grep -rnE --include='*.py' \
  "from openagents\.recipes\.(solve_issue|merge_pr|poll_comments|rfc_lifecycle|fleet) import|import openagents\.recipes\.(solve_issue|merge_pr|poll_comments|rfc_lifecycle|fleet)|from openagents\.recipes import [a-z_, ]*\b(solve_issue|merge_pr|poll_comments|rfc_lifecycle|fleet)\b|from openagents\.agents import [a-z_, ]*\bplanner\b|import openagents\.agents\.planner|agents\.planner\b" \
  openagents/ tests/ 2>/dev/null; then
  fail "Existing & Deleted recipe / agents.planner Naked. import"
fi

# 4c. stages altruistic reference (keyword-only:def line or immediately following line containing '*,').
for fn in triage rfc implement review deliver conflict ci e2e merge; do
  grep -qE "^def ${fn}\(" openagents/recipes/stages.py || fail "stages.py Atom Missing Functions ${fn}"
  sig="$(grep -A1 "^def ${fn}(" openagents/recipes/stages.py | tr -d ' \n')"
  case "$sig" in
    *"*,"*) : ;;
    *) fail "stages.${fn} Non-keywords-only(Deficit) '*,', may include position parameters)" ;;
  esac
done

# 4d. Three recide not directly import original github/workspace, no subproces straight (go utils stabilize face).
for r in stages vigil backfill; do
  f="openagents/recipes/${r}.py"
  grep -nE 'import subprocess|subprocess\.' "$f" && fail "$f Ham subprocess Direct Call"
  grep -nE 'openagents\.workspace' "$f" && fail "$f Direct import Original workspace(Let’s go. utils）"
done

# 4e. Sign closed loop: identity.post_signed_comment synced and verified the missing signature  →  supplementary signature (not just warn).
grep -q "_verify_signature_or_fix" openagents/utils/identity.py \
  || fail "identity Unsync-verified missing signature _verify_signature_or_fix(Constraint)③）"
# Sign post_comment (a genuine additional signature comment) and not only warnings.warn.
awk '/def _verify_signature_or_fix/,/^def [^_]/' openagents/utils/identity.py | grep -q "post_comment" \
  || fail "_verify_signature_or_fix Not completed (due) post_comment Add a sign comment, not just warn）"

echo "✓ grep All anchor points pass:recipes 6→3Zero nudity. importThe nine atoms, the sign closed ring."
echo
echo "✅ Spec-0064 Offline e2e All green."
