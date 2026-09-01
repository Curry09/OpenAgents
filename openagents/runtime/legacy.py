"""Fail-closed detection for pre-Spec-0081 terminal state."""

from __future__ import annotations

from typing import Any

from openagents.utils import forge

LEGACY_LABEL = "needs" + "-human"
LEGACY_RUN_STATUS = "block" + "ed"


class LegacyStateError(RuntimeError):
    """Raised before agent dispatch when explicit migration is required."""


def findings(*, state: Any, inspect_forge: bool = True) -> list[str]:
    """Return stable, human-readable legacy-state findings without modifying anything."""
    found: list[str] = []
    list_runs = getattr(state, "list_runs", None)
    if callable(list_runs):
        for run in list_runs():
            if run.get("status") == LEGACY_RUN_STATUS:
                found.append(f"runtime issue #{run.get('issue_number', '?')}: legacy terminal status")
    if inspect_forge:
        for issue in forge.list_issues(labels=[LEGACY_LABEL]):
            found.append(f"forge issue #{issue.number}: legacy terminal label")
        for pr in forge.list_open_prs():
            if forge.has_label(pr_number=pr.number, name=LEGACY_LABEL):
                found.append(f"forge PR #{pr.number}: legacy terminal label")
    return found


def assert_migrated(*, state: Any, inspect_forge: bool = True) -> None:
    """Refuse startup until the explicit Spec-0081 migration has completed."""
    found = findings(state=state, inspect_forge=inspect_forge)
    if not found:
        return
    detail = "; ".join(found)
    command = f"scripts/migrate-{LEGACY_LABEL}-state.py"
    raise LegacyStateError(
        f"检测到 Spec-0081 之前的终态：{detail}。"
        f"请先运行 {command}（先 dry-run，再 --apply）。"
    )


__all__ = ["LEGACY_LABEL", "LEGACY_RUN_STATUS", "LegacyStateError", "assert_migrated", "findings"]
