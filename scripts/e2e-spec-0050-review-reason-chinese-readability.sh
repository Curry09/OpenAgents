#!/usr/bin/env bash
# Spec-0050/T2 peer-to-end test start script: Review does not use the reason to enhance readability - enforces reviewer feedback to a short Chinese text.
#
# This group has written the output format of "REASON/ISSUES/NEXT must be in Chinese with a short paragraph" for the output of the sentence
# Hard Statute (openagents/reviewer.py It's... _RUBRIC_TAIL，code/rfc The two gates are shared, and the change is effective at the same time.
# Pure prompt Text hardening + Single measure + This browser result e2e No decision to be corrected./Aggregation/Render/The post-link running-time behavior.
#
# [Why browser results e2e (Affirmation Self-censorship Tool Set, following end-to-end-ui-screenshots skill)]
#   I examined the tool set - this environment** has ** playwright / chrome-devtools MCP.
#   The change is different without UI meeting,** this feature results precisely as "readability of the repertoire"**: issue #124 original
#   "So that humans can be directly treated in github" and the result is on GitHub PR, which reviews this ** browser's visible interface** - "Referendation Summary"
#   If you have a small Chinese piece, it's a ** rendering/visual properties**. Press skill "what has visual effects, takes the visual path to the end."
#   This group** gives priority to the design of browser results e2e** (render page + screenshot + text assertion), rather than just stating shell assertions.
#
# [An honest hierarchy: authentic justification text is LLM output, not hermetic]
#   The reason for reviewer is the real backend deduction, which is not allowed to run real claude inside the CI. So decipher the "readability" certifications on two levels, and measure them:
#   - Offline certainty segment (default, hermetic, no network/no real caude) - ruff/format/pytest complete; grep anchoring assertion
#     _RUBRIC_TAIL with T1 Language/Long Hard Rules Key;** Browser render result exercise**: after following new prompt compliance with a "reviewer"
#     Short representative Chinese to output feedback fixture Hello?**Real** reviewer.render_decision(kind="code") Getting real.
#     Comment markdown poignant to GitHub-style HTML page poignant opened by an agent with playwright, tracked
#     docs/evidence/spec-0050/, browser_evaluate draws a "results summary" piece of text to assert the CJK ratio threshold and length threshold.
#     **RED Counter-proof**: This statement is supported by a cross-checking of the statement that the feed "old English long" should be denied (low/over long CJK).
#     An honest note: this feedback is the fixure, which is certified as the "render path + readability certificate" link and the test itself;
#     The authenticity of the reason is verified by the following ReAL section.
#   - Real result segments (optional, OPENAGENTS_E2E_REAL = 1, non-default, non-hermetic) - creating a visible flaw scratch PR, run-off
#     Reviewer to get real REWORK feedback, render_decision by orchestrator/identity to put real GitHub PR,
#     Playwright opens the PR page to "# Review Gate Award"
#
# Usage:
#   bash scripts/e2e-spec-0050-review-reason-chinese-readability.sh
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0050-review-reason-chinese-readability.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] Offline certainty segment (inlint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/3] grep The anchor asserted:reviewer.py It’s... _RUBRIC_TAIL Ham T1 Languages/Hard rule keyword for length"
REVIEWER="openagents/reviewer.py"
assert_grep() {
  # $1 = anchor string;-F fix a long match, missing is set-e exit.
  if ! grep -qF -- "$1" "$REVIEWER"; then
    echo "  ✗ Missing anchor:$1" >&2
    exit 1
  fi
  echo "  ✓ $1"
}
assert_grep "Grounds for adjudication of humanity (art.REASON / ISSUES / NEXT"
assert_grep "A short Chinese text: Hit the key"
assert_grep "One sentence in Chinese indicates the key certification criteria for checking"
assert_grep "There’s a problem with the Chinese word."
assert_grep "One sentence in Chinese indicates the direction of the restoration"

echo
echo "==> [3/3] Browser renderer exercise: Real render_decision → GitHub Style HTML Page + Readable (readable)GREEN/RED）"

EVIDENCE_DIR="docs/evidence/spec-0050"
GREEN_HTML="$EVIDENCE_DIR/comment-green-short-chinese.html"
RED_HTML="$EVIDENCE_DIR/comment-red-long-english.html"

uv run python - "$GREEN_HTML" "$RED_HTML" <<'PY'
# Spec-0050/T2 Result Exercise: Using ** Real** Product Code reviewer.render_decision (kind= "code") (no stakes, no changes to product code)
# Render two feedback fixtures into real comments markdown, and wrap them into GitHub-style HTML pages; and do "short Chinese" on offline
# The machine can verify the operationalization of the test (CJK ratio thallium threshold and length thallium threshold) and assert that GREEEN passed, RED failed -
# Proofs that the judge can distinguish between the two, green and unsustainable. Angent reviews the same two-page navigation + screenshot + browser_evaluate.
import html
import os
import sys

from openagents.reviewer import (
    ReviewDecision,
    _extract_feedback_norm,
    render_decision,
)

