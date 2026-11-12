#!/usr/bin/env bash
# Spec-0031 end-to-end test to start script: hermetic closed-circle exercise for merge gate armed unset.
#
# The group re-designs the "disarm" semantic of the merge gate (PR and base-slash really): people remove their needs-human labels and do not immediately
# Reset, but enter the armed mode agent to re-test the conflict (new knob OPENAGENTS_MAX_MERGE_ATTEMPTS, QQQ)
# 3. The conflict is not re-established until the conflict has been exhausted. For the first time, it was discovered that the situation was maintained (at one time, if not unsolved, with a manual back-up).
#
# Two segments, full ** netless, no real LLM, no real gh**:
#   1) Offline certainty (default execution) - ruff lint/format + pytest package, block_gate/
#      merge_attempts Count (test_state_merge_unblock) and messages' armed unmounted/ retried
#      (test_messages_merge_unblock) Single measure.
#   2) Offline Cyclical Exercise (Default) - State + make github.has_label/mergeability+ with real drop-off
#      Make stock drive a real Messages.poll to re-engineer the whole state track in chronological order:
#      First discovered conflict hanger (block_gate =merge) unmounter arm (retain tag, return to pr-open)  → armed has a boundary
#      Retry (merge-retry, not re-mount)  →  used out re-playing; and practiced anrmed at once or clear of armed.
#
# Usage:
#   bash scripts/e2e-spec-0031-merge-unblock-agent-resolve.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline closed loop:merge The gate. armed Unmount whole state trajectory (fake github / fake resolve）"
uv run --extra dev python - <<'PY'
# Spec-0031/T3: Hermetic exercise - netless, LLM untouched, real untouched.
# Replace the github/identity/conflict function with the real dropout + (not pytest, not pytest) in the messages module
# The process is being eliminated without side effects.
import tempfile
from pathlib import Path

from openagents import messages as messages_module
from openagents.messages import Messages
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_PR_OPEN,
    State,
)
from openagents.github import PR

ISSUE = 3
PR_NUMBER = 5

# --- Variable Controls Thermometer: controls the return value of fake with a closed package shared holder, simulates the time of ----------#
state_box = {"labels": {BLOCKED_LABEL}, "resolve_ok": False}


def fake_is_merged(*, pr_number):
    return False


def fake_is_closed(*, pr_number):
    return False


def fake_has_label(*, pr_number, name):
    return name in state_box["labels"]


def fake_add_label(*, pr_number, name):
    state_box["labels"].add(name)


def fake_mergeability(*, pr_number):
    class _MS:
        merge_state_status = "DIRTY"
        mergeable = "CONFLICTING"

    return _MS()


comments = []


def fake_post_signed_comment(*, pr_number, body, agent_id):
    comments.append({"pr_number": pr_number, "body": body})


def fake_make_resolver(*, work_dir, base, backend, agent_id):
    # Returns a resulter (without touching the real git / LLM) determined by state_box ["resolve_ok " ).
    return lambda *, pr_number: state_box["resolve_ok"]


# Replaces external dependence (hermetic) in the messages module.
messages_module.github.is_merged = fake_is_merged
messages_module.github.is_closed = fake_is_closed
messages_module.github.has_label = fake_has_label
messages_module.github.add_label = fake_add_label
messages_module.github.mergeability = fake_mergeability
messages_module.identity.post_signed_comment = fake_post_signed_comment
messages_module.conflict.make_resolver = fake_make_resolver
# Stitch the upper limit to 3 and practice "Unattended upper limit try again / Up to upper limit hang" borders.
messages_module.MAX_MERGE_ATTEMPTS = 3


class _DummyBackend:
    name = "dummy"

    def run(self, *, work_dir, task, context):  # pragma: no cover - resolve Replaced
        raise AssertionError("resolve Already fake Replace, not really. backend")


def _poll(msgs):
    events = msgs.poll()
    assert len(events) == 1, f"Every round is a single event, real. {events}"
    return events[0]["reason"]


