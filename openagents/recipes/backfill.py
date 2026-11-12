# Spec-0064/T4
"""Backfill a Spec from existing code and open a draft pull request."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from openagents.recipes import stages

# Spec-0074/T1: arias-import switch - Platform operations are configured by github/gitea driver to call zero changes.
from openagents.utils import forge as github
from openagents.utils import git

# Spec-0064/T4: branch prefix for the inverse of brookfield - Enter code path (no issue) and address with path slug.
_BACKFILL_BRANCH_PREFIX = "openagents/backfill-"

# Spec-0064/T4: branch baseline default locking main (retire from old rfc_lifecycle.DEFAULT_BASE/ Spec-0023 test).
DEFAULT_BASE = "main"


class BackfillError(Exception):
    """#Spec-0064/T4: Backfill counter-draft is not valid (draffert self-claimed undelivered) and is not available when PR is not available (responsible to the old RfcLifecycleError)."""


def prepare_worktree(*, work_dir: Path, slug: str, branch: str, base: str) -> Path:
    """Default New Quarantine worktree——The long term utils.git.Workspace(may) monkeypatch I’m sorry. git）。Old-fashioned prepare_worktree。"""
    return git.Workspace(work_dir=Path(work_dir)).prepare(
        issue_number=slug, branch=branch, base=base
    )


def backfill_rfc(
    *,
    path: str,
    backend: Any,
    work_dir: Path,
    base: str = DEFAULT_BASE,
) -> dict:
    """Inverse by Stock Code spec → Reuse stages.rfc（backfill mode）Delivery → Open draft PR。Old-fashioned rfc_lifecycle.backfill_rfc。

    Here. path slug Location-building worktree → Pie. `stages.rfc`（mode=backfill, require_delivered=True）——Not yet.
      You can’t start a new one
    Reverts the current round event (including pr/summary) after completion.
    """
    slug = _slug_for(path=path)
    branch = f"{_BACKFILL_BRANCH_PREFIX}{slug}"
    worktree = prepare_worktree(work_dir=Path(work_dir), slug=slug, branch=branch, base=base)

    verdict = stages.rfc(
        backend=backend,
        worktree=worktree,
        mode=stages.MODE_BACKFILL,
        target=f"Code path `{path}`",
        branch=branch,
        detail=path,
        context_text=path,
        require_delivered=True,
    )
    if not verdict["delivered"]:
        raise BackfillError(
            f"The backfill drafter reported no delivery. Check spec validate; no PR was opened: `{path}`"
        )

    pr = github.create_pr(
        branch=branch,
        base=base,
        title=f"docs: backfill spec for {path}",
        body=(
            f"🤖 Draft Spec derived from `{path}` for review.\n\n"
            "Verify the four required sections against the code and complete any sections marked as needing human input before promoting the draft. This PR does not merge automatically."
        ),
        draft=True,
    )
    _log(message=f"▶ Backfilled `{path}` and opened draft PR #{pr.number}")
    return {"pr_number": pr.number, "reason": "backfilled", "summary": verdict["summary"]}


def _slug_for(*, path: str) -> str:
    """Generates a branch slug (non-alphate numbers) for a branch security. Enter old rfc_lifecycle._slug_for."""
    raw = "".join(ch if ch.isalnum() else "-" for ch in str(path).strip("/"))
    slug = "-".join(seg for seg in raw.split("-") if seg)
    return slug or "root"


def _log(*, message: str) -> None:
    """Backfill progress to stderr (co-link with recipes.vigil)."""
    print(message, file=sys.stderr, flush=True)
