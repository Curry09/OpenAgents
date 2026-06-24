#!/usr/bin/env python3
"""一次性迁移：docs/specs/NNNN-slug/（YAML 文件夹）→ docs/specs/NNNN-slug.md（markdown 单文件）。

2026-06-24 spec-markdown-form：读旧 metadata.yaml + tasks/T*.yaml（含 prose），构造 Group，
用新的 model.render_group 写出单 markdown 文件，然后删除旧组目录。

per-task history/ 与 origin.md（旧 RFC 原文归档）不再纳入新格式——它们完整保留在 git 历史里
（决策 D3：历史交给 git + dated 设计文档）。run 后请 `spec validate` / `spec render` 核对。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from ruamel.yaml import YAML

from openagents.spec.model import Group, Metadata, RelatesTo, Task, group_path, render_group

_yaml = YAML()
_SPECS = Path("docs/specs")


def _load_old_task(*, path: Path) -> Task:
    raw = _yaml.load(path) or {}
    relates = [
        RelatesTo(ref=str(i.get("ref", "")), type=str(i.get("type", "")))
        for i in (raw.get("relates-to") or [])
    ]

    def s(value: object) -> str:
        return "" if value is None else str(value)

    def lst(value: object) -> list[str]:
        return [] if value is None else [str(x) for x in value]

    return Task(
        id=s(raw.get("id")),
        title=s(raw.get("title")),
        status=s(raw.get("status")),
        priority=s(raw.get("priority")),
        tags=lst(raw.get("tags")),
        depends_on=lst(raw.get("depends-on")),
        relates_to=relates,
        parallel=bool(raw.get("parallel", False)),
        files=lst(raw.get("files")),
        summary=s(raw.get("summary")),
        motivation=s(raw.get("motivation")),
        scope=s(raw.get("scope")),
        design=s(raw.get("design")),
        interface=s(raw.get("interface")),
        tradeoffs=s(raw.get("tradeoffs")),
        acceptance=s(raw.get("acceptance")),
        tests=s(raw.get("tests")),
        references=s(raw.get("references")),
        open_questions=s(raw.get("open-questions")),
    )


def _migrate_group(*, group_dir: Path) -> Path:
    number = group_dir.name[:4]
    slug = group_dir.name[5:]
    meta_raw = _yaml.load(group_dir / "metadata.yaml") or {}
    metadata = Metadata(
        title=str(meta_raw.get("title", "")),
        issue=int(meta_raw.get("issue", 0)),
        slug=str(meta_raw.get("slug", slug)),
        summary=str(meta_raw.get("summary", "")),
    )
    tasks_dir = group_dir / "tasks"
    tasks = (
        [_load_old_task(path=task_path) for task_path in sorted(tasks_dir.glob("*.yaml"))]
        if tasks_dir.is_dir()
        else []
    )

    group = Group(number=number, metadata=metadata, tasks=tasks, history={})
    out = group_path(specs_root=_SPECS, number=number, slug=slug)
    out.write_text(render_group(group=group), encoding="utf-8")
    shutil.rmtree(group_dir)
    return out


def main() -> int:
    if not _SPECS.is_dir():
        print(f"找不到 {_SPECS}", file=sys.stderr)
        return 1
    group_dirs = [
        child
        for child in sorted(_SPECS.iterdir())
        if child.is_dir()
        and len(child.name) > 5
        and child.name[:4].isdigit()
        and child.name[4] == "-"
    ]
    for group_dir in group_dirs:
        out = _migrate_group(group_dir=group_dir)
        print(f"✓ {group_dir.name}/ → {out.name}")
    print(f"共迁移 {len(group_dirs)} 个组。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
