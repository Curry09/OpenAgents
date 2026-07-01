"""spec 数据层：Task / Overview / Metadata / Group 模型与 **markdown 单文件** round-trip 读写。

issue #69 rust-RFC 形态（总览先行 + 单 spec 自包含）：
一个 spec 组 = 一个 markdown 文件 `docs/specs/NNNN-slug.md`：
- **YAML frontmatter**（机器读）：组元数据 number/title/issue/slug/summary + tasks 列表
  （结构化字段 + scope/acceptance；`files` = 单一 writer 所有权声明，为 issue #71 留源）。
- **Markdown 正文**（人/agent 读）：组级 rust-RFC 9 段总览（Summary…Future possibilities），
  feature 全貌自包含地讲一遍，DAG + 文件分配收进 Reference-level；不再有 per-Task 小节。

只懂 docs/specs/ 源数据结构的纯模块（理念 10 解耦），不感知 git / GitHub。
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
# issue #69：scope/acceptance 由正文 prose 改为 frontmatter 短字段（Task 退化成工作分解行，
# 重 prose 上移到组级 Overview）。
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
    ("scope", "scope"),
    ("acceptance", "acceptance"),
)

# issue #69：组级正文 = rust-RFC 9 段总览（markdown 标题, Overview 属性），dump 按此序。
# 一个 spec 单独可读、总览先行：feature 全貌在这 9 段讲一遍，Task 只是 frontmatter 工作分解行。
_OVERVIEW_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Summary", "summary"),
    ("Motivation", "motivation"),
    ("Guide-level explanation", "guide_level"),
    ("Reference-level explanation", "reference_level"),
    ("Drawbacks", "drawbacks"),
    ("Rationale and alternatives", "rationale_alternatives"),
    ("Prior art", "prior_art"),
    ("Unresolved questions", "unresolved_questions"),
    ("Future possibilities", "future_possibilities"),
)
_SECTION_BY_HEADING = {heading: attr for heading, attr in _OVERVIEW_SECTIONS}

# 正文切分用：组级段标题 `## Summary` / `## Reference-level explanation` …
_SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")

# spec new 脚手架占位：非空（让段标题成型），但 _strip_placeholder 归一为空串。
_PLACEHOLDER = "<!-- 待填 -->"


@dataclass(frozen=True)
class RelatesTo:
    """非阻塞的跨 feature 关联（render 里画虚线）。"""

    # 跨组限定 ID，如 "0012/T2"
    ref: str
    # 关联类型 extends | supersedes | note
    type: str


@dataclass
class Task:
    """A single spec Task —— DAG + 文件分配的工作分解行（issue #69 后退化为结构化为主）。

    结构化字段（status/priority/depends-on/files…）放 frontmatter、可机器校验；
    issue #69 起，feature 设计叙述上移到组级 Overview，Task 只留两个一行短 prose
    （scope/acceptance），且二者也放 frontmatter——`files` 是单一 writer 所有权声明
    （理念 6 / issue #71 运行期 owner 检查的结构化源）。

    version/lineage 字段保留在数据类里（带默认值）以最小化 render 改动（决策 D2），
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
    # ── 工作分解短 prose（进 frontmatter；重设计叙述见组级 Overview）──
    scope: str = ""
    acceptance: str = ""


@dataclass(frozen=True)
class Overview:
    """组级 rust-RFC 9 段总览（issue #69）—— feature 全貌的自包含叙述，放 markdown 正文。

    单 spec 自包含：读完这 9 段即理解本 feature，无需打开其它 spec；DAG + 文件分配
    收进 reference_level。字段名与 `_OVERVIEW_SECTIONS` 的 attr 一一对应。
    """

    summary: str = ""
    motivation: str = ""
    guide_level: str = ""
    reference_level: str = ""
    drawbacks: str = ""
    rationale_alternatives: str = ""
    prior_art: str = ""
    unresolved_questions: str = ""
    future_possibilities: str = ""


@dataclass(frozen=True)
class E2EPlan:
    """Spec-0040/T1：组级 e2e 粗规划——RFC 阶段声明的成果验证意图，代码之后据此定稿 runbook。

    承载「要不要验、验什么」：`form` 声明执行形态（ui/api/cli/backend，见 schema.E2E_FORM_VALUES），
    `intent` 是一句话意图（RFC 闸批准后冻结，tautology guard 防线①的支点），`acceptance` 是若干条
    可验证的验收行为。整块可选（Metadata.e2e 默认 None）——非交互 PR 不声明即零回归。
    """

    form: str
    intent: str = ""
    acceptance: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Metadata:
    """组级元数据（一个 spec 组 = 一个 issue/feature）。"""

    title: str
    issue: int
    slug: str
    # Spec-0015：组级人话 TL;DR（整个 feature 的「是啥/为什么/产出什么」）。
    # 默认空串兼容旧调用点；非空由 validate 的 _summary_checks 强制。
    summary: str = ""
    # Spec-0040/T1：组级 e2e 粗规划（可选）。None = 未声明（既有 spec 零回归）；非 None 时由
    # validate._e2e_checks 强制 form 合法 / intent 非空 / acceptance≥1。
    e2e: E2EPlan | None = None


