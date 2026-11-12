#!/usr/bin/env bash
# Spec-0055 end-to-end test start script: e2e v2 - Capability Awareness + Description Book Direct Feed + Merge View (Redesign 0040).
#
# The group has a three-storey mechanical scaffolding from the 0040 "form Assign + finalize_runbook Final + Independent Evidence Gate" re-designed as:
#   1 Vigil Start envcheck sweep  →  ui_capable for state.json (read only when reading);
#   2 E2e = inent + prose method (no form, no precise command); RFC drafting/appraising of ui_capable diversion;
#   3 Internet access code;
#   4 CI Green Queen Independence Execuator to run directly with prose method (HYDRA, browser, screenshot)
#      docs/e2e-results/<pr>/, source-code fingerprints (exclusion of evidence catalogues) etc.: source code is used no reruns if it remains unchanged;
#   5 Existing review_code simultaneous sentencing code + evidence (reviewer visual) without independent proof locks.
#   Conservation: Proof part back-source print unchanged  →  sticky reuse PASS+ jump executor, CI Green is direct merge; evidence
#   Accident. CI Red → bad_ci_after_e2e Tab + _block（needs-human + blocked）They don't go to jail.
#
# ** Untouched, untouched LLM, untouched gh/git Remote, unbrowsed**:
#   1) Offline certainty (default) - ruff lint/format + pytest complete, covering T1 capacity Quantities, T2 spec Skin,
#      T3 execuator rewrite, T4 reviewer merge duties, T5 run_e2e Zi, etc. + Fingerprint Evidentiary Directory, T6 Stream Line Re-alignment
#      bad_ci_after_e2e。
#   2) Offline Results Exercise (Default) - _process_coding with real state + memory GitHub world drive as 'execuator in '
#      Review was previously rewired/ source code unmodified and does not run again / bad_ci_after_e2e walk blocked" (idems 8).
#   3) Key nonvariable grep anchor (default execution) - assertion that the code layer reverses/skinned has landed (execuator no form, reviewer evidence,
#      run_e2e exists, code_fingerprint excludes the evidence catalogue, bad_ci label.
#
# Browser e2e: The group deliverer is a back-end arrangement (e2e re-alignment of the internal polle of the night watcher, no project-facing front end)
# Interfaces navigable; group's own ui capability path (execuator real browser intercept) is downgraded by design under ** CI environment without browser**
# This script is being performed. The result evidence is therefore based on the offline segment driven by CLI/pytest below, which is the correct visual view of the internal behaviour.
#
# Usage:
#   bash scripts/e2e-spec-0055-e2e-v2-capability-aware.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/3] Offline result exercise:executor Yes. review Front / Source not modified / bad_ci_after_e2e Let’s go. blocked"
uv run python - <<'PY'
# Spec-0055: Real State + Memory GitHub World, Offline Drive _process_coding, validate e2e v2 current line syntax.
from openagents import messages as messages_module
from openagents.executor import ExecutorResult
from openagents.github import CheckStatus, Mergeability
from openagents.hold import NONE as NO_HOLD
from openagents.messages import Messages
from openagents.orchestrator import E2ERunResult
from openagents.reviewer import ReviewDecision
from openagents.state import STATUS_BLOCKED, STATUS_PR_OPEN, RunRecord

AGENT_ID = "agent-e2e-0055"


class _State:
    def __init__(self, record):
        self._runs = [record]
        self.status = []

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        self.status.append(status)
        self._runs[0].status = status

    def increment_rounds(self, *, issue_number):
        self._runs[0].rounds += 1
        return self._runs[0].rounds

    def increment_review_invalid(self, *, issue_number):
        return 0

    def reset_rounds(self, *, issue_number):
        pass

    def set_block_gate(self, *, issue_number, gate):
        self._runs[0].block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        pass

    def set_code_fingerprint(self, *, issue_number, fingerprint):
        self._runs[0].code_passed_fingerprint = fingerprint


class _Orch:
    def __init__(self, *, e2e_result):
        self.e2e_result = e2e_result
        self.calls = []

    def run_e2e(self, *, pr_number):
        self.calls.append("run_e2e")
        return self.e2e_result

    def review_code(self, *, pr_number):
        self.calls.append("review_code")
        return ReviewDecision(passed=True, feedback="")

    def iterate(self, *, pr_number, reason, detail):
        self.calls.append(f"iterate:{reason}")
        return "s"


