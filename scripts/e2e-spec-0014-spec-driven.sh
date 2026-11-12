#!/usr/bin/env bash
# Spec-0014 End-to-end test start script: string up spec in sandbox full-link links -
# New (constructed)  →  old-task (co-task)  →  validate  →  render(four) →  amend (history +1 / Overview)
# Rewrite) validate/render, etc. Full-scale hermetic (in a temporary directory, without moving the warehouse docs/specs).
#
# issue #53: original step 1 migrated from docs/rfcs to ZSpec; docs/rfcs was replaced by ZXXQ00
# `spec new` + `spec add-task` is created directly (replaces migration) to perform a real spec author process.
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest set.
#   2) spec link exercise (default also performed, purely local, no gh/net).
#
# Usage:
#   bash scripts/e2e-spec-0014-spec-driven.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

echo
echo "==> [2/2] spec Link Exercise (Link Exercise)new → add-task → validate → render → amend → (Charlie)"

sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT
specs="$sandbox/specs"

echo "--> Steps 1：spec new Group + spec add-task Add two sub-tasks (in the case of the${specs}）"
uv run spec new mvp-issue-to-pr-loop --issue 1 --title "MVP Auto Closure" \
  --summary "Pull from the warehouse. issuePie. agent Solve, raise PR The smallest self-contained ring." --specs-root "$specs"
uv run spec add-task 0001 --id T1 --title "Bones." --priority P0 \
  --files openagents/cli.py --specs-root "$specs"
uv run spec add-task 0001 --id T2 --title "GitHub Integration" --priority P1 \
  --files openagents/github.py --depends-on T1 --specs-root "$specs"

echo "--> Steps 2：spec validate All Green (none) error）"
uv run spec validate --specs-root "$specs"

echo "--> Steps 3：spec render Generate OVERVIEW.md And it’s all four."
uv run spec render --specs-root "$specs"
for heading in "## TL;DR" "## Task board" "## Cross-Spec relationships" "## File ownership overlaps" "## Spec details"; do
  grep -qF "$heading" "$specs/OVERVIEW.md" || { echo "Missing blocks:$heading"; exit 1; }
done

echo "--> Steps 4：amend One. Task(Advocacy) history +1、tasks Upgrade,OVERVIEW & Rewrite"
[[ -f "$specs/0001-mvp-issue-to-pr-loop/history/T1.yaml" ]] && { echo "New products should not be created. history"; exit 1; }
uv run spec amend 0001 T1 --reason "e2e Exercise: Dismantling the Molecular Task" --specs-root "$specs"
[[ -f "$specs/0001-mvp-issue-to-pr-loop/history/T1.yaml" ]] || { echo "amend Not generated history"; exit 1; }
grep -q "version: 2" "$specs/0001-mvp-issue-to-pr-loop/tasks/T1.yaml" || { echo "tasks Not up to v2"; exit 1; }

echo "--> Steps 5: Again render Acclaimed like a t-shirt. diff）+ validate It’s still green."
cp "$specs/OVERVIEW.md" "$sandbox/overview-before.md"
uv run spec render --specs-root "$specs"
diff -q "$sandbox/overview-before.md" "$specs/OVERVIEW.md" >/dev/null || { echo "render Non-sync"; exit 1; }
uv run spec validate --specs-root "$specs"

echo
echo "✓ Spec-0014 End to end links all through."
