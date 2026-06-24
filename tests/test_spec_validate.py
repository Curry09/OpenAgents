"""spec validate 单元测试 —— markdown 单文件形态（2026-06-24）。

覆盖每条规则的正反例：frontmatter schema 不合规 / 同组 files 重叠 / DAG 环 / 跨组引用不存在
→ error；跨组 files 重叠 → warning 且 ok=True；全合规 → ok 无 issue。history 机制已退役。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Group, Metadata, RelatesTo, Task
from openagents.spec.validate import validate


def _group(*, root: Path, number: str, slug: str, issue: int, tasks: list[Task]) -> Path:
    group = Group(
        number=number,
        metadata=Metadata(title=slug, issue=issue, slug=slug, summary=f"{slug} TL;DR"),
        tasks=tasks,
    )
    path = model.group_path(specs_root=root, number=number, slug=slug)
    model.dump_group(group=group, path=path)
    return path


def _task(**overrides: object) -> Task:
    base: dict[str, object] = dict(id="T1", title="t", status="pending", priority="P1")
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


def _errors(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "error"]


def _warnings(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "warning"]


def test_all_valid_reports_ok_no_issues(tmp_path: Path) -> None:
    _group(
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
    # 非法 status 枚举值，直接手写 frontmatter。
    (tmp_path / "0001-alpha.md").write_text(
        "---\n"
        'number: "0001"\n'
        "title: alpha\n"
        "issue: 1\n"
        "slug: alpha\n"
        "tasks:\n"
        "  - id: T1\n"
        "    title: t\n"
        "    status: bogus\n"
        "    priority: P1\n"
        "---\n\n# 0001 · alpha\n",
        encoding="utf-8",
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("bogus" in m for m in _errors(report))


def test_missing_required_frontmatter_is_error(tmp_path: Path) -> None:
    # 缺 title（GROUP_FRONTMATTER_SCHEMA required）。
    (tmp_path / "0001-alpha.md").write_text(
        '---\nnumber: "0001"\nissue: 1\nslug: alpha\ntasks: []\n---\n\n# 0001 · alpha\n',
        encoding="utf-8",
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("title" in m for m in _errors(report))


def test_intra_group_file_overlap_is_error(tmp_path: Path) -> None:
    _group(
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
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["x.py"])]
    )
    _group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["x.py"])]
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is True  # warning 不影响 ok
    assert any("跨组重叠" in m for m in _warnings(report))
    assert _errors(report) == []


def test_dependency_cycle_is_error(tmp_path: Path) -> None:
    _group(
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
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", depends_on=["0002/T9"], files=["a.py"])],
    )
    _group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["b.py"])]
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("0002/T9" in m for m in _errors(report))


def test_relates_to_resolves_to_existing_task(tmp_path: Path) -> None:
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
    report = validate(specs_root=tmp_path)
    assert report.ok is True


def test_status_abandoned_in_snapshot_is_error(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", status="abandoned", files=["a.py"])],
    )
    report = validate(specs_root=tmp_path)
    assert any("abandoned" in m for m in _errors(report))


def test_empty_summary_is_error(tmp_path: Path) -> None:
    """Spec-0015/T3：组 summary 为空白 → error。"""
    group = Group(
        number="0001",
        metadata=Metadata(title="alpha", issue=1, slug="alpha", summary="  "),
        tasks=[_task(id="T1", files=["a.py"])],
    )
    model.dump_group(
        group=group, path=model.group_path(specs_root=tmp_path, number="0001", slug="alpha")
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("summary 为空" in m for m in _errors(report))


def test_empty_specs_root_is_ok(tmp_path: Path) -> None:
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert report.issues == []
