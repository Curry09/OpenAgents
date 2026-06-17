"""spec 校验：JSON Schema + 语义规则（files 重叠 / DAG 无环 / 血缘引用）。

Spec-0014/T2: spec validate（schema + 语义校验）

依序跑七条校验链（决策 D7：同组 files 重叠是 error，跨组 files 重叠仅 warning）：
  1. JSON Schema 校验所有 task / metadata / history（结构 + 枚举）   -> error
  2. status 与 history 自洽（快照不含 abandoned、历史版本单调递增）  -> error
  3. 同组 files 不重叠（协同模式无冲突前提）                        -> error
  4. 全局 depends-on DAG（含跨组）无环                              -> error
  5. 血缘 / 跨组引用（depends-on/relates-to/supersedes/...）指向存在 Task -> error
  6. 跨组 files 重叠（协作信号，进 OVERVIEW 文件冲突报告）          -> warning
  7. metadata.summary 非空（每个 feature 必须有人话 TL;DR，Spec-0015/T3）-> error

无 error 即 ok=True（warning 不影响 ok）。纯函数，不感知 git / GitHub（理念 10 解耦）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from openagents.spec import model
from openagents.spec.model import Group
from openagents.spec.schema import (
    HISTORY_SCHEMA,
    METADATA_SCHEMA,
    TASK_SCHEMA,
)

_ERROR = "error"
_WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    """Spec-0014/T2：单条校验问题。"""

    # Spec-0014/T2：error | warning
    level: str
    # Spec-0014/T2：定位串，"0009/T3" 或文件路径
    where: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """Spec-0014/T2：一次校验的汇总。无 error 即 ok（warning 不影响 ok）。"""

    ok: bool
    issues: list[ValidationIssue]


def validate(*, specs_root: Path) -> ValidationReport:
    """Run the full schema + semantic validation chain over a specs tree.

    Spec-0014/T2: 依序跑六条链，汇总 issues；无 error 即 ok=True。
    Spec-0015/T3: 追加第七条链——metadata.summary 非空。
    """
    issues: list[ValidationIssue] = []

    # 1. JSON Schema：对原始 YAML 文件校验结构与枚举（在 model 宽松归一化之前）。
    issues.extend(_schema_checks(specs_root=specs_root))

    # 后续语义校验基于 model 加载的结构化对象。
    groups = model.load_all(specs_root=specs_root)

    # 2. status 与 history 自洽。
    issues.extend(_status_checks(groups=groups))
    # 3. 同组 files 不重叠（error）；6. 跨组 files 重叠（warning）。
    issues.extend(_file_overlap_checks(groups=groups))
    # 4. 全局 depends-on DAG 无环。
    issues.extend(_dag_acyclic_checks(groups=groups))
    # 5. 血缘 / 跨组引用指向存在的 Task。
    issues.extend(_reference_checks(groups=groups))
    # 7. metadata.summary 非空（Spec-0015/T3：每个 feature 必须有人话 TL;DR）。
    issues.extend(_summary_checks(groups=groups))

    ok = not any(issue.level == _ERROR for issue in issues)
    return ValidationReport(ok=ok, issues=issues)


def _schema_checks(*, specs_root: Path) -> list[ValidationIssue]:
    """JSON Schema 校验每个 metadata / task / history 文件；每个 schema 错误一条 error。"""
    issues: list[ValidationIssue] = []
    if not specs_root.is_dir():
        return issues

    for group_dir in sorted(specs_root.iterdir()):
        if not (group_dir.is_dir() and _is_group_dir(name=group_dir.name)):
            continue
        number = group_dir.name[:4]

        # metadata.yaml 必须存在且合规。
        meta_path = group_dir / "metadata.yaml"
        if meta_path.is_file():
            issues.extend(
                _validate_doc(
                    data=_load_raw(path=meta_path),
                    json_schema=METADATA_SCHEMA,
                    where=f"{number}/metadata.yaml",
                )
            )
        else:
            issues.append(ValidationIssue(level=_ERROR, where=number, message="缺少 metadata.yaml"))

        # tasks/T*.yaml。
        for task_path in _yaml_files(directory=group_dir / "tasks"):
            issues.extend(
                _validate_doc(
                    data=_load_raw(path=task_path),
                    json_schema=TASK_SCHEMA,
                    where=f"{number}/{task_path.stem}",
                )
            )
        # history/T*.yaml。
        for hist_path in _yaml_files(directory=group_dir / "history"):
            issues.extend(
                _validate_doc(
                    data=_load_raw(path=hist_path),
                    json_schema=HISTORY_SCHEMA,
                    where=f"{number}/history/{hist_path.stem}",
                )
            )
    return issues


def _status_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """快照不得含 abandoned；有历史则版本号严格递增且当前版高于历史末版。"""
    issues: list[ValidationIssue] = []
    for group in groups:
        for task in group.tasks:
            where = model.qualified_id(group=group.number, task_id=task.id)
            # abandoned 只能在历史里，不能留在快照（决策 D2）。
            if task.status == "abandoned":
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=where,
                        message="status=abandoned 的 Task 应进 history 而非快照",
                    )
                )
            history = group.history.get(task.id, [])
            if not history:
                continue
            versions = [item.version for item in history]
            # 历史版本严格递增。
            if any(b <= a for a, b in zip(versions, versions[1:], strict=False)):
                issues.append(
                    ValidationIssue(
                        level=_ERROR, where=where, message=f"history 版本号非严格递增：{versions}"
                    )
                )
            # 当前版必须高于历史末版。
            if task.version <= max(versions):
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=where,
                        message=f"当前版 v{task.version} 未高于历史末版 v{max(versions)}",
                    )
                )
    return issues


def _file_overlap_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """同组 files 重叠 → error；跨组 files 重叠 → warning（决策 D7）。"""
    issues: list[ValidationIssue] = []
    # file -> {group_number -> [task_id, ...]}
    owners: dict[str, dict[str, list[str]]] = {}
    for group in groups:
        for task in group.tasks:
            for path in task.files:
                owners.setdefault(path, {}).setdefault(group.number, []).append(task.id)

    for path, by_group in sorted(owners.items()):
        # 同组内多个 Task 占用同一文件 → error。
        for number, task_ids in sorted(by_group.items()):
            if len(task_ids) > 1:
                joined = ", ".join(sorted(task_ids))
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=number,
                        message=f"同组内文件 {path} 被多个 Task 占用：{joined}",
                    )
                )
        # 文件跨 ≥2 个组 → warning（协作信号）。
        if len(by_group) > 1:
            groups_str = ", ".join(sorted(by_group))
            issues.append(
                ValidationIssue(
                    level=_WARNING,
                    where=path,
                    message=f"文件 {path} 跨组重叠：{groups_str}",
                )
            )
    return issues


def _dag_acyclic_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """全局 depends-on 图（含跨组）无环；有环报 error。"""
    # 1. 构图：节点 = 当前版 Task 限定 ID；边 = depends-on（解析为限定 ID）。
    current_ids = _current_ids(groups=groups)
    adjacency: dict[str, list[str]] = {}
    for group in groups:
        for task in group.tasks:
            node = model.qualified_id(group=group.number, task_id=task.id)
            targets = [_resolve_ref(ref=ref, group=group.number) for ref in task.depends_on]
            # 只对存在的节点连边；指向不存在的由引用校验报告。
            adjacency[node] = [t for t in targets if t in current_ids]

    # 2. DFS 检测环。
    cycle = _find_cycle(adjacency=adjacency)
    if cycle is None:
        return []
    return [
        ValidationIssue(
            level=_ERROR,
            where=cycle[0],
            message=f"depends-on 存在环：{' -> '.join(cycle)}",
        )
    ]


def _reference_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """depends-on / relates-to / 血缘字段引用的 Task 必须存在（当前版或历史版）。"""
    known = _known_ids(groups=groups)
    issues: list[ValidationIssue] = []
    for group in groups:
        for task in group.tasks:
            where = model.qualified_id(group=group.number, task_id=task.id)
            refs: list[tuple[str, str]] = []
            refs.extend(("depends-on", ref) for ref in task.depends_on)
            refs.extend(("relates-to", rel.ref) for rel in task.relates_to)
            refs.extend(("supersedes", ref) for ref in task.supersedes)
            refs.extend(("merged-from", ref) for ref in task.merged_from)
            refs.extend(("derived-from", ref) for ref in task.derived_from)
            if task.split_from:
                refs.append(("split-from", task.split_from))
            for field_name, ref in refs:
                resolved = _resolve_ref(ref=ref, group=group.number)
                if resolved not in known:
                    issues.append(
                        ValidationIssue(
                            level=_ERROR,
                            where=where,
                            message=f"{field_name} 指向不存在的 Task：{ref}",
                        )
                    )
    return issues


def _summary_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Spec-0015/T3：每个组的 metadata.summary 去空白后非空，否则 error。

    缺字段与空串在 model._load_metadata 已归一为 ""，一条 .strip() 检查同时覆盖
    缺字段 / 空串 / 纯空白三种情形，消息统一友好（决策见 T3 权衡）。
    """
    issues: list[ValidationIssue] = []
    for group in groups:
        if not group.metadata.summary.strip():
            issues.append(
                ValidationIssue(
                    level=_ERROR,
                    where=f"{group.number}/metadata.yaml",
                    message="metadata.summary 为空（每个 feature 必须有人话 TL;DR）",
                )
            )
    return issues


