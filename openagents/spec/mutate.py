"""spec new / add-task / abandon：在组 markdown 文件上增改 Task + 自动 render。

2026-06-24 spec-markdown-form（取代 Spec-0014/T4）：
- new：新建 `docs/specs/NNNN-slug.md`（frontmatter + 空 tasks），自动 render。
- add-task：加载组 → 追加一个 Task → 写回 → 自动 render。
- abandon：加载组 → 从 tasks 移除该 Task → 写回 → 自动 render。

历史机制退役（决策 D3）：不再有 `spec amend`（直接编辑组 markdown 即可），版本演化由 git
历史承载，「为什么这么演变」由 dated 设计文档承载。不感知 git / GitHub（理念 10 解耦）。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import ArchitectureDecision, Group, Metadata, Task, VerificationPlan
from openagents.spec.render import write_overview


def create_group(
    *, specs_root: Path, slug: str, title: str, issue: int, summary: str, number: str | None
) -> Path:
    """Scaffold a new spec group markdown file, return its path; auto-render.

    number 缺省取本地下一号；文件已存在抛 FileExistsError，不动磁盘。
    Spec-0015：summary 为必填入参（人话 TL;DR 前置到建组当下）。
    """
    group_number = number or model.next_number(specs_root=specs_root)
    path = model.group_path(specs_root=specs_root, number=group_number, slug=slug)
    if path.exists():
        raise FileExistsError(f"spec 组已存在：{path}")
    group = Group(
        number=group_number,
        metadata=Metadata(
            title=title,
            issue=issue,
            slug=slug,
            summary=summary,
            architecture=ArchitectureDecision(),
            verification=VerificationPlan(),
        ),
        tasks=[],
        history={},
    )
    model.dump_group(group=group, path=path)
    write_overview(specs_root=specs_root)  # OVERVIEW 永不过期。
    return path


def add_task(
    *,
    specs_root: Path,
    group: str,
    task_id: str,
    title: str,
    priority: str,
    status: str,
    files: list[str],
    depends_on: list[str],
    scope: str,
    acceptance: str,
) -> Task:
    """Add a new Task to an existing group markdown file, return it; auto-render.

    组不存在抛 FileNotFoundError；task id 已存在抛 FileExistsError。
    """
    path = _group_path(specs_root=specs_root, group=group)
    grp = model.load_group(path=path)
    if any(task.id == task_id for task in grp.tasks):
        qid = model.qualified_id(group=grp.number, task_id=task_id)
        raise FileExistsError(f"Task 已存在：{qid}（直接编辑组 markdown 改既有 task）")
    task = Task(
        id=task_id,
        title=title,
        status=status,
        priority=priority,
        files=list(files),
        depends_on=list(depends_on),
        scope=scope,
        acceptance=acceptance,
    )
    grp.tasks.append(task)
    model.dump_group(group=grp, path=path)
    write_overview(specs_root=specs_root)
    return task


def abandon(*, specs_root: Path, group: str, task_id: str, reason: str) -> None:
    """Abandon a Task: remove it from the group snapshot; auto-render.

    历史交给 git（决策 D3）：被移除的版本仍在 git 历史里可查。task 不存在抛 FileNotFoundError。
    """
    path = _group_path(specs_root=specs_root, group=group)
    grp = model.load_group(path=path)
    remaining = [task for task in grp.tasks if task.id != task_id]
    if len(remaining) == len(grp.tasks):
        qid = model.qualified_id(group=grp.number, task_id=task_id)
        raise FileNotFoundError(f"Task 不存在：{qid}（{path}）")
    grp.tasks[:] = remaining
    model.dump_group(group=grp, path=path)
    write_overview(specs_root=specs_root)


def _group_path(*, specs_root: Path, group: str) -> Path:
    """按编号（NNNN）或文件名（NNNN-slug[.md]）解析组 markdown 文件；找不到抛 FileNotFoundError。"""
    # 直接文件名命中。
    for candidate in (specs_root / group, specs_root / f"{group}.md"):
        if candidate.is_file() and model._is_group_file(name=candidate.name):
            return candidate
    # 按 NNNN 前缀匹配。
    if specs_root.is_dir():
        for md_path in sorted(specs_root.glob("*.md")):
            if model._is_group_file(name=md_path.name) and md_path.name[:4] == group:
                return md_path
    raise FileNotFoundError(f"spec 组不存在：{group}（在 {specs_root} 下）")
