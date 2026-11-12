#!/usr/bin/env bash
# Spec-0048/T2 End-to-end test start script: Review protection against "Faceform skeletons are faked to complete."
#
# This group has written "design-as-implication" as three rubric text hardened (all in)
# openagents/reviewer.py, pure prompt/rubric, without changing any running time module:
#   (1) _CODE_REVIEW_TASK Add "Automated Hard Rules for Integrity" - PR When claiming to add an automated implementation link, ask each other
#       Main process trigger / called evidence / auto-generated and / formal / inverse / integrated path instead of local
#       function, without any reWORK, for the reason "only the bone skeleton, not the full link";
#   (2) _RFC_REVIEW_TASK Add "Automation spec commitment against over-commitment" - spec commitment automated link
#       Statement Trigger Time/Caller/artifact Drop Point/Failed Path/Positive·Inverse acceptance or only draft design (suppleted only) rfc (a) The gate;
#   (3) _EVIDENCE_RUBRIC from "claimed but unsubstantiated REWORK" to "claimed automated execution/door control capability"
#       A design sketch without observed behavior must receive REWORK.
#
# [Why not a browser e2e (in good faith, following the discipline of end-to-end-ui-screenshots skill]]
#   I checked my tool set -- this environment** has ** playwright / chrome-devtools MCP. But Ben spec is a pure **
#   reviewer prompt/rubric Text hardening**，**No product is out there. UI Interface**Changed: The observable result is
#   "Performing to the skeleton, the decision of reviewer is directed to REWORK, which is a change in evaluation criteria, not a page/interactive change.
#   This change by Skiller "UI Visible Interception / UI Unvisible but Changed Product Behaviour to Run Log Text / Pure Internal Preference Test"
#   The correct result is ** definitive offline assertion + real rubric text crossbones
#   Fake scene** instead of browser navigation screenshot. Forced browser procession is self-deception of "tools" with UI.
#
# [RED Resert After After, Not PRS] Provisionally restore the old rubric text before openagents/reviewer.py hardened
#   (Deleting _AUTOMATION_INTEGRITY_RUBRIC / _RFC_AUTOMATION_RUBRIC / _EVIDENCE_RUBRIC extensions) and running the runback
#   Script: Three grep anchors in the offline segment should** be missing**, and the result-drive gap-by-deposit assertion should** be red** — to prove that green is not constant.
#   Over `git checkout openagents/reviewer.py` returns, does not bring RED scaffolding into PR.
#
# Two segments, full** netless, untouched LLM, untouched gh** (except for phase real smoke, to be visible):
#   1) Offline certainty segment (default, hermetic) - ruff check/format + pytest set; and grep anchor assertion
#      openagents/reviewer.py contains three harded keywords (three groups) for T1.
#   2) Bones impersonating the result exercise (default execution, offline, real product code reviewer._task_for) - real
#      _task_for(kind=code)/_task_for(kind=rfc) Generate Actual review _Other Organiser PR #105 Reset scenes side by side
#      Rendering as readable to write to tracked docs/evidence/spec-0048/, asserting that the text of the review task covers each gap in the scene by article.
#   3) Real smoke (optional, OPENAGENTS_E2E_REAL = 1) - suggests how to create a PR, run-off reviewer observation that is only bone-coated and wireless
#      The code award REWORK contains the rationale "only achieves the skeleton, but not the complete link".
#
# Usage:
#   bash scripts/e2e-spec-0048-anti-design-as-implementation-review.sh
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0048-anti-design-as-implementation-review.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [1/2] grep The anchor asserted:reviewer.py Ham T1 Three hard-worded keywords."
REVIEWER="openagents/reviewer.py"
assert_grep() {
  # $1 = anchor string;-F fix a long match, missing is set-e exit.
  if ! grep -qF -- "$1" "$REVIEWER"; then
    echo "  ✗ Missing anchor:$1" >&2
    exit 1
  fi
  echo "  ✓ $1"
}
echo "  (a) _CODE_REVIEW_TASK Automation Integrity Six:"
assert_grep "Automation integrity"
assert_grep "Main process trigger point"
assert_grep "artifact Automatically Generate and commit"
assert_grep "- Yes, sir.·Inverse"
assert_grep "Integrated Paths instead of Local Functions"
assert_grep "Only bone skeletons, unproven link."
echo "  (b) _RFC_REVIEW_TASK Automation spec Over-commitment:"
assert_grep "Automation spec Overcommitment"
assert_grep "Trigger Time"
assert_grep "Caller"
assert_grep "artifact Drop Point"
assert_grep "Failed Path"
assert_grep "Positive·Counterfeit acceptance"
echo "  (c) _EVIDENCE_RUBRIC Extending to the declaration of automation capacity:"
assert_grep "We’re going to automate it./Door control."
assert_grep "No real or integrated evidence → REWORK"

