#!/usr/bin/env bash
# Spec-0046: shared invocation budget and truthful timeout reasons; no live model or network.
set -euo pipefail
cd "$(dirname "$0")/.."

# Prefer the existing environment so offline verification does not sync dependencies.
if [[ -x .venv/bin/python ]]; then
  spec46_python=.venv/bin/python
  spec46_ruff=.venv/bin/ruff
else
  spec46_python=python3
  spec46_ruff=ruff
fi

spec46_files=(
  openagents/backends/base.py
  openagents/backends/claude_code.py
  openagents/recipes/vigil.py
  tests/test_backend_claude_code.py
  tests/test_recipe_vigil.py
  tests/test_recipe_vigil_act.py
)
"$spec46_ruff" check "${spec46_files[@]}"
"$spec46_ruff" format --check "${spec46_files[@]}"
"$spec46_python" -m pytest \
  tests/test_backend_claude_code.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_vigil_act.py \
  tests/test_recipe_vigil_queue.py \
  tests/test_recipe_vigil_discovery.py -q
