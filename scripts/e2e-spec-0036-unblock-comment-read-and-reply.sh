#!/usr/bin/env bash
# Spec-0036/T6 End-to-end test start-up script: unmounted agent read and respond positively to comments from people -
# "All the gates are being set to feed human comments to agent (merge gates with previously discarded content) and the hierarchy certainty is being posted back to the response to the original comment."
#
# Two segments (both offline, certainty, repeatable, net-free, unmovable) LLM/gh）：
#   1) Offline certainty verification - ruff lint/format + pytest package (overwrite state/replynote/conflict/orchestrator/)
#      Messages are single-scale, full-mock for each Task.
#   2) De-link timeline demonstration - use make girlb + make relationship + make orchestrator + make stock +
#      Make state, offline driver Messages.poll, with two tracks:
#        ① rfc/code The gate's off. → Quote the original comment to paste agent Response;
#        2 Merge Gates Unmounted Comment as guidance Feed Conflict Deterrence  →  Armed ran to quote the original comment and to post the conclusion.
#
# Usage:
#   bash scripts/e2e-spec-0036-unblock-comment-read-and-reply.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline closed loop timeline demonstration: three locks off feed content + Quote the original comment and send back the response."
uv run python - <<'PY'
# Spec-0036/T6: Offline driver Messages.poll, show the whole track of "Read Comments + Positive Response" (rfc/code Sync Response, )
# The merge gate feeds the guidance + armed. The whole flight is made, without net contact, without real LLM/gh.
from openagents import messages as messages_module
from openagents.github import Comment
from openagents.messages import Messages
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_PR_OPEN,
    RunRecord,
)

AGENT_ID = "agent-e2e"


class FakeOrchestrator:
    """refine_rfc(announce)/iterate Back agent Current round of actions summary(for messages The group responded."""

    def __init__(self):
        self.refine_calls = []
        self.iterate_calls = []

    def refine_rfc(self, *, pr_number, detail, announce=True):
        self.refine_calls.append({"pr_number": pr_number, "detail": detail, "announce": announce})
        return "I’ve been completed with your opinion. spec trade-offs"

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})
        return "Empty input singles have been filled and processed as you instructed. None branch"


class FakeState:
    """Memory Version State: Maintenance of individual run, log unmounted/armed path to the field."""

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

    def set_unblock_detail(self, *, issue_number, detail):
        self._find(issue_number).unblock_detail = detail

    def reset_rounds(self, *, issue_number):
        record = self._find(issue_number)
        record.rounds = 0
        record.review_invalid = 0
        record.merge_attempts = 0

    def increment_merge_attempts(self, *, issue_number):
        record = self._find(issue_number)
        record.merge_attempts += 1
        return record.merge_attempts


class FakeBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):  # resolve It’s replaced. It shouldn’t be real. backend
        raise AssertionError("resolve Already fakeIt’s not supposed to start. backend")


# --- memory GitHub World: PR Tag Pool + Comment List (Segregation of People/Mechanical Signs) -------------------#
pr_labels = {BLOCKED_LABEL}
pr_comments = []  # list[Comment]

messages_module.github.is_merged = lambda *, pr_number: False
messages_module.github.is_closed = lambda *, pr_number: False
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels
messages_module.github.add_label = lambda *, pr_number, name: pr_labels.add(name)
messages_module.github.list_comments = lambda *, pr_number: list(pr_comments)


def _remove_label(*, pr_number, name):
    pr_labels.discard(name)


messages_module.github.remove_label = _remove_label


def _post_signed_comment(*, pr_number, body, agent_id):
    stamp = f"2026-06-30T2{len(pr_comments)}:00:00Z"
    signed = messages_module.identity.sign(body=body, agent_id=agent_id)
    pr_comments.append(Comment(id=f"m{len(pr_comments)}", author="openagents", body=signed, created_at=stamp))


messages_module.identity.post_signed_comment = _post_signed_comment
# new_human_comments is realized by realism (reading list_comments+ filtering by signature/waterline) - the unmounting side.


def _add_human_comment(body, *, stamp):
    pr_comments.append(Comment(id=f"h{len(pr_comments)}", author="alice", body=body, created_at=stamp))


def _signed_count():
    return sum(1 for c in pr_comments if messages_module.identity.parse_agent_id(body=c.body))


# ======================================================================= #
# Track 1: code locks mounted Quoted original comment to send back ant response (sync response)
# ======================================================================= #
print("--- Trajectory ① code Latch-up: Read the commentary + Quote the original comment to paste agent Response ---")
record_code = RunRecord(
    issue_number=89,
    branch="openagents/issue-89",
    pr_number=7,
    pr_url="https://example/pull/7",
    status=STATUS_BLOCKED,
    summary="",
    rounds=3,
    block_gate="code",
    block_watermark="2026-06-30T00:00:00Z",
)
orch = FakeOrchestrator()
msgs = Messages(orchestrator=orch, state=FakeState(runs=[record_code]), agent_id=AGENT_ID)

_add_human_comment("Fill in the singles entered and then process them. None branch", stamp="2026-06-30T10:00:00Z")
print("  [People comment back.] alice: ”Put empty the single measure entered before processing None Branch")