echo
echo "==> [2/2] Bones play as a result: real reviewer._task_for Contrast PR #105 Reset scene → tracked artifact"

OUT_MD="docs/evidence/spec-0048/skeleton-impersonation-drill.md"
uv run python - "$OUT_MD" <<'PY'
# Spec-0048/T2 Results Exercise: Generate actual sessions with reviewer._task_for (no stakes, no code changes)
# Feed the full report of the review job for reviewer with a "PR #105 Reset scene description" (New executor/evidence_gate only)
# Modules, door control positions, only module-level single-scale, no-sourced process proof) and renderable to readable Markdown, assertion of review task text
# ** Article by article ** Every gap in the skeletal posing scene ** * that proves that the control list that reviewer has was enough to get after this new prompt
# PR #105, the type of PR orientation REWORK (restricted to reviewer relying on truth back reasoning) cannot be hermetic, which is the assertion that "directive"
# The blog is a good one, but it is a good one, and it is a good one, but it is a good one, and it is a good one.
import os
import sys

from openagents import reviewer

PR = 105  # PR #105 / issue #104：e2e The new link delivered only skeletons, without a proven full-container fuse.

code_task = reviewer._task_for(kind="code", pr_number=PR)
rfc_task = reviewer._task_for(kind="rfc", pr_number=PR)

# PR #105 Recalculation scene: Each gap is a cross-referenced post in the new rubric (must appear in the full code review).
GAPS = [
    (
        "Add Only openagents/executor.py Modules, but no function of the main process/The status branch goes to it.",
        "Main process trigger point",
        code_task,
    ),
    (
        "executor Only call by their own single-scale modular-level monitoring, not by established organization links (dead / unwired module）",
        "Called evidence.",
        code_task,
    ),
    (
        "Claims executor Auto-outputs result.md and commit Come back. PR, but diff There’s no automatic output in there./Submission of evidence",
        "artifact Automatically Generate and commit",
        code_task,
    ),
    (
        "No formal proof. e2e PASS No, no, no, no, no, no, no, no, no, no, no, no. e2e FAIL Stop merge",
        "- Yes, sir.·Inverse",
        code_task,
    ),
    (
        "Only the test. parser/render/decision Local function, without overwhelming the real integration path",
        "Integrated Paths instead of Local Functions",
        code_task,
    ),
    (
        "If you don’t have any evidence, you’ll have to judge. REWORK, for a reason.",
        "Only bone skeletons, unproven link.",
        code_task,
    ),
    (
        "Design gate pre-dispatch:spec The commitment to automated links is not clear./Caller/artifact Drop Point/Failed Path/Positive·(Retroactive acceptance)",
        "Automation spec Overcommitment",
        rfc_task,
    ),
    (
        "Declaration of integrity: declaration of automated implementation/The door control doesn’t produce real or integrated evidence.",
        "We’re going to automate it./Door control.",
        code_task,
    ),
]

# --- Offline Ironic: review task text covers every gap of PR #105 skeleton fake scene ---
rows = []
for gap, anchor, task_text in GAPS:
    covered = anchor in task_text
    assert covered, f"review Mission does not cover gaps:{gap}(Low anchor points){anchor}』——Stabilization not effective or reversed)"
    rows.append((gap, anchor, "code" if task_text is code_task else "rfc"))

# The rifc-only rules do not leak into the code gate, or the ividence extension does not leak into the refc gate.
assert "Automation spec Overcommitment" not in code_task, "rfc The exclusive rule is missing code The gate."
assert "We’re going to automate it./Door control." not in rfc_task, "evidence Extension Error Incoming rfc The gate."

