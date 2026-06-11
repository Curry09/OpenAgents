"""Spec-0014/T5: spec CLI + 编号校验脚本单元测试。

CLI：render 写 OVERVIEW；validate 有 error 退出码非 0、仅 warning 退 0；amend/abandon
路由到 mutate。check-spec-number-conflicts：重复编号报冲突、唯一编号通过（打桩 gh）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from openagents.spec import model
from openagents.spec.cli import main
from openagents.spec.model import Task


def _write_group(*, root: Path, number: str, slug: str, tasks: list[Task]) -> Path:
    group_dir = root / f"{number}-{slug}"
    (group_dir / "tasks").mkdir(parents=True)
    (group_dir / "metadata.yaml").write_text(
        f"title: {slug}\nissue: 1\nslug: {slug}\n", encoding="utf-8"
    )
    for task in tasks:
        model.dump_task(task=task, path=group_dir / "tasks" / f"{task.id}.yaml")
    return group_dir


def _task(**overrides: object) -> Task:
    base: dict[str, object] = dict(id="T1", title="t", status="pending", priority="P1")
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


def test_render_writes_overview(tmp_path: Path) -> None:
    _write_group(root=tmp_path, number="0001", slug="alpha", tasks=[_task(files=["a.py"])])
    code = main(argv=["render", "--specs-root", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "OVERVIEW.md").is_file()


def test_validate_ok_returns_zero(tmp_path: Path) -> None:
    _write_group(root=tmp_path, number="0001", slug="alpha", tasks=[_task(files=["a.py"])])
    assert main(argv=["validate", "--specs-root", str(tmp_path)]) == 0


def test_validate_error_returns_nonzero(tmp_path: Path) -> None:
    group_dir = _write_group(root=tmp_path, number="0001", slug="alpha", tasks=[])
    # 非法 status → schema error。
    (group_dir / "tasks" / "T1.yaml").write_text(
        "id: T1\ntitle: t\nstatus: bogus\npriority: P1\n", encoding="utf-8"
    )
    assert main(argv=["validate", "--specs-root", str(tmp_path)]) == 1


def test_validate_warning_only_returns_zero(tmp_path: Path, capsys) -> None:
    # 跨组同名文件 → 仅 warning。
    _write_group(root=tmp_path, number="0001", slug="alpha", tasks=[_task(files=["x.py"])])
    _write_group(root=tmp_path, number="0002", slug="beta", tasks=[_task(files=["x.py"])])
    code = main(argv=["validate", "--specs-root", str(tmp_path)])
    assert code == 0
    assert "warning" in capsys.readouterr().out


def test_amend_routes_to_mutate(tmp_path: Path) -> None:
    group_dir = _write_group(
        root=tmp_path, number="0001", slug="alpha", tasks=[_task(version=1, files=["a.py"])]
    )
    code = main(argv=["amend", "0001", "T1", "--reason", "改一下", "--specs-root", str(tmp_path)])
    assert code == 0
    assert model.load_group(group_dir=group_dir).tasks[0].version == 2


def test_abandon_routes_to_mutate(tmp_path: Path) -> None:
    group_dir = _write_group(
        root=tmp_path, number="0001", slug="alpha", tasks=[_task(files=["a.py"])]
    )
    code = main(argv=["abandon", "0001", "T1", "--reason", "弃用", "--specs-root", str(tmp_path)])
    assert code == 0
    assert not (group_dir / "tasks" / "T1.yaml").exists()


def test_no_subcommand_returns_2(tmp_path: Path) -> None:
    assert main(argv=["--specs-root", str(tmp_path)]) == 2


# ── check-spec-number-conflicts.py ──


def _load_conflict_script():
    """以模块方式加载脚本（文件名含连字符，不能直接 import）。"""
    path = Path(__file__).resolve().parents[1] / "scripts" / "check-spec-number-conflicts.py"
    spec = importlib.util.spec_from_file_location("check_spec_conflicts", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _make_group_dir(root: Path, name: str) -> None:
    (root / "docs" / "specs" / name / "tasks").mkdir(parents=True)


def test_conflict_script_detects_duplicate_number(tmp_path: Path) -> None:
    mod = _load_conflict_script()
    _make_group_dir(tmp_path, "0001-alpha")
    _make_group_dir(tmp_path, "0001-beta")  # 同号不同 slug
    conflicts = mod._find_local_conflicts(tmp_path)
    assert any("0001" in c for c in conflicts)


def test_conflict_script_unique_numbers_pass(tmp_path: Path) -> None:
    mod = _load_conflict_script()
    _make_group_dir(tmp_path, "0001-alpha")
    _make_group_dir(tmp_path, "0002-beta")
    assert mod._find_local_conflicts(tmp_path) == []


def test_conflict_script_extract_identity() -> None:
    mod = _load_conflict_script()
    assert mod._extract_spec_identity("docs/specs/0014-spec-snapshot/tasks/T1.yaml") == (
        "0014",
        "spec-snapshot",
    )
    assert mod._extract_spec_identity("docs/rfcs/0014-x.md") is None


def test_new_subcommand_creates_group(tmp_path: Path) -> None:
    code = main(
        argv=["new", "alpha", "--issue", "7", "--title", "Alpha", "--specs-root", str(tmp_path)]
    )
    assert code == 0
    group = model.load_group(group_dir=tmp_path / "0001-alpha")
    assert group.metadata.issue == 7


def test_add_task_subcommand_writes_task(tmp_path: Path) -> None:
    main(argv=["new", "alpha", "--issue", "7", "--title", "Alpha", "--specs-root", str(tmp_path)])
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
    task = model.load_group(group_dir=tmp_path / "0001-alpha").tasks[0]
    assert task.files == ["a.py", "b.py"]
    assert task.depends_on == ["T0"]
    assert task.status == "pending"  # 默认
