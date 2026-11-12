#!/usr/bin/env bash
# Spec-0041/T4 peer-to-end test start script: Hold-merge PASS after "Playing to Merge" - adopted PR freezes
# Need-human, eliminate homogeneity review shock.
#
# This group changed the hold-merge branch from "empty operation, next re-trial" to "condulsion": reviewer PASS and --hold merge
# Blocked + needs-human + pasted "Presentation of Quote to be merged" successful case + Gate=merge-hold; blocked
# _OPEN_STATUSES  →  Next round of polts automatically skip, no longer retry, root-deleting the same number undetermined reviewer repeatedly
# PASS/REWORK review shock. With a cleanup hanging up the leaked reviewer scratchpad.
#
# Two segments, full** netless, untouched LLM, untouched gh, unreal git remote** (except stage 2, to be visible):
#   1) Offline certainty (default) - ruff lint/format + pytest package, overriding T2 success files
#      (test_blocknote_hold_merge), T3 ScratchPad Cleaning (test_reviewer_feedback_distill), T1 Prison +
#      merge-hold route (test_messages_hold_merge_freeze), T4 integration (test_hold_merge_freeze_integration).
#   2) Offline Results Exercise (Default) - Two rounds of Messages.poll with real State + memory GitHub world drive, with assertion
#      First Freezing Round No Next Round, and replay two board.html for HTML Text Matching for "Stabilizing After Freezing"
#      (Results visualized, concept 8; downgrade path when no browser MCP does not skip result validation).
#   3) Real smoke (optional, OPENAGENTS_E2E_REAL = 1) - A reminder of how to actually open a merged PR, belt in a scratch warehouse
#      --hold merge Run! vigil,Certify PR Beated. needs-human + The success story reviews, two rounds of non-repeated review reviews, are in a pile.
#
# Usage:
#   bash scripts/e2e-spec-0041-hold-merge-freeze.sh
#   OPENAGENTS_E2E_REAL = 1 bash scripts/e2e-spec-0041-hold-merge-freeze.sh # Add a real smoker
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline result exercise: First round freeze → Next round without retrial → ”Stable after freeze.”HTML Text Match"
uv run python - <<'PY'
# Spec-0041/T4: Real State + Memory GitHub World, Offline Drive Messages.poll, demonstrates anti-shock + panel stability.
import tempfile
from pathlib import Path

from openagents import blocknote
from openagents import messages as messages_module
from openagents import results
from openagents.github import CheckStatus, Comment, Mergeability, PR
from openagents.hold import Hold
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import BLOCKED_LABEL, STATUS_BLOCKED, STATUS_PR_OPEN, State

AGENT_ID = "agent-e2e-0041"
ISSUE, PR_NUM = 106, 5
labels, comments = set(), []


class Orch:
    def __init__(self):
        self.review_code_calls = 0

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return ReviewDecision(passed=True, feedback="", verdicts=("PASS",))

    def iterate(self, *, pr_number, reason, detail):  # This exercise doesn’t trigger.
        raise AssertionError("Freeze/Hanging path should not iterate")


g = messages_module.github
g.is_merged = lambda *, pr_number: False
g.is_closed = lambda *, pr_number: False
g.mergeability = lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN")
g.check_status = lambda *, pr_number: CheckStatus(state="pass", failed_logs=[])
g.list_comments = lambda *, pr_number: list(comments)
g.has_label = lambda *, pr_number, name: name in labels
g.add_label = lambda *, pr_number, name: labels.add(name)
g.remove_label = lambda *, pr_number, name: labels.discard(name)


def _post_signed(*, pr_number, body, agent_id):
    stamp = f"2026-07-02T1{len(comments)}:00:00Z"
    signed = messages_module.identity.sign(body=body, agent_id=agent_id)
    comments.append(Comment(id=f"m{len(comments)}", author="bot", body=signed, created_at=stamp))


messages_module.identity.post_signed_comment = _post_signed

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
hold = Hold(at_merge=True)


def board_row():
    html = results.render(runs=state.all_runs())
    rows = [ln for ln in html.splitlines() if f"#{PR_NUM}" in ln and "<tr>" in ln]
    assert len(rows) == 1
    return rows[0]


# --- First Round Poll: Incarceration -------------------------------------------------------------#
events1 = msgs.poll(hold=hold)
assert events1 == [{"pr_number": PR_NUM, "reason": "hold-merge", "gate": "merge-hold"}]
assert orch.review_code_calls == 1
rec = state.find_by_issue(issue_number=ISSUE)
assert rec.status == STATUS_BLOCKED and rec.block_gate == "merge-hold" and rec.block_watermark
assert BLOCKED_LABEL in labels
note = [c for c in comments if c.author == "bot"][0].body
assert blocknote.build_hold_merge_pass() in note and "It’s stuck." not in note
row1 = board_row()
assert '<span class="status">blocked</span>' in row1
print("  [Freeze] First Round poll：blocked + needs-human + Successful Text (non-failure template)+ gate=merge-hold；reviewer Review 1 Number of times")

# --- Sub-wheel Poll: No re-examination -----------------------------------------------------------#
events2 = msgs.poll(hold=hold)
assert events2 == [], f"The next round should be hung up, no incidents, actual {events2}"
assert orch.review_code_calls == 1, "Anti-shock evidence:reviewer The stakes must no longer be transferred."
rec2 = state.find_by_issue(issue_number=ISSUE)
assert rec2.status == STATUS_BLOCKED and rec2.rounds == 0
assert len([c for c in comments if c.author == "bot"]) == 1, "No further comments in the next round"
row2 = board_row()
assert row2 == row1, "The board should... PR Lines should be fully consistent across the wheel (stabilized after freezing, no shock)"
print("  [No retrial] Second poll：reviewer The number of call times for the stakes remains the same. 1# Still in status # blocked, No new comments,rounds No increase")
print("  [Watch the results.] Two rounds of retrofitting. board.html The PR Line Status=blocked And bytes are the same. → Trans-cycle stability after freezing (ideology) 8）")
print("             Note: Real browser cut-off results (in thousands of United States dollars)Playwright/chrome-devtools MCP）By agent Driven outside scripts;")
print("             No Browser MCP Press T4 spec The downgrading was for that. HTML text match, do not skip the result validation.")

print("✓ Spec-0041 The anti-shock ring closed-up claim was all passed:PASS He’s in jail. → No re-examination. → The panels are stable (out of line, repeatable).")
PY

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [Optional] Real smoke.OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  Real smoke step (needs real) GitHub Warehouse + gh Login, it’ll be real. PR）：
    1) Yes. scratch The warehouse is actually open to merge. PR（CI Green,rfc-approved）。
    2) - Yeah. --hold merge Round one. vigil：`oa vigil --hold merge --once`
       It is expected that:PR Hit. needs-human Label, one.✅ We’ve passed the review, pending your joinder.🤖 It’s stuck.”
    3) One more round:`oa vigil --hold merge --once`
       Expected: No additional comments, stable (anti-shock)——PR Not re-evaluated, comment not accumulated.
    4) Yes. GitHub Manual Merge → Next round. vigil It’s... is_merged branch reconcile Done. done + Off issue。
  (This paragraph only prints guidelines, does not automatically execute and avoids being CI/Offline error is real. gh。）
REAL
fi

echo
echo "✓ Spec-0041/T4 End-to-end demonstration completed (default offline, repeatable, net-free, unmovable) LLM/gh）。"
