"""spec 数据层：Task / Metadata / Group 模型与 YAML round-trip 读写。

Spec-0014/T1: 数据层 + JSON Schema + 依赖/入口声明

只懂 docs/specs/ 源数据结构的纯模块（理念 10 解耦），不感知 git / GitHub。
用 ruamel.yaml 以**规范化**形式写回——prose 字段强制块标量 `|`、键按固定顺序排列，
因此 load→dump→load 内容保真（块标量样式、键序、relates-to 列表均稳定），且输出确定，
为 render 幂等（决策 D9）与迁移脚本产出干净文件打底。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString

# Spec-0014/T1：统一的 YAML round-trip 实例。
# width 调大避免长行被折断；indent 固定让输出确定（幂等前提）。
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096
_yaml.indent(mapping=2, sequence=4, offset=2)

# Spec-0014/T1：prose（长文）字段——用 YAML 块标量 `|` 承载 Markdown（决策 D4）。
_PROSE_FIELDS = (
    "summary",
    "motivation",
    "scope",
    "design",
    "interface",
    "tradeoffs",
    "acceptance",
    "tests",
    "references",
    "open_questions",
)

# Spec-0014/T1：Task 字段的规范化顺序（yaml_key, attr）。dump 一律按此序输出，保证键序稳定。
_TASK_FIELD_ORDER: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("title", "title"),
    ("status", "status"),
    ("priority", "priority"),
    ("tags", "tags"),
    ("depends-on", "depends_on"),
    ("relates-to", "relates_to"),
    ("parallel", "parallel"),
    ("files", "files"),
    ("version", "version"),
    ("updated", "updated"),
    ("change-reason", "change_reason"),
    ("supersedes", "supersedes"),
    ("split-from", "split_from"),
    ("merged-from", "merged_from"),
    ("derived-from", "derived_from"),
    ("summary", "summary"),
    ("motivation", "motivation"),
    ("scope", "scope"),
    ("design", "design"),
    ("interface", "interface"),
    ("tradeoffs", "tradeoffs"),
    ("acceptance", "acceptance"),
    ("tests", "tests"),
    ("references", "references"),
    ("open-questions", "open_questions"),
)


@dataclass(frozen=True)
class RelatesTo:
    """Spec-0014/T1：非阻塞的跨 feature 关联（画虚线）。"""

    # Spec-0014/T1：跨组限定 ID，如 "0012/T2"
    ref: str
    # Spec-0014/T1：关联类型 extends | supersedes | note
    type: str


@dataclass
class Task:
    """A single spec Task —— 快照的基本单元，与当前活代码一一对应。

    Spec-0014/T1: Task 模型，覆盖旧 RFC 全部元素（见 RFC 元素→Task 字段对照表）。

    结构化字段（status/priority/depends-on/files/血缘…）可机器校验；prose 字段
    （summary/design/interface…）用块标量承载 Markdown。
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
    # ── 演化 / 血缘 ──
    version: int = 1
    updated: str = ""
    change_reason: str = ""
    supersedes: list[str] = field(default_factory=list)
    split_from: str | None = None
    merged_from: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    # ── 设计内容（prose）──
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
    """Spec-0014/T1：组级元数据（一个 spec 组 = 一个 issue/feature）。"""

    title: str
    issue: int
    slug: str


@dataclass(frozen=True)
class Group:
    """Spec-0014/T1：一个 spec 组的全部源数据（当前版快照 + 历史版本）。"""

    # Spec-0014/T1：四位编号 "0009"（与旧 RFC 编号 1:1 兼容，决策 D11）
    number: str
    metadata: Metadata
    # Spec-0014/T1：当前版 Task 快照（status 含 done，做完不离开快照，决策 D2）
    tasks: list[Task]
    # Spec-0014/T1：task_id -> 历史版本列表（旧→新），只增不改
    history: dict[str, list[Task]]


def qualified_id(*, group: str, task_id: str) -> str:
    """Build a cross-group qualified task id like "0009/T3".

    Spec-0014/T1：跨组引用用限定 ID（组内简写 T3 → 全局 0009/T3）。
    """
    return f"{group}/{task_id}"


def load_group(*, group_dir: Path) -> Group:
    """Load one spec group (metadata + current tasks + history) from disk.

    Spec-0014/T1：读 group_dir 下 metadata.yaml、tasks/T*.yaml、history/T*.yaml，
    组装成 Group。number 取目录名前四位。
    """
    # 1. 组编号取目录名前缀 NNNN。
    number = group_dir.name[:4]

    # 2. 组元数据。
    metadata = _load_metadata(path=group_dir / "metadata.yaml")

    # 3. 当前版 Task 快照（tasks/T*.yaml，按文件名排序保证确定性）。
    tasks: list[Task] = []
    tasks_dir = group_dir / "tasks"
    if tasks_dir.is_dir():
        for task_path in sorted(tasks_dir.glob("*.yaml")):
            tasks.append(task_from_mapping(data=_yaml.load(task_path)))

    # 4. 历史版本列表（history/T*.yaml，每文件是一个版本对象数组）。
    history: dict[str, list[Task]] = {}
    history_dir = group_dir / "history"
    if history_dir.is_dir():
        for hist_path in sorted(history_dir.glob("*.yaml")):
            versions = _yaml.load(hist_path) or []
            history[hist_path.stem] = [task_from_mapping(data=item) for item in versions]

    return Group(number=number, metadata=metadata, tasks=tasks, history=history)