@dataclass(frozen=True)
class Group:
    """一个 spec 组的全部源数据。markdown 形态下 history 恒为空（决策 D3）。"""

    # 四位编号 "0009"（与旧 RFC 编号 1:1 兼容）
    number: str
    metadata: Metadata
    # 当前版 Task 快照（status 含 done，做完不离开快照）
    tasks: list[Task]
    # issue #69：组级 rust-RFC 9 段总览（feature 全貌，放正文）
    overview: Overview = field(default_factory=Overview)
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

    frontmatter 提供组元数据与各 Task 结构化字段；正文按 `## <rust 段名>` 切出组级
    Overview 9 段（issue #69）。
    """
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text=text)
    number = str(meta.get("number") or path.name[:4]).zfill(4)
    metadata = Metadata(
        title=str(meta.get("title", "")),
        issue=int(meta.get("issue", 0)),
        slug=str(meta.get("slug", "")),
        summary=str(meta.get("summary", "")),
        e2e=e2e_from_mapping(data=meta.get("e2e")),  # Spec-0040/T1：无 e2e 块 → None。
    )

    overview = _parse_body(body=body)
    tasks = [task_from_mapping(data=raw) for raw in meta.get("tasks") or []]

    return Group(number=number, metadata=metadata, tasks=tasks, overview=overview, history={})


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
    # Spec-0040/T1：e2e 粗规划仅在声明时写入 frontmatter（None 即整块不出现，保持既有 spec 逐字节
    # 不变、零回归）。夹在 summary 之后、tasks 之前，与其组级元数据身份一致。
    if group.metadata.e2e is not None:
        fm["e2e"] = _e2e_frontmatter(e2e=group.metadata.e2e)
    fm["tasks"] = [_task_frontmatter(task=task) for task in group.tasks]

    buf = StringIO()
    _yaml.dump(fm, buf)
    fm_text = buf.getvalue()

    title = group.metadata.title or group.metadata.slug
    head = (
        f"---\n{fm_text}---\n\n"
        f"# {group.number} · {title}\n\n"
        "<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），"
        "正文为组级 rust-RFC 9 段总览。 -->\n"
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
        scope=str(raw.get("scope", "")),
        acceptance=str(raw.get("acceptance", "")),
    )


def e2e_from_mapping(*, data: object) -> E2EPlan | None:
    """Spec-0040/T1：frontmatter 的 e2e 映射 → E2EPlan；缺失（None）返回 None（既有 spec 零回归）。

    宽松归一化（与 task_from_mapping 同风格）：form/intent 转 str、acceptance 转 list[str]；
    合法性（form 枚举 / intent 非空 / acceptance≥1）交给 validate._e2e_checks，本函数不判空。
    """
    if data is None:
        return None
    raw = data or {}
    return E2EPlan(
        form=str(raw.get("form", "")),
        intent=str(raw.get("intent", "")),
        acceptance=_str_list(value=raw.get("acceptance")),
    )


def _e2e_frontmatter(*, e2e: E2EPlan) -> CommentedMap:
    """E2EPlan → frontmatter CommentedMap（固定键序 form/intent/acceptance）。"""
    out = CommentedMap()
    out["form"] = e2e.form
    out["intent"] = e2e.intent
    out["acceptance"] = list(e2e.acceptance)
    return out


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
    """组级 rust-RFC 9 段总览（issue #69）：永远输出全部 `## <段名>`，空段填占位。

    始终成型 9 段既给作者脚手架（spec new），又让「总览先行」结构稳定可断言/可校验。
    """
    chunks: list[str] = []
    for heading, attr in _OVERVIEW_SECTIONS:
        text = getattr(group.overview, attr).rstrip()
        chunks.append(f"## {heading}\n\n{text or _PLACEHOLDER}\n")
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


def _parse_body(*, body: str) -> Overview:
    """正文 → 组级 Overview（issue #69）。按 `## <rust 段名>` 切段；占位段归一为空串。"""
    sections: dict[str, str] = {}
    current_attr: str | None = None
    buffer: list[str] = []

    def _flush() -> None:
        if current_attr is not None:
            sections[current_attr] = _strip_placeholder(text="\n".join(buffer).strip("\n"))

    for line in body.split("\n"):
        heading_match = _SECTION_HEADING_RE.match(line)
        if heading_match and heading_match.group(1) in _SECTION_BY_HEADING:
            _flush()
            current_attr = _SECTION_BY_HEADING[heading_match.group(1)]
            buffer = []
            continue
        buffer.append(line)
    _flush()
    return Overview(**sections)


def _strip_placeholder(*, text: str) -> str:
    """占位 `<!-- 待填 -->`-only 的段归一为空串（spec new 脚手架与真实空段等价）。"""
    return "" if text.strip() == _PLACEHOLDER else text


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
