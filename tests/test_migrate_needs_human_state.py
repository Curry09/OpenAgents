"""Spec-0081 migration is dry-run by default, explicit, idempotent, and retry-safe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openagents.runtime import legacy


@pytest.fixture(scope="module")
def migration():
    path = Path(__file__).parents[1] / "scripts" / "migrate-needs-human-state.py"
    spec = importlib.util.spec_from_file_location("spec0081_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(repo: Path) -> Path:
    directory = repo / ".openagents"
    directory.mkdir()
    path = directory / "runtime-state.json"
    path.write_text(
        json.dumps(
            {
                "runs": {
                    "7": {"status": "blocked", "branch": "b", "pr_number": 9},
                    "8": {"status": "done", "branch": "c", "pr_number": 10},
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_default_dry_run_writes_nothing(migration, tmp_path, capsys):
    path = _seed(tmp_path)
    before = path.read_bytes()

    assert migration.main(["--repo", str(tmp_path), "--no-forge"]) == 0

    assert path.read_bytes() == before
    assert "dry-run" in capsys.readouterr().out


def test_runtime_apply_is_idempotent(migration, tmp_path):
    path = _seed(tmp_path)

    assert migration.apply_runtime(runtime_path=path) == [7]
    assert migration.apply_runtime(runtime_path=path) == []
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["runs"]["7"]["status"] == "failed"
    assert data["runs"]["8"]["status"] == "done"


def test_manual_owner_is_reported_but_not_rewritten(migration, tmp_path):
    directory = tmp_path / ".openagents"
    directory.mkdir()
    config = directory / "openagents.yml"
    config.write_text(
        "stages:\n  triage: human\nrepos:\n  - path: .\n    stages:\n      ci: human\n",
        encoding="utf-8",
    )
    before = config.read_bytes()

    plan = migration.scan_local(repo=tmp_path)

    assert plan["manual_owners"] == ["repos/0/stages/ci", "stages/triage"]
    assert config.read_bytes() == before


def test_forge_apply_adds_diagnostic_before_removing_old_label(migration, monkeypatch):
    comments: list[SimpleNamespace] = [SimpleNamespace(body="old needs-human reason")]
    calls: list[str] = []
    issue = SimpleNamespace(number=3)

    monkeypatch.setattr(migration.forge, "ensure_label", lambda **kwargs: calls.append("ensure"))
    monkeypatch.setattr(migration.forge, "list_issue_comments", lambda *, number: comments)
    monkeypatch.setattr(migration.forge, "issue_add_label", lambda **kwargs: calls.append("add"))

    def _comment(*, number, body):
        calls.append("comment")
        comments.append(SimpleNamespace(body=body))

    monkeypatch.setattr(migration.forge, "issue_comment", _comment)
    monkeypatch.setattr(
        migration.forge, "issue_remove_label", lambda **kwargs: calls.append("remove")
    )

    assert migration.apply_forge(plan={"issues": [issue], "prs": []}) == ["issue:3"]
    assert calls == ["ensure", "add", "comment", "remove"]
    calls.clear()
    migration.apply_forge(plan={"issues": [issue], "prs": []})
    assert calls == ["ensure", "add", "remove"]
    assert "old needs-human reason" in comments[-1].body


def test_startup_detector_fails_closed_without_forge_calls():
    state = SimpleNamespace(
        list_runs=lambda: [{"issue_number": 4, "status": legacy.LEGACY_RUN_STATUS}]
    )
    with pytest.raises(legacy.LegacyStateError, match="Spec-0081"):
        legacy.assert_migrated(state=state, inspect_forge=False)
