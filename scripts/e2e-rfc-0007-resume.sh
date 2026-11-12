#!/usr/bin/env bash
# RFC-0007 End-to-end test start script: Vigil Restore - Activate Solving as Resume Entry.
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest, full-scale mock, unattractive to real gh/claude.
#   2) Real Crash Recovery Exercise (which needs to be visible opt-in) - OPENAGENTS_E2E_REAL = 1 is currently bound and
#      gh Login warehouse** artificially constructed a start_rfc drawing-up of a breakdown **:
#        - Build a problemu with door-control labels;
#        - Writes a status = solving / pr_number = 0 for orphans running directly to. openagents/state.json;
#        - Recapture of the issue of worktree (a semi-finished draft) after the collapse of `git worktree add`.
#      Then run `openagents vigil --once`, claiming that the Night's Watch found it to be identified as "for recovery" and reused the residue.
#      Worktree moves from drafting to reruning, eventually starting a draft PR, state to rfc-review -- no manual deletion of state.
#
# Usage:
#   rash scripts/e2e-rfc-0007-resume.sh# Offline Only
#   OPENAGENTS_E2E_REAL = 1 bash scripts/e2e-rfc-0007-resume.sh # with real crash recovery exercise (Pr will be real)
#
# Optional environment variable (real exercise session):
#   VIGIL_LABEL door control tag, default optagents
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ Offline validation passed. Real crash resume exercise has been skipped (set) OPENAGENTS_E2E_REAL=1 Open."
  exit 0
fi

echo
echo "==> [2/2] Real crash recovery exercise: construction solving/pr=0 The leftover. → vigil --once Autorecover → draft PR"
command -v gh >/dev/null || { echo "Require installation and login gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh Not registered, please first. gh auth login"; exit 1; }
command -v claude >/dev/null || { echo "Available Claude Code CLI（claude）"; exit 1; }
command -v python3 >/dev/null || { echo "Yes. python3 For writing state.json"; exit 1; }

label="${VIGIL_LABEL:-openagents}"
base="main"
gh label create "$label" --description "openagents vigil The Night’s Watch will take it." >/dev/null 2>&1 || true

# Step ---: Build a belt label issue (target to be restored) --------------------------------#
title="[e2e] RFC-0007 Crash recovery $(date -u +%Y%m%dT%H%M%SZ)"
echo "--> Steps 1: Create labels issue：$title（label=$label）"
uv run openagents issue "$title" \
  --body "By e2e-rfc-0007 Script creation: Please in README Add a line at the end 'resume e2e ok'。" \
  --label "$label"
issue="$(gh issue list --label "$label" --state open --search "$title" --json number --jq '.[0].number')"
[[ -n "${issue:-}" && "$issue" != "null" ]] || { echo "Could not locate the created issue"; exit 1; }
echo "    issue = #$issue"

branch="openagents/issue-$issue"
worktree=".openagents/worktrees/issue-$issue"

# Step ---: Simulate "drafting crash" - Residual workktree + solving/pr = 0 run -----#
echo "--> Steps 2: Recapturing the collapse of the mess (residual) worktree + state.json - Yes. solving/pr=0 Orphans run）"
git fetch origin "$base"
# Recapturing the start_rfc-built harf-drafted workspace (half-drafed) that was built before the crash, but the branch never push, PR never opened.
git worktree remove --force "$worktree" 2>/dev/null || true
git branch -D "$branch" 2>/dev/null || true
git worktree add -b "$branch" "$worktree" "origin/$base"

# Writes a solving/pr = 0-orphan run directly into state.json (simulate begin_run crashes after landing).
python3 - "$issue" "$branch" <<'PY'
import json
import sys
from pathlib import Path

issue_number = int(sys.argv[1])
branch = sys.argv[2]
path = Path(".openagents/state.json")
data = {"runs": [], "cursors": {}}
if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
data.setdefault("runs", [])
data.setdefault("cursors", {})
data["runs"] = [r for r in data["runs"] if r.get("issue_number") != issue_number]
data["runs"].append(
    {
        "issue_number": issue_number,
        "branch": branch,
        "pr_number": 0,
        "pr_url": "",
        "status": "solving",
        "summary": "",
    }
)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"_Other Organiser run：issue #{issue_number} status=solving pr_number=0")
PY

# --- Steps 3: Run a round of Night's Watch, recovery. ------------------------------------- #
echo "--> Steps 3：openagents vigil --once —— The discovery section should include issue Recognized as to be restored resume Keep running."
uv run openagents vigil --once --label "$label" --base "$base"

# Step 4 of ---: Verify the Restore Results (draft PR + state refc-review) -----------------#
echo "--> Steps 4: Verify automatic restoration result"
pr="$(gh pr list --head "$branch" --state open --json number --jq '.[0].number')"
[[ -n "${pr:-}" && "$pr" != "null" ]] || { echo "✗ Recovery failed: not issue #$issue Open PR"; exit 1; }
echo "    ✓ Opened draft PR = #$pr"

status="$(python3 - "$issue" <<'PY'
import json
import sys
from pathlib import Path

issue_number = int(sys.argv[1])
data = json.loads(Path(".openagents/state.json").read_text(encoding="utf-8"))
rec = next((r for r in data["runs"] if r.get("issue_number") == issue_number), None)
print(rec["status"] if rec else "MISSING")
PY
)"
[[ "$status" == "rfc-review" ]] || { echo "✗ Restore failed:state Status as '$status'Expectations rfc-review"; exit 1; }
echo "    ✓ state From solving Turn to rfc-review(Lands) PR #$pr）"

echo
echo "✓ Real crash recovery exercise completed:issue #$issue Orphaned solving run The Night’s Watch automatically recovered. → draft PR #$pr。"
echo "  No manual deletions for the whole trip. state.json——That’s exactly what I’m talking about. RFC-0007 Objective."
echo "  Note: This script does not automatically close PR / Delete issue / Clear. worktree, please be in GitHub With local cleaning."
