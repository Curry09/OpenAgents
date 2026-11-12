# Spec-0071/T1: spec.ownership - A single Writer file ownership index + ultra-authority guard (design period declaration & & & & & QR)

"""Resolve the single-writer owner of each Spec-declared file and flag unowned writes.

This module does not consult Git or the forge. Runtime gates enforce the result.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Group

# Default specs root directory (symmetrically with spec CLI); the generator path is spelled accordingly.
_DEFAULT_SPECS_ROOT = Path("docs/specs")


@dataclass(frozen=True)
class OwnerIndex:
    """Spec-0071/T1: A single Writer Index for a spec group - a path  →  unique limit ID for own Task.

    Each key of `by_path` is a file path (repository relative) that Task has declared in frontmatter `files`, and the value is its
    Only owner (`"0071/T1"`-defined ID). The same group is not overlapping with `spec validate`, so there is only one path
    `build_index` in case of repeated statements** (certainty, no raise, overlap itself and valaidate newspaper error)
    """

    by_path: dict[str, str]

    def owner_of(self, *, path: str) -> str | None:
        """Returns `path` owner Task restricted ID; no one (not any Task declaration) returns None."""
        return self.by_path.get(path)


def build_index(*, group: Group) -> OwnerIndex:
    """Build the single-writer ownership index for one spec group.

    Spec-0071/T1: Current version of Task throughout the calendar group, map each `files` item to its owner ’s limited ID (`build`) first
    Declarors win, guarantees certainty. A file in the same group has been declared by more than one Task as `spec validate` error, index
    Do not repeat this check-up, only take the first owner for query.

    Args:
        Group: A loaded spec group (`spec.model.Group`).

    Returns:
        OwnerIndex: path  →  owner limits the unvariable index of ID.
    """
    by_path: dict[str, str] = {}
    for task in group.tasks:
        owner = model.qualified_id(group=group.number, task_id=task.id)
        for path in task.files:
            # First speaker wins: repeat declaration (error of Validate) does not rewrite recorded owner, and maintains certainty.
            by_path.setdefault(path, owner)
    return OwnerIndex(by_path=by_path)


def generated_artifacts(*, group: Group, specs_root: Path = _DEFAULT_SPECS_ROOT) -> set[str]:
    """Return the set of generated/spec artifacts a group is always allowed to write.

    Spec-0071/T1: When resolving issue #71, a changeset will inevitably touch three categories, in addition to the `files` declared by Task
    ** Generating** - The group’s spec markdown (`NNNN-slug.md`) and `spec render`/ `spec graph` replayed
    `OVERVIEW.md` / `ARCHITECTURE.md`. These are not written in `tasks[].files` (under contract), but are not overstepped and are therefore always released.

    Args:
        Group: Target spec group.
        specs_root: root directories (default docs/specs) for the relative path of the warehouse where the product is used to spell out the product.

    Returns:
        The collection of three warehouses relative paths: this group spec md + OVERVIEW.md + ARCHITECTURE.md.
    """
    spec_md = model.group_path(specs_root=specs_root, number=group.number, slug=group.metadata.slug)
    return {
        str(spec_md),
        str(specs_root / "OVERVIEW.md"),
        str(specs_root / "ARCHITECTURE.md"),
    }


def unowned_writes(
    *,
    group: Group,
    changed_paths: Iterable[str],
    specs_root: Path = _DEFAULT_SPECS_ROOT,
) -> list[str]:
    """Return the changed paths that no Task in the group owns and that aren't generated artifacts.

    Spec-0071/T1: issue #71 ”Excessive Write” test - Pushing a ”single Writer” from the design-period statement to the running-time to the execution of the decision.
    Allowed File Set = All path  → s in this group of single Writer indexes (spec md / overVIEW/
    ARCHITECTURE. Changes that fall outside this cluster are unauthorised, sorted and re-reweighted and returned (empty list = all compliance).

    Args:
        Group: Target spec group (providing `files` declarations and a collection of generators).
        changed_paths: The file path that actually changes (repository relative, usually obtained by harness from `git diff --name-only`).
        specs_root: root directory (default docs/specs), passed via `generated_artifacts`.

    Returns:
        Sorts a list of unauthorised paths; empty lists indicate that there is no excess.
    """
    index = build_index(group=group)
    allowed = set(index.by_path) | generated_artifacts(group=group, specs_root=specs_root)
    return sorted({path for path in changed_paths if path not in allowed})
