#!/usr/bin/env bash
# Spec-0090/T1: hermetic convergence regression and concurrent delivery controls.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
test_python=${TEST_PYTHON:-.venv/bin/python}
"$test_python" -m pytest -q \
  tests/test_recipe_vigil.py tests/test_recipe_vigil_act.py \
  tests/test_recipe_vigil_queue.py tests/test_runtime_gates.py
"$test_python" scripts/stress_delivery_recovery.py \
  --workers 1 4 8 16 --repeats 4 --baseline 16 --deadline 120 "$@"
