"""Spec new / add-task / abandon unit test - markdown single file form (2026-06-24).

Overwrite: create_group down markdown + autorender; add_task written and render; abandon removed from snapshot;
Repeat/Missing group/missing task is the wrong path.amend Retired (History handed over to git）- No more tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openagents.spec import model
from openagents.spec.mutate import abandon, add_task, create_group


def test_create_group_scaffolds_and_renders(tmp_path: Path) -> None:
    path = create_group(
        specs_root=tmp_path,
        slug="alpha",
        title="Alpha Group",
        issue=7,
        summary="Talent TL;DR",
        number=None,
    )
    assert path == tmp_path / "0001-alpha.md"  # Empty warehouse.
    group = model.load_group(path=path)
    assert (group.metadata.title, group.metadata.issue, group.metadata.slug) == (
        "Alpha Group",
        7,
        "alpha",
    )
    assert group.metadata.summary == "Talent TL;DR"
    assert group.tasks == []
    assert (tmp_path / "OVERVIEW.md").is_file()  # Automatic render


def test_create_group_auto_numbers_next(tmp_path: Path) -> None:
    create_group(specs_root=tmp_path, slug="a", title="A", issue=1, summary="x", number="0003")
    nxt = create_group(specs_root=tmp_path, slug="b", title="B", issue=2, summary="y", number=None)
    assert nxt.name == "0004-b.md"


def test_create_group_existing_raises(tmp_path: Path) -> None:
    create_group(specs_root=tmp_path, slug="a", title="A", issue=1, summary="x", number="0001")
    with pytest.raises(FileExistsError):
        create_group(specs_root=tmp_path, slug="a", title="A", issue=1, summary="x", number="0001")


def test_add_task_writes_task_and_renders(tmp_path: Path) -> None:
    create_group(specs_root=tmp_path, slug="a", title="A", issue=1, summary="x", number="0001")
    task = add_task(
        specs_root=tmp_path,
        group="0001",
        task_id="T1",
        title="First assignment",
        priority="P1",
        status="pending",
        files=["openagents/x.py"],
        depends_on=[],
        scope="Scope",
        acceptance="acceptance",
    )
    assert task.id == "T1"
    loaded = model.load_group(path=tmp_path / "0001-a.md").tasks[0]
    assert (loaded.title, loaded.status, loaded.priority, loaded.files) == (
        "First assignment",
        "pending",
        "P1",
        ["openagents/x.py"],
    )
    # Assue #69: scope/acceptance goes frontmotter (structured).
    assert loaded.scope == "Scope"
    assert loaded.acceptance == "acceptance"
    assert "0001/T1" in (tmp_path / "OVERVIEW.md").read_text(encoding="utf-8")


def test_new_group_scaffolds_nine_sections(tmp_path: Path) -> None:
    """The text scaffolding of the title in paragraph 9 of the title of the title ”Rust-RFC” is included in the issue #69: spec new output."""
    path = create_group(
        specs_root=tmp_path, slug="demo", title="D", issue=1, summary="One word.", number=None
    )
    body = path.read_text(encoding="utf-8")
    for heading in (
        "## Summary",
        "## Motivation",
        "## Guide-level explanation",
        "## Reference-level explanation",
        "## Drawbacks",
        "## Rationale and alternatives",
        "## Prior art",
        "## Unresolved questions",
        "## Future possibilities",
    ):
        assert heading in body


def test_add_task_duplicate_raises(tmp_path: Path) -> None:
    create_group(specs_root=tmp_path, slug="a", title="A", issue=1, summary="x", number="0001")
    kwargs = dict(
        specs_root=tmp_path,
        group="0001",
        task_id="T1",
        title="t",
        priority="P1",
        status="pending",
        files=[],
        depends_on=[],
        scope="",
        acceptance="",
    )
    add_task(**kwargs)
    with pytest.raises(FileExistsError):
        add_task(**kwargs)


def test_add_task_unknown_group_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        add_task(
            specs_root=tmp_path,
            group="9999",
            task_id="T1",
            title="t",
            priority="P1",
            status="pending",
            files=[],
            depends_on=[],
            scope="",
            acceptance="",
        )


def test_abandon_removes_task_from_snapshot(tmp_path: Path) -> None:
    create_group(specs_root=tmp_path, slug="a", title="A", issue=1, summary="x", number="0001")
    add_task(
        specs_root=tmp_path,
        group="0001",
        task_id="T1",
        title="t",
        priority="P1",
        status="in-progress",
        files=["a.py"],
        depends_on=[],
        scope="",
        acceptance="",
    )
    abandon(specs_root=tmp_path, group="0001", task_id="T1", reason="No more.")
    assert model.load_group(path=tmp_path / "0001-a.md").tasks == []
    assert (tmp_path / "OVERVIEW.md").is_file()


def test_abandon_missing_task_raises(tmp_path: Path) -> None:
    create_group(specs_root=tmp_path, slug="a", title="A", issue=1, summary="x", number="0001")
    with pytest.raises(FileNotFoundError):
        abandon(specs_root=tmp_path, group="0001", task_id="T9", reason="x")


def test_abandon_missing_group_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        abandon(specs_root=tmp_path, group="9999", task_id="T1", reason="x")
