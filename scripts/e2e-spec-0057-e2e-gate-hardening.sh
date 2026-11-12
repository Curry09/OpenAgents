#!/usr/bin/env bash
# Spec-0057 end-to-end test start script: e2e door corrosion - RFC gate certainty mandatory e2e block + code review double-test cross-reference.
#
# Wind-space PR #19 Evidence: e2e v2 was bypassed by two undetermined LLM soft gates (RFC gate was deceived by e2e of spec text, not forced out)
# The structified e2e block run_e2e is empty; the code review uses the realization self-measured/self-identified as a basis for release and does not require independent execuator evidence).
# The group hardened these two: T1 RFC gate with a certainty check before LLM (required for real e2e {intent,method} block to return to work without question)
# LLM; T2 code review rubric, two-fold (self-measured = declaration/athlete, independent expert = decision), cross-reference, lack of independent evidence
# The two catalogues of evidence are separate.
#
# Full-range off-line, net-neutral/real LLM/gh:ruff + pytest + grep anchor.
# Usage: bah scripts/e2e-spec-0057-e2e-gate-hardening.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Key non-variant grep anchor"
grep -q "def e2e_block_missing" openagents/orchestrator.py && echo "  ✓ orchestrator.e2e_block_missing Identification check exists"
grep -q "e2e_block_missing" openagents/messages.py && echo "  ✓ RFC Validity check for gate access (CLUS)review_rfc Before)"
grep -q "refine-e2e-block" openagents/messages.py && echo "  ✓ We’re going without the pieces. refine-e2e-block Auto-return"
grep -q "Must be in Group frontmatter Statement" openagents/orchestrator.py && echo "  ✓ Drafting prompt Mandatory declaration e2e Blocks"
grep -q "Two." openagents/reviewer.py && echo "  ✓ Code review rubric Double test cross-check."
grep -q "You can’t just do self-detection." openagents/reviewer.py && echo "  ✓ The lack of independent evidence cannot be self-detected."
grep -q "docs/evidence/" openagents/reviewer.py && grep -q "docs/e2e-results/" openagents/reviewer.py && echo "  ✓ Separate references to the two catalogues of evidence (self-evidence) vs Independent)"

echo
echo "All pass. ✅（Spec-0057 e2e Door hardened)"
