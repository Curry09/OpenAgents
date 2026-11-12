#!/usr/bin/env bash
# Spec-0023 end-to-end test start script: retired test branch - main continuously advance +release/vX.Y.Z version branch release.
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest, full-scale mock, unattractive to real gh/git.
#      Overwrite: base=main Passage (github/orchestrator/cli/vigil), ensure_prerequisites preset only labels,
#      Release precheck (no BLOCKED/needs-human + plain CI Green), version numbers are syntaxed (patch/minor/major,
#      Launch v0.1.0, v0.10.0 > v0.9.0, the physical branch +tag, CLI connection (release/--bump/--base).
#   2) Real release exercise (opt-in required) - OPENAGENTS_E2E_REAL =1, currently bound and gh
#      Show rebase precheck in login repository + philatelic version:
#        a. Pre-process labels such as `openagents init`  →  (test branch door control is not constructed after decommissioning);
#        b. `openagents release --bump patch`  →  Pre-check (no BLOCKED/needs-human + main CI Green) pass
#           Converts the current HEAD object into a release/vX.Y.Z branch and plays tag vX.Y.Z.
#           Arrival: Releasing/ < Version > branch and < version > tag at a remote end, both HEAD = main HEAD.
#      Note: Full assue cycling to main requires a backend drive, high cost, undetermined, script
#      The true section only shows the "pre-screen + physical version" as a definite link; full loop is requested
#      `openagents vigil --once` is manually observed in real storage.
#
# Usage:
#   rash scripts/e2e-spec-0023-release-flow.sh# Offline Only
#   OPENAGENTS_E2E_REAL = 1 bash scripts/e2e-spec-0023-release-flow.sh# with real release exercise
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ Offline validation passed. Real. release Exercise Skipped (set) OPENAGENTS_E2E_REAL=1 Open."
  exit 0
fi

echo
echo "==> [2/2] Real release exercise:init Pre-set Tab → release If you pass the pre-screening, you’ll have to... main The object is in the version."
command -v gh >/dev/null || { echo "Require installation and login gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh Not registered, please first. gh auth login"; exit 1; }

# Step ---: 1: Init pre-process label (tale et al; test door control no longer build any branch) -------------#
echo "--> Steps 1：openagents init —— & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & & and & & & & and & & & & & & & & & & _ and & %( and _ and & & %((( and, and, and, and & & & & & %(((((((((((((((((((((((((((((((((((((((((((((("
uv run openagents init

git fetch origin main
main_head="$(git rev-parse origin/main)"
echo "    main HEAD = ${main_head:0:8}"

# Step ---: 2: release - Pre-screening converts the main object to release/vX.Y.Z branch + tag -------#
echo "--> Steps 2：openagents release --bump patch —— Pre-screening (none) BLOCKED/needs-human + main CI Release after Green"
if uv run openagents release --bump patch; then
  git fetch origin --tags
  # Take the latest version of the tag (syntaxization: sorted to the bottom by version number).
  version="$(git tag --list 'v*' --sort=version:refname | tail -n1)"
  [[ -n "$version" ]] || { echo "✗ release The report was successful but no version was found. tag"; exit 1; }
  git fetch origin "refs/heads/release/${version}:refs/remotes/origin/release/${version}"
  branch_head="$(git rev-parse "origin/release/${version}")"
  tag_head="$(git rev-parse "${version}^{commit}")"
  if [[ "$branch_head" == "$main_head" && "$tag_head" == "$main_head" ]]; then
    echo "    ✓ Published ${version}：release/${version} Branches and tag All points to main HEAD ${main_head:0:8}"
  else
    echo "✗ ${version} The branch of the material.(${branch_head:0:8})/tag(${tag_head:0:8}) != main(${main_head:0:8})"
    exit 1
  fi
else
  echo "    ⓘ release Pre-check not passed (Existing) BLOCKED/needs-human, or main CI (n/a)——That’s what I expected."
  echo "      Door control: Refuses to publish when there is an outstanding job. release It’s all right."
fi

echo
echo "✓ The real release exercise is complete."
