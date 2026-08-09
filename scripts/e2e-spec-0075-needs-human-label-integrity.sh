#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

.venv/bin/pytest -q \
  tests/test_runtime_engine.py \
  tests/test_recipe_vigil.py::test_reconcile_centrally_parks_structured_needs_human \
  tests/test_recipe_vigil.py::test_reconcile_restores_deleted_labels_then_parks \
  tests/test_recipe_vigil.py::test_review_refresh_allows_only_framework_owned_stale_verdict_removal \
  tests/test_recipe_vigil_act.py::test_needs_human_contract_uses_structured_exit_and_forbids_forge_writes \
  tests/test_agents_merger.py \
  tests/test_gitea_driver.py::test_issue_add_label_resolves_id

.venv/bin/python -m openagents.spec.cli validate
.venv/bin/python -m openagents.spec.cli render
.venv/bin/python -m openagents.spec.cli graph --package-root openagents --check
