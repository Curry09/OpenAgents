"""spec new / add-task / abandon 单元测试 —— markdown 单文件形态（2026-06-24）。

覆盖：create_group 落 markdown + 自动 render；add_task 写入并 render；abandon 从快照移除；
重复/缺失组/缺失 task 的错误路径。amend 已退役（历史交给 git），不再测试。
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
        title="Alpha 组",
        issue=7,
        summary="人话 TL;DR",
        number=None,
    )
    assert path == tmp_path / "0001-alpha.md"  # 空仓库 → 下一号 0001
    group = model.load_group(path=path)
    assert (group.metadata.title, group.metadata.issue, group.metadata.slug) == (
        "Alpha 组",
        7,
        "alpha",
    )
    assert group.metadata.summary == "人话 TL;DR"
    assert group.tasks == []
    assert (tmp_path / "OVERVIEW.md").is_file()  # 自动 render


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
        title="第一个任务",
        priority="P1",
        status="pending",
        files=["openagents/x.py"],
        depends_on=[],
        scope="范围",
        acceptance="验收",
    )
    assert task.id == "T1"
    loaded = model.load_group(path=tmp_path / "0001-a.md").tasks[0]
    assert (loaded.title, loaded.status, loaded.priority, loaded.files) == (
        "第一个任务",
        "pending",
        "P1",
        ["openagents/x.py"],
    )
    # issue #69：scope/acceptance 进 frontmatter（结构化）。
    assert loaded.scope == "范围"
    assert loaded.acceptance == "验收"
    assert "0001/T1" in (tmp_path / "OVERVIEW.md").read_text(encoding="utf-8")


def test_new_group_scaffolds_nine_sections(tmp_path: Path) -> None:
    """issue #69：spec new 产出含 rust-RFC 9 段标题的正文脚手架。"""
    path = create_group(
        specs_root=tmp_path, slug="demo", title="D", issue=1, summary="一句话", number=None
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
    abandon(specs_root=tmp_path, group="0001", task_id="T1", reason="不再需要")
    assert model.load_group(path=tmp_path / "0001-a.md").tasks == []
    assert (tmp_path / "OVERVIEW.md").is_file()


def test_abandon_missing_task_raises(tmp_path: Path) -> None:
    create_group(specs_root=tmp_path, slug="a", title="A", issue=1, summary="x", number="0001")
    with pytest.raises(FileNotFoundError):
        abandon(specs_root=tmp_path, group="0001", task_id="T9", reason="x")


def test_abandon_missing_group_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        abandon(specs_root=tmp_path, group="9999", task_id="T1", reason="x")
