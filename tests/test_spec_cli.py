"""Spec CLI+ Numbered Script Module Test - markdown single file form (2026-06-24).

CLI: Ender writes for Overview; Validate exit code; abandon/new/add-task route to mutate; graph generation/ verification
ARCHITECTURE. check-spec-nomber-conflits: conflicting and single-numbered.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from openagents.spec import model
from openagents.spec.cli import main
from openagents.spec.model import Group, Metadata, Overview, Task


def _overview() -> Overview:
    return Overview(summary="s", motivation="m", reference_level="r", rationale_alternatives="ra")


def _group(*, root: Path, number: str, slug: str, tasks: list[Task]) -> Path:
    group = Group(
        number=number,
        metadata=Metadata(title=slug, issue=1, slug=slug, summary=f"{slug} TL;DR"),
        tasks=tasks,
        overview=_overview(),
    )
    path = model.group_path(specs_root=root, number=number, slug=slug)
    model.dump_group(group=group, path=path)
    return path


def _task(**overrides: object) -> Task:
    base: dict[str, object] = dict(id="T1", title="t", status="pending", priority="P1")
    base.update(overrides)
    base.setdefault("files", [f"{base['id']}.py"])
    base.setdefault("acceptance", "Validated.")
    return Task(**base)  # type: ignore[arg-type]


def test_render_writes_overview(tmp_path: Path) -> None:
    _group(root=tmp_path, number="0001", slug="alpha", tasks=[_task(files=["a.py"])])
    code = main(argv=["render", "--specs-root", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "OVERVIEW.md").is_file()


def test_validate_ok_returns_zero(tmp_path: Path) -> None:
    _group(root=tmp_path, number="0001", slug="alpha", tasks=[_task(files=["a.py"])])
    assert main(argv=["validate", "--specs-root", str(tmp_path)]) == 0


def test_validate_error_returns_nonzero(tmp_path: Path) -> None:
    (tmp_path / "0001-alpha.md").write_text(
        '---\nnumber: "0001"\ntitle: alpha\nissue: 1\nslug: alpha\n'
        "tasks:\n  - id: T1\n    title: t\n    status: bogus\n    priority: P1\n"
        "---\n\n# 0001 · alpha\n",
        encoding="utf-8",
    )
    assert main(argv=["validate", "--specs-root", str(tmp_path)]) == 1


def test_validate_warning_only_returns_zero(tmp_path: Path, capsys) -> None:
    _group(root=tmp_path, number="0001", slug="alpha", tasks=[_task(files=["x.py"])])
    _group(root=tmp_path, number="0002", slug="beta", tasks=[_task(files=["x.py"])])
    code = main(argv=["validate", "--specs-root", str(tmp_path)])
    assert code == 0
    assert "warning" in capsys.readouterr().out


def test_abandon_routes_to_mutate(tmp_path: Path) -> None:
    path = _group(root=tmp_path, number="0001", slug="alpha", tasks=[_task(files=["a.py"])])
    code = main(
        argv=["abandon", "0001", "T1", "--reason", "Discard", "--specs-root", str(tmp_path)]
    )
    assert code == 0
    assert model.load_group(path=path).tasks == []


def test_no_subcommand_returns_2(tmp_path: Path) -> None:
    assert main(argv=["--specs-root", str(tmp_path)]) == 2


def test_new_subcommand_creates_group(tmp_path: Path) -> None:
    code = main(
        argv=[
            "new",
            "alpha",
            "--issue",
            "7",
            "--title",
            "Alpha",
            "--summary",
            "Talent TL;DR",
            "--specs-root",
            str(tmp_path),
        ]
    )
    assert code == 0
    group = model.load_group(path=tmp_path / "0001-alpha.md")
    assert group.metadata.issue == 7
    assert group.metadata.summary == "Talent TL;DR"


def test_add_task_subcommand_writes_task(tmp_path: Path) -> None:
    main(
        argv=[
            "new",
            "alpha",
            "--issue",
            "7",
            "--title",
            "Alpha",
            "--summary",
            "TL;DR",
            "--specs-root",
            str(tmp_path),
        ]
    )
    code = main(
        argv=[
            "add-task",
            "0001",
            "--id",
            "T1",
            "--title",
            "Task one",
            "--priority",
            "P1",
            "--files",
            "a.py, b.py",
            "--depends-on",
            "T0",
            "--specs-root",
            str(tmp_path),
        ]
    )
    assert code == 0
    task = model.load_group(path=tmp_path / "0001-alpha.md").tasks[0]
    assert task.files == ["a.py", "b.py"]
    assert task.depends_on == ["T0"]
    assert task.status == "pending"  # Default


def test_graph_generates_architecture(tmp_path: Path) -> None:
    """Spec graph sweeps a small package to generate ARCHITECTURE.md."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Example subsystem."""\n', encoding="utf-8")
    (pkg / "a.py").write_text('"""Component a: Do A."""\nimport pkg.b\n', encoding="utf-8")
    (pkg / "b.py").write_text('"""Component b: Do B."""\n', encoding="utf-8")
    code = main(argv=["graph", "--package-root", str(pkg), "--specs-root", str(tmp_path)])
    assert code == 0
    text = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "Component a: Do A." in text
    assert "graph LR" in text


