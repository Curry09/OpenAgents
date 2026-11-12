#!/usr/bin/env bash
# Spec-0035 end-to-end test start script: nudised git network calls flat-open + detected a slow check progress log.
#
# Pure internal reliability change, no UI, so e2e is a pillar for hermetic offline script - full subprocess.run Throw TimeoutExpired,
# Confirm three types of fail-open branch + two lines of discovery log set, unt/ network:
#   1) To reproven the needle timeout  →  conservatively return True ("possibly on the way")
#      git.remote_branch_exists / Workspace.remote_branch_exists。
#   2) Fetch timeout  →  Drops the WorldspaceError (prepare/ensure/assert_delivered) and is in per-issue isolation.
#   3) Push timeout poaching the RunteError (release, with action) CLI layer cleans a line of tips.
#   ) Found a two-line progress log before / _admit to LLM) settderr.
#   5) Normal network path behaviour remains the same bytes: returns value / exit code unchanged; _git both timeout=_GIT_NET_TIMEOUT_SECONDS.
#
# Usage:
#   bash scripts/e2e-spec-0035-git-net-timeout.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Orientation Authentication Spec-0035 Four. Task(claps) subprocess.run Throw! TimeoutExpired，hermetic Offline)"
uv run --extra dev pytest -q \
  tests/test_utils_git.py \
  tests/test_workspace.py \
  tests/test_release.py \
  tests/test_recipe_vigil_discovery.py

echo
echo "==> [2/2] Full lint + format + Units/Integrated testing (verified zero regression)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "✓ Spec-0035 Offline authentication through: Network git timeout fail-open Toothy, progress logdown. stderr, the default path remains unchanged."
