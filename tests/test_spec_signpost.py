"""Spec end-to-end signpost unit test - rust-RFC form (issue #69).

Overwrite: Script drawn from group-level Overview, rendering pointer sign (with/without script), group file does not return None.
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Group, Metadata, Overview, Task
from openagents.spec.signpost import script_path_for_group, signpost_for_group


def _group(*, root: Path, reference_level: str) -> Path:
    group = Group(
        number="0008",
        metadata=Metadata(title="demo", issue=8, slug="demo"),
        tasks=[Task(id="T1", title="t", status="done", priority="P1")],
        overview=Overview(reference_level=reference_level),
    )
    path = model.group_path(specs_root=root, number="0008", slug="demo")
    model.dump_group(group=group, path=path)
    return path


def test_script_path_extracted_from_overview(tmp_path: Path) -> None:
    path = _group(
        root=tmp_path, reference_level="Run offline `scripts/e2e-demo.sh` (ruff + pytest)."
    )
    assert script_path_for_group(group_path=path) == "scripts/e2e-demo.sh"


def test_script_path_none_when_no_script(tmp_path: Path) -> None:
    path = _group(root=tmp_path, reference_level="Pure manual validation, no script.")
    assert script_path_for_group(group_path=path) is None


def test_signpost_with_script_gives_run_command(tmp_path: Path) -> None:
    path = _group(root=tmp_path, reference_level="`scripts/e2e-demo.sh`")
    body = signpost_for_group(group_path=path)
    assert "## End-to-end verification" in body
    assert "`bash scripts/e2e-demo.sh`" in body
    assert "docs/specs/0008-demo.md" in body


def test_signpost_without_script_points_to_group(tmp_path: Path) -> None:
    path = _group(root=tmp_path, reference_level="")
    body = signpost_for_group(group_path=path)
    assert "Spec-0008" in body
    assert "bash" not in body  # No script not give run command


def test_signpost_none_when_group_missing(tmp_path: Path) -> None:
    assert signpost_for_group(group_path=tmp_path / "nope.md") is None
    assert script_path_for_group(group_path=tmp_path / "nope.md") is None
