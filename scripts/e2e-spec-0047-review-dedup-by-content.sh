#!/usr/bin/env bash
# Spec-0047 End-to-end test start script: the evaluation decision is heavy as " substance " (same as conclusion . for reasons).
#
# This group upgrades the deweighted identity of orchestrator._decision_already_posted from the "Face-head + Type + Award" line to
# reviewer.extract_decision_content (body=rendered) received a decisionContent (conclusion + normative feedback):
# Only when verdict_line is the same as feedback_norm. This preserves the protection of PR#61 "33 identical PASS"
# The screen is re-heated and the image #116 is posted on each round of independent decision reviews.
# PR can see how the cards evolve.
#
# Three sections, full** netless, untranched LLM, untouched gh, unconnected to the git ** (except stage 3, to be visible):
#   1) Offline certainty (default) - ruff lint/format + pytest package, overwrite T1 (extract_decision_content)
#      Parser: EnderQextract / comment.body / PASS empty feedback / regularize Whitespace irrelevant /
#      The non-decided None) and T2 (issue #116) are different from the two rounds of REWORK-suppl./ PR #61 and PASS-supple/ REWORK
#      Go heavy / Take the latest contrast / PASS → REWORK Flip-Embrace / Kind / list_comments fail-open.
#   2) Offline result exercise (default execution, browser priority) - with reviewer.render_decision+
#      orchestrator._decision_already_posted Runs a memory comment area scene: round1 code REWORK (justification A) →
#      Round2 code REWORK (ground B → A) round3/4 Same PASS, capture "which ones are actually sent out" and deliver the award
#      Commenting is a simulation of PR session static HTML by timeline. Browser (Playwright/chrome-devtools MCP by agent)
#      The + snapshot+ transcribed assertion that both REWORK (ground A  →  reason B) is visible and PASS only 1
#      bar, console/network. No error reported. No browser MCP script is downgraded to a text assertion for this HTML, and does not skip the result validation.
#   3) Real smoke (optional, OPENAGENTS_E2E_REAL = 1) - A hint of how to build a two-wheeled code in a scratch warehouse
#      REWORK, for different reasons, ran vigil observation PR comment ** Two different REWK decision comments appear (only one before being changed).
#
# Usage:
#   bash scripts/e2e-spec-0047-review-dedup-by-content.sh
#   OPENAGENTS_E2E_REAL = 1 bash scripts/e2e-spec-0047-review-dedup-by-content.sh # Add a real smoker
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline result exercise: Real render_decision + _decision_already_posted Driver Memory Comment Area → HTML"

OUT_HTML="docs/evidence/spec-0047/pr-conversation.html"
uv run python - "$OUT_HTML" <<'PY'
# Spec-0047 Result Exercise: Using ** Real** Product Code - reviewer.render_decision (Rendering the body of the award review) +
# orchestrator._decision_already_posted (extension by content of the group) - Simulates a PR multiple-round review
# Memory comment area, captures "judgment comments actually sent after weight" and then wraps it in static HTML browser/text assertion.
# The script only provides memory comment areas and HTML packages (test side clips) to re-evaluate that the body of comments is all from the product code.
import html
import os
import sys

from openagents import github, identity, reviewer
from openagents.github import Comment
from openagents.orchestrator import Orchestrator
from openagents.reviewer import ReviewDecision

PR = 6  # Correspond issue #116 Reverted Drifting12345/LLMwiki4rolePlay PR #6

# --- Memory comment area (substitute) github.list_comments / identity.post_signed_comment, the rest of the product code remains intact)---
_comments: list[Comment] = []
_clock = [0]


def _list_comments(*, pr_number):
    return list(_comments)


def _post_signed(*, pr_number, body, agent_id):
    # Simulates the identity stamp: Add a signed tail (extract_decision_content should exclude it from feedback) after the decision body.
    _clock[0] += 1
    signed = body + f"\n\n---\n🤖 By {agent_id} Autopublishing · #{_clock[0]}\n"
    _comments.append(
        Comment(id=f"c{_clock[0]}", author=agent_id, body=signed, created_at=f"2026-07-03T13:{_clock[0]:02d}:00Z")
    )


github.list_comments = _list_comments
identity.post_signed_comment = _post_signed

# _decision_already_posted / _post_review_decision only used github/identity/reviewer/_progress,
# Do not touch other self properties; a _procress account with an uninitialized example can run the product through the logic.
orch = object.__new__(Orchestrator)
orch._agent_id = "agent-0047"
orch._progress = lambda *, message: print(f"    [orchestrator] {message}")

