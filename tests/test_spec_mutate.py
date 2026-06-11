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
