#!/usr/bin/env bash
# Spec-0088: hermetic gate/state/forge-projection integration regressions; no live model or forge.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m pytest -q \
  tests/test_spec_model.py \
  tests/test_runtime_gates.py \
  tests/test_runtime_state.py \
  tests/test_recipe_stages.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_vigil_act.py
