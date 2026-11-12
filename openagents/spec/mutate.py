"""Create Spec groups, add tasks, and remove abandoned tasks from the snapshot."""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import ArchitectureDecision, Group, Metadata, Task, VerificationPlan
from openagents.spec.render import write_overview
from openagents.spec.reservation import reserve_number


def create_group(
    *, specs_root: Path, slug: str, title: str, issue: int, summary: str, number: str | None
) -> Path:
    """Scaffold a new spec group markdown file, return its path; auto-render.

    Share Git working area with a pre-set number at a remote atom; local working area will follow the next number.
    Spec-0015:summary is the mandatory entry (personal TL; DR front to the time of the builder).
    """
    group_number = reserve_number(specs_root=specs_root, issue=issue, slug=slug, number=number)
    path = model.group_path(specs_root=specs_root, number=group_number, slug=slug)
    if path.exists():
        raise FileExistsError(f"Spec group already exists:{path}")
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
    write_overview(specs_root=specs_root)  # OWERVIEW Never expire.
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

    Group does not exist for FileNotFundError;task id already exists for FileExistsError.
    """
    path = _group_path(specs_root=specs_root, group=group)
    grp = model.load_group(path=path)
    if any(task.id == task_id for task in grp.tasks):
        qid = model.qualified_id(group=grp.number, task_id=task_id)
        raise FileExistsError(f"Task Exists:{qid}(direct edit group markdown instead of task)")
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

    History is given to the git (decision D3). The removed version is still available in the git history. Task does not throw FileNootFoundError.
    """
    path = _group_path(specs_root=specs_root, group=group)
    grp = model.load_group(path=path)
    remaining = [task for task in grp.tasks if task.id != task_id]
    if len(remaining) == len(grp.tasks):
        qid = model.qualified_id(group=grp.number, task_id=task_id)
        raise FileNotFoundError(f"Task does not exist:{qid}（{path}）")
    grp.tasks[:] = remaining
    model.dump_group(group=grp, path=path)
    write_overview(specs_root=specs_root)


def _group_path(*, specs_root: Path, group: str) -> Path:
    """Parsing group markdown files by number (NNNNN) or filename (NNNN-slug [.md]; FileNotFundError could not be found."""
    # Direct file hit.
    for candidate in (specs_root / group, specs_root / f"{group}.md"):
        if candidate.is_file() and model._is_group_file(name=candidate.name):
            return candidate
    # Press NNNN prefix.
    if specs_root.is_dir():
        for md_path in sorted(specs_root.glob("*.md")):
            if model._is_group_file(name=md_path.name) and md_path.name[:4] == group:
                return md_path
    raise FileNotFoundError(
        f"Spec group does not exist:{group}(In the middle of the day) {specs_root} Down)"
    )
