"""Spec-0060/T5: runtime.context + runtime.state single-measured.

Contact: Phase placeholder dict is complete, issue text/PR history utils.github injected (prick, net-free).
State: Read and write the independent namespace file runtime-state.json, which conflicts with the old state.json file level zero.
"""

from __future__ import annotations

from pathlib import Path

from openagents.runtime import context as context_module
from openagents.runtime.context import Context
from openagents.runtime.state import RUNTIME_STATE_FILENAME, RuntimeState
from openagents.utils.github import Comment, Issue


def _stub_github(monkeypatch, *, issue, comments):
    monkeypatch.setattr(context_module.github, "get_issue", lambda *, number: issue)
    monkeypatch.setattr(context_module.github, "list_comments", lambda *, pr_number: comments)


def _ctx(*, pr_number):
    return Context(
        work_dir=Path("/tmp/wt"),
        issue_number=145,
        branch="openagents/issue-145",
        pr_number=pr_number,
    )


def test_for_plan_keys(monkeypatch):
    _stub_github(
        monkeypatch, issue=Issue(number=145, title="Reconstruct", body="Text X"), comments=[]
    )
    payload = _ctx(pr_number=154).for_plan(issue_number=145)
    assert payload["work_dir"] == Path("/tmp/wt")
    assert payload["issue_number"] == 145
    assert payload["issue_body"] == "Text X"
    assert "Text X" in payload["context"]


def test_for_implement_and_iterate_feedback(monkeypatch):
    _stub_github(monkeypatch, issue=Issue(number=145, title="t", body="b"), comments=[])
    ctx = _ctx(pr_number=154)
    impl = ctx.for_implement(issue_number=145)
    assert impl["feedback"] == ""
    assert impl["pr_number"] == 154
    itr = ctx.for_iterate(issue_number=145, feedback="Completing Test")
    assert itr["feedback"] == "Completing Test"


def test_for_review_injects_pr_history(monkeypatch):
    comments = [Comment(id="1", author="curry", body="Change it here.", created_at="2026-07-09")]
    _stub_github(monkeypatch, issue=Issue(number=145, title="t", body="b"), comments=comments)
    payload = _ctx(pr_number=154).for_review(issue_number=145)
    assert payload["pr_number"] == 154
    assert "Change it here." in payload["context"]
    assert "@curry" in payload["context"]


def test_for_deliver_keys():
    payload = _ctx(pr_number=154).for_deliver(issue_number=145)
    assert payload["branch"] == "openagents/issue-145"
    assert payload["pr_number"] == 154


def test_workspace_property():
    assert _ctx(pr_number=None).workspace == Path("/tmp/wt")


def test_review_context_without_pr(monkeypatch):
    # No PR: Only the context of the issue, without list_comments.
    _stub_github(monkeypatch, issue=Issue(number=145, title="t", body="b"), comments=[])
    payload = _ctx(pr_number=None).for_review(issue_number=145)
    assert "PR #" not in payload["context"]


def test_runtime_state_roundtrip_independent_namespace(tmp_path):
    path = tmp_path / ".openagents" / RUNTIME_STATE_FILENAME
    state = RuntimeState(path=path)
    assert state.get_run(issue_number=145) is None
    state.set_run(issue_number=145, status="solving", branch="openagents/issue-145", pr_number=154)
    got = state.get_run(issue_number=145)
    assert got == {"status": "solving", "branch": "openagents/issue-145", "pr_number": 154}
    state.set_cursor(pr_number=154, comment_id="c-9")
    assert state.get_cursor(pr_number=154) == "c-9"
    # Independent Namespace: File name runtime-state.json, not old state.json.
    assert path.name == "runtime-state.json"
    assert path.exists()


def test_runtime_state_tolerates_corrupt_file(tmp_path):
    path = tmp_path / RUNTIME_STATE_FILENAME
    path.write_text("{not json", encoding="utf-8")
    state = RuntimeState(path=path)
    assert state.get_run(issue_number=1) is None  # Damage is considered empty, undiscarded.


# Spec-0093/T2: mutable body/config cannot erase a previously accepted dispatch requirement.
def test_execution_dispatch_survives_restart_and_is_scoped(tmp_path):
    path = tmp_path / RUNTIME_STATE_FILENAME
    state = RuntimeState(path=path)
    assert context_module.execution_required(issue_number=7) is False
    with context_module.execution_dispatch(state=state, required=True):
        assert context_module.execution_required(issue_number=7) is True
    state.set_run(issue_number=7, status="solving", branch="issue-7", pr_number=None)
    restored = RuntimeState(path=path)
    with context_module.execution_dispatch(state=restored, required=False):
        assert context_module.execution_required(issue_number=7) is True
        assert context_module.execution_required(issue_number=8) is False
    assert context_module.execution_required(issue_number=7) is False


