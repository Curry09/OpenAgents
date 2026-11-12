#!/usr/bin/env bash
# Spec-0052 End-to-end test start script: Unified entry context injection (all single entry belt PR+ inject this PR dialogue history).
#
# This group of governance issues #129 revealed two types of gaps (trigger case: PR #128 e2e gate repeated FAIL # needs-human):
#   Gap 1 P-injection Unharmonized - refine_rfc/ implement 's task missing PR; this group is added to form 'all Piles '
#     The entry point is always a unified agreement to write the PR number into the task.
#   Gap two. Ben. PR The history of dialogue never infusion.——All agent It's... context None of the judges have seen the verdicts./Author Response/Human Review;
#     The group draws build_agent_context, pulls it in one, removes it noise, and then cuts it and injects it into the four-entry (refine/implement/iterate + reviewer).
#   Reviewer, a "screw-in-the-book" rubric: both make it visible and keep its own warehouse unreadable.
#     The value of the phrase is not clear (it is precisely why PR #128 can** correctly** FAIL)
#
# ** Browser e2e Not applicable**: This feature is a backend prompt/context assembly change - the change is for the cli-agent subprocess
# Text, no product front-end interface driver (no navigation)/Interactive/The screenshot is a presumable visual result.UI I can't see it.
# But change the external behavior of the product" class, results test form** resembling definitive text** (pytest Improgram test + Ben shell runs it for printing
# Evidence) instead of browser e2e. The whole process is netless and does not match the real gh/LLM/git remote.
#
# Usage:
#   bash scripts/e2e-spec-0052-agent-context-injection.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# Prefer uv (same as other e2e scripts); back to python/pytest/ruff/spec in the current environment when uv is not available.
if command -v uv >/dev/null 2>&1; then
  PYTHON=(uv run python)
  PYTEST=(uv run --extra dev pytest)
  RUFF=(uv run --extra dev ruff)
  SPEC=(uv run spec)
else
  PYTHON=(python)
  PYTEST=(python -m pytest)
  RUFF=(ruff)
  SPEC=(spec)
fi

echo "==> [1/4] Static Check (Standard)ruff lint + format）"
"${RUFF[@]}" check openagents/agentcontext.py openagents/reviewer.py openagents/orchestrator.py \
  tests/test_agentcontext.py tests/test_reviewer_history.py tests/test_orchestrator_context.py \
  tests/test_agent_context_integration.py
"${RUFF[@]}" format --check openagents/agentcontext.py openagents/reviewer.py \
  openagents/orchestrator.py tests/test_agentcontext.py tests/test_reviewer_history.py \
  tests/test_orchestrator_context.py tests/test_agent_context_integration.py

echo
echo "==> [2/4] Orientation module/Integrated Test (Integrator Test)Spec-0052 T1–T4）+ Repatriation (return)reviewer / orchestrator Zero returns)"
"${PYTEST[@]}" -q \
  tests/test_agentcontext.py \
  tests/test_reviewer_history.py \
  tests/test_orchestrator_context.py \
  tests/test_agent_context_integration.py \
  tests/test_reviewer.py \
  tests/test_orchestrator.py

echo
echo "==> [3/4] Evidence of results: use**Real** build_agent_context + orchestrator + reviewer Revert #128 History, four pieces of evidence."
"${PYTHON[@]}" - <<'PY'
# Spec-0052 Result Exercise: Using **real** Product Code - agentcontext.build_agent_context (Play History+Noise+Close+PR)
# Orchestrator.refine_rfc/implement/iterate/review_code (Quadrance build_agent_context), reviewer.review
# (histoory injection + drop product is the ruler) -- run out of the two types of gap repair, print evidence. Scripts only provide evidence.
# Memory version GitHub Comment Book (#128 History: Claim Noise + Round FAIL Award + Author "changed PASS"+ Human Review)
# No guit's subproces double; PR-injected/ historical assembly/ denoise/ rubric all from product code.
import subprocess

from openagents import agentcontext, identity, reviewer
from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Comment
from openagents.reviewer import ReviewDecision
from openagents.state import State

# --- #128 Historic Book (real product replicating, drift-catching) ---#
DECISION = identity.sign(
    body=reviewer.render_decision(
        decision=ReviewDecision(
            passed=False, feedback="result.md Still. skipped", verdicts=("REWORK",), actionable=True
        ),
        kind="code",
    ),
    agent_id="reviewer-1",
)
REFINE = identity.sign(
    body=orch_module._REFINE_COMMENT.format(summary="Signed result.md Replace with PASS"), agent_id="author-1"
)
HUMAN = "Humans: Into the warehouse. result.md The truth is the truth, not just the commentary."
CLAIM = identity.build_claim_note(agent_id="claimer-9")
LEDGER = [
    Comment(id="1", author="claimer", body=CLAIM, created_at="2026-06-01T00:00:00Z"),
    Comment(id="2", author="reviewer", body=DECISION, created_at="2026-06-02T00:00:00Z"),
    Comment(id="3", author="author", body=REFINE, created_at="2026-06-03T00:00:00Z"),
    Comment(id="4", author="alice", body=HUMAN, created_at="2026-06-04T00:00:00Z"),
]


