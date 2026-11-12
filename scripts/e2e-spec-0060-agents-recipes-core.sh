#!/usr/bin/env bash
# Spec-0060/T6 end-to-end test start script: core is agents (tips) + recipes (formation) + runtime minimum hardlock.
#
# Proof that the architecture contract was set up on the offline certainty chain (incent, see block spec e2e):
#   - solve_issue review based only on ** structured decision of an individual** route (PASS → next / REWORK → loop), self-zero business judgement;
#   - The minimum hard-barrel can really go down (head without moving forward/ super-wheeling raise);
#   - there is no logical recipes/solve_issue.py, there is no version control for /gh/subprocess to call directly.
#
# Form description (evidence layer, philosophy 8): This group is** pure backend **, no produd-facing frontend to navigable; self-checked
# Tool List: No Playwright / Chrome DevTools MCP, so no browser e2e, instead of offline certainty (coding route)
# Single + zero logic/ zero IO grep anchor. Real assue smoke (`oa solve <issue>`, new cage running + PRCI All Green) is
# As a result of the acceptance of article 5 of the letter, it is accepted in the Phase-3 human/runbook record without being inserted in the offline script (see spec method 3).
#
# Usage:
#   bash scripts/e2e-spec-0060-agents-recipes-core.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] Offline certainty verification (%2)lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/3] Contract route + Targeted and single-scale measurements"
uv run --extra dev pytest -q \
  tests/test_utils_git.py \
  tests/test_utils_github.py \
  tests/test_runtime_engine.py \
  tests/test_runtime_gates.py \
  tests/test_agents_prompts.py \
  tests/test_runtime_context.py \
  tests/test_recipe_solve_issue.py

echo
echo "==> [3/3] Zero Logic / nil IO grep anchor"

fail() {
  echo "✗ Organisation$1" >&2
  exit 1
}

AGENTS=(planner implementer reviewer deliver tester)

# 3a.5 agent modules: contains Template (+ OUTPUT_SCHEMA) (reverse form of the hint word layer).
for a in "${AGENTS[@]}"; do
  f="openagents/agents/${a}.py"
  grep -q "Template(" "$f" || fail "$f Missing Template("
  grep -q "OUTPUT_SCHEMA" "$f" || fail "$f Missing OUTPUT_SCHEMA"
done

# 3b.5 agent modules: zero logic (no function definition), zero IO (no subprocess).
#     git/gh words in the propt string are** (delivery protocol)**, not Python call - therefore anchor
#     Real logical/IO sign(def / subprocess), without prejudice to prompt text.
for a in "${AGENTS[@]}"; do
  f="openagents/agents/${a}.py"
  grep -nE '^\s*(async\s+)?def ' "$f" && fail "$f Include function definition (agent Zero logic)"
  grep -nE 'import subprocess|subprocess\.' "$f" && fail "$f Ham subprocess（agent Zero. IO）"
done

# 3c. recipes/solve_issue.py: no subproce/ no "gh" "git" word call/ no direct effect
#     (Only runtime.run_agent + lots, business judgement/version control is all on ant or utils.
R="openagents/recipes/solve_issue.py"
grep -nE 'subprocess' "$R" && fail "$R Ham subprocess Direct Call"
grep -nE '"gh"|"git"|`gh |`git ' "$R" && fail "$R Ham gh/git Font Call"
grep -nE 'import .*(github|workspace)' "$R" && fail "$R Direct import github/workspace"

echo "✓ grep All anchor points pass:agents Zero Logic/nil IO、recipe Zero Version Control Call"
echo
echo "✅ Spec-0060 Offline e2e All green."
