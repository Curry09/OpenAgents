#!/usr/bin/env bash
# Spec-0076: fully offline architecture-decision gate regression loop.
set -euo pipefail

python -m pytest -q \
  tests/test_spec_model.py \
  tests/test_spec_validate.py \
  tests/test_agents_architect.py \
  tests/test_agent_config.py \
  tests/test_recipe_stages.py \
  tests/test_recipe_vigil_act.py \
  tests/test_runtime_gates.py \
  tests/test_runtime_state.py \
  tests/test_runtime_evidence.py
python -m ruff check \
  openagents/agents/architect.py \
  openagents/runtime/evidence.py \
  openagents/runtime/gates.py \
  openagents/runtime/state.py
python -c 'from openagents.spec.cli import main; raise SystemExit(main(argv=["validate"]))'
python -c 'from openagents.spec.cli import main; raise SystemExit(main(argv=["graph", "--check"]))'
