from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openagents.runtime import gates
from openagents.runtime.user_test import UserTestEvent, UserTestPlan, UserTestResult
from openagents.v02.model import DevelopmentResult, IssueInput, SpecNode
from openagents.v02.openagents_adapter import OpenAgentsAdapter, _delivery_dirty


def test_delivery_dirty_ignores_only_untracked_runtime_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.git.porcelain",
        lambda **kwargs: "\n".join(
            [
                "?? __pycache__/",
                "?? tests/__pycache__/",
                "?? .pytest_cache/",
                "?? package/module.pyc",
                "?? .coverage",
                " M tracked.py",
                "?? untracked.py",
            ]
        ),
    )

    assert _delivery_dirty(work_dir=tmp_path) == " M tracked.py\n?? untracked.py"


def test_delivery_dirty_never_ignores_tracked_cache_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.git.porcelain",
        lambda **kwargs: " M package/__pycache__/tracked.pyc",
    )

    assert _delivery_dirty(work_dir=tmp_path) == " M package/__pycache__/tracked.pyc"


def test_developer_head_is_stamped_from_git_not_model(monkeypatch, tmp_path):
    spec = tmp_path / "docs" / "objectives" / "issue-1.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("frozen", encoding="utf-8")
    node = SpecNode(
        issue=IssueInput(1, "title", "body"),
        branch="openagents/v02-issue-1",
        worktree=tmp_path,
        spec_path=spec,
        spec_digest="digest",
        summary="summary",
        files=("entry.py",),
        selected_intervention={},
        evidence_pack=(),
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.stages.assert_minimal_design_approved",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.forge.find_pr_by_branch",
        lambda **kwargs: SimpleNamespace(number=9),
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.gates.snapshot_head", lambda **kwargs: "BEFORE"
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.gates.assert_head_advanced",
        lambda **kwargs: "ACTUAL-HEAD",
    )
    monkeypatch.setattr("openagents.v02.openagents_adapter.git.porcelain", lambda **kwargs: "")
    delivered = []
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.Workspace.assert_delivered",
        lambda self, *, worktree, branch: delivered.append((Path(worktree), branch)),
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.engine.run_agent",
        lambda *args, **kwargs: {
            "status": "DELIVERED",
            "summary": "implemented",
            "changed_files": ["entry.py"],
            "evidence": ["tests pass"],
            "reason": "",
        },
    )

    result = OpenAgentsAdapter(backend=object(), work_dir=tmp_path).develop(node=node)

    assert result.head_sha == "ACTUAL-HEAD"
    assert delivered == [(tmp_path, "openagents/v02-issue-1")]


def test_developer_receives_target_meta_spec_as_context(monkeypatch, tmp_path):
    spec = tmp_path / "docs" / "objectives" / "issue-1.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("frozen", encoding="utf-8")
    (tmp_path / "META_SPEC.md").write_text(
        "# Harness Meta-Spec\n\n双方仓库均可修改。", encoding="utf-8"
    )
    node = SpecNode(
        issue=IssueInput(1, "title", "body"),
        branch="openagents/v02-issue-1",
        worktree=tmp_path,
        spec_path=spec,
        spec_digest="digest",
        summary="summary",
        files=("entry.py",),
        selected_intervention={},
        evidence_pack=(),
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.stages.assert_minimal_design_approved",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.forge.find_pr_by_branch",
        lambda **kwargs: SimpleNamespace(number=9),
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.gates.snapshot_head", lambda **kwargs: "BEFORE"
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.gates.assert_head_advanced",
        lambda **kwargs: "ACTUAL-HEAD",
    )
    monkeypatch.setattr("openagents.v02.openagents_adapter.git.porcelain", lambda **kwargs: "")
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.Workspace.assert_delivered",
        lambda self, *, worktree, branch: None,
    )
    received = {}

    def _run_agent(*args, **kwargs):
        received["context"] = kwargs["context"]
        return {
            "status": "DELIVERED",
            "summary": "implemented",
            "changed_files": ["entry.py"],
            "evidence": ["tests pass"],
            "reason": "",
        }

    monkeypatch.setattr("openagents.v02.openagents_adapter.engine.run_agent", _run_agent)

    result = OpenAgentsAdapter(backend=object(), work_dir=tmp_path).develop(node=node)

    assert result.status == "DELIVERED"
    assert "project Meta-Spec" in received["context"]
    assert "双方仓库均可修改" in received["context"]


def test_spec_writer_receives_target_meta_spec_as_context(monkeypatch, tmp_path):
    (tmp_path / "META_SPEC.md").write_text("# Harness Meta-Spec\n\n因果链优先。", encoding="utf-8")
    received = {}

    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.Workspace.prepare",
        lambda self, **kwargs: tmp_path,
    )

    def _minimal_spec(**kwargs):
        received["context"] = kwargs["context_text"]
        return {"status": "BLOCKED", "summary": "test", "blocker": "test", "head_sha": "HEAD"}

    monkeypatch.setattr("openagents.v02.openagents_adapter.stages.minimal_spec", _minimal_spec)

    result = OpenAgentsAdapter(backend=object(), work_dir=tmp_path).write_spec(
        issue=IssueInput(1, "title", "body")
    )

    assert result.status == "BLOCKED"
    assert "project Meta-Spec" in received["context"]
    assert "因果链优先" in received["context"]


