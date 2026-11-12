#!/usr/bin/env bash
# Spec-0028 end-to-end test start script: PR Automation of two improved hermetic closed loop exercises.
#
# Improve the three-part summary of the summary of the 9-part of the embedded group level in the text of the draft 1: spec / Reference-level.
# Improvement 2: Merage Real Conflicting Convention andent semantic conflict resolution, downgraded by indexheal  →  andent  →  manual.
#
# Two segments, full ** netless, no real LLM, no real gh**:
#   1) Offline certainty (default) - ruff lint/format + pytest package, overdigest extraction, conflict
#      Single measurements of the resolve_branch tri-branch, rebase/messages stratification downlink.
#   2) Offline Cyclops (default execution) - three parts of a real drop-out spec group of overview_digest_for_group,
#      Use conflict.resolve_branch 'clean merge/ agent to solve / residue
#      The conflict is back on three paths. No proof, no CI, can run, can repeat.
#
# Usage:
#   bash scripts/e2e-spec-0028-pr-digest-and-conflict.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline closed loop:digest Three. + resolve_branch Decline in tiered (%2)fake backend / fake run）"
uv run --extra dev python - <<'PY'
# Spec-0028/T4: Hermetic exercise - netless, LLM untouched, real untouched.
import tempfile
from pathlib import Path
from subprocess import CompletedProcess

from openagents.backends.base import AgentResult
from openagents.conflict import resolve_branch
from openagents.spec import model as spec_model
from openagents.spec.model import Group, Metadata, Overview, Task
from openagents.spec.signpost import overview_digest_for_group

# --- Improvements 1: Disassembly a real spec group, draw a three-part summary of the --------------------#
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    group = Group(
        number="0028",
        metadata=Metadata(
            title="PR Automation of two improvements", issue=79, slug="pr-digest-and-conflict-agent", summary="TL;DR"
        ),
        tasks=[Task(id="T1", title="digest", status="done", priority="P1")],
        overview=Overview(
            summary="It’s from the field. PR #76 Two independent observations.",
            motivation="Both of them. PR Automation chain road: design is not read in the body, conflict is manual.",
            reference_level="Offline. `scripts/e2e-spec-0028-pr-digest-and-conflict.sh`（ruff + pytest）。",
            drawbacks="This part should not go in. digest(twelfth only).",
        ),
    )
    path = spec_model.group_path(
        specs_root=root, number="0028", slug="pr-digest-and-conflict-agent"
    )
    spec_model.dump_group(group=group, path=path)

    digest = overview_digest_for_group(group_path=path)
    assert digest is not None, "digest No, it’s not. None"
    assert digest.startswith("## spec Overview (from docs/specs/0028-pr-digest-and-conflict-agent.md）")
    assert "### Summary" in digest and "It’s from the field. PR #76 Two independent observations." in digest
    assert "### Motivation" in digest and "### Reference-level explanation" in digest
    # Take only three paragraphs, excluding Drawbacks.
    assert "Drawbacks" not in digest and "You shouldn’t have come in. digest" not in digest
    # Spec is not readable  → None (zero returns).
    assert overview_digest_for_group(group_path=root / "missing.md") is None
    print("  ✓ Improvements 1：overview_digest Extract Summary/Motivation/Reference-level Three paragraphs. Missing. None")


# --- Improvements 2：fake backend / fake run Driver resolve_branch Decline 3 Paths ----- #
def cp(*, returncode=0, stdout=""):
    return CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr="")


class FakeGit:
    """Hypocrisy. git: distributed by order;conflicts Variable, supply fake backend We’ll clear the air after the conflict."""

    def __init__(self, *, merge_rc, conflicts):
        self.merge_rc = merge_rc
        self.conflicts = list(conflicts)
        self.calls = []

    def __call__(self, *, args, cwd, check):
        self.calls.append(args)
        if args[0] == "merge" and args[1] != "--abort":
            return cp(returncode=self.merge_rc)
        if args[:3] == ["diff", "--name-only", "--diff-filter=U"]:
            return cp(stdout="\n".join(str(c) for c in self.conflicts))
        return cp(returncode=0)


class FakeBackend:
    """Hypocrisy. coding Backend: Tones on_run Simulation agent Semantic Conflict LLM）。"""

    name = "fake"

    def __init__(self, *, on_run):
        self._on_run = on_run

    def run(self, *, work_dir, task, context):
        self._on_run(work_dir)
        return AgentResult(changed=True, summary="resolved")


with tempfile.TemporaryDirectory() as tmp:
    wt = Path(tmp)

    # Path A: Clean Merge (no entry) True.
    git_a = FakeGit(merge_rc=0, conflicts=[])
    assert resolve_branch(worktree=wt, base="main", backend=FakeBackend(on_run=lambda d: None), run=git_a) is True
    assert ["merge", "origin/main", "--no-edit"] in git_a.calls
    print("  ✓ Improvements 2 Path A: Clean Merge → resolved(No tunes) agent）")

    # Path B: Conflict → agent Clean it up. + Self-surveyed. → add/commit → True。
    git_b = FakeGit(merge_rc=1, conflicts=["a.py"])

    def resolve_clean(d):
        (d / "a.py").write_text("clean\n", encoding="utf-8")
        git_b.conflicts = []

    assert resolve_branch(worktree=wt, base="main", backend=FakeBackend(on_run=resolve_clean), run=git_b) is True
    assert ["add", "-A"] in git_b.calls and ["commit", "--no-edit"] in git_b.calls
    print("  ✓ Improvements 2 Path B：agent Semantic Resolution + Self-surveyed. → add/commit → resolved")

    # Path C: Conflict  →  agent left (self-successful)  → merge --abort  →  False (returning manual).
    git_c = FakeGit(merge_rc=1, conflicts=["a.py"])

    def leave_marker(d):
        (d / "a.py").write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>>\n", encoding="utf-8")
        git_c.conflicts = []

    assert resolve_branch(worktree=wt, base="main", backend=FakeBackend(on_run=leave_marker), run=git_c) is False
    assert ["merge", "--abort"] in git_c.calls and ["commit", "--no-edit"] not in git_c.calls
    print("  ✓ Improvements 2 Path C: Residual conflict markers / Self-measure failure → merge --abort → Backwards")

print()
print("✓ Spec-0028 hermetic Exercise through: Improvement 1 digest Extract + Improvements 2 resolve Decline in layers, and you’re not going to touch the net./None LLM/None gh。")
PY

echo
echo "✓ Spec-0028 End-to-end script complete (delineal certainty) + The two-part closed-ring exercise is over."
