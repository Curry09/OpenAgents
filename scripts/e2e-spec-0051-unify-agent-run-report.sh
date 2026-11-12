#!/usr/bin/env bash
# Spec-0051 End-to-end test start script: Unique agent post-exit PR comments (observable portal).
#
# The group has "Peagengent execution completed in PR and posted a signed note to comment" from the method to the layout level.
# (messages) Unidise: each step of executor/evidence_gate/ is matched with a pure function of render_* in
# _process_rfc_review / _process_coding / _evidence_gate Unified Three Entry Points "Enforcement of  → render_*
# _post_agent_report (identity.post_signed_comment, with brushscreen to re-heavy)" and fill in implement/
# Iterate (ci review e2e) / finalize_runbook / run_executor / review_evidence Five Silent Steps.
# After closing, executor/evidence_gate maintains no effect, no IO, and the only exit for comments.
#
# ** Browser e2e Not applicable**: This feature 'results 'is a machine review stream (observable) on GitHub PR, which has no one in this repository
# Product front-end interface driver (no navigation)/Interactive/I'm sure it's a good idea to make a real comment. GitHub。So the result test pattern is
# **Structific integration recurrence** (pytest drive whole chain + Ben shell runs it and prints evidence) instead of browser e2e. The whole journey** is net-free,
# Do not tune the real gh/LLM/git remote**.
#
# Usage:
#   bash scripts/e2e-spec-0051-unify-agent-run-report.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] Static Check (Standard)ruff lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] Orientation module/Integrated Test (Integrator Test)Spec-0051 T1–T6）"
uv run --extra dev pytest -q \
  tests/test_executor.py \
  tests/test_evidence_gate.py \
  tests/test_worknote.py \
  tests/test_orchestrator.py \
  tests/test_messages.py \
  tests/test_messages_agent_report.py \
  tests/test_agent_report_integration.py

echo
echo "==> [3/4] Evidence of results: use**Real** Messages Shut up. + render_* Drive the whole chain back and print three pieces of evidence to assert it."
uv run python - <<'PY'
# Spec-0051 Result Exercise: Using **real** product code - messages.Messages (with _post_agent_report/_report_already_posted)
# +5-Dig + executor.render_result/ evidence_gate.render_decision/ worknote.render_* True Rendering Functions
# – Runs out of "Peagen agent executes a signed note comment" and prints evidence. Scripts only provide memory versions of GitHub comments book +
# False orchestrator(Return to programmable) summary/handle）+ false award;release rendering/- To the heavy./The portal is all from product code.
from pathlib import Path

from openagents import identity
from openagents import messages as messages_module
from openagents.evidence_gate import EvidenceDecision
from openagents.executor import ExecutorResult
from openagents.github import CheckStatus, Comment, Mergeability
from openagents.messages import Messages
from openagents.orchestrator import RunbookHandle
from openagents.reviewer import ReviewDecision
from openagents.state import (
    STATUS_BLOCKED,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
)

AGENT_ID = "agent-self"


class Ledger:
    """Memory Leave GitHub Comment books:post_signed_comment It’s signed by the real man. body + Incremental created_at；list_comments Read back."""

    def __init__(self):
        self.comments = []
        self._seq = 0
        self.raise_on_post = False

    def post_signed_comment(self, *, pr_number, body, agent_id):
        if self.raise_on_post:
            raise RuntimeError("gh We’re dead.")
        self._seq += 1
        self.comments.append(
            Comment(
                id=f"c{self._seq}",
                author="openagents",
                body=identity.sign(body=body, agent_id=agent_id),
                created_at=f"2026-01-01T00:00:{self._seq:02d}Z",
            )
        )

    def list_comments(self, *, pr_number):
        return list(self.comments)

    def headers(self):
        out = []
        for c in self.comments:
            for line in c.body.splitlines():
                if line.strip().startswith("## "):
                    out.append(line.strip())
                    break
        return out


class FakeOrch:
    def __init__(self, *, code_decision, handle):
        self._code_decision = code_decision
        self._handle = handle
        self.iterate_calls = []

    def implement(self, *, pr_number):
        return "Achieved. issue Core logic"

    def review_code(self, *, pr_number):
        return self._code_decision

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append(reason)
        return f"According to the source, {reason} Feedback changed the code."

    def finalize_runbook(self, *, pr_number):
        return self._handle

    def commit_evidence(self, *, pr_number):
        pass


