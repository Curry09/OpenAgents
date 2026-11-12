#!/usr/bin/env bash
# Spec-0074: Offline certainty e2e——ruff + Targeted pytest + grep anchor (no real touch) LLM/Network/The warehouse.
set -euo pipefail
cd "$(dirname "$0")/.."

ruff check .
ruff format --check .

pytest tests/test_forge.py tests/test_gitea_driver.py tests/test_agents_merger.py \
  tests/test_agent_config.py tests/test_recipe_stages.py -q

# grep anchor: spec ID/ lias-import re-line / memer no gh literally.
head -1 openagents/utils/forge.py | grep -q "Spec-0074/T1"
head -1 openagents/utils/gitea.py | grep -q "Spec-0074/T2"
for f in openagents/recipes/vigil.py openagents/recipes/stages.py openagents/recipes/backfill.py \
  openagents/runtime/gates.py openagents/runtime/context.py openagents/utils/identity.py \
  openagents/utils/release.py openagents/cli.py; do
  grep -q "from openagents.utils import forge as github" "$f"
done
if grep -q "gh pr merge" openagents/agents/merger.py; then
  echo "✗ merger The hint still contains gh Hard Encoding" >&2
  exit 1
fi

echo "✓ spec-0074 e2e All green."