def _validate_doc(*, data: object, json_schema: dict, where: str) -> list[ValidationIssue]:
    """对单个文档跑 JSON Schema，每个错误产出一条 error issue。"""
    validator = Draft202012Validator(json_schema)
    issues: list[ValidationIssue] = []
    for error in sorted(validator.iter_errors(data), key=str):
        location = "/".join(str(part) for part in error.absolute_path)
        prefix = f"{where}:{location}" if location else where
        issues.append(ValidationIssue(level=_ERROR, where=prefix, message=error.message))
    return issues


def _current_ids(*, groups: list[Group]) -> set[str]:
    """全部当前版 Task 的限定 ID 集合。"""
    return {
        model.qualified_id(group=group.number, task_id=task.id)
        for group in groups
        for task in group.tasks
    }


def _known_ids(*, groups: list[Group]) -> set[str]:
    """已知 Task 限定 ID = 当前版 ∪ 历史版（血缘可指向已废弃/旧版 Task）。"""
    known = _current_ids(groups=groups)
    for group in groups:
        for task_id in group.history:
            known.add(model.qualified_id(group=group.number, task_id=task_id))
    return known


def _resolve_ref(*, ref: str, group: str) -> str:
    """组内简写 T3 → 限定 group/T3；已含 '/' 的视为跨组限定 ID 原样返回。"""
    return ref if "/" in ref else model.qualified_id(group=group, task_id=ref)