# --- Four-round evaluation: R1 code REWORK (ground A)  →  R2 code REWORK (ground B → A)  →  R3/R4 Same PASS ---
REASON_A = "EntityWithContent Inheritance is not compatible. / Chapter-Field pattern missing / _validate_specs CWD bug"
REASON_B = "_validate_specs:65 Crash bug + 8 individual task Zero achieved (with R1 A completely different card point)"
rounds = [
    ("R1", ReviewDecision(passed=False, feedback=REASON_A, verdicts=("REWORK",), actionable=True)),
    ("R2", ReviewDecision(passed=False, feedback=REASON_B, verdicts=("REWORK",), actionable=True)),
    ("R3", ReviewDecision(passed=True, feedback="", verdicts=("PASS",))),
    ("R4", ReviewDecision(passed=True, feedback="", verdicts=("PASS",))),
]
for name, decision in rounds:
    before = len(_comments)
    orch._post_review_decision(pr_number=PR, kind="code", decision=decision)
    verb = "- I’ll do it." if len(_comments) > before else "To skip again."
    print(f"  [{name}] {'REWORK' if not decision.passed else 'PASS'} → {verb}")

# --- results self-check (de-cordar): R1 is left with R1 one REWORK; R1+R2 with two different ROWORKs, PASS only 1 ---
posted_bodies = [c.body for c in _comments]
rework_count = sum(1 for b in posted_bodies if "❌ REWORK" in b)
pass_count = sum(1 for b in posted_bodies if "✅ PASS" in b)
assert any(REASON_A in b for b in posted_bodies), "Rationale A（R1 REWORK）missing"
assert any(REASON_B in b for b in posted_bodies), "Rationale B（R2 REWORK）They’re gonna swallow it again.——issue #116 Not repaired"
assert rework_count == 2, f"I should have. 2 It’s different. REWORK Comment of the award, actual {rework_count}（issue #116 (Photos)"
assert pass_count == 1, f"Same PASS It’s time to get worse. 1 Article (Article)PR #61 Brushscreen) {pass_count}"

# --- Scrolls the ruling comments actually issued after weighting into a simulation by timeline for the HTML --- session
items = []
for c in _comments:
    items.append(
        "<li class='comment'>"
        f"<div class='meta'>{html.escape(c.author)} · {html.escape(c.created_at)}</div>"
        f"<pre>{html.escape(c.body)}</pre></li>"
    )
page = (
    "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
    "<title>Spec-0047 PR Comment Area Results</title>"
    "<style>body{font-family:sans-serif;max-width:820px;margin:24px auto}"
    ".comment{border:1px solid #d0d7de;border-radius:8px;padding:12px;margin:12px 0;list-style:none}"
    ".meta{color:#57606a;font-size:12px;margin-bottom:6px}"
    "pre{white-space:pre-wrap;margin:0}h1{font-size:18px}</style></head><body>"
    f"<h1>Simulation PR #{PR} Comment area: comments on decisions actually issued after they have been re-examined</h1>"
    f"<ul id='pr-conversation'>{''.join(items)}</ul>"
    "</body></html>"
)
out = sys.argv[1]
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(page)

print(f"  [Render] It’s actually coming out after we re-reload. {len(_comments)} The judgment commentary is still in the state. HTML：{out}")
print(f"  [Textual assertion] REWORK Rationale A ∧ Rationale B Each 1 Article (total) 2 It’s different. REWORK）、PASS Only 1 Article ✓")
PY

echo
echo "  [Browser Result] Use the browser, please. MCP（Playwright / chrome-devtools）Navigator and assertion (in the case of theagent Driven outside script:"
echo "    navigate  → file://$(pwd)/$OUT_HTML"
echo "    snapshot/Screenshot → The assertion that two pages appear at the same time REWORK award (’grounds ’ ) A』And ’cause B』The text is visible."
echo "                    ✅ PASS The verdict only appears. 1 Article (same) PASS Weighted)"
echo "    console/network → Claim no error, no request for failure (none local static page)"
echo "  No Browser MCP Time: The offline version assertion above is certified as a downgrade result (not skipping)."

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [Optional] Real smoke.OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  Real smoke step (needs real) GitHub Warehouse + gh Login, it’ll be real. PR/Comment, run. vigil）：
    1) Yes. scratch The warehouse will be built in two consecutive rounds for ”all reasons.”code REWORK It’s... PR：
       Let it happen. agent Yes. R1 And then we’ll get rid of some of the problems and expose a new set of problems. 2 Wheel reviewer Feedback ≠ I’m not sure. 1 Round.
    2) Run! vigil Watch the time PR The comment area:`oa vigil --once`(SINGING IN RADIO) R2 (c) Evaluation.
       Expected (re)/Corrected): comment area emerging**Two.**Independent `## Review of the lock ruling ❌ REWORK`The two ”revenue summaries” are different.
       Contrast (before reword):R2 with R1 Same as REWORKThey’ve been re-inflated by the conclusion. R1 One. REWORK。
    3) Let the time be. PR Final evaluation passed and multiple rounds run: same as test `✅ PASS` Still only stay. 1 Article (Article)PR #61 The brush screen is not back.
  (This paragraph only prints guidelines, does not automatically execute and avoids being CI/Offline error is real. gh。）
REAL
fi

echo
echo "✓ Spec-0047 End-to-end demonstration completed (default offline, repeatable, net-free, unmovable) LLM/gh）。"