# ---- Readable Threshold (Spec-0050 Unresolved Questions) ----
# CJK ratio  → 0.5: Allows the entrapment of file paths/English terms (for a spec Drawbacks, use the decomposition belt instead of the "Chinese-language" term).
# Length 300: The upper limit of a "single " of a single summary of feedback is enough to express the conclusion + the next step is not too long to pile.
CJK_MIN_RATIO = 0.5
MAX_LEN = 300

# GREEN:reviewer should output a "Simplicit Chinese" reason (with a small number of file paths/English token) after complying with the new _RUBRIC_TAIL.
GREEN_FEEDBACK = (
    "ISSUES:\n"
    "- openagents/reviewer.py:42 Empty input without boundary processing, which is unusual\n"
    "NEXT: A single test and defense of an empty string branch\n"
    "REASON: Core path missing boundary cover, key certification criteria not met, and reset"
)
# RED Countered: The old English long-form justification (reviewer ' s typical bad output when ignoring language constraints) - the CJK is extremely low and too long and should be denied.
RED_FEEDBACK = (
    "ISSUES:\n"
    "- The empty-input path in openagents/reviewer.py:42 is not guarded, which means "
    "that when the caller passes an empty string the function will raise an unhandled "
    "exception and crash the whole review pipeline instead of degrading gracefully.\n"
    "NEXT: Please add a dedicated unit test that exercises the empty-string branch and "
    "introduce a defensive guard so that the reviewer never blows up on degenerate input.\n"
    "REASON: The core code path lacks boundary coverage and the key verification criteria "
    "are therefore not satisfied, so this change must be reworked before it can pass."
)


def cjk_ratio(text: str) -> float:
    """CJK Characters as a proportion of non-empty characters (the operationalized definition of Chinese as a percentage)."""
    stripped = [c for c in text if not c.isspace()]
    if not stripped:
        return 0.0
    cjk = sum(1 for c in stripped if "One." <= c <= "Zenium")
    return cjk / len(stripped)


def feedback_text_of(feedback: str) -> str:
    """Let’s go.**Real**Product render path:ReviewDecision → render_decision Comments markdown → The main text of the feedback section is taken from the text.

    Extract the rendered feedback block through the same path used by comment deduplication.
    ”That’s what I’m looking at. PR   The people are   GitHub The text read in the commentary.
    """
    decision = ReviewDecision(
        passed=False, feedback=feedback, verdicts=("REWORK",), actionable=True
    )
    body = render_decision(decision=decision, kind="code")
    return _extract_feedback_norm(lines=body.splitlines())


