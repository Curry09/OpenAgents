#!/usr/bin/env bash
set -euo pipefail
# Spec-0045/T5: result test for document calibration cleanup——lint/Format/Test All Green + Dead caliber grep Zero.
uv run --extra dev ruff check openagents tests
uv run --extra dev ruff format --check openagents tests
uv run --extra dev pytest -q

echo "== Dead caliber grep Zero Validation =="
# The deleted symbol should never be in code/test as "Current Realization " again.
! grep -rn "rebase_open_prs\|rebase\.CONFLICT_COMMENT" openagents tests
# indexheal.py has been deleted and the module name should not be present again in the openomics source.
! grep -rn "indexheal" openagents
# The sync-prs command has been deleted and should no longer be considered a living construction path in the test note.
! grep -rn "sync-prs" tests
echo "ALL GREEN: No residual lethal caliber"
