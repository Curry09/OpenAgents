"""spec.ownership unit test - Single Writer Index + Excessive Guard (Spec-0071/T1).

Overwrite: build_index maps the file statements to the only owner (first speaker wins); generated_artifacts constant group
Spec md + Overseas + ARCHETECTURE; unowned_writes unauthorised (Leave declaration file and generator, stop owner file,
Sorts to weight, empty changeset back. Pure function, zero IO.
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import ownership
from openagents.spec.model import Group, Metadata, Task


def _group(*, number: str = "0071", slug: str = "single-writer-ownership-guard") -> Group:
    """A double Task group: T1 for a.py/b.py, T2 for c.py."""
    return Group(
        number=number,
        metadata=Metadata(title=slug, issue=71, slug=slug, summary="tl;dr"),
        tasks=[
            Task(id="T1", title="t1", status="pending", priority="P1", files=["a.py", "b.py"]),
            Task(id="T2", title="t2", status="pending", priority="P1", files=["c.py"]),
        ],
    )


def test_build_index_maps_each_file_to_single_owner() -> None:
    index = ownership.build_index(group=_group())
    assert index.owner_of(path="a.py") == "0071/T1"
    assert index.owner_of(path="b.py") == "0071/T1"
    assert index.owner_of(path="c.py") == "0071/T2"


def test_owner_of_unknown_path_is_none() -> None:
    index = ownership.build_index(group=_group())
    assert index.owner_of(path="nowhere.py") is None


def test_build_index_first_declarer_wins_on_duplicate() -> None:
    """When the same document is declared by two Tasks (error of validate), the index takes the first owner, certainty, no raise."""
    group = Group(
        number="0071",
        metadata=Metadata(title="s", issue=71, slug="s", summary="x"),
        tasks=[
            Task(id="T1", title="t1", status="pending", priority="P1", files=["dup.py"]),
            Task(id="T2", title="t2", status="pending", priority="P1", files=["dup.py"]),
        ],
    )
    assert ownership.build_index(group=group).owner_of(path="dup.py") == "0071/T1"


def test_generated_artifacts_covers_spec_md_and_rendered_docs() -> None:
    arts = ownership.generated_artifacts(group=_group(), specs_root=Path("docs/specs"))
    assert "docs/specs/0071-single-writer-ownership-guard.md" in arts
    assert "docs/specs/OVERVIEW.md" in arts
    assert "docs/specs/ARCHITECTURE.md" in arts


def test_unowned_writes_allows_declared_files() -> None:
    assert ownership.unowned_writes(group=_group(), changed_paths=["a.py", "b.py", "c.py"]) == []


def test_unowned_writes_allows_generated_artifacts() -> None:
    changed = [
        "docs/specs/0071-single-writer-ownership-guard.md",
        "docs/specs/OVERVIEW.md",
        "docs/specs/ARCHITECTURE.md",
    ]
    assert ownership.unowned_writes(group=_group(), changed_paths=changed) == []


def test_unowned_writes_flags_files_no_task_owns() -> None:
    offenders = ownership.unowned_writes(
        group=_group(), changed_paths=["a.py", "evil.py", "other/steal.py"]
    )
    assert offenders == ["evil.py", "other/steal.py"]


def test_unowned_writes_sorts_and_dedupes() -> None:
    offenders = ownership.unowned_writes(group=_group(), changed_paths=["z.py", "z.py", "m.py"])
    assert offenders == ["m.py", "z.py"]


def test_unowned_writes_empty_changeset_is_clean() -> None:
    assert ownership.unowned_writes(group=_group(), changed_paths=[]) == []


def test_unowned_writes_respects_custom_specs_root() -> None:
    """specs_root has changed the path of the generator; the old default path is no longer released as the generator."""
    offenders = ownership.unowned_writes(
        group=_group(),
        changed_paths=["docs/specs/OVERVIEW.md"],
        specs_root=Path("other/specs"),
    )
    assert offenders == ["docs/specs/OVERVIEW.md"]
