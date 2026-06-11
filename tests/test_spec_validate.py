"""Spec-0014/T2: spec validate 单元测试。

用临时 specs 树覆盖每条规则的正反例：schema 不合规 / 同组 files 重叠 / DAG 环 /
跨组引用不存在 → error；跨组 files 重叠 → warning 且 ok=True；全合规 → ok 无 issue。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import RelatesTo, Task
from openagents.spec.validate import validate


def _write_task(*, group_dir: Path, task: Task) -> None:
    model.dump_task(task=task, path=group_dir / "tasks" / f"{task.id}.yaml")


def _write_group(
    *,
    root: Path,
    number: str,
    slug: str,
    issue: int,
    tasks: list[Task],
) -> Path:
    group_dir = root / f"{number}-{slug}"
    (group_dir / "tasks").mkdir(parents=True)
    (group_dir / "metadata.yaml").write_text(
        f"title: {slug}\nissue: {issue}\nslug: {slug}\n", encoding="utf-8"
    )
    for task in tasks:
        _write_task(group_dir=group_dir, task=task)
    return group_dir


def _task(**overrides: object) -> Task:
    base: dict[str, object] = dict(id="T1", title="t", status="pending", priority="P1")
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


def _errors(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "error"]


def _warnings(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "warning"]


def test_all_valid_reports_ok_no_issues(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(id="T1", files=["a.py"]),
            _task(id="T2", depends_on=["T1"], files=["b.py"]),
        ],
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert report.issues == []


def test_schema_violation_is_error(tmp_path: Path) -> None:
    group_dir = _write_group(root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[])
    # 非法 status 枚举值。
    (group_dir / "tasks" / "T1.yaml").write_text(
        "id: T1\ntitle: t\nstatus: bogus\npriority: P1\n", encoding="utf-8"
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("bogus" in m for m in _errors(report))


def test_missing_metadata_is_error(tmp_path: Path) -> None:
    group_dir = tmp_path / "0001-alpha"
    (group_dir / "tasks").mkdir(parents=True)
    _write_task(group_dir=group_dir, task=_task(id="T1"))
    report = validate(specs_root=tmp_path)
    assert any("metadata" in m for m in _errors(report))


def test_intra_group_file_overlap_is_error(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["shared.py"]), _task(id="T2", files=["shared.py"])],
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("同组内文件" in m for m in _errors(report))


def test_cross_group_file_overlap_is_warning_only(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["x.py"])]
    )
    _write_group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["x.py"])]
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is True  # warning 不影响 ok
    assert any("跨组重叠" in m for m in _warnings(report))
    assert _errors(report) == []


def test_dependency_cycle_is_error(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(id="T1", depends_on=["T2"], files=["a.py"]),
            _task(id="T2", depends_on=["T1"], files=["b.py"]),
        ],
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("存在环" in m for m in _errors(report))


def test_cross_group_dependency_to_missing_task_is_error(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", depends_on=["0002/T9"], files=["a.py"])],
    )
    _write_group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["b.py"])]
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("0002/T9" in m for m in _errors(report))


def test_relates_to_resolves_to_existing_task(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(
                id="T1",
                files=["a.py"],
                relates_to=[RelatesTo(ref="0002/T1", type="extends")],
            )
        ],
    )
    _write_group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["b.py"])]
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is True


def test_status_abandoned_in_snapshot_is_error(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", status="abandoned", files=["a.py"])],
    )
    report = validate(specs_root=tmp_path)
    assert any("abandoned" in m for m in _errors(report))


def test_history_version_must_increase(tmp_path: Path) -> None:
    group_dir = _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", version=1, files=["a.py"])],
    )
    (group_dir / "history").mkdir()
    model.dump_history(
        versions=[_task(id="T1", status="done", version=1)],
        path=group_dir / "history" / "T1.yaml",
    )
    # 当前版 v1 未高于历史末版 v1 → error。
    report = validate(specs_root=tmp_path)
    assert any("未高于历史末版" in m for m in _errors(report))


def test_empty_specs_root_is_ok(tmp_path: Path) -> None:
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert report.issues == []
