"""spec 数据层：Task / Metadata / Group 模型与 **markdown 单文件** round-trip 读写。

2026-06-24 spec-markdown-form（取代 Spec-0014/T1 的 YAML 文件夹形态）：
一个 spec 组 = 一个 markdown 文件 `docs/specs/NNNN-slug.md`：
- **YAML frontmatter**（机器读）：组元数据 number/title/issue/slug + tasks 列表（结构化字段）。
- **Markdown 正文**（人/agent 读）：每个 Task 一个 `## <id> · <title>` 小节，内含 `### <Prose>` 子节。

只懂 docs/specs/ 源数据结构的纯模块（理念 10 解耦），不感知 git / GitHub。
保留 Task/Metadata/Group 数据类与 validate/render 消费的对象形状不变（决策 D2）；
per-task 版本历史机制退役（决策 D3），历史交给 git + dated 设计文档，Group.history 恒为空。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

# 统一的 YAML round-trip 实例（用于 frontmatter）。
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096
_yaml.indent(mapping=2, sequence=4, offset=2)

# frontmatter 里每个 Task 的结构化字段顺序（yaml_key, attr）。dump 一律按此序，键序稳定。
# 注意：version/lineage/change-reason 等随历史机制退役（决策 D3），不再进 frontmatter。
_TASK_FM_ORDER: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("title", "title"),
    ("status", "status"),
    ("priority", "priority"),
    ("tags", "tags"),
    ("depends-on", "depends_on"),
    ("relates-to", "relates_to"),
    ("parallel", "parallel"),
    ("files", "files"),
)

# 正文 prose 小节：(markdown 标题, Task 属性)，dump 按此序，空 prose 省略。
_PROSE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Summary", "summary"),
    ("Motivation", "motivation"),
    ("Scope", "scope"),
    ("Design", "design"),
    ("Interface", "interface"),
    ("Tradeoffs", "tradeoffs"),
    ("Acceptance", "acceptance"),
    ("Tests", "tests"),
    ("References", "references"),
    ("Open-Questions", "open_questions"),
)
_HEADING_TO_ATTR = {heading: attr for heading, attr in _PROSE_SECTIONS}

# 正文切分用：Task 小节标题 `## T1 · ...`；prose 子节标题 `### Design`。
_TASK_HEADING_RE = re.compile(r"^##\s+(T[0-9A-Za-z]+)\b")
_PROSE_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")


@dataclass(frozen=True)
class RelatesTo:
    """非阻塞的跨 feature 关联（render 里画虚线）。"""

    # 跨组限定 ID，如 "0012/T2"
    ref: str
    # 关联类型 extends | supersedes | note
    type: str


@dataclass
class Task:
    """A single spec Task —— 快照的基本单元，与当前活代码一一对应。

    结构化字段（status/priority/depends-on/files…）放 frontmatter、可机器校验；
    prose 字段（summary/design/interface…）放 markdown 正文。

    version/lineage 字段保留在数据类里（带默认值）以最小化 render/validate 改动（决策 D2），
    但历史机制退役后不再由 frontmatter 写入、Group.history 恒空。
    """

    # ── 身份与状态 ──
    id: str
    title: str
    status: str
    priority: str
    tags: list[str] = field(default_factory=list)
    # ── 关系 ──
    depends_on: list[str] = field(default_factory=list)
    relates_to: list[RelatesTo] = field(default_factory=list)
    parallel: bool = False
    files: list[str] = field(default_factory=list)
    # ── 演化 / 血缘（保留默认值，决策 D3 后不活跃）──
    version: int = 1
    updated: str = ""
    change_reason: str = ""
    supersedes: list[str] = field(default_factory=list)
    split_from: str | None = None
    merged_from: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    # ── 设计内容（prose，放正文）──
    summary: str = ""
    motivation: str = ""
    scope: str = ""
    design: str = ""
    interface: str = ""
    tradeoffs: str = ""
    acceptance: str = ""
    tests: str = ""
    references: str = ""
    open_questions: str = ""


@dataclass(frozen=True)
class Metadata:
    """组级元数据（一个 spec 组 = 一个 issue/feature）。"""

    title: str
    issue: int
    slug: str
    # Spec-0015：组级人话 TL;DR（整个 feature 的「是啥/为什么/产出什么」）。
    # 默认空串兼容旧调用点；非空由 validate 的 _summary_checks 强制。
    summary: str = ""


@dataclass(frozen=True)
class Group:
    """一个 spec 组的全部源数据。markdown 形态下 history 恒为空（决策 D3）。"""

    # 四位编号 "0009"（与旧 RFC 编号 1:1 兼容）
    number: str
    metadata: Metadata
    # 当前版 Task 快照（status 含 done，做完不离开快照）
    tasks: list[Task]
    # 退役：保留字段让 render/validate 无需改动，恒为空 dict
    history: dict[str, list[Task]] = field(default_factory=dict)


def qualified_id(*, group: str, task_id: str) -> str:
    """Build a cross-group qualified task id like "0009/T3"."""
    return f"{group}/{task_id}"


def group_path(*, specs_root: Path, number: str, slug: str) -> Path:
    """组 markdown 文件路径 docs/specs/NNNN-slug.md。"""
    return specs_root / f"{number}-{slug}.md"


def load_group(*, path: Path) -> Group:
    """Load one spec group from a markdown file (frontmatter + body).

    frontmatter 提供组元数据与各 Task 结构化字段；正文按 `## <id>` 切出各 Task 的 prose。
    """
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text=text)
    number = str(meta.get("number") or path.name[:4]).zfill(4)
    metadata = Metadata(
        title=str(meta.get("title", "")),
        issue=int(meta.get("issue", 0)),
        slug=str(meta.get("slug", "")),
        summary=str(meta.get("summary", "")),
    )

    prose_by_task = _parse_body(body=body)
    tasks: list[Task] = []
    for raw in meta.get("tasks") or []:
        task = task_from_mapping(data=raw)
        # 用正文 prose 覆盖（frontmatter 不含 prose）。
        for attr, value in prose_by_task.get(task.id, {}).items():
            setattr(task, attr, value)
        tasks.append(task)

    return Group(number=number, metadata=metadata, tasks=tasks, history={})


def load_all(*, specs_root: Path) -> list[Group]:
    """Load every spec group markdown file under specs_root (sorted by number).

    只认组文件 `NNNN-slug.md`（slug 以字母起，排除 dated 设计文档 `YYYY-MM-DD-*.md`
    与 OVERVIEW.md / ARCHITECTURE.md / README.md）；空仓库返回 []。
    """
    if not specs_root.is_dir():
        return []
    groups: list[Group] = []
    for md_path in sorted(specs_root.glob("*.md")):
        if _is_group_file(name=md_path.name):
            groups.append(load_group(path=md_path))
    return groups


def dump_group(*, group: Group, path: Path) -> None:
    """Write a Group to a markdown file (frontmatter + body), deterministically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_group(group=group), encoding="utf-8")


