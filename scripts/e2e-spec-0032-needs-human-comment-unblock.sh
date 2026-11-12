#!/usr/bin/env bash
# Spec-0032/T6 End-to-end Test Start Script: Neds-human closed the whole process in GitHub comments -
# "Adjust hang up the tweak structure review + the watermark tweaker writes a new comment  →  Next round of automatic tags + feed detail + restore state"
#
# Two segments (both offline, certainty, repeatable, net-free, unmovable) LLM/gh）：
#   1) Offline certainty verification - ruff lint/format + pytest package (overwrite state/github/blocknote/identity/)
#      Messages are single-scale, full-mock for each Task.
#   2) Offline Closed Circle Timeline Demonstration - fake gitthub (list_comments/has_label/remove_label/add_label)+
#      fake identity（new_human_comments/post_signed_comment）+ fake orchestrator + fake state，
#      Two rounds of offline driver Messages.poll, which asserted that the whole article was unmounted and printed.
#
# Usage:
#   bash scripts/e2e-spec-0032-needs-human-comment-unblock.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline closed loop timeline demonstration: Hanging up to leave a message → People comment back. → Auto-label removal + Hello? detail + Restore flow"
uv run python - <<'PY'
# Spec-0032/T6: Offline driver Messages.poll,Play code The gate is hanging. → People comment back. → Auto-leaving. detail」The whole track.
from openagents import blocknote
from openagents import messages as messages_module
from openagents.github import Comment
from openagents.messages import Messages
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    RunRecord,
)


class FakeOrchestrator:
    """Records iterate / refine_rfc calling;suffying detail And here it is."""

    def __init__(self):
        self.iterate_calls = []
        self.refine_calls = []

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})

    def refine_rfc(self, *, pr_number, detail):
        self.refine_calls.append({"pr_number": pr_number, "detail": detail})


class FakeState:
    """Memory Version State: Maintenance of individual run, the field where the demounting path will move."""

    def __init__(self, *, runs):
        self._runs = list(runs)

    def all_runs(self):
        return list(self._runs)

    def _find(self, issue_number):
        return next(r for r in self._runs if r.issue_number == issue_number)

    def update_status(self, *, issue_number, status):
        self._find(issue_number).status = status

    def set_block_gate(self, *, issue_number, gate):
        self._find(issue_number).block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        self._find(issue_number).block_watermark = watermark

    def reset_rounds(self, *, issue_number):
        record = self._find(issue_number)
        record.rounds = 0
        record.review_invalid = 0
        record.merge_attempts = 0


# --- memory GitHub World: Pr label collection + Comment List (man/ machine signed) ----------------#
AGENT_ID = "agent-e2e"
pr_labels = set()
pr_comments = []  # list[Comment]

messages_module.github.is_merged = lambda *, pr_number: False
messages_module.github.is_closed = lambda *, pr_number: False
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels
messages_module.github.add_label = lambda *, pr_number, name: pr_labels.add(name)
messages_module.github.list_comments = lambda *, pr_number: list(pr_comments)


def _remove_label(*, pr_number, name):
    pr_labels.discard(name)  #   Wait: No, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no.


messages_module.github.remove_label = _remove_label


def _post_signed_comment(*, pr_number, body, agent_id):
    # ; created_at single-tele-Incremental Simulation Time Order (ISO 8601 dictionary order current order).
    stamp = f"2026-06-29T1{len(pr_comments)}:00:00Z"
    pr_comments.append(
        Comment(id=f"m{len(pr_comments)}", author="openagents", body=blocknote_sign(body), created_at=stamp)
    )


def blocknote_sign(body):
    # Re-use identity.sign to sign the machine's comment (with the unmounted side filtering the machine's comment).
    return messages_module.identity.sign(body=body, agent_id=AGENT_ID)


messages_module.identity.post_signed_comment = _post_signed_comment
# new_human_comments is realized by realism (reading list_comments+ filtering by signature/waterline) - the side of the reading that is to be demonstrated.

record = RunRecord(
    issue_number=89,
    branch="openagents/issue-89",
    pr_number=7,
    pr_url="https://example/pull/7",
    status=STATUS_ITERATING,
    summary="",
    rounds=3,
    block_gate="code",
    block_watermark="",
)
orch = FakeOrchestrator()
state = FakeState(runs=[record])
msgs = Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)

# --- Hang up: Go straight _block (gate = code) Simulate the code lock above K Roundside (Stagger Full + Water Level) ------#
msgs._block(record=record, gate="code", blocker="reviewer: Filling input singles; processing None branch")
assert BLOCKED_LABEL in pr_labels, "Hang up should be beaten needs-human Tab"
assert record.status == STATUS_BLOCKED
assert len(pr_comments) == 1, "Hang up to fit a structured comment"
note = pr_comments[0].body
for section in ("**Reason**", "**I tried.**", "**Where’s the card?**", "**What can you do?**"):
    assert section in note, f"Structured comments missing paragraphs:{section}"
assert "gate=code" in note
assert record.block_watermark == pr_comments[0].created_at, "Waterlines=Hanging up comments createdAt"
print("  [park] _block(gate=code):Put on 1 Article IV Structural signature comments + Fight! needs-human + Remember watermark")
print(f"         watermark = {record.block_watermark}(with comments on this article, so that no self-trigger will be used)")

# --- Round 1 Poll: People haven't commented + needs-human is still hanging ---------------------#
events = msgs.poll()
assert events == [], "No comment, no incident."
assert record.status == STATUS_BLOCKED
print("  [Wait] I’m not sure. 1 Wheel poll: No New Human Review + The tag is still in place. → Keep hangup (machine own hangup filtered, unstarted)")

# --- returns an unsigned comment (later than the water level) -----------------------------------------------#
pr_comments.append(
    Comment(
        id="human-1",
        author="alice",
        body="Don’t move here. messagesChange it. state Add a field and continue in this way.",
        created_at="2026-06-29T20:00:00Z",
    )
)
print("  [People comment back.] alice Answer: ”Don’t move. messagesChange it. state Add a field and continue in this way.”")

# --- Round 2 Poll: New Human Review  →  Automatic Label + Detail to itsate + Restore flow ---#
events = msgs.poll()
assert events == [{"pr_number": 7, "reason": "resumed"}], f"Should be unloaded resumedactual {events}"
assert BLOCKED_LABEL not in pr_labels, "Unmount should automatically remove needs-human Tab"
assert record.rounds == 0, "Unset the round budget"
assert orch.iterate_calls == [
    {"pr_number": 7, "reason": "human", "detail": "Don’t move here. messagesChange it. state Add a field and continue in this way."}
], f"The body of the human comments should be taken into account. detail Here. reason=human Here. iterateactual {orch.iterate_calls}"
assert orch.refine_calls == []
print("  [Unmount] I’m not sure. 2 Wheel poll: Auto-extract needs-human + reset Budget + iterate(reason=human, detail=Text of the commentary) + resumed")

print("✓ All the closed-ring tracks claim passed: hang up the foothold. → People comment back. → Auto-leaving. detail → Restore flow (whole-in-the-way) PR In the commentary.")
PY

echo
echo "✓ Spec-0032/T6 End-to-end demonstration completed (offline, repeatable, net-free, unmovable) LLM/gh）。"
