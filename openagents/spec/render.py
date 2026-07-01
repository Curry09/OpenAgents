"""spec render：把源数据派生成唯一人读视图 OVERVIEW.md。

Spec-0014/T3: spec render → OVERVIEW.md

纯函数、幂等（决策 D3/D9）：同一份源数据两次 render 字节级一致。生成五块：
  0. TL;DR 顶部速览（Spec-0015/T4：逐 feature 列 metadata.summary，人一眼看懂每个 feature）
  1. 全局看板表（组 | NNNN/T* | 标题 | 状态 | 依赖 | 涉及文件）
  2. 跨 feature 关系图（Mermaid，按 feature 分 subgraph；depends-on 实线、relates-to 虚线标 type）
  3. 文件冲突报告（跨组 files 重叠，协作信号）
  4. 每 feature 段（组内看板 + 依赖 DAG + 演化图：节点=Task 版本、按 status 着色、血缘连边）

不感知 git / GitHub（理念 10 解耦）。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Group, Task

# Spec-0014/T3：演化图节点按 status 着色（pending/in-progress/done/abandoned）。
_STATUS_FILL = {
    "pending": "#eeeeee",
    "in-progress": "#fff3b0",
    "done": "#b7e4c7",
    "abandoned": "#f4b8b8",
}

# Spec-0014/T3：固定标题，便于断言「各块齐全」。
# Spec-0015/T4：TL;DR 顶部区块标题（与 _BOARD_HEADING 等同构，便于测试断言区块存在）。
_TLDR_HEADING = "## TL;DR（人话速览）"
_BOARD_HEADING = "## 全局看板"
_RELATION_HEADING = "## 跨 feature 关系图"
_CONFLICT_HEADING = "## 文件冲突报告"
_FEATURE_HEADING = "## 各 feature 详情"


def render(*, specs_root: Path) -> str:
    """Render the full OVERVIEW.md text from a specs tree (pure, idempotent).

    Spec-0014/T3：纯函数返回全文；空仓库返回仅含四块标题的骨架，不报错。
    """
    groups = model.load_all(specs_root=specs_root)
    blocks = [
        "# Spec 总览（OVERVIEW）",
        "> 本文件由 `spec render` 自动生成，请勿手工编辑（Spec-0014/T3）。",
        _render_tldr(groups=groups),  # Spec-0015/T4：顶部人话速览，先于全局看板。
        _render_board(groups=groups),
        _render_relations(groups=groups),
        _render_conflicts(groups=groups),
        _render_features(groups=groups),
    ]
    # 统一以单个换行连接、整体以换行结尾，保证确定性。
    return "\n\n".join(blocks).rstrip("\n") + "\n"


def write_overview(*, specs_root: Path) -> Path:
    """Render and write docs/specs/OVERVIEW.md, returning its path.

    Spec-0014/T3：render + 落盘到 specs_root/OVERVIEW.md。
    """
    path = specs_root / "OVERVIEW.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(specs_root=specs_root), encoding="utf-8")
    return path


def _render_tldr(*, groups: list[Group]) -> str:
    """块 0：TL;DR 顶部速览——逐 feature 输出组级 summary（Spec-0015/T4）。

    放在全局看板之前，人不必先读密表就能一眼看懂每个 feature 在干嘛。
    空仓库时只剩标题（骨架），不报错；幂等由确定的 group 排序与 _cell 归一保证。
    """
    lines = [_TLDR_HEADING]
    for group in groups:
        title = group.metadata.title or group.metadata.slug
        lines.append("")
        lines.append(f"### {group.number} {_cell(title)}")
        lines.append(_cell(group.metadata.summary))
        # Spec-0040/T1：声明了 e2e 粗规划的组，把「意图 + 验收行为」渲进 TL;DR（人一眼看清这个
        # feature 该怎么被成果验证，理念 8）。None 即整块不出现，既有 spec 逐字节不变（零回归）。
        lines.extend(_render_e2e(group=group))
    return "\n".join(lines)


def _render_e2e(*, group: Group) -> list[str]:
    """Spec-0040/T1：把组级 e2e 粗规划渲成 TL;DR 里的「e2e 意图（form）+ 验收行为」若干行。

    e2e 未声明返回空列表（零回归）；声明则输出一行意图 + 逐条验收行为。纯函数、_cell 归一保证幂等。
    """
    e2e = group.metadata.e2e
    if e2e is None:
        return []
    lines = [f"- e2e 粗规划（{_cell(e2e.form)}）：{_cell(e2e.intent)}"]
    for behavior in e2e.acceptance:
        lines.append(f"  - 验收行为：{_cell(behavior)}")
    return lines


def _render_board(*, groups: list[Group]) -> str:
    """块 1：全局看板表，每行一个当前版 Task。"""
    lines = [
        _BOARD_HEADING,
        "",
        "| 组 | 任务 | 标题 | 状态 | 依赖 | 涉及文件 |",
        "|----|----|----|----|----|----|",
    ]
    for group in groups:
        for task in group.tasks:
            qid = model.qualified_id(group=group.number, task_id=task.id)
            deps = ", ".join(task.depends_on) or "—"
            files = "<br>".join(task.files) or "—"
            lines.append(
                f"| {group.number} | {qid} | {_cell(task.title)} | {task.status} | {deps} | {files} |"
            )
    return "\n".join(lines)


def _render_relations(*, groups: list[Group]) -> str:
    """块 2：跨 feature 关系图（Mermaid，subgraph/feature；depends-on 实线、relates-to 虚线）。"""
    lines = [_RELATION_HEADING, "", "```mermaid", "graph LR"]
    current_ids = {
        model.qualified_id(group=g.number, task_id=t.id) for g in groups for t in g.tasks
    }
    # 1. 每个 feature 一个 subgraph，内含其当前版 Task 节点。
    for group in groups:
        lines.append(f"    subgraph G{group.number}[{group.number} {group.metadata.slug}]")
        for task in group.tasks:
            qid = model.qualified_id(group=group.number, task_id=task.id)
            lines.append(f'        {_node(qid)}["{task.id} {_cell(task.title)}"]')
        lines.append("    end")
    # 2. depends-on 实线边（解析为限定 ID；只连存在节点）。
    for group in groups:
        for task in group.tasks:
            src = model.qualified_id(group=group.number, task_id=task.id)
            for ref in task.depends_on:
                dst = _resolve(ref=ref, group=group.number)
                if dst in current_ids:
                    lines.append(f"    {_node(src)} --> {_node(dst)}")
    # 3. relates-to 虚线边（标 type）。
    for group in groups:
        for task in group.tasks:
            src = model.qualified_id(group=group.number, task_id=task.id)
            for rel in task.relates_to:
                dst = _resolve(ref=rel.ref, group=group.number)
                if dst in current_ids:
                    lines.append(f"    {_node(src)} -.{rel.type}.-> {_node(dst)}")
    lines.append("```")
    return "\n".join(lines)


def _render_conflicts(*, groups: list[Group]) -> str:
    """块 3：文件冲突报告——同一文件被 ≥2 个组占用（协作信号）。"""
    # file -> 占用它的组编号集合。
    owners: dict[str, set[str]] = {}
    for group in groups:
        for task in group.tasks:
            for path in task.files:
                owners.setdefault(path, set()).add(group.number)

    conflicts = {path: nums for path, nums in owners.items() if len(nums) > 1}
    lines = [_CONFLICT_HEADING, ""]
    if not conflicts:
        lines.append("无跨组文件冲突。")
        return "\n".join(lines)
    lines.extend(["| 文件 | 涉及组 |", "|----|----|"])
    for path, nums in sorted(conflicts.items()):
        lines.append(f"| {path} | {', '.join(sorted(nums))} |")
    return "\n".join(lines)


def _render_features(*, groups: list[Group]) -> str:
    """块 4：每 feature 段——组内看板 + 依赖 DAG + 演化图。"""
    lines = [_FEATURE_HEADING]
    for group in groups:
        title = group.metadata.title or group.metadata.slug
        lines.append("")
        lines.append(f"### {group.number} {title}（issue #{group.metadata.issue}）")
        lines.append("")
        lines.append(_render_group_dag(group=group))
        lines.append("")
        lines.append(_render_evolution(group=group))
    return "\n".join(lines)


def _render_group_dag(*, group: Group) -> str:
    """组内依赖 DAG（Mermaid）；无任务时给占位。"""
    lines = ["```mermaid", "graph LR"]
    ids = {task.id for task in group.tasks}
    for task in group.tasks:
        lines.append(f'    {_node(task.id)}["{task.id} {_cell(task.title)}"]')
    for task in group.tasks:
        for ref in task.depends_on:
            # 组内 DAG 只画组内依赖（跨组在全局关系图体现）。
            if "/" not in ref and ref in ids:
                lines.append(f"    {_node(ref)} --> {_node(task.id)}")
    if not group.tasks:
        lines.append("    empty[空]")
    lines.append("```")
    return "\n".join(lines)


def _render_evolution(*, group: Group) -> str:
    """组内演化图：节点=某 Task 某一版，按 status 着色，血缘字段连边。"""
    lines = ["演化图：", "", "```mermaid", "graph LR"]

    # 1. 汇总每个 task 的版本序列（历史版 + 当前版），current 节点便于血缘连边。
    versions = _task_versions(group=group)
    used_status: set[str] = set()
    node_class: list[str] = []

    # 2. 节点声明 + 同 task 版本间 redefined 链。
    for task_id in sorted(versions):
        chain = versions[task_id]
        for snapshot in chain:
            node_id = _ver_node(task_id=task_id, version=snapshot.version)
            lines.append(f'    {node_id}["{task_id} v{snapshot.version}"]')
            used_status.add(snapshot.status)
            node_class.append(f"    class {node_id} st_{_safe(snapshot.status)};")
        for older, newer in zip(chain, chain[1:], strict=False):
            lines.append(
                f"    {_ver_node(task_id=task_id, version=older.version)} "
                f"-->|redefined| {_ver_node(task_id=task_id, version=newer.version)}"
            )

    # 3. 血缘边（split / merged / supersedes / derived）：源 task 最新版 → 本 task 首版。
    lines.extend(_lineage_edges(versions=versions))

    # 4. 着色 classDef（仅声明用到的 status，保证确定性）。
    for status in sorted(used_status):
        fill = _STATUS_FILL.get(status, "#ffffff")
        lines.append(f"    classDef st_{_safe(status)} fill:{fill};")
    lines.extend(node_class)
    lines.append("```")
    return "\n".join(lines)


def _task_versions(*, group: Group) -> dict[str, list[Task]]:
    """每个 task_id → 版本序列（历史版按版本号 + 当前版），用于演化图。"""
    all_ids = set(group.history) | {task.id for task in group.tasks}
    current = {task.id: task for task in group.tasks}
    result: dict[str, list[Task]] = {}
    for task_id in all_ids:
        chain = sorted(group.history.get(task_id, []), key=lambda t: t.version)
        if task_id in current:
            chain = [*chain, current[task_id]]
        result[task_id] = chain
    return result


def _lineage_edges(*, versions: dict[str, list[Task]]) -> list[str]:
    """从最新版 Task 的血缘字段连边：源最新版 → 本 task 首版。"""
    edges: list[str] = []
    for task_id in sorted(versions):
        chain = versions[task_id]
        if not chain:
            continue
        latest = chain[-1]
        first_node = _ver_node(task_id=task_id, version=chain[0].version)
        specs = [
            ("split", [latest.split_from] if latest.split_from else []),
            ("merged", latest.merged_from),
            ("supersedes", latest.supersedes),
            ("derived", latest.derived_from),
        ]
        for label, refs in specs:
            for ref in refs:
                src_id = ref.split("/")[-1]  # 演化图限组内，取末段 task id
                if src_id in versions and versions[src_id]:
                    src_node = _ver_node(task_id=src_id, version=versions[src_id][-1].version)
                    edges.append(f"    {src_node} -->|{label}| {first_node}")
    return edges


def _resolve(*, ref: str, group: str) -> str:
    """组内简写 → 限定 ID。"""
    return ref if "/" in ref else model.qualified_id(group=group, task_id=ref)


def _node(qid: str) -> str:
    """限定 ID → 合法 Mermaid 节点名（n + 非字母数字转下划线）。"""
    return "n" + _safe(qid)


def _ver_node(*, task_id: str, version: int) -> str:
    """演化图版本节点名。"""
    return f"v_{_safe(task_id)}_{version}"


def _safe(text: str) -> str:
    """把任意串转成 Mermaid 安全标识（非字母数字 → 下划线）。"""
    return "".join(ch if ch.isalnum() else "_" for ch in text)


def _cell(text: str) -> str:
    """表格 / 节点 label 单元：压成单行、转义竖线。"""
    return text.replace("\n", " ").replace("|", "\\|").replace('"', "'")