def test_graph_check_flags_missing_docstring(tmp_path: Path) -> None:
    """--check returns non-0 when it lacks docstring."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””””\n",
        encoding="utf-8",
    )
    (pkg / "a.py").write_text("x = 1\n", encoding="utf-8")  # No doingcstring
    code = main(
        argv=["graph", "--package-root", str(pkg), "--specs-root", str(tmp_path), "--check"]
    )
    assert code == 1


# ── spec ownership（Spec-0071）──


def test_ownership_table_lists_owner_and_path(tmp_path: Path, capsys) -> None:
    """No --check: Print a single Writer table, owner Task for a restricted ID+ declaration file."""
    _group(root=tmp_path, number="0071", slug="own", tasks=[_task(files=["a.py", "b.py"])])
    code = main(argv=["ownership", "--specs-root", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "0071/T1\ta.py" in out
    assert "0071/T1\tb.py" in out


def test_ownership_check_passes_for_declared_files(tmp_path: Path) -> None:
    _group(root=tmp_path, number="0071", slug="own", tasks=[_task(files=["a.py"])])
    code = main(
        argv=[
            "ownership",
            "--specs-root",
            str(tmp_path),
            "--check",
            "--group",
            "0071",
            "--changed",
            "a.py",
        ]
    )
    assert code == 0


def test_ownership_check_flags_unowned_write(tmp_path: Path, capsys) -> None:
    _group(root=tmp_path, number="0071", slug="own", tasks=[_task(files=["a.py"])])
    code = main(
        argv=[
            "ownership",
            "--specs-root",
            str(tmp_path),
            "--check",
            "--group",
            "0071",
            "--changed",
            "a.py,evil.py",
        ]
    )
    assert code == 1
    assert "evil.py" in capsys.readouterr().out


def test_ownership_check_without_group_returns_2(tmp_path: Path) -> None:
    _group(root=tmp_path, number="0071", slug="own", tasks=[_task(files=["a.py"])])
    code = main(argv=["ownership", "--specs-root", str(tmp_path), "--check", "--changed", "a.py"])
    assert code == 2


def test_ownership_check_unknown_group_returns_2(tmp_path: Path) -> None:
    _group(root=tmp_path, number="0071", slug="own", tasks=[_task(files=["a.py"])])
    code = main(
        argv=[
            "ownership",
            "--specs-root",
            str(tmp_path),
            "--check",
            "--group",
            "9999",
            "--changed",
            "a.py",
        ]
    )
    assert code == 2


# ── check-spec-number-conflicts.py ──


def _load_conflict_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check-spec-number-conflicts.py"
    spec = importlib.util.spec_from_file_location("check_spec_conflicts", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _make_group_file(root: Path, name: str) -> None:
    specs = root / "docs" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / name).write_text("---\n---\n", encoding="utf-8")


def test_conflict_script_detects_duplicate_number(tmp_path: Path) -> None:
    mod = _load_conflict_script()
    _make_group_file(tmp_path, "0001-alpha.md")
    _make_group_file(tmp_path, "0001-beta.md")  # Same number different slug
    conflicts = mod._find_local_conflicts(tmp_path)
    assert any("0001" in c for c in conflicts)


def test_conflict_script_unique_numbers_pass(tmp_path: Path) -> None:
    mod = _load_conflict_script()
    _make_group_file(tmp_path, "0001-alpha.md")
    _make_group_file(tmp_path, "0002-beta.md")
    # The dated design document should not be considered a group.
    _make_group_file(tmp_path, "2026-06-24-design.md")
    assert mod._find_local_conflicts(tmp_path) == []


def test_conflict_script_extract_identity() -> None:
    mod = _load_conflict_script()
    assert mod._extract_spec_identity("docs/specs/0014-spec-snapshot.md") == (
        "0014",
        "spec-snapshot",
    )
    assert mod._extract_spec_identity("docs/specs/2026-06-24-design.md") is None
    assert mod._extract_spec_identity("docs/specs/OVERVIEW.md") is None
