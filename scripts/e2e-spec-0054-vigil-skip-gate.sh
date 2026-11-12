#!/usr/bin/env bash
# Spec-0054/T5 End-to-end test start script: vigil --skip spec side-by-side road - "skip spec  →  Directly achieves".
#
# Presentation issue #135 _Other Organiser draft PR Load spec Time,Here. `--skip spec` - Put it on. spec The judges. PASS
# Direct release - no reviewer, rifc-approved label and go to realization (coding); re-demonstration against the same spec
# `--hold spec --skip spec` (both stopping and letting people jump) will be reported on the spot by reconcile_hold_skip.
#
# Two sections (consisting with e2e-spec-0020-hold-gate.sh):
#   1) Offline certainty (default execution) - ruff lint/format + pytest package, full mock, untouched real
#      gh/claude (sole detection over skip resolution/ contradictory detection/ five-gate short circuit/ CLI connection).
#   2) Timeline Detached (Default Execution) - Simulate with a orchestrator/state + memory label
#      GitHub, offline driver Messages.poll (skip=spec) asserts that "spec gate is used as PASS straight into it" and demonstrates
#      --hold spec --skip spec is wrong. No certificate, CI can run, repeatable.
#
# Form description: CLI / offline (no browser MCP, pure internal control flow, no front-end).skip is the door inside the autonomous ring.
# The spin button, which is "is it true that the time line is diverted" and not any visualized result, is taken offline for certainty.
#
# Usage:
#   bash scripts/e2e-spec-0054-vigil-skip-gate.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification(lint + format + Unit Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline gate timeline demonstration:vigil --skip spec Direct release spec The gate. → Progress;--hold spec --skip spec Wrong"
uv run python - <<'PY'
# Spec-0054/T5: Offline driver Messages.poll(skip=spec),The assertion. spec The gate is being set. PASS Directly.
from openagents import messages as messages_module
from openagents.hold import parse_hold
from openagents.messages import APPROVAL_LABEL, Messages
from openagents.skip import parse_skip, reconcile_hold_skip
from openagents.state import STATUS_RFC_REVIEW, RunRecord


class FakeOrchestrator:
    """Records implement / review_rfc Call;skip spec Down review_rfc Shouldn’t have been transferred."""

    def __init__(self):
        self.implement_calls = []
        self.review_rfc_calls = []

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)
        return "impl-summary"  # Spec-0051/T4：implement Summary of the current round returned(None→str)

    def review_rfc(self, *, pr_number):  # skip spec I shouldn’t have been transferred down there.
        self.review_rfc_calls.append(pr_number)
        raise AssertionError("skip spec Down should not trigger automatic reviewer")


class FakeState:
    """Memory Maintenance Individual run,Record status update."""

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


# Memory label assembly simulation GitHub PR tag; the ngat code for sskip spec hit will go to Riga refc-approved.
pr_labels = set()
messages_module.github.is_merged = lambda *, pr_number: False
messages_module.github.is_closed = lambda *, pr_number: False
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels
messages_module.github.add_label = lambda *, pr_number, name: pr_labels.add(name)

record = RunRecord(
    issue_number=135,
    branch="openagents/issue-135",
    pr_number=5,
    pr_url="https://example/pull/5",
    status=STATUS_RFC_REVIEW,
    summary="",
)
orch = FakeOrchestrator()
state = FakeState(runs=[record])
msgs = Messages(orchestrator=orch, state=state, agent_id="agent-e2e")
# The adhesion is a real IO that does its best, and it has nothing to do with this gate's assertion that no-op.
msgs._post_agent_report = lambda *, pr_number, body: None
skip = parse_skip(raw="spec")

# --- sskip spec: spec is used as PASS without review, refc-approved label and ---
events = msgs.poll(skip=skip)
assert orch.review_rfc_calls == [], "skip spec No automatic evaluation"
assert APPROVAL_LABEL in pr_labels, "skip spec Should be hit straight. rfc-approved label"
assert orch.implement_calls == [5], "skip spec It should be done directly.(implement)"
assert any(e["reason"] == "skip-spec" for e in events), "Due outputs skip-spec Events"
print("  [Let go!] --skip spec → Unevaluated, direct rfc-approved labelDirect implement In coding")

# --- Align demonstration:--hold spec --skip spec It's the same. spec The gate's in contradiction. → reconcile_hold_skip Wrong ---
try:
    reconcile_hold_skip(hold=parse_hold(raw="spec"), skip=parse_skip(raw="spec"))
    raise SystemExit("✗ Projected --hold spec --skip spec You’re wrong.,But it was not wrong.")
except ValueError as exc:
    assert "spec" in str(exc)
    print(f"  [Contradiction] --hold spec --skip spec → You’re right.(I’m not quiet.):{exc}")

print("✓ The time line is all passed:skip spec Directly achieved + hold/skip The Quarters are a contradiction.")
PY

echo
echo "✓ Spec-0054/T5 End-to-end demonstration complete(Offline, repeatable)。"
