#!/usr/bin/env bash
# Spec-0053/T4 End-to-end test start script: Code Review Gate sticky short circuit - Reuse the last wheel PASS when code is in the same state, skip over rehearsing.
#
# The team introduced the PR net change fingerprint short circuit to the Vigil Poll ** The code review gate in the loop: reviewer full vote PASS round
# PR Net diff fingerprints relative to base (sha256(gh pr diff)) enter run state; next round goes first before review_code
# Fingerprints, consistent with the last PASS, are used directly to re-use the PASS, skip the re-examination, and re-examine the fingerprints as usual. This stops.
# "Base Forward (BehIND update_branch) pullmain CI rerun next round CI Green) Run again for nothing N reveewer"
# . Design against k8s Tide sticky approve / lgtm store_tree_hash (codes are not changed).
#
# Two parts, full ** netless, unreal LLM, unreal gh, unreal git far **:
#   1) Offline certainty (default) - ruff lint/format + pytest complete, overlay T1 state fingerprint field/setter
#      (test_state_code_fingerprint), T2 gitthub fingerprinting value (test_github_code_fingerprint),
#      T3 messages 3c short-circuit connection (test_messages_review_sticky).
#   2) Offline Results Exercise (Default) - Three rounds run with real State + memory GitHub World Drive _process_coding:
#      Two rounds of the same-coded claim, reviewer only once, flip-printing, third-round claim, reviewer again.
#      (Fingerprint change  →  re-examination). That is, the proof of short-circuit syntax (idemic 8) with the observable result of "reviewer caller number".
#
# Test the boundary (a visible statement, ividence layer): This script is based on a stub code_fingerprint feed "same fingerprints and/or flip fingerprints" and is used to create a new script.
# The test is ** set up short-circuit syntax** (same re-use PASS, variable re-refer) without running real update_branch to observe "merge"
# Main gh pr diff remains the same after head" - a live GitHub service PR state (e2e e2e live GitHub)
# base...head Three Point Diff remains unchanged after no conflict Qrange base is Spec-0053 Reference-level already given
# Three semantics are strictly introduced and endorsed by official documents, and are not subject to every e2e retest of the running-life behaviour (see spec Unresolved 3).
#
# Browser e2e: This feature does not have a program-facing front-end interface (night watcher polle cycling internal layout short-circuit, only visible result
# is "no reviewer process when code changes" without any HTTP frontend/paint rendering. So browser e2e is not applicable, result evidence
# The following script, driven by CLI/pytest, is asserted as a "reviewer call count" and is the correct visual of this internal behavior.
#
# Usage:
#   bash scripts/e2e-spec-0053-review-sticky-pass.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] The results show that the people are not going to be able to do anything.reviewer Number of calls 1(Two rounds of same size)→ 2(Fingerprint flips)"
uv run python - <<'PY'
# Spec-0053/T4: Real State + Memory GitHub World, Offline Drive _process_coding as "reviewer call times"
# Validates the sticky short-circuit syntax (synthesis reuse PASS, variable re-review).
import tempfile
from pathlib import Path

from openagents import messages as messages_module
from openagents.github import CheckStatus, Mergeability, PR
from openagents.hold import NONE as NO_HOLD
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import STATUS_PR_OPEN, State

AGENT_ID = "agent-e2e-0053"
ISSUE, PR_NUM = 133, 5

# Variable stub fingerprint: round 1/2 coding "fp-A", round 3 flip to "fp-B" (simulation of itserate recode).
current_fingerprint = {"value": "fp-A"}


class Orch:
    def __init__(self):
        self.review_code_calls = 0

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return ReviewDecision(passed=True, feedback="", verdicts=("PASS",))

    def iterate(self, *, pr_number, reason, detail):  # PASS Path does not trigger
        raise AssertionError("PASS Paths Should Not iterate")


# Memory GitHub World: can be merged, CI Green, fingerprints taken from current_fingerprint; merge/close All No-op.
g = messages_module.github
g.mergeability = lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN")
g.check_status = lambda *, pr_number: CheckStatus(state="pass", failed_logs=[])
g.code_fingerprint = lambda *, pr_number: current_fingerprint["value"]
g.merge_pr = lambda *, pr_number: None
g.close_issue = lambda *, number: None

tmp = Path(tempfile.mkdtemp())
state = State(path=tmp / "state.json")
state.record_run(
    issue_number=ISSUE,
    branch=f"openagents/issue-{ISSUE}",
    pr=PR(number=PR_NUM, url=f"https://example/pull/{PR_NUM}"),
    status=STATUS_PR_OPEN,
)
orch = Orch()
msgs = Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)


def run_once():
    # Direct driver code appraisal gate; return run-run to pr-open to enter the next round (PASS → merge will doe).
    record = state.find_by_issue(issue_number=ISSUE)
    event = msgs._process_coding(record=record, hold=NO_HOLD)
    state.update_status(issue_number=ISSUE, status=STATUS_PR_OPEN)
    return event


# --- First Round: No Historical Fingerprints  →  Regular Review, Fp-A ------------------------------------ #
run_once()
assert orch.review_code_calls == 1, f"First round should be evaluated once, actual {orch.review_code_calls}"
assert state.find_by_issue(issue_number=ISSUE).code_passed_fingerprint == "fp-A"
print("  [First Round] No historical fingerprints → Review as usual (reviewer Call=1）+ Fingerprints fp-A")

# --- Sub-wheel: Same code "fp-A"  → sticky hit, reviewer is not remodulated ---------------------------#
run_once()
assert orch.review_code_calls == 1, f"The next round should go. sticky、reviewer Call number still is 1actual {orch.review_code_calls}"
print("  [Second] Fingerprints unchanged (%2)fp-A）→ Re-use the last wheel PASS, Skip over re-trialreviewer Call still=1）★sticky Iron evidence.")

# --- Round three: Flip fingerprints "fp-B" → Re-examine, drop new prints. --------------------------------- #
current_fingerprint["value"] = "fp-B"
run_once()
assert orch.review_code_calls == 2, f"Third round of fingerprint flips should be retried.reviewer Call=2actual {orch.review_code_calls}"
assert state.find_by_issue(issue_number=ISSUE).code_passed_fingerprint == "fp-B"
print("  [Three rounds.] Fingerprint Flip (Phone)fp-A→fp-BSimulation iterate Changed)→ Retrial (Retrial)reviewer Call=2）+ New Fingerprints for Dropboard fp-B")

print()
print(f"✓ reviewer Number of call tracks:1(Two rounds of same size)→ 2(Fingerprint flips)")
print("✓ Spec-0053 sticky All the short-circuit closing claims are passed: same number reuse PASS, variable re-examination (full de-line, repeatable, net-free).")
PY

echo
echo "✓ Spec-0053/T4 End-to-end demonstration completed (default offline, repeatable, net-free, unmovable) LLM/gh）。"