class FakeState:
    def __init__(self, *, runs):
        self._runs = list(runs)

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.status = status

    def increment_rounds(self, *, issue_number):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.rounds += 1
                return r.rounds
        return 0

    def increment_review_invalid(self, *, issue_number):
        return 0

    def reset_rounds(self, *, issue_number):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.rounds = r.review_invalid = r.merge_attempts = 0

    def set_block_gate(self, *, issue_number, gate):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        pass

    def set_unblock_detail(self, *, issue_number, detail):
        pass


HANDLE = RunbookHandle(
    worktree=Path("/wt"),
    runbook_path=Path("/wt/docs/e2e-results/5/runbook.md"),
    evidence_dir=Path("/wt/docs/e2e-results/5"),
    intent="Intent:x\nReceiving and inspection:\n- a",
    form="cli",
)


def run_record(*, status):
    return RunRecord(
        issue_number=3, branch="openagents/issue-3", pr_number=5, pr_url="u/pull/5",
        status=status, summary="", rounds=0,
    )


class Cfg:
    has_approval = True
    ci_state = "success"


def wire(ledger, cfg, *, evidence_decision):
    """- Put it on. messages Dependence on the memory book/False award (in thousands of United States dollars)monkeypatch Handmade equal value setattrIt doesn’t matter if the script recovers itself."""
    g = messages_module.github
    g.is_merged = lambda *, pr_number: False
    g.is_closed = lambda *, pr_number: False
    g.has_label = lambda *, pr_number, name: cfg.has_approval and name.endswith("approved")
    g.add_label = lambda *, pr_number, name: None
    g.remove_label = lambda *, pr_number, name: None
    g.merge_pr = lambda *, pr_number: None
    g.close_issue = lambda *, number: None
    g.update_branch = lambda *, pr_number: None
    g.mergeability = lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN")
    g.check_status = lambda *, pr_number: CheckStatus(state=cfg.ci_state, failed_logs=["FAIL test_x"])
    g.list_comments = ledger.list_comments
    messages_module.identity.post_signed_comment = ledger.post_signed_comment
    messages_module.identity.new_human_comments = lambda *, pr_number, since: []
    messages_module.executor.run_executor = (
        lambda *, backend, work_dir, runbook_path, evidence_dir, pr_number: ExecutorResult(
            outcome="passed", form="cli", notes="Run! init, exit code 0"
        )
    )
    messages_module.evidence_gate.review_evidence = (
        lambda *, backend, work_dir, intent, evidence_dir, pr_number: evidence_decision
    )


# --- Evidence 1 Leaves a letter of reply at each of the five points of entry ----------------------------------------#
ledger = Ledger()
cfg = Cfg()
orch = FakeOrch(code_decision=ReviewDecision(passed=True, feedback=""), handle=HANDLE)
rec = run_record(status=STATUS_RFC_REVIEW)
state = FakeState(runs=[rec])
wire(ledger, cfg, evidence_decision=EvidenceDecision(passed=False, feedback="Receiving and inspection behaviour①Not achieved"))
msgs = Messages(orchestrator=orch, state=state, agent_id=AGENT_ID, backend=object())

cfg.has_approval = True
msgs.poll()                       # rfc-approved → implement
rec.status = STATUS_PR_OPEN
cfg.has_approval = False
cfg.ci_state = "fail"
msgs.poll()                       # CI fail → iterate(ci)
rec.status = STATUS_ITERATING
cfg.ci_state = "success"
orch._code_decision = ReviewDecision(passed=False, feedback="Completion measurement", actionable=True)
msgs.poll()                       # reviewer REWORK → iterate(review)
orch._code_decision = ReviewDecision(passed=True, feedback="")
msgs.poll()                       # reviewer PASS → Evidence gate. FAIL → iterate(e2e)