# --- Review the whole of the real task + scene contrasting to readable tracked product ---
lines = []
lines.append("# Spec-0048 Results exercise:reviewer rubric Contrast PR #105 The skeleton is a fake scene.\n")
lines.append(
    "> The present document is submitted by `scripts/e2e-spec-0048-anti-design-as-implementation-review.sh` Auto-generated (results test,"
    "Concept 8）。All review Task text from**Real product code** `openagents/reviewer._task_for(...)`，"
    "It’s not manual.\n"
)
lines.append("## PR #105 Recapitulation scene (bones skeletal posing as complete)\n")
lines.append(
    "PR #105 Says to put e2e Upgrade to a new link (spec Statement e2e Intention → implement Write code → finalize_runbook "
    "Finalization of the notes → executor agent Run for your own life. → Solidize evidence → evidence_gate Door control. merge）and**Indeed.**It’s new. "
    "`executor.py`/`evidence_gate.py`Put the evidence in the door. `review_code PASS` Back `merge_pr` I’ve made up a few pieces."
    "Module-level monometry——**Looks like it’s done.**。But... diff/The comments do not prove the most critical product closure:executor Whether to be the main process"
    "**Auto-activate**？`result.md` Is it possible?**Automatically Generate and commit**？evidence_gate Is it real or hypothetical?"
    "The negative control has no evidence that these steps work together.\n"
)
lines.append("## New rubric Cover every gap by article\n")
lines.append("| PR #105 Scene Gap | reviewer Check the anchor. | Which gate? |")
lines.append("| --- | --- | --- |")
for gap, anchor, gate in rows:
    lines.append(f"| {gap} | `{anchor}` | {gate} |")
lines.append("")
lines.append(
    "Conclusion: after strangulation rubric，reviewer The control list.**One by one.** PR #105 The skeletons are a gap in the scene."
    "Enough to put this kind of stuff in. PR Orientation `VERDICT: REWORK`The reason is ”the bone is only achieved, not complete link.”——No more. reviewer "
    "It just happened to be real.\n"
)
lines.append("## Real code review Full Task (Preliminary)reviewer._task_for(kind=\"code\")）\n")
lines.append("```text")
lines.append(code_task)
lines.append("```")
lines.append("## Real rfc review Full Task (Preliminary)reviewer._task_for(kind=\"rfc\")）\n")
lines.append("```text")
lines.append(rfc_task)
lines.append("```")

out = sys.argv[1]
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print(f"  [Render] Real review Task Text + PR #105 Script written tracked Product:{out}")
print(f"  [Textual assertion] {len(GAPS)} A gap is broken down. review Task Overwrite ✓(Blocks separated and double-checked)")
PY

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [Optional] Real smoke.OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  Real smoke step (needs real) GitHub Warehouse + gh Login + True claude backendIt’ll be real. PR/Comment, run. reviewer）：
    1) Yes. scratch The warehouse built a ”bonescence to be complete.” PR: Only one new executor/evidence_gate Bones module,
       Plug in the door control in the right position, and fill only the module level singles, but**No main process, no automatic output/commit artifactNo exceptions. fixture**，
       PR The text states that ”automated execution has been achieved/The door is connected.”
    2) One run, huh? reviewer（code The gate, really. backend）：`oa vigil --once`(SINGING IN RADIO) code (c) Evaluation.
       Expected (renumbered):code The award is that `VERDICT: REWORK`，ISSUES Clicked by article Missing Trigger Point/Not connected/artifact Not Automatic
       Outputs/No positive or negative action./Locally measured, for reasons of ”only bone skeletons, not full links”.
    3) Comparison (above): same PR It’s... code The gate is easily miscalculated. PASS(module exists) + Single green + Door control is in the right place.
  (This paragraph only prints guidelines, does not automatically execute and avoids being CI/Offline error is real. gh/claude。）
REAL
fi

echo
echo "✓ Spec-0048 End-to-end demonstration completed (default offline, repeatable, net-free, unmovable) LLM/gh;n/a UI I don’t need a browser to meet. e2e）。"
