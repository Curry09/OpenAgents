#!/usr/bin/env python3
"""一次性迁移：把 docs/rfcs/NNNN-*.md 转成 docs/specs/NNNN-slug/ spec 组。

Spec-0014/T6: 迁移脚本 + spec-driven skill + specs README + e2e

每份 RFC → 一个 spec 组：
- metadata.yaml：title / issue / slug
- tasks/T*.yaml：子任务表每行一个 Task（status 映射 implemented→done、blocked→pending；
  files / depends-on 解析；范围/验收标准从「子任务定义」块抽进 scope/acceptance）；version=1
- origin.md：整份 RFC 正文（只读归档，render 不读取）
- history/：初始为空（首次 amend 才落 v1）

依赖 model 层做 round-trip 写出（保证与 spec render/validate 同源、幂等）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 允许脚本直接运行时 import 顶层 openagents 包。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openagents.spec import model  # noqa: E402
from openagents.spec.model import Metadata, Task  # noqa: E402

# Spec-0014/T6：RFC 子任务状态 → Task status 枚举映射。
_STATUS_MAP = {
    "implemented": "done",
    "done": "done",
    "in-progress": "in-progress",
    "pending": "pending",
    "blocked": "pending",
    "abandoned": "abandoned",
}

# Spec-0014/T6：合法的 Task ID（T 后跟字母数字）。整 RFC 级依赖 RFC-NNNN 不匹配 → 丢弃。
_TASK_REF_RE = re.compile(r"^(?:\d{4}/)?T[0-9A-Za-z]+$")
_FILENAME_RE = re.compile(r"^(\d{4})-(.+)\.md$")


def migrate_rfc(*, rfc_path: Path, specs_root: Path) -> Path:
    """Migrate a single RFC markdown file into a spec group directory.

    Spec-0014/T6: 解析 RFC → 写 metadata.yaml + tasks/ + origin.md，返回组目录。
    """
    match = _FILENAME_RE.match(rfc_path.name)
    if match is None:
        raise ValueError(f"非 RFC 文件名（应为 NNNN-slug.md）：{rfc_path.name}")
    number, slug = match.group(1), match.group(2)
    text = rfc_path.read_text(encoding="utf-8")

    # 1. 头部元数据（优先级 / 标签 / issue / 标题）。
    header = _header_region(text=text)
    priority = _parse_priority(header=header)
    tags = _parse_tags(header=header)
    issue = _parse_issue(header=header)
    title = _parse_title(text=text, fallback=slug)

    # 2. 子任务表 → 行；子任务定义块 → 每 task 的范围/验收标准。
    rows = _parse_subtask_table(text=text)
    definitions = _parse_definitions(text=text)

    # 3. 组装并写出。
    group_dir = specs_root / f"{number}-{slug}"
    (group_dir / "tasks").mkdir(parents=True, exist_ok=True)
    model_metadata = Metadata(title=title, issue=issue, slug=slug)
    _write_metadata(metadata=model_metadata, path=group_dir / "metadata.yaml")
    (group_dir / "origin.md").write_text(text, encoding="utf-8")

    # 同组 files 必须互不重叠（D7 协同前提）。历史 RFC 中多个子任务常共用一个文件，
    # 迁移按表序把每个文件只留给「首个声明它」的 Task，后续 Task 丢弃该重复项。
    seen_files: set[str] = set()
    for row in rows:
        kept = [f for f in row["files"] if f not in seen_files]
        seen_files.update(kept)
        row["files"] = kept
        task = _row_to_task(
            row=row,
            priority=priority,
            tags=tags,
            definition=definitions.get(row["id"], {}),
        )
        model.dump_task(task=task, path=group_dir / "tasks" / f"{task.id}.yaml")

    return group_dir


def migrate_all(*, rfcs_dir: Path, specs_root: Path) -> list[Path]:
    """Migrate every NNNN-*.md under rfcs_dir; return created group dirs (sorted)."""
    created: list[Path] = []
    for rfc_path in sorted(rfcs_dir.glob("*.md")):
        if _FILENAME_RE.match(rfc_path.name) is None:
            continue  # 跳过 README.md 等非 RFC 文件
        created.append(migrate_rfc(rfc_path=rfc_path, specs_root=specs_root))
    return created


def _row_to_task(*, row: dict, priority: str, tags: list[str], definition: dict) -> Task:
    """单行 + 定义块 → Task（v1，history 留空）。"""
    return Task(
        id=row["id"],
        title=row["title"],
        status=_STATUS_MAP.get(row["status"], "pending"),
        priority=priority,
        tags=list(tags),
        depends_on=row["depends_on"],
        files=row["files"],
        version=1,
        scope=definition.get("scope", ""),
        acceptance=definition.get("acceptance", ""),
    )


def _header_region(*, text: str) -> str:
    """RFC 正文第一个 `## ` 标题之前的头部区域。"""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            break
        lines.append(line)
    return "\n".join(lines)


def _parse_priority(*, header: str) -> str:
    """`- **优先级**: P1` → P1；缺省 / 非法 → P1。"""
    match = re.search(r"\*\*优先级\*\*[:：]\s*(P[0-3])", header)
    return match.group(1) if match else "P1"


def _parse_tags(*, header: str) -> list[str]:
    """`- **标签**: `a`, `b`` → [a, b]；取该行内所有反引号标记。"""
    for line in header.splitlines():
        if "**标签**" in line:
            return re.findall(r"`([^`]+)`", line)
    return []


def _parse_issue(*, header: str) -> int:
    """从头部抽 issue 编号（issue-NN / issue #NN / #NN）；缺省 0。"""
    match = re.search(r"issue[-#\s]*?(\d+)", header, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _parse_title(*, text: str, fallback: str) -> str:
    """首个 `# RFC-NNNN: 标题` → 标题；解析不出用 fallback（slug）。"""
    for line in text.splitlines():
        if line.startswith("# "):
            heading = line[2:].strip()
            # 去掉 "RFC-NNNN:" / "RFC-NNNN：" 前缀。
            stripped = re.sub(r"^RFC-\d+\s*[:：]\s*", "", heading)
            return stripped or fallback
    return fallback


def _parse_subtask_table(*, text: str) -> list[dict]:
    """定位子任务表（表头含 ID/标题/依赖/涉及文件/状态），逐行解析为结构化 dict。"""
    lines = text.splitlines()
    header_idx = _find_table_header(lines=lines)
    if header_idx is None:
        return []

    rows: list[dict] = []
    # 数据行从表头 + 2（跳过分隔行 |----|）开始。
    for line in lines[header_idx + 2 :]:
        if not line.lstrip().startswith("|"):
            break  # 表结束
        cells = _split_row(line=line)
        if len(cells) < 5 or not _TASK_REF_RE.match(cells[0]):
            continue
        rows.append(
            {
                "id": cells[0],
                "title": cells[1],
                "depends_on": _parse_refs(cell=cells[2]),
                "files": _parse_files(cell=cells[3]),
                "status": cells[4].strip().lower(),
            }
        )
    return rows


def _find_table_header(*, lines: list[str]) -> int | None:
    """找到子任务表头行的下标：含 ID 且含 状态 与 涉及文件。"""
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("|") and "ID" in line and "状态" in line and "涉及文件" in line:
            return idx
    return None


def _split_row(*, line: str) -> list[str]:
    """切分 Markdown 表行为去空白的单元格列表。"""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _parse_refs(*, cell: str) -> list[str]:
    """依赖单元格 → Task 引用列表；丢弃 `-` 与整 RFC 级 `RFC-NNNN`。"""
    tokens = re.split(r"[、,，\s]+", cell.strip())
    return [tok for tok in tokens if _TASK_REF_RE.match(tok)]


def _parse_files(*, cell: str) -> list[str]:
    """涉及文件单元格 → 路径列表；去反引号、去（新增/改）等括注。"""
    tokens = re.split(r"[、,，]", cell.strip())
    files: list[str] = []
    for tok in tokens:
        cleaned = tok.replace("`", "").strip()
        # 去掉末尾的 （新增）/（改） 等中英文括注。
        cleaned = re.sub(r"[（(][^）)]*[）)]\s*$", "", cleaned).strip()
        if cleaned and cleaned != "-":
            files.append(cleaned)
    return files


def _parse_definitions(*, text: str) -> dict[str, dict]:
    """解析「子任务定义」块：每个 `**TX: ...**` → {scope, acceptance}。"""
    lines = text.splitlines()
    blocks: dict[str, dict] = {}
    current_id: str | None = None
    current_label: str | None = None
    buffer: dict[str, list[str]] = {}

    def _flush() -> None:
        if current_id is not None:
            blocks[current_id] = {
                "scope": " ".join(buffer.get("scope", [])).strip(),
                "acceptance": " ".join(buffer.get("acceptance", [])).strip(),
            }

    for line in lines:
        head = re.match(r"^\*\*(T[0-9A-Za-z]+)[:：]", line.strip())
        if head:
            _flush()
            current_id = head.group(1)
            current_label = None
            buffer = {}
            continue
        if current_id is None:
            continue
        # 命中范围 / 验收标准 bullet，开始累积其值。
        scope_m = re.match(r"^-\s*\*\*范围\*\*[:：]\s*(.*)$", line.strip())
        acc_m = re.match(r"^-\s*\*\*验收标准\*\*[:：]\s*(.*)$", line.strip())
        other_bullet = re.match(r"^-\s*\*\*", line.strip())
        if scope_m:
            current_label = "scope"
            buffer.setdefault("scope", []).append(scope_m.group(1))
        elif acc_m:
            current_label = "acceptance"
            buffer.setdefault("acceptance", []).append(acc_m.group(1))
        elif other_bullet:
            current_label = None  # 其它 bullet（涉及文件/依赖）不抽
        elif current_label and line.strip():
            buffer[current_label].append(line.strip())
        elif not line.strip():
            current_label = None
    _flush()
    return blocks


def _write_metadata(*, metadata: Metadata, path: Path) -> None:
    """写 metadata.yaml。issue #53：委托 model.dump_metadata（固定键序的单一来源）。"""
    model.dump_metadata(metadata=metadata, path=path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rfcs-dir", type=Path, default=Path("docs/rfcs"))
    parser.add_argument("--specs-root", type=Path, default=Path("docs/specs"))
    args = parser.parse_args()

    created = migrate_all(rfcs_dir=args.rfcs_dir, specs_root=args.specs_root)
    for group_dir in created:
        print(f"✓ 迁移 {group_dir}")
    print(f"共迁移 {len(created)} 个 RFC → spec 组")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
