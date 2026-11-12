#!/usr/bin/env bash
# Spec-0059/T3 End-to-end test start script: Comment regulates alignment of PEP 257/PEP 8/ Google - Module + function doescstring compliance on two levels
# Lets the process generate a natural compliance note.
#
# Proof that the architecture contract was set up on the offline certainty chain (incent, see block spec e2e):
#   - T2: PROMPT is injected to generate/ modify animators / data / replier
#     Two-layer docstring rule anchor - Modular Layer (Exports: / Ban ""#" / spec-id up to # Comment)+Function Layer
#     (AGs: / RETURNS: / Raises: / / Quest) and trace three authoritative criteria (PEP 257 / PEP 8 / Google);
#   - Sample Layer (T3): runtime/engine.py module docsturing remove ""# writing, spec-id up to top of file# Comment line,
#     First line clean English digest, supplement Exports: Columns run_agent/AgentOutputError；recipes/vigil.py::run_vigil Function
#     Docstring Add Args: (Aggregations) with Raises:, Summary in the line of prayer, spec in the second line.
#
# Form description (evidence layer, concept 8): This group is** pure document + hint + internal sample** with no produd-facing frontend
# Navigator; Self-checking Tool List does not have Playwright / Chrome DevTools MCP, so no browser e2e, Spec-0060/0064 offline
# The determinative test (targeted pytest + grep anchor). This is a pure internal modification, and a proportionate automated test is sufficient for evidence.
#
# Note (T1 Undetainable - Inviolable Border): two code-comment-conventions.mds to be modified by spec T1 are both in `.claude/`
# Permissions are controlled under the directory (see spec Drawbacks / Unresolved ".claude/ write permissions". This environment is hard bound to write the directory, so T1
# The two files that were clearly skipped, and the script was not grep; the landed T2 (tip)+T3 (sample) is covered as follows.
#
# Usage:
#   bash scripts/e2e-spec-0059-docstring-conventions.sh
set -euo pipefail

cd "$(dirname "$0")/.."

fail() {
  echo "✗ Organisation$1" >&2
  exit 1
}

echo "==> [1/4] Offline certainty verification (%2)lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] Targeted single measurements (injection of hints) + Sample docstring  Don’t touch the truth   LLM/Network/(In United States dollars)"
uv run --extra dev pytest -q \
  tests/test_agents_docstring_rule.py \
  tests/test_docstring_samples.py

echo
echo "==> [3/4] grep Oct: Phrasing Layer (Phrasing)T2）Two floors. docstring The rules have been injected into three code generations. agent"
for f in openagents/agents/implementer.py openagents/agents/drafter.py openagents/agents/replier.py; do
  grep -q "Exports:" "$f" || fail "$f Missing Modular Layer anchor Exports:"
  # Source code with transposed \" \" \"# load (written 3 quotes close the Template string earlier); renders to .template, ""#.
  grep -qF '\"\"\"#' "$f" || fail "$f Unenacted \"\"\"# ”Write” expression"
  grep -q "Args:" "$f" || fail "$f Missing Function Omnips Args:"
  grep -q "Raises:" "$f" || fail "$f Missing Function Omnips Raises:"
  grep -q "I pray to you." "$f" || fail "$f The ”Punishment” of the missing functional anchor"
  grep -q "PEP 257" "$f" || fail "$f Lack of authority standard references PEP 257"
done

echo
echo "==> [4/4] grep Omnibus: Sample Level (Performance Layer)T3）engine Modules docstring None \"\"\"# + spec-id Move Up # Comment"
# engine.py module docstring no longer has a ""# sequence (# will enter __doc__ contamination help()).
grep -q '"""#' openagents/runtime/engine.py && \
  fail 'openagents/runtime/engine.py Still """# Writing (should move up) spec-id To Top of File # Comment)'
# Spec-id falls on the first line of the top of the file # Comment.
head -n 1 openagents/runtime/engine.py | grep -q "^# Spec-0060/T2" || \
  fail "openagents/runtime/engine.py The first line should read '# Spec-0060/T2' Comment"
# Moduledocstring adds Exports: Column export objects.
grep -q "Exports:" openagents/runtime/engine.py || fail "engine Modules docstring Missing Exports:"

echo
echo "✓ Spec-0059 Offline certainty e2e All Green (T2 prompt + T3 (a) Sample examples;T1 Because .claude/ Write Border Skipping)"
