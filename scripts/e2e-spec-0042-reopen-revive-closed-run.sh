#!/usr/bin/env bash
# Spec-0042/T4 End-to-end test start script: PR close  → reopen and then wake up frozen run-closed is not the end of the day.
#
# This group adds "restored" to the local run of the closed: pollll found a closed run-on PR reset on GitHub
# (draft → rfc-review/  → pr-open) and closed_at to continue the process as it is;
# Use closed_at Easter Window (Default) 7 God, put "all the time" on every round. closed run Let's go. gh Cha. reopen」The cost of living above the border.
# The super-window is hardened to the end. is_merged is still irreversible and does not participate in the resurrection.
#
# Two segments, full** netless, untweaked LLM, untouched gh, unconnected to the git remote** (except stage 3, to be visible):
#   1) Offline certainty (default execution) - ruff lint/format + pytest package over T1 closed_at field/setter
#      (test_state_closed_at), T2 is_open/is_draft Envelope (test_github_is_open_draft), T3 Resurrection Window
#      Guard + reopen resurrected reconcile (test_messages_reopen_revive), T4 integration (test_reopen_revive_integration).
#   2) Offline Results Exercise (Default) - A four-wheel time line driven by Messages.poll with a real State + memory GitHub world drive,
#      Show that a closed PR stays closed until reopening, then resumes normal delivery.
#      And replay the HTML version of the board.html for "Closed  → pr-open"
#      (Results visualized, concept 8; downgrade path when no browser MCP does not skip result validation).
#   3) True smoke (optional, OPENAGENTS_E2E_REAL = 1) - A hint of how to make a real close in a scratch warehouse and reopen a PR,
#      Run vigil, verify that the frozen run was resurrected pr-open/rfc-review.
#
# Usage:
#   bash scripts/e2e-spec-0042-reopen-revive-closed-run.sh
#   OPENAGENTS_E2E_REAL = 1 bash scripts/e2e-spec-0042-reopen-revive-closed-run.sh # Add a real smoker
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline result exercise:close→Poke → Still closed Not to come back. → reopen Reborn. pr-open → Normal processing; panels flipped over time lines"
uv run python - <<'PY'
# Spec-0042/T4: Real State + Memory GitHub World, offline driver Messages.poll four-wheel showcasing the recovery closed ring + board flipping.
import tempfile
from pathlib import Path

from openagents import messages as messages_module
from openagents import results
from openagents.github import PR, CheckStatus, Mergeability
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import STATUS_CLOSED, STATUS_DONE, STATUS_PR_OPEN, State

AGENT_ID = "agent-e2e-0042"
ISSUE, PR_NUM = 108, 105

# Memory GitHub World: Variable PR state / draft.
world = {"pr_state": "OPEN", "draft": False, "merge_pr_calls": [], "closed_issues": []}

g = messages_module.github
g.is_merged = lambda *, pr_number: world["pr_state"] == "MERGED"
g.is_closed = lambda *, pr_number: world["pr_state"] == "CLOSED"
g.is_open = lambda *, pr_number: world["pr_state"] == "OPEN"
g.is_draft = lambda *, pr_number: world["draft"]
g.mergeability = lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN")
g.check_status = lambda *, pr_number: CheckStatus(state="pass", failed_logs=[])
g.merge_pr = lambda *, pr_number: world["merge_pr_calls"].append(pr_number)
g.close_issue = lambda *, number: world["closed_issues"].append(number)


class Orch:
    def __init__(self):
        self.review_code_calls = 0

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return ReviewDecision(passed=True, feedback="", verdicts=("PASS",))


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


def board_row():
    html = results.render(runs=state.all_runs())
    rows = [ln for ln in html.splitlines() if f"#{PR_NUM}" in ln and "<tr>" in ln]
    assert len(rows) == 1
    return rows[0]