def _find_cycle(*, adjacency: dict[str, list[str]]) -> list[str] | None:
    """DFS 找一条环路径（节点序列，首尾相同）；无环返回 None。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in adjacency}
    stack: list[str] = []

    def _dfs(node: str) -> list[str] | None:
        color[node] = GRAY
        stack.append(node)
        for nxt in adjacency.get(node, []):
            if color.get(nxt, BLACK) == GRAY:
                # 命中灰色节点 → 环；截取栈中该节点起的片段。
                idx = stack.index(nxt)
                return [*stack[idx:], nxt]
            if color.get(nxt, BLACK) == WHITE:
                found = _dfs(nxt)
                if found is not None:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(adjacency):
        if color[node] == WHITE:
            found = _dfs(node)
            if found is not None:
                return found
    return None


def _load_raw(*, path: Path) -> object:
    """读原始 YAML（ruamel 容器，dict/list/str 子类，可直接喂 jsonschema）。"""
    return model._yaml.load(path)


def _yaml_files(*, directory: Path) -> list[Path]:
    """目录下 *.yaml 文件（排序）；目录不存在返回 []。"""
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.yaml"))


def _is_group_dir(*, name: str) -> bool:
    """目录名是否 NNNN-slug 形态。"""
    return len(name) > 5 and name[:4].isdigit() and name[4] == "-"