events = msgs.poll()
assert events == [{"pr_number": 7, "reason": "resumed"}], events
assert orch.iterate_calls == [
    {"pr_number": 7, "reason": "human", "detail": "Fill in the singles entered and then process them. None branch"}
], orch.iterate_calls
reply = pr_comments[-1].body
assert "> Fill in the singles entered and then process them. None branch" in reply, "Response should refer to the original comment"
assert "Empty input singles have been filled with your instructions." in reply, "Response should include agent summary"
assert messages_module.identity.parse_agent_id(body=reply) == AGENT_ID, "The response should be signed."
assert BLOCKED_LABEL not in pr_labels, "Unmounted needs-human"
print("  [Unmount+Response] iterate(reason=human, detail=Comments) → Quote original comments + agent summary (article 1)")

# Self-absorption: The response with the signature is filtered off the side of the next de-mounted and will not be triggered as a new human commentary.
fresh = messages_module.identity.new_human_comments(pr_number=7, since="2026-06-30T10:00:00Z")
assert fresh == [], f"agent The answer to your signature should not be read back, actually. {fresh}"
print("  [Self-absorption.] Reply tape signature → Next round. new_human_comments # Erase #agent I can’t read myself.")

# ======================================================================= #
# Track 2:merge gate untie comment by guidance feed the deconflictor  →  armed ran to the original comment and put the conclusion back to the conclusion.
# ======================================================================= #
print()
print("--- Trajectory ② merge Ladder: Comment guidance + pr_number Feed the desolator. → agent Use your own tools to return, and not to re-emerge. ---")
pr_labels = {BLOCKED_LABEL}
pr_comments.clear()
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels

record_merge = RunRecord(
    issue_number=84,
    branch="openagents/issue-84",
    pr_number=10,
    pr_url="https://example/pull/10",
    status=STATUS_BLOCKED,
    summary="",
    rounds=3,
    block_gate="merge",
    block_watermark="2026-06-30T00:00:00Z",
)
orch2 = FakeOrchestrator()
state2 = FakeState(runs=[record_merge])
msgs2 = Messages(
    orchestrator=orch2,
    state=state2,
    agent_id=AGENT_ID,
    work_dir="/repo",
    base="main",
    backend=FakeBackend(),
)

# fake deconflicting world: report conflict, diagnostic return static case, resolve record receipt of guidance + pr_number.
seen = {"guidance": None, "pr_number": None}


class _MS:
    merge_state_status = "DIRTY"
    mergeable = "CONFLICTING"


messages_module.github.mergeability = lambda *, pr_number: _MS()
messages_module.conflictdiag.make_diagnoser = (
    lambda *, work_dir, base: lambda *, pr_number: messages_module.conflictdiag.CONFLICT_COMMENT
)


def _make_resolver(*, work_dir, base, backend, agent_id):
    def _resolve(*, pr_number, guidance=""):
        seen["guidance"] = guidance
        seen["pr_number"] = pr_number
        # True Inner Conflict Resolution Angent will return comments (with signature) with `openagents reply-comment --pr <n>`; this presentation makes a break
        # Resolve, not really agent, so the frame side does not generate comments.
        return messages_module.conflict.ResolveOutcome(resolved=True)

    return _resolve


messages_module.conflict.make_resolver = _make_resolver

# Step 1: A maintainer comments on the PR while conflict resolution is blocked.
_add_human_comment("First, put it on. OVERVIEW.md The conflict is dealt with on both sides of the reservation. rebase state.py", stamp="2026-06-30T10:00:00Z")
print("  [People comment back.] alice: ”Put first.” OVERVIEW.md The conflict is dealt with on both sides of the reservation. rebase state.py』")

events = msgs2.poll()
assert events == [{"pr_number": 10, "reason": "resumed"}], events
assert record_merge.status == STATUS_PR_OPEN, "merge Unlock should be restored. pr-open In armed"
assert record_merge.block_gate == "merge", "armed Mark should be kept"
assert record_merge.unblock_detail == "First, put it on. OVERVIEW.md The conflict is dealt with on both sides of the reservation. rebase state.py", "Comments should be made guidance"
assert _signed_count() == 0, "merge Unmounted wheel does not respond (action not yet occurring)"
print("  [Unmounted wheel] Save unblock_detail Do it. guidanceRecovery pr-open In armed、**No response**Next round. armed I’ll do it!")

# Step 2: Next round of polll  → armed to solve conflict, comment on pr_number
# Reply-comment tool returns comments (this presentation makes loss of resource, not real agent, so no response to frame side); run clean.
events = msgs2.poll()
assert events == [{"pr_number": 10, "reason": "resolved"}], events
assert seen["guidance"] == "First, put it on. OVERVIEW.md The conflict is dealt with on both sides of the reservation. rebase state.py", "Comments should be made guidance Feed the desolator."
assert seen["pr_number"] == 10, "pr_number It’s coming through. resolve(for agent `reply-comment --pr 10`）"
assert _signed_count() == 0, "Framework does not send a response (responds by agent Take your own signature. reply-comment Tool Issue)"
assert record_merge.unblock_detail == "", "armed We should clear the place after the run. unblock_detail"
print("  [armed Run.] resolve(guidance=Comments, pr_number=10) Success → By agent Use it yourself. reply-comment Toolback, Frame Unremoved + Clear. unblock_detail")

print()
print("✓ Both tracks are confirmed: all the locks are fed. agent + The hierarchy certainty is posted back to the response that quoted the original comment.")
PY

echo
echo "✓ Spec-0036/T6 End-to-end demonstration completed (offline, repeatable, net-free, unmovable) LLM/gh）。"
