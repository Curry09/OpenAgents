#!/usr/bin/env bash
# Spec-0044 End-to-end test boot script: "End-to-end running real app and intercept" validates skill (issue #113).
#
# Two paragraphs:
#   1) Offline certainty segment (default, hermetic, no network/ no real caude) - ruff lint/format + pytest,
#      And grep asserts three locations: (a) SKILL.md for transplantation with core discipline anchor (anti-inertity/nationalization /
#      Integrity obstruction / completion of sentence) to prove original transplant rather than empty shell; (b) reviewer.py contains "claimed proven but not proven
#       →  REWORK's check entry; (c) orchestrator.py achieves the propt with three class words + skill.
#   2) Browser's own demonstration session (results test, concept 8; instruction book, execution by ant by Browner MCP) - paired
#      The reference-app.html, which contains the reference page, uses the closed loop of the "navigation console/network assertion" to read:
#      Screenshot into docs/evidence/spec-0044/, with RED reverse contrasts. When there is no Browner MCP, you will be honest about blocking and not offline.
#
# Usage:
#   bash scripts/e2e-spec-0044-e2e-screenshot-skill.sh
set -euo pipefail

cd "$(dirname "$0")/.."

SKILL_DIR="docs/skills/end-to-end-ui-screenshots"
SKILL_MD="$SKILL_DIR/SKILL.md"
REF_APP="$SKILL_DIR/examples/reference-app.html"

echo "==> [1/2] Offline certainty segment (inlint + format + Units/Integrated Test + grep Omnibus Claim)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "  -- grep The assertion. (a)：SKILL.md Original port anchor (non-empty shell)"
test -f "$SKILL_MD" || { echo "✗ Missing $SKILL_MD"; exit 1; }
for anchor in "Inertity" "rationalization" "The honesty of the report." "Complete sentence" \
              "case 2 vs case 3" "Take the visual path."; do
  grep -qF "$anchor" "$SKILL_MD" || { echo "✗ SKILL.md Missing anchor:$anchor"; exit 1; }
done
# Runbook Example + Templates are ready (sic port + empty template).
test -f "$SKILL_DIR/references/north-coder.md" || { echo "✗ Missing north-coder.md"; exit 1; }
grep -qF "Project exclusive command" "$SKILL_DIR/references/_runbook-template.md" \
  || { echo "✗ _runbook-template.md Missing Project Exclusive Command partition"; exit 1; }
grep -qF "Common methodology" "$SKILL_DIR/references/_runbook-template.md" \
  || { echo "✗ _runbook-template.md Missing ”Universal Method” partition"; exit 1; }
echo "  ✓ SKILL.md / north-coder.md / _runbook-template.md The anchor is down."

echo
echo "  -- grep The assertion. (b)：reviewer.py It’s ”proclaimed to have been verified but no evidence.” → REWORK」Checkpoint"
grep -qF "He claims to have been certified but no evidence. → REWORK" openagents/reviewer.py \
  || { echo "✗ reviewer.py No evidence available=REWORK Checkpoint"; exit 1; }
echo "  ✓ reviewer rubric No evidence.=REWORK Checkpoint"

echo
echo "  -- grep The assertion. (c)：orchestrator.py implementation prompt With three classification judgements + skill Point the way."
grep -qF "Three categories." openagents/orchestrator.py \
  || { echo "✗ orchestrator.py Three categories of judgement missing"; exit 1; }
grep -qF "$SKILL_DIR/" openagents/orchestrator.py \
  || { echo "✗ orchestrator.py Missing skill Original to indicate the way"; exit 1; }
echo "  ✓ orchestrator Pier/implementation prompt With three classification judgements + skill Point the way."

echo
echo "  ✓ Green offline (ruff + pytest + All grep anchor hit)"

echo
echo "==> [2/2] Browser self-presentation session (results test; required) agent Use playwright / chrome-devtools MCP (implemented)"
test -f "$REF_APP" || { echo "✗ Missing reference page $REF_APP"; exit 1; }
REF_URL="file://$(pwd)/$REF_APP"
cat <<EOF
  References (pages)file:// Open it, don’t touch any production ports./Data:
    $REF_URL

  By agent Use browser MCP Let’s go. skill The prescribed closed loop (this script does not drive the browser, only notes are given):
    1. navigate  → Open $REF_URL
    2. snapshot  → Take Apply configuration button + #status Element handle
    3. interact  → clickApply configuration button
    4. wait_for  → Wait. #status ”Entry in force” case
    5. screenshot→ Can not open message docs/evidence/spec-0044/（tracked (in United States dollars)
    6. console·network The assertion. → list_console_messages None error；list_network_requests No request failed
    7. RED Counter Contrast → I’m just gonna... reference-app.html Lee. status.textContent="Configuration applied" I’m not a real person.
                     Run again:wait_for Timeout should be done. / Screenshot shows old state (empty) #status）(i) Proof that evidence is not empty;
                     After the scaffolding revertNo, I’m not. PR。

  If this environment is not objective browser MCP / None shown: Press skill The honesty of the discipline is clear.
    The block item ”No browser automation, browser not implemented from the demonstration section” does not have to leave the section to claim to have run.
EOF

echo
echo "✓ Spec-0044 Offline segment passes; browser has been exported from the presentation (to be taken into account as a result of the above steps)."
