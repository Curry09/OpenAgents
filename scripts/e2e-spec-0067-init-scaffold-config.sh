#!/usr/bin/env bash
# Spec-0067 End-to-end test start script: oa init automatically creates default. openagents/openagents.yml.
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest (agent_config/cli all mock, not touch the gh).
#   2) smoke init (default execution, pure offline, netless) - real run in a temporary guit warehouse for `openagents init`
#      scaffold Drop-out exit: first generation → The Quilix does not cover → --force Reset the template, the whole story.
#
# Usage:
#   bash scripts/e2e-spec-0067-init-scaffold-config.sh
set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$(pwd)"

echo "==> [1/2] Offline certainty verification (%2)lint + format + agent_config/cli (Modular Test)"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/test_agent_config.py tests/test_cli.py

echo
echo "==> [2/2] scaffold Smoke: temporary git Run in the warehouse. init → The assertion is generated/idempotent/--force"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
git init -q
git config user.email e2e@openagents.local
git config user.name e2e
git remote add origin https://github.com/openagents/e2e-smoke.git

cfg=".openagents/openagents.yml"

# ---1 First time: Generates default configuration and can be deciphered by loader ---
# Directly calls scaffold exit (the drop-off of the `openagents init` equal, bypassing gh pre-check, keeping pure offline).
run_init() { uv run --project "$repo_root" python - "$@" <<'PY'
import sys
from pathlib import Path
from openagents.utils.agent_config import scaffold_default_config, load_agent_config

force = "--force" in sys.argv[1:]
path = Path(".openagents/openagents.yml")
wrote = scaffold_default_config(path=path, force=force)
# The generator must be capable of being misdecommended by an existing loader (round-trip).
load_agent_config(path=path)
print("wrote" if wrote else "skipped")
PY
}

out="$(run_init)"
[[ "$out" == "wrote" ]] || { echo "✗ First init The configuration should be generated, in practice:$out"; exit 1; }
[[ -f "$cfg" ]] || { echo "✗ Not generated $cfg"; exit 1; }
grep -q "OpenAgents Declaration Configuration" "$cfg" || { echo "✗ Generating without comment header"; exit 1; }
echo "✓ ①First Generated $cfg And it’s a good thing to solve."

# --- 2 Q: Run after line change without overwhelming user changes ---
printf 'stages:\n  review: human\n' > "$cfg"
out="$(run_init)"
[[ "$out" == "skipped" ]] || { echo "✗ When there is a presence, skip, actually:$out"; exit 1; }
grep -q "review: human" "$cfg" || { echo "✗ The Zen Run covered the user’s changes."; exit 1; }
echo "✓ ② →  etc.: Skip, Save user changes if they exist"

# ---3 --force: Reset package template ---
out="$(run_init --force)"
[[ "$out" == "wrote" ]] || { echo "✗ --force It should be rewritten to read:$out"; exit 1; }
grep -q "OpenAgents Declaration Configuration" "$cfg" || { echo "✗ --force Template not reset"; exit 1; }
# Note that the template contains a line of examples of comments `#   review: human` - only the "unnoted" user change residue is denied.
grep -Eq '^\s*review: human' "$cfg" && { echo "✗ --force Uncleared user changes"; exit 1; }
echo "✓ ③--force: Reset the package default template"

echo
echo "✓ Spec-0067 End-to-end authentication is all passed."
