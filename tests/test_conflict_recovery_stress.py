"""Concurrent conflict-recovery stress checks.

These tests stay entirely at the orchestration seam: no forge, git repository, or model is
needed.  They exercise the same `_do_rebase` path used by Vigil and verify that one unresolved
PR becomes an isolated bounded failure while independent PRs continue to resolve.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openagents.recipes import vigil
from openagents.utils.workspace import WorkspaceError


def _facts(number: int) -> vigil._Facts:
    head = f"{number:040x}"
    return vigil._Facts(
        subject=f"pr:{number}",
        pr_number=number,
        head_sha=head,
        merged=False,
        closed=False,
        labels=frozenset(),
        deps_done=True,
        mergeable_state="dirty",
        ci="success",
        e2e_head_sha=head,
        review_state="APPROVED",
        review_commit_id=head[:7],
        latest_comment_is_ours=True,
    )


def test_parallel_conflicts_are_isolated_and_bounded(tmp_path: Path, monkeypatch) -> None:
    """512 concurrent PRs: blocked resolvers fail locally; successes are unaffected."""
    calls: list[int] = []

    class FakeWorkspace:
        def __init__(self, *, work_dir: Path) -> None:
            self.work_dir = Path(work_dir)

        def ensure(self, *, issue_number: int, branch: str) -> Path:
            return self.work_dir / f"ensure-{issue_number}"

        def sync_delivered(self, *, worktree: Path, branch: str) -> bool:
            return True

        def prepare(self, *, issue_number: int, branch: str, base: str) -> Path:
            return self.work_dir / f"prepared-{issue_number}"

    monkeypatch.setattr(vigil.git, "Workspace", FakeWorkspace)
    monkeypatch.setattr(vigil.github, "update_branch", lambda **kwargs: False)
    monkeypatch.setattr(
        vigil.github,
        "pr_head_branch",
        lambda *, pr_number: f"openagents/pr-{pr_number}",
    )
    monkeypatch.setattr(vigil, "_log", lambda **kwargs: None)

    def conflict(**kwargs):
        number = int(kwargs["pr_number"])
        calls.append(number)
        if number % 4 == 0:
            return {"delivered": False, "reason": "duplicate spec resource"}
        return {"delivered": True, "summary": "published"}

    monkeypatch.setattr(vigil.stages, "conflict", conflict)

    def resolve(facts: vigil._Facts) -> tuple[int, str]:
        try:
            summary = vigil._do_rebase(
                backend=object(), work_dir=tmp_path, base="main", facts=facts
            )
        except WorkspaceError:
            return facts.pr_number or 0, "failed"
        return facts.pr_number or 0, summary

    facts = [_facts(1000 + i) for i in range(512)]
    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(resolve, facts))

    failed = {number for number, status in results if status == "failed"}
    succeeded = {number for number, status in results if status != "failed"}
    assert failed == {number for number in range(1000, 1512) if number % 4 == 0}
    assert succeeded == {number for number in range(1000, 1512) if number % 4 != 0}
    # Successful resolvers finish on the first attempt; the 128 intentionally blocked
    # resolvers consume the bounded three-attempt budget before returning failure.
    assert len(calls) == 512 + 128 * 2
    fingerprints = {
        vigil._conflict_fingerprint(
            facts=item, base="main", branch=f"openagents/pr-{item.pr_number}"
        )
        for item in facts
    }
    assert len(fingerprints) == 512
