#!/usr/bin/env bash
# Spec-0079 opt-in acceptance through the existing Claude Code API configuration.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if ! command -v claude >/dev/null 2>&1; then
  echo "Claude Code CLI is not available on PATH" >&2
  exit 2
fi

python_bin="${OPENAGENTS_PYTHON:-$repo_root/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  echo "OpenAgents Python is not executable: $python_bin" >&2
  exit 2
fi

PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" \
  scripts/live_spec_0079_token_usage_observability.py