# --- First round: People close PR & + beat closed_at jab ----------------------------#
world["pr_state"] = "CLOSED"
assert msgs.poll() == [{"pr_number": PR_NUM, "reason": "closed"}]
rec = state.find_by_issue(issue_number=ISSUE)
assert rec.status == STATUS_CLOSED and rec.closed_at
stamp = rec.closed_at
row_closed = board_row()
assert '<span class="status">closed</span>' in row_closed
print("  [close] First Round poll: Set closed + Fight! closed_at Time stamp (start of the resurrection window); board line=closed")

# --- Round 2: PR still closed and scanned but not revived, without retouching --------------------------------#
assert msgs.poll() == []
rec2 = state.find_by_issue(issue_number=ISSUE)
assert rec2.status == STATUS_CLOSED and rec2.closed_at == stamp, "No retouching (windows are not refreshed)"
assert board_row() == row_closed, "The board is stable across the line."
print("  [Stillclosed] Second poll: scanned but is_open=False→return Noneand will not be raised up,closed_at No update (costs defined)")

# --- Round 3: People reopen Yes. PR(retroactive)→ To the world. pr-open Clear closed_at ------------------- #
world["pr_state"] = "OPEN"
world["draft"] = False
assert msgs.poll() == [{"pr_number": PR_NUM, "reason": "reopened", "stage": STATUS_PR_OPEN}]
rec3 = state.find_by_issue(issue_number=ISSUE)
assert rec3.status == STATUS_PR_OPEN and rec3.closed_at == ""
assert orch.review_code_calls == 0, "The wheel will return to its place and not renew the gate."
row_reopened = board_row()
assert '<span class="status">pr-open</span>' in row_reopened and row_reopened != row_closed
print("  [reopen] Round three. poll: To be resurrected pr-open + Clear. closed_at + Back reopened;board lines closed→pr-open Flip")

# --- Round 4: After-emergence pr-open run Go through the coded gates and handle it properly.PASS→merge→done）-------- #
assert msgs.poll() == [{"pr_number": PR_NUM, "reason": "merged"}]
assert orch.review_code_calls == 1 and world["merge_pr_calls"] == [PR_NUM]
assert world["closed_issues"] == [ISSUE]
assert state.find_by_issue(issue_number=ISSUE).status == STATUS_DONE
print("  [Normal] Round four. poll: When the resurrection comes run Go through the coded gate. → PASS → merge → done”Restore and return to the process”")

print("  [Watch the results.] board.html The PR Line state flips correctly over timeline:closed → pr-open”Concepts.” 8）")
print("             Note: Real browser cut-off results (in thousands of United States dollars)Playwright/chrome-devtools MCP）By agent Driven outside scripts;")
print("             No Browser MCP Press T4 spec The downgrading was for that. HTML The text asserted that the results were not being tested.")

print("✓ Spec-0042 The restoration ring claims were all passed:closed It’s not the end of the world. → reopen Reborn. → Reverts existing processes (full offline, repeatable).")
PY

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [Optional] Real smoke.OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  Real smoke step (needs real) GitHub Warehouse + gh Login, it’ll be real./Off/Reopen PR）：
    1) Yes. scratch The warehouse is open. PRRun round vigil Let Local run Enter pr-open/rfc-review。
    2) Yes. GitHub Go, go, go! close This. PR(not merged)→ Round one. vigil：`oa vigil --once`
       Expected: Local run Set closed”Look at the board line=closed）。
    3) Yes. GitHub Go, go, go! reopen This. PR → Another round. vigil：`oa vigil --once`
       Expected: frozen to death run To be resurrected. pr-open(revision) or rfc-review（draft），closed_at Empty, watch the board line flips back.
    4) Run another round: after the resurrection run Continue to move forward by the established milestones (comments) / CI / The conflict is being re-managed and is no longer empty.
  (This paragraph only prints guidelines, does not automatically execute and avoids being CI/Offline error is real. gh。）
REAL
fi

echo
echo "✓ Spec-0042/T4 End-to-end demonstration completed (default offline, repeatable, net-free, unmovable) LLM/gh）。"