def test_corrupt_execution_dispatch_cannot_downgrade_to_ordinary_issue(tmp_path):
    import pytest

    from openagents.observations.execution_contracts import ExecutionContractUnavailable

    path = tmp_path / RUNTIME_STATE_FILENAME
    path.write_text('{"execution_requirements":{"7":"false"}}')
    with context_module.execution_dispatch(state=RuntimeState(path=path), required=False):
        with pytest.raises(ExecutionContractUnavailable):
            context_module.execution_required(issue_number=7)


def test_vigil_freezes_requirement_before_enqueue(monkeypatch, tmp_path):
    from dataclasses import replace
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from openagents.recipes import vigil
    from openagents.utils import agent_config

    state = RuntimeState(path=tmp_path / RUNTIME_STATE_FILENAME)
    observed = SimpleNamespace(facts=object())
    verdict = SimpleNamespace(kind=vigil._ACTIONABLE, action="solve")
    monkeypatch.setattr(vigil, "_sense", lambda **kwargs: observed)
    monkeypatch.setattr(vigil, "_refresh_failure_projection", lambda **kwargs: observed)
    monkeypatch.setattr(vigil, "_classify", lambda **kwargs: verdict)
    monkeypatch.setattr(vigil, "_resume_verdict", lambda **kwargs: verdict)
    monkeypatch.setattr(vigil, "_fingerprint", lambda **kwargs: "fingerprint")
    monkeypatch.setattr(vigil, "_implementation_pending", lambda **kwargs: False)
    monkeypatch.setattr(vigil, "_has_attempt_stamp", lambda **kwargs: False)
    monkeypatch.setattr(vigil, "_record_timing", lambda **kwargs: None)
    monkeypatch.setattr(vigil, "_issue_number_of", lambda **kwargs: 7)

    def enqueue(**kwargs):
        assert RuntimeState(path=tmp_path / RUNTIME_STATE_FILENAME).execution_requirement(
            issue_number=7, required=False
        )
        return True

    monkeypatch.setattr(vigil, "_enqueue", enqueue)
    assert (
        vigil._consider(
            conn=None,
            state=state,
            subject="issue:7",
            config=replace(agent_config.default_config(), execution_evidence_required=True),
            work_dir=tmp_path,
            in_flight={},
            priority_fn=lambda **kwargs: 1,
            thresholds={},
            quiet_counts={},
            now=datetime.now(UTC),
            agent_id="probe",
        )
        == 1
    )


