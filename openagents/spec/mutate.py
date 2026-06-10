"""spec amend / abandon：改快照 + 追加历史 + 自动 render。

Spec-0014/T4: spec amend / abandon（历史追加 + 自动 render）

- amend：把**当前版**对象 append 进 history/T*.yaml，再把 tasks/T*.yaml 覆盖为新版
  （version+1、updated=今天、change-reason=reason），最后自动 render（决策 D6）。
- abandon：把当前 task append 进 history（末态 status=abandoned）→ 从 tasks/ 删除 → render。

历史只增不改（决策 D6）；amend 不存在的 task 直接报错且不破坏任何文件。
不感知 git / GitHub（理念 10 解耦）。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Task
from openagents.spec.render import write_overview


def amend(*, specs_root: Path, group: str, task_id: str, reason: str) -> Task:
    """Amend a Task: snapshot current version into history, write a bumped new version.

    Spec-0014/T4: 当前版 → history append；tasks 覆盖为 version+1 新版；自动 render。
    返回新版 Task。task 不存在则抛 FileNotFoundError，不改任何文件。
    """
    group_dir = _group_dir(specs_root=specs_root, group=group)
    task_path = group_dir / "tasks" / f"{task_id}.yaml"

    # 1. 读当前版（不存在则报错，先于任何写入）。
    current = _load_current(task_path=task_path, group=group, task_id=task_id)

    # 2. 当前版 append 进历史（追加式，只增不改）。
    _append_history(group_dir=group_dir, task_id=task_id, snapshot=current)

    # 3. tasks 覆盖为新版：version+1、updated=今天、change-reason=reason。
    new_version = replace(
        current,
        version=current.version + 1,
        updated=_today(),
        change_reason=reason,
    )
    model.dump_task(task=new_version, path=task_path)

    # 4. 自动 render（OVERVIEW 永不过期）。
    write_overview(specs_root=specs_root)
    return new_version


def abandon(*, specs_root: Path, group: str, task_id: str, reason: str) -> None:
    """Abandon a Task: snapshot it into history as abandoned, remove from snapshot.

    Spec-0014/T4: 当前 task → history append（末态 abandoned）；删 tasks/T*.yaml；自动 render。
    task 不存在则抛 FileNotFoundError，不改任何文件。
    """
    group_dir = _group_dir(specs_root=specs_root, group=group)
    task_path = group_dir / "tasks" / f"{task_id}.yaml"

    # 1. 读当前版（不存在则报错）。
    current = _load_current(task_path=task_path, group=group, task_id=task_id)

    # 2. 以 abandoned 末态 append 进历史。
    tombstone = replace(current, status="abandoned", updated=_today(), change_reason=reason)
    _append_history(group_dir=group_dir, task_id=task_id, snapshot=tombstone)

    # 3. 从快照删除（abandoned 只活在历史，决策 D2）。
    task_path.unlink()

    # 4. 自动 render。
    write_overview(specs_root=specs_root)


def _load_current(*, task_path: Path, group: str, task_id: str) -> Task:
    """读当前版 Task；文件不存在抛 FileNotFoundError（含限定 ID 便于定位）。"""
    if not task_path.is_file():
        qid = model.qualified_id(group=group, task_id=task_id)
        raise FileNotFoundError(f"Task 不存在：{qid}（{task_path}）")
    return model.task_from_mapping(data=model._yaml.load(task_path))


def _append_history(*, group_dir: Path, task_id: str, snapshot: Task) -> None:
    """把一个 Task 快照追加进 history/T*.yaml（保留已有版本，只增不改）。"""
    history_path = group_dir / "history" / f"{task_id}.yaml"
    existing: list[Task] = []
    if history_path.is_file():
        loaded = model._yaml.load(history_path) or []
        existing = [model.task_from_mapping(data=item) for item in loaded]
    model.dump_history(versions=[*existing, snapshot], path=history_path)


def _group_dir(*, specs_root: Path, group: str) -> Path:
    """按编号或目录名解析组目录；找不到抛 FileNotFoundError。"""
    # 完整目录名直接命中。
    direct = specs_root / group
    if direct.is_dir():
        return direct
    # 否则按 NNNN 前缀匹配 NNNN-slug/。
    for candidate in sorted(specs_root.iterdir()) if specs_root.is_dir() else []:
        if candidate.is_dir() and candidate.name[:4] == group:
            return candidate
    raise FileNotFoundError(f"spec 组不存在：{group}（在 {specs_root} 下）")


def _today() -> str:
    """今天的 ISO 日期串（updated 字段）。"""
    return date.today().isoformat()
