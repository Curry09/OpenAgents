#!/usr/bin/env bash
# Spec-0043/T4 End-to-end test start-up script: whether the self-resorting course before the issue enters the RFC is pacified - hit first
# Need-human alignment does not directly generate spec.
#
# This group inserts a light self-check before vigil finds a part-size start_rfc drafts a spec
# Interpret whether there is an inherent conflict "that will directly affect the direction of the law" (issue #106 accident: title = ssha cache,
# If you draw up a text by title, you will not write it.
# Needs-human+Pend a signed comment with a list of points of conflict and candidate for revision, and wait for alignment; Neds-human as a persistent freezing signal
# The same person will be sentenced to one sentence and no review of the shock.
#
# Two segments, full** netless, untouched LLM, untouched gh, unreal git remote** (except stage 2, to be visible):
#   1) Offline certainty (default execution) - ruff lint/format + pytest complete, covering T1 (issue_comment export),
#      T2 (issuecheck interpretation + alignment comment rendering + fail-open), T3 (precheck connection + _dispatch_kind anti-shock),
#      T4 Integration (test_issue_precheck_integration: #106 Conflict Identification + Freeze / Anti-Smock / Release / Unfreeze).
#   2) Offline Results Exercise (Default) - Real ** Alignment Comment with Real issuecheck.build_alignment_comment Output
#      Text** Rendered into a static HTML browser (Playwright/chrome-devtools MCP, driven by agent on the outside of script)
#      Navigation + snapshot + transcribation asserts two directions of the lawn / candidacy/ needs-human recommended visible, console/network none
#      Error reporting; no browser MCP script downgraded to a texting assertion for this HTML (grep two directions plus candidate section)
#      Do not skip the validation of results (idemical 8: results visualize).
#   3) True smoke (optional, OPENAGENTS_E2E_REAL = 1) - A reminder of how to build a real "title claim X, X" in a scratch warehouse
#      The text is a clutter. Y」It's... issue Run round with a contract label vigil --once Checked. needs-human + One.
#      Alignment comment + no draft PR; then check a self-conforming issue for normal drafting.
#
# Usage:
#   bash scripts/e2e-spec-0043-issue-conflict-precheck.sh
#   OPENAGENTS_E2E_REAL = 1 bash scripts/e2e-spec-0043-issue-conflict-precheck.sh # Add a real smoker
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline result exercise: render true alignment comments → Browser/The text affirms two directions of the law. + Candidates + needs-human"

OUT_HTML="$(mktemp -d)/alignment-comment.html"
uv run python - "$OUT_HTML" <<'PY'
# Spec-0043/T4: Wrapped into the minimum static HTML (test side package) with the true issuecheck output #106 rectangular review body of the scene.
# The comment body is the product output (return value of build_alignment_comment).
import html
import sys

from openagents import issuecheck
from openagents.issuecheck import ConflictVerdict

verdict = ConflictVerdict(
    has_conflict=True,
    conflicts=(
        "Title by commit sha Cache evaluation findings; body propositions hold-merge The last one. PASS It’s... PR Freezing needs-human。",
        "The semantics are different.——A reservation PR Reuse Cache in Active Round of Inquiry, One Cache PR Move out of active round of inquiries and others.",
    ),
    candidate_fixes=("Press commit sha Cache evaluation findings", "hold-merge Freeze PR"),
)
body = issuecheck.build_alignment_comment(verdict=verdict)

# Self-censorship of results (default evidence): Two directions of the law reform + candidate section + needs-human recommendations all, without PR failure cases.
assert "Press commit sha Cache evaluation findings" in body and "hold-merge Freeze PR" in body, "Direction of the default law"
assert "Candidates" in body, "Candidature Paragraph"
assert "needs-human" in body and "Alignment" in body, "Missing needs-human Alignment Guidance"
assert "It’s stuck." not in body and "🤖" not in body, "Misinform PR Class failure"

out = sys.argv[1]
page = (
    "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
    "<title>Spec-0043 Alignment of comments</title></head><body>"
    f"<article id='alignment-comment'><pre>{html.escape(body)}</pre></article>"
    "</body></html>"
)
with open(out, "w", encoding="utf-8") as f:
    f.write(page)

print("  [Render] True Alignment Review Body is rendered static HTML：", out)
print("  [Textual assertion] Two directions for the reform of the law + Candidates + needs-human All the lines are in place, nothing. PR Failed Files ✓")
PY

echo
echo "  [Browser Result] Use the browser, please. MCP（Playwright / chrome-devtools）Navigator and assertion (in the case of theagent Driven outside script:"
echo "    navigate  → file://$OUT_HTML"
echo "    snapshot/Screenshot → The assertion that the page appears simultaneously commit sha Cache assessment findings andhold-merge Freeze PR』、"
echo "                    ”Approval” is a trade-off, and a ”supplement” is a ”supplement.”needs-human / We’ll get in there first. RFC』Recommendations"
echo "    console/network → Claim no error, no request for failure (none local static page)"
echo "  No Browser MCP Time: The offline version assertion above is certified as a downgrade result (not skipping)."

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [Optional] Real smoke.OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  Real smoke step (needs real) GitHub Warehouse + gh Login, it’ll be real. issue/Comment:
    1) Yes. scratch The warehouse built a title proposition. XThe text is one-sided. Y」It’s... issue- Yeah. openagents Found the label.
       Example: Title ”Pressed by sha Cache evaluation findings/ The text should read hold-merge Freeze PR」。
    2) Round one. vigil：`oa vigil --once`
       Expected: issue Hit. needs-human Label, one alignment comment (shows two directions for the amendment) + The blog is a blog of the blog :
             and**Not available**Open draft PR（precheck Building worktree/Stop before drafting.
    3) One more round:`oa vigil --once`
       Expected: no additional comments, no drafting——needs-human - Yes, sir. → _dispatch_kind Skip, interpret, and not run again (anti-shock).
    4) Create another title/The text is consistent. issueRun! vigil --once → Normal drafting, open draft PR(Zero returns)
  (This paragraph only prints guidelines, does not automatically execute and avoids being CI/Offline error is real. gh。）
REAL
fi

echo
echo "✓ Spec-0043/T4 End-to-end demonstration completed (default offline, repeatable, net-free, unmovable) LLM/gh）。"