def render_html(*, title: str, feedback: str, verdict_label: str) -> str:
    """Put the real comment on it. markdown Render GitHub Style HTML Page, ”Summary of Feedback” box in id=feedback-summary For the assertion."""
    decision = ReviewDecision(
        passed=False, feedback=feedback, verdicts=("REWORK",), actionable=True
    )
    markdown = render_decision(decision=decision, kind="code")
    fb = feedback_text_of(feedback)
    esc_md = html.escape(markdown)
    esc_fb = html.escape(fb)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ background:#f6f8fa; font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
          color:#1f2328; margin:0; padding:32px; }}
  .comment {{ max-width:760px; margin:0 auto; background:#fff; border:1px solid #d0d7de;
              border-radius:6px; overflow:hidden; }}
  .comment-header {{ background:#f6f8fa; border-bottom:1px solid #d0d7de; padding:8px 16px;
                     font-size:12px; color:#59636e; }}
  .comment-body {{ padding:16px; }}
  h2 {{ font-size:18px; margin:0 0 12px; padding-bottom:6px; border-bottom:1px solid #d8dee4; }}
  ul {{ padding-left:20px; }}
  #feedback-summary {{ background:#f6f8fa; border:1px solid #d0d7de; border-radius:6px;
                       padding:12px; white-space:pre-wrap; font-family:ui-monospace,
                       SFMono-Regular,Menlo,monospace; font-size:13px; line-height:1.6; }}
  .raw {{ margin-top:24px; color:#59636e; font-size:12px; }}
  pre.raw-md {{ background:#f6f8fa; border:1px solid #d0d7de; border-radius:6px; padding:12px;
                white-space:pre-wrap; font-size:12px; }}
</style>
</head>
<body>
  <div class="comment">
    <div class="comment-header">openagents-bot Comment in GitHub PR · {html.escape(verdict_label)}</div>
    <div class="comment-body">
      <h2>Review of the lock ruling</h2>
      <ul>
        <li>Type: Code</li>
        <li>Decision:❌ REWORK</li>
        <li>Number of votes: 01 Number of votes 0 Tickets. PASS</li>
        <li>Type of ticket:REWORK</li>
      </ul>
      <p><strong>Summary of feedback:</strong></p>
      <div id="feedback-summary">{esc_fb}</div>
    </div>
  </div>
  <div class="raw">
    <p>—— The ”referral summary” section above is taken from the real <code>reviewer.render_decision(kind="code")</code> Comments markdown Original (Folded below):</p>
    <pre class="raw-md">{esc_md}</pre>
  </div>
</body>
</html>
"""


def check(label: str, feedback: str) -> tuple[float, int]:
    fb = feedback_text_of(feedback)
    ratio = cjk_ratio(fb)
    length = len(fb)
    passed = ratio >= CJK_MIN_RATIO and length <= MAX_LEN
    verdict = "Passed (short Chinese)" if passed else "Not Passed (Extralong)/English)"
    print(f"  [{label}] CJK Percentage={ratio:.2f}(Landlines)≥{CJK_MIN_RATIO}）"
          f" Length={length}(Landlines)≤{MAX_LEN}） → {verdict}")
    return ratio, length


green_out, red_out = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(green_out), exist_ok=True)

print("  -- Readable jurisprudence (real) render Path draws the ”referendant summary” block:")
g_ratio, g_len = check("GREEN Short Chinese", GREEN_FEEDBACK)
r_ratio, r_len = check("RED   Long English", RED_FEEDBACK)

# The ruling distinguishes between "short Chinese" and "old English" and "green and unsuspecting" (the "old Chinese" and "old English").
assert g_ratio >= CJK_MIN_RATIO and g_len <= MAX_LEN, (
    "GREEN Short Chinese fixture I can’t believe I’m not going through reading.——Threshold or rendering path abnormal"
)
assert not (r_ratio >= CJK_MIN_RATIO and r_len <= MAX_LEN), (
    "RED English Long fixture I’m sure it’s a reading test.——The verdict is indistinguishable, Green Sing-jin (invalidity)"
)

with open(green_out, "w", encoding="utf-8") as f:
    f.write(render_html(title="Review comments (short Chinese)·(i) Should adopt)",
                        feedback=GREEN_FEEDBACK, verdict_label="GREEN Short Chinese"))
with open(red_out, "w", encoding="utf-8") as f:
    f.write(render_html(title="Review comments (long English)·(should not be adopted)",
                        feedback=RED_FEEDBACK, verdict_label="RED Long English counter-argument."))

print(f"  [Render] GitHub Style Comment page written tracked List of evidence:")
print(f"    GREEN → {green_out}")
print(f"    RED   → {red_out}")
print("  [Textual assertion] Readability distinction GREEN/RED passed ✓”Green is not ever real.”")
PY

echo
echo "  References (pages)file:// Open it, don’t touch any production ports./Data:"
echo "    GREEN: file://$(pwd)/$GREEN_HTML"
echo "    RED  : file://$(pwd)/$RED_HTML"
cat <<'RUNBOOK'

  By agent Use browser MCP（playwright / chrome-devtools）Closed loop of the browser result (scripts render pages only) + To the instructions:
    1. navigate  → Open it up. GREEN Page file:// URL
    2. screenshot→ Can not open message docs/evidence/spec-0050/（tracked The ”Register Summary” is short Chinese.
    3. browser_evaluate → Remove document.getElementById('feedback-summary').innerTextIt’s fine. CJK Percentage with Length,
                          The assertion. Percentage ≥ 0.5 and Length ≤ 300;nuclear list_console_messages None error
    4. RED Counter-argument → Yeah. RED Page Repeat 1–3It’s the same thing.**I can’t pass.**（CJK Low/Overlong)
  If this environment is not objective browser MCP / None shown: Press end-to-end-ui-screenshots skill The honesty of the discipline is clear.
    ”The browser outcome segment was not implemented because no browser automation was done” blocking the entry, without de-lineating the part claiming to have run.
RUNBOOK

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [Optional] Real result paragraph (%2)OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  Real results steps (require real) GitHub Warehouse + gh Login + True claude backendIt’ll be real. PR/Comment, run. reviewer）：
    1) Yes. scratch The warehouse built a ”manifestly defective” PR(e.g., if a function is empty for entering a boundary, deletes the caller from the interface).
    2) One run, huh? reviewer（code The gate, really. backend）: Run-in-the-line code The judges have been able to get the truth. REWORK feedback，
       The long term render_decision → orchestrator/identity Paste to the real GitHub PR。
       Expected (renumbered): Comment ’Summary of Feedback’ section**A short paragraph in Chinese**（CJK High, short, watch. PR People read it at once.
    3) Use playwright Open the PR ”Page, Positioning”## ”Audit the gate ruling.” Comment, cut-off. docs/evidence/spec-0050/、
       browser_evaluate The summary of the feedback is the assertion CJK Percentage ≥ 0.5 and Length ≤ 300。
    4) Comparison (before) PR The results of the survey are often in English, but they are not in English.CJK Low percentage/It’s too long.——That’s Ben. feature Healing.
  (This paragraph only prints guidelines, does not automatically execute and avoids being CI/Offline error is real. gh/claude- It’s true. LLM The degree to which outputs were achieved is measured by this paragraph.
REAL
fi

echo
echo "✓ Spec-0050 End-to-end demonstration: All green offline (ruff+format+pytest+grep anchor)+ Real render The page has been rendered and readable;"
echo "  Browser ’s Outcome Closed Ring (Guavier)+Screenshot+browser_evaluate）By agent Press top to specify book use playwright/chrome-devtools MCP Implementation."
