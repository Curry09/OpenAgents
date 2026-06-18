"""Spec-0014/T4: spec amend / abandon 单元测试。

覆盖：amend 后 history +1（含旧版完整快照）、tasks 版本自增、OVERVIEW 被重写；
连续 amend 版本单调；abandon 后 tasks/ 无该文件、history 末项 abandoned；
amend 不存在 task 报错且不破坏文件。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from openagents.spec import model
from openagents.spec.model import Task
from openagents.spec.mutate import abandon, amend


def _setup(*, root: Path, version: int = 1) -> Path:
    group_dir = root / "0001-alpha"
    (group_dir / "tasks").mkdir(parents=True)
    (group_dir / "metadata.yaml").write_text(
        "title: alpha\nissue: 1\nslug: alpha\n", encoding="utf-8"
    )
    model.dump_task(
        task=Task(
            id="T1",
            title="原始",
            status="in-progress",
            priority="P1",
            version=version,
            files=["a.py"],
        ),
        path=group_dir / "tasks" / "T1.yaml",
    )
    return group_dir


def _load_history(*, group_dir: Path, task_id: str) -> list[Task]:
    path = group_dir / "history" / f"{task_id}.yaml"
    loaded = model._yaml.load(path) or []
    return [model.task_from_mapping(data=item) for item in loaded]


def test_amend_appends_history_and_bumps_version(tmp_path: Path) -> None:
    group_dir = _setup(root=tmp_path)
    new_task = amend(specs_root=tmp_path, group="0001", task_id="T1", reason="拆出鉴权")

    # 返回的新版：version+1、change-reason、updated=今天。
    assert new_task.version == 2
    assert new_task.change_reason == "拆出鉴权"
    assert new_task.updated == date.today().isoformat()

    # tasks/T1.yaml 已是新版。
    current = model.load_group(group_dir=group_dir).tasks[0]
    assert current.version == 2

    # history 含旧版完整快照（v1）。
    history = _load_history(group_dir=group_dir, task_id="T1")
    assert len(history) == 1
    assert history[0].version == 1
    assert history[0].title == "原始"

    # OVERVIEW 已生成。
    assert (tmp_path / "OVERVIEW.md").is_file()


def test_consecutive_amends_are_monotonic(tmp_path: Path) -> None:
    group_dir = _setup(root=tmp_path)
    amend(specs_root=tmp_path, group="0001", task_id="T1", reason="r1")
    amend(specs_root=tmp_path, group="0001", task_id="T1", reason="r2")

    current = model.load_group(group_dir=group_dir).tasks[0]
    assert current.version == 3
    history = _load_history(group_dir=group_dir, task_id="T1")
    assert [h.version for h in history] == [1, 2]


def test_abandon_removes_task_and_marks_history(tmp_path: Path) -> None:
    group_dir = _setup(root=tmp_path)
    abandon(specs_root=tmp_path, group="0001", task_id="T1", reason="不再需要")

    # tasks/ 不再有该文件。
    assert not (group_dir / "tasks" / "T1.yaml").exists()
    # history 末项 status=abandoned。
    history = _load_history(group_dir=group_dir, task_id="T1")
    assert history[-1].status == "abandoned"
    assert history[-1].change_reason == "不再需要"
    assert (tmp_path / "OVERVIEW.md").is_file()


def test_amend_missing_task_raises_and_keeps_files(tmp_path: Path) -> None:
    group_dir = _setup(root=tmp_path)
    before = (group_dir / "tasks" / "T1.yaml").read_text(encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        amend(specs_root=tmp_path, group="0001", task_id="T9", reason="x")
    # 既有文件未被破坏，且没有生成 history/T9。
    assert (group_dir / "tasks" / "T1.yaml").read_text(encoding="utf-8") == before
    assert not (group_dir / "history" / "T9.yaml").exists()


def test_missing_group_raises(tmp_path: Path) -> None:
    _setup(root=tmp_path)
    with pytest.raises(FileNotFoundError):
        amend(specs_root=tmp_path, group="9999", task_id="T1", reason="x")


# --------------------------------------------------------------------------- #
# issue #53：spec new / add-task 创作入口
# --------------------------------------------------------------------------- #


def test_create_group_scaffolds_metadata_and_renders(tmp_path: Path) -> None:
    from openagents.spec.mutate import create_group

    group_dir = create_group(
        specs_root=tmp_path,
        slug="alpha",
        title="Alpha 组",
        issue=7,
        summary="人话 TL;DR",
        number=None,
    )
    assert group_dir == tmp_path / "0001-alpha"  # 空仓库 → 下一号 0001
    assert (group_dir / "tasks").is_dir()
    group = model.load_group(group_dir=group_dir)
    assert (group.metadata.title, group.metadata.issue, group.metadata.slug) == (
        "Alpha 组",
        7,
        "alpha",
    )
    assert (tmp_path / "OVERVIEW.md").is_file()  # 自动 render


def test_create_group_persists_summary(tmp_path: Path) -> None:
    """Spec-0015/T2：create_group 的 summary 落盘到 metadata.yaml。"""
    from openagents.spec.mutate import create_group

    group_dir = create_group(
        specs_root=tmp_path, slug="a", title="A", issue=1, summary="一句话人话", number="0001"
    )
    assert model.load_group(group_dir=group_dir).metadata.summary == "一句话人话"


def test_create_group_auto_numbers_next(tmp_path: Path) -> None:
    from openagents.spec.mutate import create_group

    create_group(
        specs_root=tmp_path, slug="a", title="A", issue=1, summary="人话 TL;DR", number="0003"
    )
    nxt = create_group(
        specs_root=tmp_path, slug="b", title="B", issue=2, summary="人话 TL;DR", number=None
    )
    assert nxt.name == "0004-b"


def test_create_group_existing_dir_raises(tmp_path: Path) -> None:
    from openagents.spec.mutate import create_group

    create_group(
        specs_root=tmp_path, slug="a", title="A", issue=1, summary="人话 TL;DR", number="0001"
    )
    with pytest.raises(FileExistsError):
        create_group(
            specs_root=tmp_path, slug="a", title="A", issue=1, summary="人话 TL;DR", number="0001"
        )


def test_add_task_writes_task_and_renders(tmp_path: Path) -> None:
    from openagents.spec.mutate import add_task, create_group

    create_group(
        specs_root=tmp_path, slug="a", title="A", issue=1, summary="人话 TL;DR", number="0001"
    )
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
    group = model.load_group(group_dir=tmp_path / "0001-a")
    loaded = group.tasks[0]
    assert (loaded.title, loaded.status, loaded.priority, loaded.files) == (
        "第一个任务",
        "pending",
        "P1",
        ["openagents/x.py"],
    )
    assert "0001/T1" in (tmp_path / "OVERVIEW.md").read_text(encoding="utf-8")


def test_add_task_duplicate_raises(tmp_path: Path) -> None:
    from openagents.spec.mutate import add_task, create_group

    create_group(
        specs_root=tmp_path, slug="a", title="A", issue=1, summary="人话 TL;DR", number="0001"
    )
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
    from openagents.spec.mutate import add_task

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