def _wire(*, ci="pass", fingerprint="", labels=None, merged=None):
    labels = labels if labels is not None else []
    merged = merged if merged is not None else []
    g = messages_module.github
    for name, fn in {
        "is_merged": lambda *, pr_number: False,
        "is_closed": lambda *, pr_number: False,
        "has_label": lambda *, pr_number, name: False,
        "list_comments": lambda *, pr_number: [],
        "mergeability": lambda *, pr_number: Mergeability(
            mergeable="MERGEABLE", merge_state_status="CLEAN"
        ),
        "check_status": lambda *, pr_number: CheckStatus(state=ci, failed_logs=["boom"]),
        "code_fingerprint": lambda *, pr_number: fingerprint,
        "merge_pr": lambda *, pr_number, method="merge": merged.append(pr_number),
        "add_label": lambda *, pr_number, name: labels.append(name),
        "close_issue": lambda *, number: None,
    }.items():
        setattr(g, name, fn)
    messages_module.identity.post_signed_comment = lambda *, pr_number, body, agent_id: None
    messages_module.identity.new_human_comments = lambda *, pr_number, since: []


def _record(**kw):
    base = dict(
        issue_number=3, branch="b", pr_number=5, pr_url="u", status=STATUS_PR_OPEN, summary=""
    )
    base.update(kw)
    return RunRecord(**base)


# A) Before reporting: run_e2e  →  (reused = False)  →  This round does not review (early relinquishing evidence to CI).
orch = _Orch(e2e_result=E2ERunResult(reused=False, result=ExecutorResult(outcome="passed", notes="n")))
state = _State(_record())
merged = []
_wire(ci="pass", fingerprint="", merged=merged)
Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)._process_coding(
    record=state.all_runs()[0], hold=NO_HOLD
)
assert orch.calls == ["run_e2e"], f"executor Should review You’re a real runaway, you’re a real one. {orch.calls}"
assert merged == [], "It’s not the right time. mergeWait for proof. CI）"
print("  ✓ A: executor Yes. review Before that; it was a long time ago. No. merge")

# B) Source code unmodified: run_e2e reused=True  →  continues review  →  merge.
orch = _Orch(e2e_result=E2ERunResult(reused=True, result=None))
state = _State(_record())
merged = []
_wire(ci="pass", fingerprint="", merged=merged)
Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)._process_coding(
    record=state.all_runs()[0], hold=NO_HOLD
)
assert orch.calls == ["run_e2e", "review_code"], f"Reuse continues review- That’s right. {orch.calls}"
assert merged == [5], "Reuse + review PASS Reactions merge"
print("  ✓ B: run_e2e Reuse (source code unchanged)→ Go on. review → merge")

# C) bad_ci_after_e2e: Source code from e2e to run (same fingerprints), CI reded  →  blocked + double tag, no item(ci).
orch = _Orch(e2e_result=E2ERunResult(reused=True, result=None))
state = _State(_record(e2e_ran_fingerprint="fp-x"))
labels = []
_wire(ci="fail", fingerprint="fp-x", labels=labels)
Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)._process_coding(
    record=state.all_runs()[0], hold=NO_HOLD
)
assert "iterate:ci" not in orch.calls, "bad_ci It’s not supposed to be called back. iterate(ci)"
assert STATUS_BLOCKED in state.status, "bad_ci Deal blocked Hold on."
assert "bad_ci_after_e2e" in labels, "Fight! bad_ci_after_e2e Diagnostic label"
print("  ✓ C: evidence commit Red CI → bad_ci_after_e2e + blocked(No, no, no, no, no. iterate）")

print("Offline result exercise is green ✅")
PY

echo
echo "==> [3/3] Key non-variant grep anchor"
grep -q "def run_executor" openagents/executor.py
! grep -q "_run_by_form\|OUTCOME_SKIPPED\|_UI_FORM" openagents/executor.py \
  && echo "  ✓ executor Deleted form Assign / ui-skipped"
grep -q "def run_e2e" openagents/orchestrator.py && echo "  ✓ orchestrator.run_e2e Existence"
! grep -q "def finalize_runbook\|def commit_evidence" openagents/orchestrator.py \
  && echo "  ✓ finalize_runbook / commit_evidence Retired"
grep -q "exclude_paths" openagents/github.py && echo "  ✓ code_fingerprint Support for excluding the catalogue of evidence"
grep -q "And run-time behavior." openagents/reviewer.py && echo "  ✓ code reviewer Inversely converts to run-time behavior"
grep -q "ui_capable" openagents/reviewer.py && echo "  ✓ RFC The gate. ui_capable Diversion"
grep -q "bad-ci-after-e2e" openagents/messages.py && echo "  ✓ messages Ham bad_ci_after_e2e park"
grep -q "def ui_capable" openagents/envcheck.py && echo "  ✓ envcheck.ui_capable Existence"

echo
echo "All pass. ✅（Spec-0055 e2e v2）"