class CaptureBackend:
    name = "capture"

    def __init__(self):
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"task": task, "context": context})
        return AgentResult(changed=True, summary="VERDICT: PASS")


class GitRecorder:
    def __call__(self, args, **kwargs):
        class P:
            returncode = 0
            stdout = '{"comments": []}' if "comments" in args else ""
            stderr = ""

        return P()


import tempfile

tmp = tempfile.mkdtemp()
import pathlib

root = pathlib.Path(tmp)

# Manual version of MonkeyPatch (scripts are not pytest): Directly replaces the modular level function.
orch_module.github.list_comments = lambda *, pr_number: LEDGER
orch_module.github.post_comment = lambda *, pr_number, body: None
orch_module.github.mark_ready = lambda *, pr_number: None
orch_module.identity.post_signed_comment = lambda *, pr_number, body, agent_id: None
subprocess.run = GitRecorder()

backend = CaptureBackend()
state = State(path=root / ".openagents" / "state.json")
orch = orch_module.Orchestrator(backend=backend, state=state, work_dir=root, agent_id="agent-x")
state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=128, url="u/pull/128"))

# Evidence 1: build_agent_context Three types of historical advances + PR + noise.
ctx = agentcontext.build_agent_context(pr_number=128, extra_detail="Current round of feedbackX")
c1 = all(s in ctx for s in ("Ben. PR yes #128", "Review of the lock ruling", "Signed result.md Replace with PASS", HUMAN, "Current round of feedbackX"))
c1_noise = "openagents:claim" not in ctx and "openagents:agent=" not in ctx and "You know, I’m gonna have to go to the hospital. issue" not in ctx
print("  evidence①[Thirty-three historical developments] + PR No. No. + Current round of feedback / Sign it.+Sign noises:", c1 and c1_noise)

# Evidence 2: fill the PR (deficient I) with the tool.
orch.refine_rfc(pr_number=128, detail="reviewer Observations", announce=False)
orch.implement(pr_number=128)
orch.iterate(pr_number=128, reason="ci", detail="CI Feedback")
refine_c, implement_c, iterate_c = backend.calls
c2 = "PR #128" in refine_c["task"] and "PR #128" in implement_c["task"]
print("  evidence②【refine/implement It’s... task Ham PR   I’m not gonna get away with it  ", c2)

# Evidence 3: Three-entry constext contains a PR history (deficient II).
c3 = all(
    ("Ben. PR yes #128" in c["context"] and "Review of the lock ruling" in c["context"] and HUMAN in c["context"])
    for c in (refine_c, implement_c, iterate_c)
)
print("  evidence③【refine/implement/iterate It’s... context Hamburn. PR History (Face 2):", c3)

# Evidence 4: reviewer history + landing product is valid.
backend.calls.clear()
decision = orch.review_code(pr_number=128)
rev_ctx = backend.calls[0]["context"]
c4_hist = "Ben. PR yes #128" in rev_ctx and "Review of the lock ruling" in rev_ctx and HUMAN in rev_ctx
c4_rubric = all(
    ("The fallout will be the product." in t and "Comments for information purposes only" in t)
    for t in (reviewer._RFC_REVIEW_TASK, reviewer._CODE_REVIEW_TASK)
)
print("  evidence④【reviewer History. + The fallout will be the product. rubric Entry into force]", c4_hist and c4_rubric)

assert c1 and c1_noise, "evidence①Failure: Three Historys/PR No. No./Noise Filter"
assert c2, "evidence②Failed:refine/implement task Missing PR No. No."
assert c3, "evidence③Failed: Entry context Missing PR History"
assert c4_hist and c4_rubric, "evidence④Failed:reviewer Not yet history or rubric Not in force"
print("  ✓ All four claims passed.")
PY

echo
echo "==> [4/4] spec VerifySpec-0052 Group Structure + OVERVIEW/ARCHITECTURE No drift)"
"${SPEC[@]}" validate --specs-root docs/specs
# ZiQQ000QXZ: A copy of render/graph should be stored before replaying and diff should be consistent byte - without git-based submission.
cp docs/specs/OVERVIEW.md /tmp/oa-0052-overview.bak
cp docs/specs/ARCHITECTURE.md /tmp/oa-0052-arch.bak
"${SPEC[@]}" render --specs-root docs/specs
"${SPEC[@]}" graph --specs-root docs/specs
diff /tmp/oa-0052-overview.bak docs/specs/OVERVIEW.md
diff /tmp/oa-0052-arch.bak docs/specs/ARCHITECTURE.md

echo
echo "✅ Spec-0052 End-to-end authentication is through:PR No. In. prompt / Three types of historical development context / Noise filtered / reviewer It’s history. rubric Entry into force (repeated evidence above)."