def _acceptance_fixture(tmp_path: Path) -> tuple[SpecNode, DevelopmentResult]:
    spec = tmp_path / "docs" / "objectives" / "issue-1.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("frozen", encoding="utf-8")
    node = SpecNode(
        issue=IssueInput(1, "title", "body"),
        branch="openagents/v02-issue-1",
        worktree=tmp_path,
        spec_path=spec,
        spec_digest="digest",
        summary="summary",
    )
    return node, DevelopmentResult(status="DELIVERED", head_sha="HEAD", pr_number=9)


def test_acceptance_fails_closed_when_user_test_times_out(monkeypatch, tmp_path):
    node, development = _acceptance_fixture(tmp_path)
    monkeypatch.setattr("openagents.v02.openagents_adapter._delivery_dirty", lambda **kwargs: "")
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.gates.snapshot_head", lambda **kwargs: "HEAD"
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.forge.find_pr_by_branch",
        lambda **kwargs: SimpleNamespace(number=9),
    )
    timed_out = UserTestResult(status="timed_out", artifact_dir="/tmp/user-test", error="timeout")
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.run_user_test", lambda **kwargs: timed_out
    )
    called = []
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.stages.acceptance",
        lambda **kwargs: (
            called.append(kwargs) or {"verdict": "PASS", "reason": "bad", "evidence": []}
        ),
    )

    result = OpenAgentsAdapter(
        backend=object(),
        work_dir=tmp_path,
        user_test_plan=UserTestPlan(command=("harness",), events=(UserTestEvent("x"),)),
    ).accept(node=node, development=development)

    assert result.verdict == "FAIL"
    assert "timed_out" in result.reason
    assert result.evidence[0]["passed"] is False
    assert called == []


def test_acceptance_rejects_candidate_head_drift_before_user_test(monkeypatch, tmp_path):
    node, development = _acceptance_fixture(tmp_path)
    monkeypatch.setattr("openagents.v02.openagents_adapter._delivery_dirty", lambda **kwargs: "")
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.gates.snapshot_head", lambda **kwargs: "OTHER-HEAD"
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.run_user_test",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("user test must not run")),
    )

    adapter = OpenAgentsAdapter(
        backend=object(),
        work_dir=tmp_path,
        user_test_plan=UserTestPlan(command=("harness",), events=(UserTestEvent("x"),)),
    )
    with pytest.raises(gates.GateError, match="HEAD"):
        adapter.accept(node=node, development=development)


def test_acceptance_pass_is_bound_to_user_test_artifact(monkeypatch, tmp_path):
    node, development = _acceptance_fixture(tmp_path)
    monkeypatch.setattr("openagents.v02.openagents_adapter._delivery_dirty", lambda **kwargs: "")
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.gates.snapshot_head", lambda **kwargs: "HEAD"
    )
    artifact_dir = tmp_path / "user-test"
    artifact_dir.mkdir()
    (artifact_dir / "stdout.log").write_text("reply\n", encoding="utf-8")
    (artifact_dir / "status.json").write_text("{}\n", encoding="utf-8")
    completed = UserTestResult(
        status="completed",
        exit_code=0,
        artifact_dir=str(artifact_dir),
        status_path=str(artifact_dir / "status.json"),
    )
    monkeypatch.setattr(
        "openagents.v02.openagents_adapter.run_user_test", lambda **kwargs: completed
    )
    received = {}

    def _stage(**kwargs):
        received.update(kwargs)
        return {
            "verdict": "PASS",
            "reason": "observable behavior passed",
            "evidence": [
                {
                    "case_id": "interaction",
                    "source": "user_test",
                    "kind": "behavior",
                    "observed": "reply changed as requested",
                    "expected": "user-visible objective is satisfied",
                    "path": str(artifact_dir / "stdout.log"),
                    "passed": True,
                }
            ],
        }

    monkeypatch.setattr("openagents.v02.openagents_adapter.stages.acceptance", _stage)
    result = OpenAgentsAdapter(
        backend=object(),
        work_dir=tmp_path,
        user_test_plan=UserTestPlan(command=("harness",), events=(UserTestEvent("x"),)),
    ).accept(node=node, development=development)

    assert result.verdict == "PASS"
    assert result.evidence[0]["source"] == "user_test"
    assert received["require_user_test"] is True
    assert received["user_test_result"]["status"] == "completed"


def test_v02_requirement_persists_before_roles_and_survives_restart(monkeypatch, tmp_path):
    from openagents.runtime import context
    from openagents.v02.model import NodeResult

    seen = []

    def inspect(self, *, issue):
        seen.append(context.execution_required(issue_number=issue.number))
        return NodeResult(issue.number, "BLOCKED", "controlled no-model probe")

    monkeypatch.setattr(OpenAgentsAdapter, "_write_spec", inspect)
    issue = IssueInput(7, "public issue", "no evidence marker here")
    OpenAgentsAdapter(
        backend=object(), work_dir=tmp_path, execution_evidence_required=True
    ).write_spec(issue=issue)
    OpenAgentsAdapter(backend=object(), work_dir=tmp_path).write_spec(issue=issue)
    OpenAgentsAdapter(backend=object(), work_dir=tmp_path).write_spec(
        issue=IssueInput(8, "ordinary", "body")
    )
    assert seen == [True, True, False]
    assert context.execution_required(issue_number=7) is False