def render_group(*, group: Group) -> str:
    """Serialize a Group to markdown text (frontmatter + body). Pure."""
    fm = CommentedMap()
    fm["number"] = DoubleQuotedScalarString(group.number)
    fm["title"] = group.metadata.title
    fm["issue"] = group.metadata.issue
    fm["slug"] = group.metadata.slug
    fm["summary"] = group.metadata.summary
    fm["tasks"] = [_task_frontmatter(task=task) for task in group.tasks]

    buf = StringIO()
    _yaml.dump(fm, buf)
    fm_text = buf.getvalue()

    title = group.metadata.title or group.metadata.slug
    head = (
        f"---\n{fm_text}---\n\n"
        f"# {group.number} · {title}\n\n"
        "<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据，正文为各 Task 设计 prose。 -->\n"
    )
    body = _render_body(group=group)
    return head + ("\n" + body if body else "") + "\n"


def next_number(*, specs_root: Path) -> str:
    """Return the next free 4-digit group number (max existing + 1, "0001" if none)."""
    highest = 0
    for group in load_all(specs_root=specs_root):
        try:
            highest = max(highest, int(group.number))
        except ValueError:
            continue
    return f"{highest + 1:04d}"


def task_from_mapping(*, data: object) -> Task:
    """Build a Task from a frontmatter task mapping (structured fields only)."""
    raw = data or {}
    relates = [
        RelatesTo(ref=str(item.get("ref", "")), type=str(item.get("type", "")))
        for item in (raw.get("relates-to") or [])
    ]
    return Task(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        status=str(raw.get("status", "")),
        priority=str(raw.get("priority", "")),
        tags=_str_list(value=raw.get("tags")),
        depends_on=_str_list(value=raw.get("depends-on")),
        relates_to=relates,
        parallel=bool(raw.get("parallel", False)),
        files=_str_list(value=raw.get("files")),
    )


