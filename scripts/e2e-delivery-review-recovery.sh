#!/usr/bin/env bash
# Spec-0089/T1: offline recovery and exact-candidate delivery regression entrypoint.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
RECOVERY_PYTHON="${RECOVERY_PYTHON:-.venv/bin/python}"
"$RECOVERY_PYTHON" -m pytest -q \
  tests/test_delivery_recovery_stress.py \
  tests/test_delivery_recovery_git.py \
  tests/test_workspace.py \
  tests/test_recipe_stages.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_vigil_act.py \
  tests/test_recipe_vigil_timing.py \
  tests/test_runtime_gates.py \
  tests/test_github.py \
  tests/test_gitea_driver.py \
  tests/test_forge.py
