#!/usr/bin/env bash
# Spec-0020/T5 End-to-end test start script: vigil --hold spec monitoring gate - "Stop at spec Zentententententents to continue".
#
# Demonstration of the core time line of issue #59: Waterlines are stopped at the `--hold spec` gate, etc., after spec; simulation
# The next round of polll lines continues to enter the code after hand-on refc-approved label.
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest package, full mock, untouched real
#      gh/claude (single measurement over analign / hold / two gates split / CLI connection).
#   2) Timeline Detached (Default Execution) - Simulate with a orchestrator/state + memory label
#      GitHub, offline driver Messages.poll (hold=spec) two rounds, claiming "stop the batch and continue" and printing tracks.
#      No proof, no CI can run, no repeat.
#
# Soft Dependence (Spec-0020/T3 to solve): Real scenes are spec-readable human readable from Overview
# (issue #58 / Spec-0014 system); script focus timeline not achieved submary #58 not ready
# hold spec It's still gonna stop./Released, just a downgrading of a person's reading experience.merge Gate--hold merge）Diversion T3 Single-scale coverage,
# This script focuses on the end of the receipt call spec time line.
#
# Usage:
#   bash scripts/e2e-spec-0020-hold-gate.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline gate timeline demonstration:vigil --hold spec Stop in spec → Granted rfc-approved → Go on. coding"
uv run python - <<'PY'
# Spec-0020/T5: Offline driver Messages.poll(hold=spec) Two rounds, for sure. spec "Stop the gate." → Batch → Go on."
from openagents import messages as messages_module
from openagents.hold import parse_hold
from openagents.messages import APPROVAL_LABEL, Messages
from openagents.state import STATUS_RFC_REVIEW, RunRecord


class FakeOrchestrator:
    """Records implement / review_rfc Call, not really call backend."""

    def __init__(self):
        self.implement_calls = []
        self.review_rfc_calls = []

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)

    def review_rfc(self, *, pr_number):  # spec The gate. hold I shouldn’t have been transferred down there.
        self.review_rfc_calls.append(pr_number)
        raise AssertionError("hold spec Down should not trigger automatic reviewer")


class FakeState:
    """Memory Maintenance Individual run, record status update."""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        self.status_updates.append(status)
        for record in self._runs:
            if record.issue_number == issue_number:
                record.status = status

    def increment_rounds(self, *, issue_number):
        return 0

    def reset_rounds(self, *, issue_number):
        pass


# Memory label assembly simulation GitHub PR tag; manual rifc-approved is to the assembly Riga.
pr_labels = set()
messages_module.github.is_merged = lambda *, pr_number: False
messages_module.github.is_closed = lambda *, pr_number: False
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels

record = RunRecord(
    issue_number=59,
    branch="openagents/issue-59",
    pr_number=5,
    pr_url="https://example/pull/5",
    status=STATUS_RFC_REVIEW,
    summary="",
)
orch = FakeOrchestrator()
state = FakeState(runs=[record])
msgs = Messages(orchestrator=orch, state=state, agent_id="agent-e2e")
hold = parse_hold(raw="spec")

# --- Round 1: completed spec, no rfc-approved label, --hold spec stopped at spec gate ---
events = msgs.poll(hold=hold)
assert orch.review_rfc_calls == [], "Stop in spec The gate should not be automatically reviewed."
assert orch.implement_calls == [], "Stop in spec The gate should not. implement"
assert record.status == STATUS_RFC_REVIEW, "We should still stop. rfc-review"
assert any(e["reason"] == "hold-spec" for e in events), "Due outputs hold-spec Events"
print("  [Stop.] I’m not sure. 1 Round:--hold spec → Not automatically evaluated, not called labelNo, I don’t. implementStop at spec The gate and others.")

# --- person batch: Simulation manual to rifc-Approved label ---
pr_labels.add(APPROVAL_LABEL)
print(f"  [Batch] Manual PR #5 Hit it. {APPROVAL_LABEL} label”The real scene is a comparison.” OVERVIEW summary Nod, nod.#58）")

# --- Round 2: Carrying hand-held label Zulu Continues to enter the codement ---
events = msgs.poll(hold=hold)
assert orch.implement_calls == [5], "Bringing a hand. rfc-approved label Continue implement In coding"
assert any(e["reason"] == "approved" for e in events), "Due outputs approved Events"
print("  [Go on.] I’m not sure. 2 Wheel: Check out manual rfc-approved label → implement In coding")

print("✓ All the timelines are passed: stop at spec → Granted → Go on.")
PY

echo
echo "✓ Spec-0020/T5 End-to-end demonstration complete (offline, repeatable)."
