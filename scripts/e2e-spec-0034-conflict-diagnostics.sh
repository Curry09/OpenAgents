#!/usr/bin/env bash
# Spec-0034 end-to-end test start script: Conflict/stuff notification tape for hermetic closed loops for location-based diagnostics.
#
# The group has moved all "consolidated conflict" notifications from undiagnosed static cans to positionable diagnostics (conflict list + key hunk summary).
# Note: The original "Consolidated Fan Out of Diagnosis/ Repression Reproduction" exercise was removed with the fan after the zip-synchronous re-engineering (deleting push/ rebase module);
# The diagnostic collection and formatting (confectdiag) retained the "where" section of the Merge gate that still serves the comment.
#
# Two parts, full ** netless, unreal LLM, unreal gh, unreal git far **:
#   1) Offline certainty (default execution) - ruff lint/format + pytest package, override confectdiag collection/ formatting
#      (test_conflictdiag), messages merge gate blocker with a single test (test_messages_conflict_diag).
#   2) Offline Cyclops Exercise (default execution) - Drive Real with make run (feeding fixed git merge-tree output + guit show blue)
#      Confectdiag pipe: Conflict collection list of diagnostic tapes + where the card is from hunk abstract; diagnosis is empty and retrogressive
#      CONFLICT_COMMENT. The whole process does not touch the real git / gh / LLM.
#
# Usage:
#   bash scripts/e2e-spec-0034-conflict-diagnostics.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline closed loop exercise: diagnostic collection + Formatting (fake runTrue conflictdiag Pipeline)"
uv run --extra dev python - <<'PY'
# Spec-0034/T4: Hermetic Exercise - netless, LLM untouched, real untouched, and not even real git remote.
import subprocess

from openagents import conflictdiag

# Measured git 2.39 `git merge-tree --write-tree` conflict stdout: first line
MERGE_TREE_CONFLICT = (
    "024c0515807b89dc52f29f54d0025ae41eee4aca\n"
    "100644 83db48f84ec878fbfb30b46d16630e944e34f205 1\tdocs/specs/OVERVIEW.md\n"
    "100644 39aa102c5896143ea31aaf3404efe59b6b91f62e 2\tdocs/specs/OVERVIEW.md\n"
    "100644 f80d8ff774d980e0c4b0899c6f0e6a737b06938e 3\tdocs/specs/OVERVIEW.md\n"
    "\nAuto-merging docs/specs/OVERVIEW.md\n"
    "CONFLICT (content): Merge conflict in docs/specs/OVERVIEW.md\n"
)
MERGE_TREE_CLEAN = "024c0515807b89dc52f29f54d0025ae41eee4aca\n"
BLOB_WITH_CONFLICT = (
    "| 0031 | merge Unmount |\n"
    "<<<<<<< (ours)\n| 0032 | Closed comment |\n=======\n| 0034 | Conflict diagnosis |\n>>>>>>> origin/main\n"
)


def _cp(*, returncode, stdout):
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr="")


def fake_run_conflict(*, args):
    # Makeg-tree to conflict output, show to conflict-marked blob, the rest of the success - without touching the real git remote.
    if args[0] == "merge-tree":
        return _cp(returncode=1, stdout=MERGE_TREE_CONFLICT)
    if args[0] == "show":
        return _cp(returncode=0, stdout=BLOB_WITH_CONFLICT)
    return _cp(returncode=0, stdout="")


def fake_run_clean(*, args):
    if args[0] == "merge-tree":
        return _cp(returncode=0, stdout=MERGE_TREE_CLEAN)
    return _cp(returncode=0, stdout="")


# --- Steps 1：conflictdiag.collect + format_blocker Real pipe (injection) fake run）------------------- #
diag = conflictdiag.collect(base="main", head="feature", run=fake_run_conflict)
assert diag.files == ["docs/specs/OVERVIEW.md"], diag.files
assert "<<<<<<<" in diag.hunks["docs/specs/OVERVIEW.md"]
blocker = conflictdiag.format_blocker(diag=diag, step="Automatically merge target branches origin/main Time")
assert "List of conflict documents (in millions of United States dollars)1）" in blocker
assert "docs/specs/OVERVIEW.md" in blocker
assert "Chile hunk Summary" in blocker
print("  ✓ Steps 1：collect Compilation of conflict list + Chile hunk Summary,format_blocker Render the ”where” section.")

# --- Steps 2: Diagnosis empty (clean merger)→ format_blocker Back to pancreasing CONFLICT_COMMENT(Security downgrade)-------- #
empty = conflictdiag.collect(base="main", head="feature", run=fake_run_clean)
assert empty.is_empty()
assert conflictdiag.format_blocker(diag=empty, step="x") == conflictdiag.CONFLICT_COMMENT
print("  ✓ Steps 2: Diagnosis empty (clean merger)/(The collection failed)→ Back to pancreasing CONFLICT_COMMENTNever throw it up.")

print()
print("✓ Spec-0034 hermetic Through exercises: diagnostic collection→Where’s the card?→The air-diagnostic downgrade,")
print("  I’m not going to touch the net./None LLM/None gh/No real git Far away.")
PY

echo
echo "✓ Spec-0034 End-to-end script complete (delineal certainty) + The two-part closed-ring exercise is over."