def test_required_evidence_fault_releases_slot_without_candidate_failure(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    from openagents.observations.execution_contracts import ExecutionContractUnavailable
    from openagents.recipes import vigil
    from openagents.utils import agent_config

    def unavailable(**kwargs):
        raise ExecutionContractUnavailable("required execution evidence missing")

    endings = []
    monkeypatch.setattr(vigil, "_reconcile", unavailable)
    monkeypatch.setattr(vigil, "_finish", lambda **kwargs: endings.append(kwargs))
    vigil._run_claimed(
        conn=None,
        row={"id": 1, "subject": "issue:7", "attempts": 1},
        fd=-1,
        backend=object(),
        state=RuntimeState(path=tmp_path / RUNTIME_STATE_FILENAME),
        work_dir=tmp_path,
        config=agent_config.default_config(),
        agent_id="probe",
        now_fn=lambda: datetime.now(UTC),
    )
    assert len(endings) == 1
    assert endings[0]["park"] is None
    assert endings[0]["reason"] == "execution_contract_unavailable"


def test_missing_required_marker_recovers_through_real_queue_and_reader(monkeypatch, tmp_path):
    """A transient missing package must neither park nor leave a suppressing attempt stamp."""
    import gzip
    import hashlib
    import json
    import subprocess
    from dataclasses import replace
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from openagents.agents import architect
    from openagents.backends.base import AgentResult
    from openagents.observations import evidence
    from openagents.recipes import vigil
    from openagents.runtime import engine
    from openagents.utils import agent_config

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    package = json.loads(
        (Path(__file__).parent / "fixtures/execution_evidence_contract.json").read_text()
    )["package"]
    data = gzip.compress(json.dumps(package, ensure_ascii=False).encode(), mtime=0)
    handle = {"asset_id": 1, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    material = {"body": "temporarily missing marker", "finished": False}
    monkeypatch.setattr(evidence.forge, "active_forge", lambda: "gitea")
    monkeypatch.setattr(
        evidence.forge, "get_issue", lambda **kwargs: SimpleNamespace(body=material["body"])
    )
    monkeypatch.setattr(
        evidence.forge, "download_observation_asset", lambda **kwargs: data, raising=False
    )
    facts = SimpleNamespace(pr_number=None)
    monkeypatch.setattr(vigil, "_sense", lambda **kwargs: SimpleNamespace(facts=facts))
    monkeypatch.setattr(vigil, "_refresh_failure_projection", lambda **kwargs: kwargs["observed"])
    monkeypatch.setattr(
        vigil,
        "_classify",
        lambda **kwargs: vigil._Verdict(
            kind=vigil._TERMINAL if material["finished"] else vigil._ACTIONABLE,
            action=vigil._ACT_SOLVE,
        ),
    )
    monkeypatch.setattr(vigil, "_resume_verdict", lambda **kwargs: kwargs["verdict"])
    monkeypatch.setattr(vigil, "_fingerprint", lambda **kwargs: "unchanged")
    monkeypatch.setattr(vigil, "_implementation_pending", lambda **kwargs: False)
    monkeypatch.setattr(vigil, "_issue_number_of", lambda **kwargs: 7)
    monkeypatch.setattr(vigil, "_record_timing", lambda **kwargs: None)
    monkeypatch.setattr(vigil, "_reconcile_progress", lambda **kwargs: ("unchanged",))
    monkeypatch.setattr(vigil, "_capture_label_targets", lambda **kwargs: ())
    monkeypatch.setattr(vigil, "_allowed_label_removals", lambda **kwargs: ())
    monkeypatch.setattr(vigil, "_restore_label_integrity", lambda **kwargs: None)
    stamps, failures, calls = [], [], []
    monkeypatch.setattr(vigil, "_has_attempt_stamp", lambda **kwargs: bool(stamps))
    monkeypatch.setattr(vigil, "_post_attempt_stamp", lambda **kwargs: stamps.append(kwargs))
    monkeypatch.setattr(vigil, "_fail_automation", lambda **kwargs: failures.append(kwargs))

    class Backend:
        name = "context-capture"

        def run(self, *, work_dir, task, context):
            assert package["execution_evidence"]["payload_sha256"] in context
            calls.append(context)
            output = json.dumps(
                {
                    "verdict": "PASS",
                    "objective_fidelity": "ok",
                    "intervention_fit": "ok",
                    "boundary_integrity": "ok",
                    "verification_strength": "ok",
                    "reason": "ok",
                    "findings": [],
                }
            )
            return AgentResult(changed=False, summary=output, raw_output=output)

    def act(**kwargs):
        engine.run_agent(
            architect,
            backend=kwargs["backend"],
            work_dir=tmp_path,
            issue_number=7,
            design_digest="test",
            context="public synthetic goal",
        )
        material["finished"] = True
        return "delivered"

    monkeypatch.setattr(vigil, "_act", act)
    db_path = tmp_path / "queue.db"
    vigil._init_db(db_path=db_path)
    conn = vigil._connect(db_path=db_path)
    now = datetime.now(UTC)
    state_path = tmp_path / RUNTIME_STATE_FILENAME
    try:
        for attempt in range(2):
            state = RuntimeState(path=state_path)  # real restart between attempts
            config = replace(
                agent_config.default_config(), execution_evidence_required=attempt == 0
            )
            if attempt:
                material["body"] = f"<!-- {evidence.MARKER} {json.dumps(handle)} -->"
            assert (
                vigil._consider(
                    conn=conn,
                    state=state,
                    subject="issue:7",
                    config=config,
                    work_dir=tmp_path,
                    in_flight={},
                    priority_fn=lambda **kwargs: 1,
                    thresholds={},
                    quiet_counts={},
                    now=now,
                    agent_id="probe",
                )
                == 1
            )
            row, fd = vigil._claim_next(conn=conn, work_dir=tmp_path, worker_id="probe", now=now)
            assert row["attempts"] == 1  # infrastructure wait does not spend model retries
            vigil._run_claimed(
                conn=conn,
                row=row,
                fd=fd,
                backend=Backend(),
                state=state,
                work_dir=tmp_path,
                config=config,
                agent_id="probe",
                now_fn=lambda: now,
            )
            assert not conn.execute("SELECT * FROM work_queue").fetchall()
            assert not stamps and not failures
            assert state.execution_requirement(issue_number=7, required=False)
            assert len(calls) == attempt
        assert material["finished"]
    finally:
        conn.close()
