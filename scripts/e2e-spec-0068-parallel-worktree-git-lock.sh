#!/usr/bin/env bash
# Spec-0068 end-to-end test start script: parallel night watche worktree prepare share.git lock competition is eliminated.
#
# The evidence discipline is based on the "pure internal automation test" ("pure internal automation test"), which is a "no produd-facing front end of the system.
# Offline with hermetic and re-entry (without real LLM/ GitHub/ network, only with local temporary guit warehouse):
#   1) T1 Single Detect (tests/test_workspace.py): share the whole part of prepare / ensure.git changes are holding
#      _GIT_MUTATION_LOCK; assert_delivered (pure read) does not lock; lock is the modular threading.Lock.
#   2) T2 Conduit (tests/test_workspace_concurrency.py): Start N( → 4) thread to the same temporary guit warehouse and retweet
#      Prepare (different issue_number/branch), claims to be all worktree, zero WorkspaceError,
#      gtstderr does not include 'cannot lock ref'/ 'cannot lock working tree' and maximum co-length of the change segment = 1.
#      Contrast (documentation, no long run): remove the lock and turn the test to flaky/fail - the competition that this lock is about to be removed.
#
# Usage:
#   bash scripts/e2e-spec-0068-parallel-worktree-git-lock.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Orientation Authentication Spec-0068 T1+T2（hermetic Offline and back, only temporary local. git (Kilo)"
uv run --extra dev pytest -q \
  tests/test_workspace.py \
  tests/test_workspace_concurrency.py

echo
echo "==> [2/2] Full lint + format(Acknowledging no behavior change)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "✓ Spec-0068 Offline authentication passes:K worker Created worktree nil git Lock the competition,prepare/ensure Change a line line, a pure read path, without locking."