def load_all(*, specs_root: Path) -> list[Group]:
    """Load every spec group under specs_root (sorted by number).

    Spec-0014/T1：聚合 docs/specs/ 下全部 NNNN-slug/ 组目录；空仓库返回 []。
    """
    if not specs_root.is_dir():
        return []
    groups: list[Group] = []
    for group_dir in sorted(specs_root.iterdir()):
        # 仅 NNNN-slug 形态的目录视为 spec 组（跳过 OVERVIEW.md / README.md 等）。
        if group_dir.is_dir() and _is_group_dir(name=group_dir.name):
            groups.append(load_group(group_dir=group_dir))
    return groups


def dump_task(*, task: Task, path: Path) -> None:
    """Write a Task to path as canonical YAML (block scalars + fixed key order).

    Spec-0014/T1：规范化写回——prose 用块标量、键按 _TASK_FIELD_ORDER 排序，输出确定。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        _yaml.dump(task_to_mapping(task=task), handle)


def dump_history(*, versions: list[Task], path: Path) -> None:
    """Write a history version list (append-only) to path.

    Spec-0014/T1：历史文件是版本对象数组，每项是一个完整 Task 快照（决策 D6）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [task_to_mapping(task=version) for version in versions]
    with path.open("w", encoding="utf-8") as handle:
        _yaml.dump(payload, handle)


def dump_metadata(*, metadata: Metadata, path: Path) -> None:
    """Write metadata.yaml with fixed key order (title/issue/slug).

    issue #53：组级元数据的规范化写入单一来源——migrate 与 `spec new` 共用，避免键序漂移。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = CommentedMap(
        [("title", metadata.title), ("issue", metadata.issue), ("slug", metadata.slug)]
    )
    with path.open("w", encoding="utf-8") as handle:
        _yaml.dump(payload, handle)


def next_number(*, specs_root: Path) -> str:
    """Return the next free 4-digit group number (max existing + 1, "0001" if none).

    issue #53：`spec new` 缺省取本地最大组号 +1（与旧 RFC 流程「扫描取下一号」同构）。
    跨 PR 的编号冲突由 CI 的 check-spec-number-conflicts 兜底（本函数只看本地）。
    """
    highest = 0
    for group in load_all(specs_root=specs_root):
        try:
            highest = max(highest, int(group.number))
        except ValueError:
            continue
    return f"{highest + 1:04d}"


def task_to_mapping(*, task: Task) -> CommentedMap:
    """Convert a Task to a canonical-ordered CommentedMap (prose as block scalars).

    Spec-0014/T1：dump 与 history append 复用的单一序列化入口。
    """
    out = CommentedMap()
    for yaml_key, attr in _TASK_FIELD_ORDER:
        value = getattr(task, attr)
        if attr == "relates_to":
            # relates-to 列表 → [{ref, type}] 映射列表。
            out[yaml_key] = [
                CommentedMap([("ref", item.ref), ("type", item.type)]) for item in value
            ]
        elif attr in _PROSE_FIELDS:
            # prose 字段强制块标量 `|`（含内嵌 mermaid 的 Markdown）。
            out[yaml_key] = _as_block_scalar(text=value)
        else:
            out[yaml_key] = value
    return out


def task_from_mapping(*, data: object) -> Task:
    """Build a Task from a loaded YAML mapping, applying defaults for optional fields.

    Spec-0014/T1：缺省可选字段（tags/tests/open-questions…）取合理默认；
    relates-to 解析为 RelatesTo 列表。
    """
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
        version=int(raw.get("version", 1)),
        updated=str(raw.get("updated", "")),
        change_reason=str(raw.get("change-reason", "")),
        supersedes=_str_list(value=raw.get("supersedes")),
        split_from=_optional_str(value=raw.get("split-from")),
        merged_from=_str_list(value=raw.get("merged-from")),
        derived_from=_str_list(value=raw.get("derived-from")),
        summary=_text(value=raw.get("summary")),
        motivation=_text(value=raw.get("motivation")),
        scope=_text(value=raw.get("scope")),
        design=_text(value=raw.get("design")),
        interface=_text(value=raw.get("interface")),
        tradeoffs=_text(value=raw.get("tradeoffs")),
        acceptance=_text(value=raw.get("acceptance")),
        tests=_text(value=raw.get("tests")),
        references=_text(value=raw.get("references")),
        open_questions=_text(value=raw.get("open-questions")),
    )


def _load_metadata(*, path: Path) -> Metadata:
    """读 metadata.yaml → Metadata；缺字段取空默认（issue 缺省 0）。"""
    raw = (_yaml.load(path) if path.is_file() else None) or {}
    return Metadata(
        title=str(raw.get("title", "")),
        issue=int(raw.get("issue", 0)),
        slug=str(raw.get("slug", "")),
    )


def _is_group_dir(*, name: str) -> bool:
    """目录名是否 NNNN-slug 形态（四位数字 + 连字符 + slug）。"""
    return len(name) > 5 and name[:4].isdigit() and name[4] == "-"


def _as_block_scalar(*, text: str) -> object:
    """非空 prose 包成块标量 `|`；空串原样返回（避免空块标量歧义）。"""
    if text == "":
        return ""
    return LiteralScalarString(text)


def _text(*, value: object) -> str:
    """prose 字段取字符串；None → 空串。"""
    return "" if value is None else str(value)


def _optional_str(*, value: object) -> str | None:
    """可空字符串字段：None / 空串 → None。"""
    if value is None:
        return None
    text = str(value)
    return text or None


def _str_list(*, value: object) -> list[str]:
    """列表字段统一成 list[str]；None → []。"""
    if value is None:
        return []
    return [str(item) for item in value]