def _task_frontmatter(*, task: Task) -> CommentedMap:
    """Task → frontmatter CommentedMap（仅结构化字段，固定键序）。"""
    out = CommentedMap()
    for yaml_key, attr in _TASK_FM_ORDER:
        value = getattr(task, attr)
        if attr == "relates_to":
            out[yaml_key] = [
                CommentedMap([("ref", item.ref), ("type", item.type)]) for item in value
            ]
        else:
            out[yaml_key] = value
    return out


def _render_body(*, group: Group) -> str:
    """各 Task 的 `## <id> · <title>` 小节 + 非空 prose 子节。"""
    chunks: list[str] = []
    for task in group.tasks:
        lines = [f"## {task.id} · {task.title}"]
        for heading, attr in _PROSE_SECTIONS:
            text = getattr(task, attr)
            if text:
                lines.append(f"\n### {heading}\n\n{text.rstrip()}")
        chunks.append("\n".join(lines) + "\n")
    return "\n".join(chunks)


def _split_frontmatter(*, text: str) -> tuple[dict, str]:
    """拆出 YAML frontmatter（首段 --- … ---）与其后正文。无 frontmatter 则返回 ({}, text)。"""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    meta = _yaml.load(fm_text) if fm_text.strip() else None
    return (meta or {}), body


def _parse_body(*, body: str) -> dict[str, dict[str, str]]:
    """正文 → {task_id: {prose_attr: text}}。按 `## <id>` 切 Task，按 `### <Prose>` 切子节。"""
    result: dict[str, dict[str, str]] = {}
    current_task: str | None = None
    current_attr: str | None = None
    buffer: list[str] = []

    def _flush() -> None:
        if current_task is not None and current_attr is not None:
            text = "\n".join(buffer).strip("\n")
            if text.strip():
                result.setdefault(current_task, {})[current_attr] = text

    for line in body.split("\n"):
        task_match = _TASK_HEADING_RE.match(line)
        if task_match:
            _flush()
            current_task = task_match.group(1)
            current_attr = None
            buffer = []
            result.setdefault(current_task, {})
            continue
        prose_match = _PROSE_HEADING_RE.match(line)
        if prose_match and prose_match.group(1) in _HEADING_TO_ATTR:
            _flush()
            current_attr = _HEADING_TO_ATTR[prose_match.group(1)]
            buffer = []
            continue
        buffer.append(line)
    _flush()
    return result


def _is_group_file(*, name: str) -> bool:
    """文件名是否组文件 `NNNN-slug.md`（四位数字 + '-' + 字母起的 slug）。

    排除 dated 设计文档 `YYYY-MM-DD-*.md`（第 6 位是数字）与生成物/README。
    """
    return bool(re.match(r"^\d{4}-[A-Za-z][^/]*\.md$", name))


def _str_list(*, value: object) -> list[str]:
    """列表字段统一成 list[str]；None → []。"""
    if value is None:
        return []
    return [str(item) for item in value]
