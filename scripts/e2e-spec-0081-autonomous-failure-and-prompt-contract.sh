#!/usr/bin/env bash
# Spec-0081 offline acceptance: no model or network calls.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

legacy_pattern='needs-human|NeedsHumanRequest|OWNER_HUMAN|--hold'
if rg -n "$legacy_pattern" \
  README.md openagents apps/desktop/src openagents/data/openagents.yml.template \
  --glob '*.py' --glob '*.ts' --glob '*.tsx' --glob '*.css' --glob '*.md' --glob '*.template'; then
  echo "Spec-0081 active-source retirement scan failed" >&2
  exit 1
fi

help_text="$(OPENAGENTS_NO_UPDATE=1 .venv/bin/openagents vigil --help)"
if grep -Eq "$legacy_pattern" <<<"$help_text"; then
  echo "Spec-0081 CLI retirement scan failed" >&2
  exit 1
fi

.venv/bin/ruff check \
  openagents/runtime/engine.py \
  openagents/runtime/context.py \
  openagents/runtime/legacy.py \
  openagents/runtime/state.py \
  openagents/backends/claude_code.py \
  openagents/recipes/stages.py \
  openagents/recipes/vigil.py \
  openagents/utils/agent_config.py \
  openagents/utils/fleet.py \
  openagents/utils/release.py \
  openagents/desktop/daemon.py \
  scripts/migrate-needs-human-state.py \
  tests/test_prompt_contract.py \
  tests/test_migrate_needs_human_state.py

.venv/bin/pytest -q \
  tests/test_prompt_contract.py \
  tests/test_runtime_engine.py \
  tests/test_runtime_context.py \
  tests/test_backend_claude_code.py \
  tests/test_agent_config.py \
  tests/test_cli_new_stack.py \
  tests/test_migrate_needs_human_state.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_vigil_act.py \
  tests/test_recipe_vigil_queue.py \
  tests/test_release.py \
  tests/test_runtime_state_converge.py

.venv/bin/python -m openagents.spec.cli validate
.venv/bin/python -m openagents.spec.cli render
.venv/bin/python -m openagents.spec.cli graph --check