with tempfile.TemporaryDirectory() as tmp:
    state = State(path=Path(tmp) / ".openagents" / "state.json")
    state.record_run(
        issue_number=ISSUE,
        branch=f"openagents/issue-{ISSUE}",
        pr=PR(number=PR_NUMBER, url=f"u/pull/{PR_NUMBER}"),
        status=STATUS_PR_OPEN,
    )
    msgs = Messages(
        orchestrator=object(),  # Conflict Precheck In reviewer I’ve been short-circuited, never touched. orchestrator
        state=state,
        agent_id="agent-self",
        work_dir="/repo",
        base="main",
        backend=_DummyBackend(),
    )

    def record():
        return state.find_by_issue(issue_number=ISSUE)

    # 1) First conflict detected, conflict failed  →  hang up: + blocked + block_gate = merge.
    state_box["resolve_ok"] = False
    assert _poll(msgs) == "unmergeable"
    assert record().status == STATUS_BLOCKED
    assert record().block_gate == "merge"
    assert len(comments) == 1
    assert BLOCKED_LABEL in state_box["labels"]
    print("  ✓ Steps 1: First time you find a conflict you can’t solve → Message + Suspend (%1)block_gate=merge）Keep the manual cover.")

    # 2) The next round of Poll still needs to-human  →  soft-sloking, still in condition (no behavior change).
    assert msgs.poll() == []
    assert record().status == STATUS_BLOCKED
    print("  ✓ Steps 2：needs-human Still → SLOW HANGING,poll Skip (no retry, no turn)")

    # 3) Take them off. needs-human → Unmount arm: Back pr-open Reservations block_gate=merge、merge_attempts Clear.
    state_box["labels"].discard(BLOCKED_LABEL)
    assert _poll(msgs) == "resumed"
    assert record().status == STATUS_PR_OPEN
    assert record().block_gate == "merge"  # armed Mark Keep
    assert record().merge_attempts == 0
    print("  ✓ Steps 3: person needs-human → armBack pr-openReservations merge Mark, budget full)")

    # 4) Armed has retry: resolve still fails  → merge-retry, keep pr-open, unmounted, unmessaged; count in.
    comments.clear()
    state_box["resolve_ok"] = False
    assert _poll(msgs) == "merge-retry"
    assert record().status == STATUS_PR_OPEN and record().merge_attempts == 1
    assert _poll(msgs) == "merge-retry"
    assert record().status == STATUS_PR_OPEN and record().merge_attempts == 2
    assert comments == []  # No messages hung up
    print("  ✓ Steps 4：armed I can’t. → Cross-wheel merge-retry(Present) pr-open  No more, no more messages  ")

    # 5) The 3rd (damn MAX_MERGE_ATTEMPTS = 3) failed  →  Re-suffling: Message + blocked + block_gate =merge.
    assert _poll(msgs) == "unmergeable"
    assert record().status == STATUS_BLOCKED
    assert record().block_gate == "merge"  # Again mergeNext time, I’ll let you go. arm
    assert record().merge_attempts == 3
    assert len(comments) == 1
    print("  ✓ Steps 5：armed Exhaustion of ceiling (%)3 (a) Number of reports→ Re-staggered. armShut up!")

    # 6) Exercise armed is clear armed: People untie  → arm, next round resolve successfully resolved + mark.
    state_box["labels"].discard(BLOCKED_LABEL)
    assert _poll(msgs) == "resumed"  # Again. arm
    state_box["resolve_ok"] = True
    comments.clear()
    assert _poll(msgs) == "resolved"
    assert record().block_gate == ""  # armed Clear
    assert record().merge_attempts == 0  # Budget Reset
    assert record().status == STATUS_PR_OPEN
    assert comments == []  # It’s settled. No messages.
    print("  ✓ Steps 6：armed One-time solution. → resolved + Clear. armed（block_gate='') Natural development")

print()
print("✓ Spec-0031 hermetic The exercise was conducted by:merge The gate. armed Unlock the entire state trajectory, unnet-free/None LLM/None gh。")
PY

echo
echo "✓ Spec-0031 End-to-end script complete (delineal certainty) + The two-part closed-ring exercise is over."
