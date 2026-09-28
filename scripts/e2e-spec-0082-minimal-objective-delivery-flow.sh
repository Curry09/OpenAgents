#!/usr/bin/env bash
# Spec-0082/T2: replay the minimal-flow role sequence and terminal outcomes offline.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

uv run pytest -s -q \
  tests/test_agent_config.py \
  tests/test_agents_prompts.py \
  tests/test_recipe_stages.py \
  tests/test_recipe_vigil_act.py \
  -k 'minimal or generate_only or standard or packaged_template or module_exposes or prompt_placeholders or merge_mechanical'

echo 'Spec-0082 PASS: minimal keeps acceptance; generate-only is spec_writer -> executor -> mechanical merge.'
