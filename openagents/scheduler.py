"""Spec-0058/T1：跨 issue 调度 agent 判边 + 解析 spec 文件分配（纯逻辑，backend 注入，无 IO）。

给 OpenAgents 补上「跨 issue 的顺序概念」（issue #150）：读所有「已出 RFC」的 open issue
（标题 / 正文 + 其 spec 的文件分配），语义判两类依赖边——① **逻辑序**（下游要复用 / 依赖上游
先落地的接口、模块、协议）② **文件冲突序**（两个 spec 的 `files` 分配有交集 → 并行 implement
必在 rebase / merge 期撞车，应提前排开）——产出一张 issue DAG 的边集。

本模块刻意镜像 issuecheck.py / align.py 形态：冻结 dataclass 进、结构化裁决出、`_MARK_*`
稳定标记回解析、`backend` 依赖注入、无任何 IO（不碰 github / argparse / 文件系统），**fail-open**
——解析不出明确的边就返回空边集（宁可漏排也不乱连：乱连会误挡本可并行的 issue，比漏排更违背
「能并行尽量并行」，见 spec Reference-level「调度 agent 的判读契约」）。

文件冲突是**确定性可辅助**的：`parse_owned_files` 给出的交集是喂给 agent 的强证据，但「谁先谁后」
的方向仍是语义判断（哪个 spec 更接近底座 / 改动更小更该先合）——交给 agent，不写死。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

from openagents.backends.base import AgentBackend

# Spec-0058/T1：依赖边的两类 kind——logical（逻辑序，藏在 RFC 设计正文）/ file-conflict（文件
# 冲突序，两 spec 的 files 分配有交集）。判读输出的 kind 值必须落在此集合、否则该边 fail-open 丢弃。
KIND_LOGICAL = "logical"
KIND_FILE_CONFLICT = "file-conflict"
_VALID_KINDS = {KIND_LOGICAL, KIND_FILE_CONFLICT}

# Spec-0058/T1：判读输出的稳定标记——既是喂给 backend 的输出契约，也是 _parse_verdict 回解析的锚点
# （对齐 issuecheck.py 的 `_MARK_*` 套路）。一条边占三行：边（方向）/ 类型 / 理由，EDGE 行起一条新边。
_MARK_EDGE = "边："
_MARK_KIND = "类型："
_MARK_REASON = "理由："

# Spec-0058/T1：边方向分隔符——`<下游号> <- <上游号>`（下游依赖上游、上游先做）。回解析两侧取整。
_EDGE_ARROW = "<-"

# Spec-0058/T1：判读指令——严令「只在确有依据时连边、独立 issue 不连、文件交集作强证据」，并要求
# 按稳定标记逐条输出边。措辞刻意压「误连」侧（fail-open + 只在确有依据时连），漏连侧靠人在 DAG 图
# 上兜底（见 spec Drawbacks / Rationale 备选 2）。
_SCHEDULE_TASK = (
    "你是独立的跨 issue 调度员。下面给你一批「已出 RFC」的待排 issue（每个含编号 / 标题 / 正文 / "
    "其 spec 声明的文件分配 owned_files）。请判断它们之间有没有「下游必须等上游先做完」的依赖边，"
    "只认以下两类：\n"
    "① 逻辑序（logical）：下游明确要复用 / 依赖上游先落地的接口、模块、协议（依据藏在标题 / 正文 / "
    "设计里）；\n"
    "② 文件冲突序（file-conflict）：两个 issue 的 owned_files 有交集，并行改同一批文件必在 rebase / "
    "merge 期撞车，应排开先后。owned_files 交集是**强证据**，但「谁先谁后」由你据「谁更接近底座 / "
    "改动更小更该先合」判定。\n"
    "【只在确有依据时连边】毫无关系的两个 issue **不要连**——它们天然同波并行，乱连会误挡本可并行的"
    "工作，比漏连更糟。独立 issue 一条边都不输出。\n"
    "【硬性格式】每条依赖边严格按以下三行输出（下游依赖上游、上游先做），多条边就重复这三行；"
    "没有任何边就什么都别输出：\n"
    f"{_MARK_EDGE}<下游 issue 号> {_EDGE_ARROW} <上游 issue 号>\n"
    f"{_MARK_KIND}<{KIND_LOGICAL} 或 {KIND_FILE_CONFLICT}>\n"
    f"{_MARK_REASON}<一句话人话理由，说明为什么下游要等上游>"
)


@dataclass(frozen=True)
class IssueContext:
    """Spec-0058/T1：一个待排 issue 的快照——编号 + 标题 + 正文 + 其 spec 的文件分配。

    owned_files：该 issue 对应 spec 组 frontmatter tasks[].files 的并集（parse_owned_files 产出），
    是文件冲突序判读的强证据；无 spec / 无 files 时为空 frozenset。
    """

    number: int
    title: str
    body: str
    owned_files: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DepEdge:
    """Spec-0058/T1：一条依赖边——下游 downstream 依赖上游 upstream（上游先做）。

    kind ∈ {logical, file-conflict}；reason 是一句人话理由（供渲图 / 回帖 / 人审依赖时看）。
    """

    downstream: int
    upstream: int
    kind: str
    reason: str = ""


@dataclass(frozen=True)
class ScheduleVerdict:
    """Spec-0058/T1：调度判读的全量边集（fail-open 时为空 tuple）。"""

    edges: tuple[DepEdge, ...] = ()


def parse_owned_files(*, spec_markdown: str) -> frozenset[str]:
    """Spec-0058/T1：从一个 spec 组 markdown 的 frontmatter tasks[].files 收集文件分配并集（纯解析）。

    这是文件冲突序判读的**输入**（排序依据）。容错：无 frontmatter / 非法 YAML / 无 tasks / 无 files
    一律返回空 frozenset（无 IO、绝不上抛）。只收非空字符串条目、去重（frozenset 天然去重）。
    """
    meta = _load_frontmatter(text=spec_markdown)
    tasks = meta.get("tasks") if isinstance(meta, dict) else None
    files: set[str] = set()
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        for name in task.get("files") or []:
            if isinstance(name, str) and name.strip():
                files.add(name.strip())
    return frozenset(files)


def schedule(*, issues: list[IssueContext], backend: AgentBackend) -> ScheduleVerdict:
    """Spec-0058/T1：调注入的 backend 判两类依赖边，回解析成 ScheduleVerdict（不打印、不做 IO）。

    backend 以关键字参数注入（遵 CLAUDE.md 参数规范）；判读文本由 _parse_verdict 按稳定标记组织成
    边集。**fail-open**：空 / 格式跑偏 / 单条边解析不出 → 丢弃该边（宁漏排不乱连），全部解析不出即
    返回空边集。只保留两端都在本批 issue 内、方向不自环、kind 合法的边（越界号 / 自环 / 未知 kind 丢弃）。
    """
    if not issues:
        return ScheduleVerdict()
    result = backend.run(
        work_dir=Path.cwd(),
        task=_SCHEDULE_TASK,
        context=_render_issues(issues=issues),
    )
    valid_numbers = {issue.number for issue in issues}
    return _parse_verdict(text=result.summary, valid_numbers=valid_numbers)


def _render_issues(*, issues: list[IssueContext]) -> str:
    """Spec-0058/T1：把待排 issue 批渲成喂给 backend 的上下文文本（编号 / 标题 / 正文 / 文件分配）。"""
    blocks: list[str] = []
    for issue in issues:
        owned = "、".join(sorted(issue.owned_files)) if issue.owned_files else "（无）"
        blocks.append(
            f"issue #{issue.number}\n"
            f"标题：{issue.title}\n"
            f"正文：{issue.body}\n"
            f"文件分配 owned_files：{owned}"
        )
    return "\n\n".join(blocks)


def _parse_verdict(*, text: str, valid_numbers: set[int]) -> ScheduleVerdict:
    """Spec-0058/T1：把 backend 的标记输出解析成 ScheduleVerdict；逐条边 fail-open。

    按标记逐行拆：EDGE 行起一条新边（先 flush 上一条），KIND / REASON 行填当前边。flush 时校验
    两端可解析为整数、都在 valid_numbers 内、方向不自环、kind 合法——任一不满足即丢弃该边（不乱连）。
    """
    edges: list[DepEdge] = []
    pending: dict[str, str] | None = None

    def flush() -> None:
        if pending is None:
            return
        edge = _build_edge(pending=pending, valid_numbers=valid_numbers)
        if edge is not None:
            edges.append(edge)

    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(_MARK_EDGE):
            flush()
            pending = {"edge": stripped[len(_MARK_EDGE) :].strip(), "kind": "", "reason": ""}
        elif stripped.startswith(_MARK_KIND) and pending is not None:
            pending["kind"] = stripped[len(_MARK_KIND) :].strip().lower()
        elif stripped.startswith(_MARK_REASON) and pending is not None:
            pending["reason"] = stripped[len(_MARK_REASON) :].strip()
    flush()
    # 去重保序：同一 (下游, 上游, kind) 只留首条（agent 偶发重复输出不放大标签）。
    seen: set[tuple[int, int, str]] = set()
    unique: list[DepEdge] = []
    for edge in edges:
        key = (edge.downstream, edge.upstream, edge.kind)
        if key not in seen:
            seen.add(key)
            unique.append(edge)
    return ScheduleVerdict(edges=tuple(unique))


def _build_edge(*, pending: dict[str, str], valid_numbers: set[int]) -> DepEdge | None:
    """Spec-0058/T1：把一条待定边（edge/kind/reason 三字段）校验成 DepEdge；任一不合规返回 None。"""
    kind = pending["kind"]
    if kind not in _VALID_KINDS:
        return None
    parts = pending["edge"].split(_EDGE_ARROW)
    if len(parts) != 2:
        return None
    downstream = _parse_int(text=parts[0])
    upstream = _parse_int(text=parts[1])
    if downstream is None or upstream is None:
        return None
    if downstream == upstream:
        return None  # 自环不是依赖边
    if downstream not in valid_numbers or upstream not in valid_numbers:
        return None  # 越界号（agent 幻觉出不在本批的 issue）丢弃
    return DepEdge(downstream=downstream, upstream=upstream, kind=kind, reason=pending["reason"])


def _parse_int(*, text: str) -> int | None:
    """从一段文本里解析出首个整数（容 `#150` / `150` / ` 150 ` 等）；失败返回 None。"""
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def _load_frontmatter(*, text: str) -> dict:
    """Spec-0058/T1：拆出 markdown 首段 `--- … ---` YAML frontmatter 并加载为 dict；任何异常回落 {}。

    镜像 spec.model._split_frontmatter 的切分方式，但独立持有（本模块不反向依赖 spec.model，避免
    耦合）。无 frontmatter / 非法 YAML / 载出非 dict 一律 {}（fail-open，绝不上抛）。
    """
    if not text.startswith("---"):
        return {}
    lines = text.split("\n")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}
    fm_text = "\n".join(lines[1:end])
    if not fm_text.strip():
        return {}
    try:
        meta = YAML(typ="safe").load(fm_text)
    except Exception:  # noqa: BLE001 — 非法 YAML 视为无文件分配，fail-open 回落空
        return {}
    return meta if isinstance(meta, dict) else {}
