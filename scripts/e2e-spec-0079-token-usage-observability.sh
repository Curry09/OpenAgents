#!/usr/bin/env bash
# Spec-0079 offline acceptance: no model or network calls.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

uv run --extra dev ruff check \
  openagents/backends/base.py \
  openagents/backends/claude_code.py \
  openagents/runtime/engine.py \
  openagents/runtime/token_usage.py \
  openagents/cli.py \
  scripts/live_spec_0079_token_usage_observability.py \
  tests/test_base.py \
  tests/test_backend_claude_code.py \
  tests/test_cli.py \
  tests/test_recipe_vigil.py \
  tests/test_runtime_engine.py \
  tests/test_runtime_token_usage.py \
  tests/test_cli_timing.py
uv run --extra dev pytest -q \
  tests/test_base.py \
  tests/test_backend_claude_code.py \
  tests/test_cli.py \
  tests/test_recipe_vigil.py \
  tests/test_runtime_engine.py \
  tests/test_runtime_token_usage.py \
  tests/test_cli_timing.py
uv run spec validate
uv run spec render
uv run spec graph --check