expected = [
    "## Implementation report",
    "## Recursive self-presentation (infra).CI (Received)",
    "## Interpret (code review feedback)",
    "## Finalization of the manual",
    "## Evidence execution",
    "## Evidence lock ruling",
    "## Reciprocal self-statement (inventory gate feedback)",
]
headers = ledger.headers()
counts = {h: headers.count(h) for h in expected}
all_signed = all(identity.parse_agent_id(body=c.body) == AGENT_ID for c in ledger.comments)
print("  evidence①”Five exits each sign: one each with one signature in each of the seven categories.” =",
      all(v == 1 for v in counts.values()) and all_signed)
for h in expected:
    print(f"      {h}：{counts[h]} Article")
assert all(v == 1 for v in counts.values()), f"Some type of reply is unusual:{counts}"
assert all_signed, "Unsigned reply exists"

# --- Evidence 2 Repeat Poll without screening ------------------------------------------#
ledger2 = Ledger()
cfg2 = Cfg()
cfg2.has_approval = False
orch2 = FakeOrch(code_decision=ReviewDecision(passed=True, feedback=""), handle=HANDLE)
rec2 = run_record(status=STATUS_PR_OPEN)
state2 = FakeState(runs=[rec2])
wire(ledger2, cfg2, evidence_decision=EvidenceDecision(passed=False, feedback="Same feedback"))
msgs2 = Messages(orchestrator=orch2, state=state2, agent_id=AGENT_ID, backend=object())
msgs2.poll()
rec2.status = STATUS_ITERATING
msgs2.poll()                      # Two successive rounds of evidence, no change in content.
h2 = ledger2.headers()
dedup_ok = (
    h2.count("## Finalization of the manual") == 1
    and h2.count("## Evidence execution") == 1
    and h2.count("## Evidence lock ruling") == 1
    and h2.count("## Reciprocal self-statement (inventory gate feedback)") == 1
)
print("  evidence②[Repeats] poll No screen brush: one for each type after two rounds of the same proof gate (in thousands of years)_report_already_posted Hit=",
      dedup_ok)
assert dedup_ok, f"Reactivation:{h2}"

# --- Evidence 3 Commenting that failure does not interrupt the --------------------------------------------#
ledger3 = Ledger()
ledger3.raise_on_post = True
cfg3 = Cfg()
cfg3.has_approval = False
cfg3.ci_state = "fail"
orch3 = FakeOrch(code_decision=ReviewDecision(passed=True, feedback=""), handle=HANDLE)
rec3 = run_record(status=STATUS_PR_OPEN)
state3 = FakeState(runs=[rec3])
wire(ledger3, cfg3, evidence_decision=EvidenceDecision(passed=True, feedback=""))
msgs3 = Messages(orchestrator=orch3, state=state3, agent_id=AGENT_ID, backend=object())
events = msgs3.poll()             # Backends send all wrongs and the organization should go as usual.
not_blocked = (
    orch3.iterate_calls == ["ci"]
    and events == [{"pr_number": 5, "reason": "ci"}]
    and ledger3.comments == []
)
print("  evidence③[A comment failure continues]:post When all is thrown wrong iterate Still being transferred.poll Back ci Event, Book of Accounts is empty =",
      not_blocked)
assert not_blocked, "The comment failure blocked the organization."

print("  ✓ All three claims passed.")
PY

echo
echo "==> [4/4] spec VerifySpec-0051 Group Structure + OVERVIEW/ARCHITECTURE No drift)"
uv run spec validate --specs-root docs/specs
# ZiQQ000QXZ: A copy of render/graph should be stored before replaying and diff should be consistent byte - without git-based submission.
cp docs/specs/OVERVIEW.md /tmp/oa-0051-overview.bak
cp docs/specs/ARCHITECTURE.md /tmp/oa-0051-arch.bak
uv run spec render --specs-root docs/specs
uv run spec graph --specs-root docs/specs
diff /tmp/oa-0051-overview.bak docs/specs/OVERVIEW.md
diff /tmp/oa-0051-arch.bak docs/specs/ARCHITECTURE.md
uv run spec graph --specs-root docs/specs --check

echo
echo "✅ Spec-0051 End-to-end authentication pass: letter of signature for each of the five closing points + Repeat poll Do Not Screen + The failure to issue comments is not interrupted (the evidence is available for reproduction)."
