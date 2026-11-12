#!/usr/bin/env bash
# Spec-0033 end-to-end test start-up script: openagents init start-up of a new remote post-remote ed origin.
#
# Hermetic - not true gh/ GitHub. Two paragraphs:
#   1) Offline certainty validation (ruff lint/format + pytest, round).
#   2) Cold Start Walking: Drived in temporary non-guit directory with create_repo dropped by stub
#      ensure_project(interactive=True)  Say it's local at the end   git config It's...
#      remote.origin.url corresponds to the new url (certifying _bootstream that a remote end has been written back to the local area).
#
# Usage:
#   bash scripts/e2e-spec-0033-init-remote-add.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check openagents/config.py tests/test_config.py
uv run --extra dev ruff format --check openagents/config.py tests/test_config.py
uv run --extra dev pytest tests/test_config.py -q

echo
echo "==> [2/2] Cold-started walk:stub create_repo Driver ensure_project(interactive=True)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL="https://github.com/acme/widget.git"
ACTUAL="$(cd "$TMP" && PYTHONPATH="$ROOT" URL="$URL" uv run --project "$ROOT" python - <<'PY'
import os
import subprocess
from unittest import mock

from openagents.config import ensure_project

url = os.environ["URL"]
answers = iter(["y", "y", "acme/widget", "y"])  # git init / New Far / Warehouse Name / Private
with (
    mock.patch("builtins.input", lambda prompt="": next(answers)),
    mock.patch("openagents.github.create_repo", lambda *, name, private: url),
):
    ctx = ensure_project(interactive=True)
assert ctx.remote == url, ctx.remote
written = subprocess.run(
    ["git", "config", "--get", "remote.origin.url"],
    capture_output=True, text=True, check=True,
).stdout.strip()
print(written)
PY
)"

echo "  Local remote.origin.url = $ACTUAL"
[ "$ACTUAL" = "$URL" ] \
  || { echo "✗ Local after cold startup remote.origin.url Not written or inconsistent"; exit 1; }
echo "  ✓ New Remote Back End for Cold Start git config remote.origin.url & With New url Unanimously."

echo
echo "✓ Spec-0033 End-to-end through:init New Remote Auto after Cold Start git remote add origin Closed rings are available."
