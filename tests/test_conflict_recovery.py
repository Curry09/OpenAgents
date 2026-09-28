"""Regression tests for the autonomous PR conflict-recovery loop."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openagents.recipes import vigil
from openagents.utils.workspace import WorkspaceError


def _facts() -> vigil._Facts:
    head = "a" * 40
    return vigil._Facts(
        subject="pr:12",
        pr_number=12,
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


class _Workspace:
    def __init__(self, *, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        self.calls: list[tuple] = []

    def ensure(self, *, issue_number: int, branch: str) -> Path:
        self.calls.append(("ensure", issue_number, branch))
        return self.work_dir / f"issue-{issue_number}"

    def sync_delivered(self, *, worktree: Path, branch: str) -> bool:
        self.calls.append(("sync", Path(worktree), branch))
        return True

    def prepare(self, *, issue_number: int, branch: str, base: str) -> Path:
        self.calls.append(("prepare", issue_number, branch, base))
        return self.work_dir / f"prepared-{issue_number}"


def test_rebase_retries_a_failed_resolver_and_reuses_actual_head_branch(monkeypatch, tmp_path):
    workspace = _Workspace(work_dir=tmp_path)
    monkeypatch.setattr(vigil.git, "Workspace", lambda *, work_dir: workspace)
    monkeypatch.setattr(vigil.github, "update_branch", lambda **_: False)
    monkeypatch.setattr(vigil.github, "pr_head_branch", lambda *, pr_number: "feature/pr-12")

    calls = 0

    def conflict(**kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["branch"] == "feature/pr-12"
        if calls < 3:
            return {"delivered": False, "reason": "rebase state needs recovery"}
        return {"delivered": True, "summary": "published"}

    monkeypatch.setattr(vigil.stages, "conflict", conflict)
    monkeypatch.setattr(vigil, "_log", lambda **_: None)

    summary = vigil._do_rebase(backend=object(), work_dir=tmp_path, base="main", facts=_facts())

    assert calls == 3
    assert "published" in summary
    assert all(call[2] == "feature/pr-12" for call in workspace.calls if call[0] == "ensure")


def test_rebase_failure_is_bounded_and_keeps_a_diagnostic(monkeypatch, tmp_path):
    workspace = _Workspace(work_dir=tmp_path)
    monkeypatch.setattr(vigil.git, "Workspace", lambda *, work_dir: workspace)
    monkeypatch.setattr(vigil.github, "update_branch", lambda **_: False)
    monkeypatch.setattr(vigil.github, "pr_head_branch", lambda *, pr_number: "feature/pr-12")
    monkeypatch.setattr(
        vigil.stages,
        "conflict",
        lambda **_: {"delivered": False, "reason": "semantic conflict remains"},
    )
    monkeypatch.setattr(vigil, "_log", lambda **_: None)

    with pytest.raises(WorkspaceError, match="冲突恢复暂未完成"):
        vigil._do_rebase(backend=object(), work_dir=tmp_path, base="main", facts=_facts())

    assert len([call for call in workspace.calls if call[0] == "prepare"]) == 3


def test_rebase_retries_worktree_preparation_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(vigil.github, "update_branch", lambda **_: False)
    monkeypatch.setattr(vigil.github, "pr_head_branch", lambda *, pr_number: "feature/pr-12")
    attempts = 0

    def prepare(**_):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise WorkspaceError("transient worktree failure")
        return tmp_path / "conflict"

    monkeypatch.setattr(vigil, "_conflict_worktree", prepare)
    monkeypatch.setattr(
        vigil.stages,
        "conflict",
        lambda **_: {"delivered": True, "summary": "published"},
    )
    monkeypatch.setattr(vigil, "_log", lambda **_: None)

    summary = vigil._do_rebase(backend=object(), work_dir=tmp_path, base="main", facts=_facts())

    assert attempts == 3
    assert "published" in summary


def test_interrupted_conflict_claim_is_delayed_and_retried_without_parking(monkeypatch, tmp_path):
    db_path = tmp_path / ".openagents" / "queue.db"
    vigil._init_db(db_path=db_path)
    conn = vigil._connect(db_path=db_path)
    before = datetime.now(UTC)
    vigil._enqueue(
        conn=conn,
        subject="pr:12",
        priority=2,
        now=before,
        action=vigil._ACT_REBASE,
    )
    conn.execute(
        "UPDATE work_queue SET status='claimed', attempts=?, worker='dead' WHERE subject='pr:12'",
        (vigil._MAX_ATTEMPTS + 1,),
    )
    row = dict(conn.execute("SELECT * FROM work_queue WHERE subject='pr:12'").fetchone())
    lock_path = tmp_path / "claim.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    monkeypatch.setattr(
        vigil,
        "_fail_automation",
        lambda **_: pytest.fail("conflict recovery must not be parked"),
    )
    monkeypatch.setattr(vigil, "_log", lambda **_: None)

    vigil._run_claimed(
        conn=conn,
        row=row,
        fd=fd,
        backend=object(),
        state=object(),
        work_dir=tmp_path,
        config=object(),
        agent_id="vigil-1",
        now_fn=lambda: before,
    )

    queued = conn.execute("SELECT * FROM work_queue WHERE subject='pr:12'").fetchone()
    assert queued["status"] == "queued"
    assert queued["attempts"] == 0
    assert datetime.fromisoformat(queued["available_at"]) > before
    assert vigil._claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=before) is None
    conn.close()


def test_same_conflict_episode_eventually_enters_machine_isolation(monkeypatch, tmp_path):
    db_path = tmp_path / ".openagents" / "queue.db"
    vigil._init_db(db_path=db_path)
    conn = vigil._connect(db_path=db_path)
    now = datetime.now(UTC)
    vigil._enqueue(
        conn=conn,
        subject="pr:12",
        priority=2,
        now=now,
        action=vigil._ACT_REBASE,
    )
    row = conn.execute("SELECT id FROM work_queue WHERE subject='pr:12'").fetchone()
    monkeypatch.setattr(vigil, "_failure_facts", lambda **_: _facts())
    failures: list[dict] = []
    monkeypatch.setattr(vigil, "_fail_automation", lambda **kwargs: failures.append(kwargs))
    monkeypatch.setattr(vigil, "_log", lambda **_: None)

    for index in range(vigil._CONFLICT_EPISODE_LIMIT):
        conn.execute(
            "UPDATE work_queue SET status='claimed', attempts=? WHERE id=?",
            (vigil._MAX_ATTEMPTS, row["id"]),
        )
        fd = os.open(tmp_path / f"claim-{index}", os.O_CREAT | os.O_RDWR, 0o600)
        vigil._requeue_or_park(
            conn=conn,
            task_id=row["id"],
            subject="pr:12",
            fd=fd,
            agent_id="vigil-1",
            reason=(
                f"{vigil._CONFLICT_RETRY_PREFIX} conflict_fp=deadbeefdeadbeef "
                "semantic conflict remains"
            ),
        )

    assert len(failures) == 1
    assert failures[0]["category"] == "conflict_episode_exhausted"
    assert conn.execute("SELECT 1 FROM work_queue WHERE id=?", (row["id"],)).fetchone() is None
    conn.close()


def test_each_internal_attempt_refreshes_conflict_facts(monkeypatch, tmp_path):
    old = _facts()
    fresh = replace(old, head_sha="b" * 40, mergeable_state="dirty")
    monkeypatch.setattr(vigil.github, "update_branch", lambda **_: False)
    monkeypatch.setattr(vigil.github, "pr_head_branch", lambda *, pr_number: "feature/pr-12")
    monkeypatch.setattr(vigil, "_conflict_worktree", lambda **_: tmp_path / "conflict")
    contexts: list[str] = []

    def conflict(**kwargs):
        contexts.append(kwargs["context_text"])
        return {"delivered": True, "summary": "published"}

    monkeypatch.setattr(vigil.stages, "conflict", conflict)
    monkeypatch.setattr(vigil, "_log", lambda **_: None)

    vigil._do_rebase(
        backend=object(),
        work_dir=tmp_path,
        base="main",
        facts=old,
        refresh_facts=lambda: fresh,
    )

    assert contexts and '"head_sha": "' + "b" * 40 in contexts[0]
