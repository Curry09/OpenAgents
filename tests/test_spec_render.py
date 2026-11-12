"""Spec render unit test - markdown single file form (2026-06-24).

Overwrite: 4-bit full, Board of view lines = current version of Task numbers, cross-group relates-to dot-line edges, current version node by status
The color, file conflict reports, cylindrical, etc. (two render bytes consistent), empty warehouse is not misreported. The history mechanism is decommissioned, and the system is not in place.
Evolution maps are degraded to single-version nodes of Task.
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import E2EPlan, Group, Metadata, RelatesTo, Task
from openagents.spec.render import render, write_overview


def _group(*, root: Path, number: str, slug: str, issue: int, tasks: list[Task]) -> Path:
    group = Group(
        number=number,
        metadata=Metadata(
            title=f"{slug} feature", issue=issue, slug=slug, summary=f"{slug} summary."
        ),
        tasks=tasks,
    )
    path = model.group_path(specs_root=root, number=number, slug=slug)
    model.dump_group(group=group, path=path)
    return path


def _task(**overrides: object) -> Task:
    base: dict[str, object] = dict(id="T1", title="t", status="pending", priority="P1")
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


def test_four_blocks_present(tmp_path: Path) -> None:
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "## Task board" in text
    assert "## Cross-Spec relationships" in text
    assert "## File ownership overlaps" in text
    assert "## Spec details" in text


def test_tldr_block_shows_group_summary(tmp_path: Path) -> None:
    """Spec-0015/T4: OverVIEW Top TL; DR presents the Summary by feature."""
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "## TL;DR" in text
    assert "alpha summary" in text


def test_board_row_count_equals_task_count(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["a.py"]), _task(id="T2", files=["b.py"])],
    )
    text = render(specs_root=tmp_path)
    rows = [ln for ln in text.splitlines() if ln.startswith("| 0001 |")]
    assert len(rows) == 2


def test_idempotent(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["a.py"]), _task(id="T2", depends_on=["T1"], files=["b.py"])],
    )
    assert render(specs_root=tmp_path) == render(specs_root=tmp_path)


def test_cross_group_relates_to_dashed_edge(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(id="T1", files=["a.py"], relates_to=[RelatesTo(ref="0002/T1", type="extends")])
        ],
    )
    _group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["b.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "-.extends.->" in text


def test_evolution_graph_colors_current_status(tmp_path: Path) -> None:
    """After history is retired, the evolutionary diagram presents the current single version of Task and colours the status."""
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", status="done", files=["a.py"])],
    )
    text = render(specs_root=tmp_path)
    assert "v_T1_1" in text
    assert "classDef st_done" in text


def test_file_conflict_reported(tmp_path: Path) -> None:
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["x.py"])]
    )
    _group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["x.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "x.py" in text.split("## File ownership overlaps")[1].split("# Every feauty")[0]


def test_empty_root_does_not_error(tmp_path: Path) -> None:
    text = render(specs_root=tmp_path)
    assert "## Task board" in text
    assert "No files are shared across groups" in text


def test_e2e_plan_rendered_in_tldr(tmp_path: Path) -> None:
    """Spec-0040/T1: Declares the e2e group, the OVERVIEW TL; DR shows the intent + acceptance behavior."""
    group = Group(
        number="0001",
        metadata=Metadata(
            title="alpha feature",
            issue=1,
            slug="alpha",
            summary="alpha summary",
            e2e=E2EPlan(
                intent="Initialization reports a missing origin",
                method="1. Without origin, init exits nonzero and prints a hint\n2. Set origin and rerun successfully",
            ),
        ),
        tasks=[_task(id="T1", files=["a.py"])],
    )
    path = model.group_path(specs_root=tmp_path, number="0001", slug="alpha")
    model.dump_group(group=group, path=path)
    text = render(specs_root=tmp_path)
    assert "End-to-end intent: Initialization reports a missing origin" in text
    assert "Method: " in text
    assert "exits nonzero and prints a hint" in text


def test_no_e2e_plan_omits_block(tmp_path: Path) -> None:
    """Undeclared group: OVERVIEW does not appear e2e rough plan line (no behavior change)."""
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "e2e Crude planning" not in text


def test_write_overview_writes_file(tmp_path: Path) -> None:
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    path = write_overview(specs_root=tmp_path)
    assert path == tmp_path / "OVERVIEW.md"
    assert path.read_text(encoding="utf-8") == render(specs_root=tmp_path)
