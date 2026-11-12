#!/usr/bin/env bash
# Spec-0040 end-to-end test start script: Note book drive + independent execution + evidence evaluation door control (Phaase 1 skeleton) hermetic closed loop.
#
# The group upgraded e2e from "The Realmer Writes Script, Implement, Label, No Door Control" to a front door-controlled water line in front of the merge:
# Spec declares e2e intent  →  final draft runbook  →  independent execuator by form (cli/api/backend)
# • Evidence gate reviewer takes RFCs with intent to control the merger against the evidence door (PASS release, FAIL go itsate (reason=e2e), and fill K up).
#
# Two parts, full ** netless, unreal LLM, unreal gh, unreal git far **:
#   1) Offline certainty (default) - ruff lint/format + pytest package, overspec e2e field/validate
#      (test_spec_*), execuator (test_executor), evidence gate (test_evidence_gate), reviewer duty gate
#      Single measurements of test_reviewer, test_orchestrator/test_messages.
#   2) Offline Closed Loop Exercise (Default Execution) - Drive real execuator + evidence_gate pipe, group dogfood
#      The three accepted and accepted acts that are self-planned e2e: a cli runbook  → execuator ran and put the evidence into docs/e2e-results/ <pr>/;
#      The evidence “intention” is not reached, the evidence is sealed, the evidence is closed, and the evidence is closed, the evidence is closed, and the evidence is closed, the PASS is closed.
#
# Usage:
#   bash scripts/e2e-spec-0040-runbook-driven-evidence-gate.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline closed loop:executor Run! + Evidence gate control (in thousands of euros)fake backendReal pipe line)"
uv run --extra dev python - <<'PY'
# Spec-0040/T5: Hermetic Exercise - netless, LLM untouched, real untouched, and not even real git remote.
import tempfile
from pathlib import Path

from openagents import evidence_gate, executor
from openagents.backends.base import AgentResult


class _Backend:
    """fake backend: By default summary Response (Reaction)executor / The evidence gate. summary The ruling is to be diagnosed."""

    name = "fake"

    def __init__(self, *, summary):
        self._summary = summary

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=False, summary=self._summary)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    pr = 12
    evidence_dir = root / evidence_gate.evidence_dir_for(pr_number=pr)
    runbook = root / "runbook.md"
    runbook.write_text("Implementation pattern:cli\nRun! init- Look at the exit code.", encoding="utf-8")
    intent = "Intent:init None origin It has to be a visible failure.\nReceiving and inspection:\n- Non-zero exit + Hint"

    # --- Receiving and inspection behaviour ①：cli runbook → executor Run and bring in the evidence. docs/e2e-results/<pr>/ ------------ #
    assert str(evidence_gate.evidence_dir_for(pr_number=pr)) == "docs/e2e-results/12", (
        "evidence_dir_for The path agreement should read docs/e2e-results/<pr>/"
    )
    result = executor.run_executor(
        backend=_Backend(summary="Run away. init, exit code 0- That’s what I expected.\nOUTCOME: PASSED"),
        work_dir=root,
        runbook_path=runbook,
        evidence_dir=evidence_dir,
        pr_number=pr,
    )
    assert result.outcome == "passed" and result.form == "cli", result
    assert (evidence_dir / executor.RESULT_FILENAME).is_file(), "evidence result.md Unset"
    print("  ✓ Behaviour①：cli runbook → executor - Yeah.fake）The evidence is solidified. docs/e2e-results/12/result.md")

    # --- Receiving and inspection behaviour ②"Image not reached." → Evidence lockdown. FAIL(contains merger)------------------------------ #
    fail = evidence_gate.review_evidence(
        backend=_Backend(summary="VERDICT: FAIL\nReceiving and inspection behaviour①Not achieved: only ran away --help- And the weight is light."),
        work_dir=root,
        intent=intent,
        evidence_dir=evidence_dir,
        pr_number=pr,
    )
    assert fail.passed is False and fail.feedback, fail
    print("  ✓ Behaviour②Evidence of intent not reached → Evidence gate. FAIL（feedback It’s not empty. The link will go. iterate(reason=e2e) No, no, no. merge）")

    # --- Conduct 3: "Facing" Evidence  →  Evidence Gate PASS (Leasure to Merge) ------------------------------------#
    ok = evidence_gate.review_evidence(
        backend=_Backend(summary="VERDICT: PASS\nThe evidence is article by article, paragraph 1."),
        work_dir=root,
        intent=intent,
        evidence_dir=evidence_dir,
        pr_number=pr,
    )
    assert ok.passed is True and ok.feedback == "", ok
    print("  ✓ Behaviour③: Evidence of intent → Evidence gate. PASS（feedback Empty, let go. merge）")

    # Missing --- evidence = missing: no result.md hard sentence FAIL (Tautology guard 3) ---------------------#
    missing = evidence_gate.review_evidence(
        backend=_Backend(summary="Shouldn’t be called."),
        work_dir=root,
        intent=intent,
        evidence_dir=root / "no-such-dir",
        pr_number=pr,
    )
    assert missing.passed is False, missing
    print("  ✓ Bottom: missing evidence (nil) result.md）→ Hard ruling FAILNo evidence to do so.")

print()
print("✓ Spec-0040 hermetic The exercise was conducted by:executor It’s a quick fix. → Take the evidence. RFC The intention is to control the merger against the evidence.")
print("  evidence FAIL Block Merge / evidence PASS Let go! / Evidence missing hard FAIL# The whole way without a net #/None LLM/None gh/No real git Far away.")
PY

echo
echo "✓ Spec-0040 End-to-end script complete (delineal certainty) + The two-part closed-ring exercise is over."
