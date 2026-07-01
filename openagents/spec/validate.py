"""spec 校验：JSON Schema + 语义规则（files 重叠 / DAG 无环 / 血缘引用）。

Spec-0014/T2: spec validate（schema + 语义校验）

依序跑六条校验链（决策 D7：同组 files 重叠是 error，跨组 files 重叠仅 warning）：
  1. JSON Schema 校验所有 task / metadata / history（结构 + 枚举）   -> error
  2. status 与 history 自洽（快照不含 abandoned、历史版本单调递增）  -> error
  3. 同组 files 不重叠（协同模式无冲突前提）                        -> error
  4. 全局 depends-on DAG（含跨组）无环                              -> error
  5. 血缘 / 跨组引用（depends-on/relates-to/supersedes/...）指向存在 Task -> error
  6. 跨组 files 重叠（协作信号，进 OVERVIEW 文件冲突报告）          -> warning

无 error 即 ok=True（warning 不影响 ok）。纯函数，不感知 git / GitHub（理念 10 解耦）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from openagents.spec import model
from openagents.spec.model import Group
from openagents.spec.schema import E2E_FORM_VALUES, GROUP_FRONTMATTER_SCHEMA

_ERROR = "error"
_WARNING = "warning"

# issue #69：单 spec 自包含 + 总览先行的质量门槛。
# 必填总览段（attr, 人读标题）——这四段撑起「读完即懂、无需翻别的 spec」。
_REQUIRED_SECTIONS: tuple[tuple[str, str], ...] = (
    ("summary", "Summary"),
    ("motivation", "Motivation"),
    ("reference_level", "Reference-level explanation"),
    ("rationale_alternatives", "Rationale and alternatives"),
)
# 疑似跨 spec 裸引用：`Spec-0012`、`Spec-0012 决策 8`、`Spec-0012/T2`。命中即提示就地复述。
_BARE_REF_RE = re.compile(r"Spec-\d{4}(?:\s*决策\s*\d+|/T\w+)?")


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
    # 8. 必填总览段非空（issue #69：总览先行）。                          -> error
    issues.extend(_overview_required_checks(groups=groups))
    # 9. 总览里疑似跨 spec 裸引用（issue #69：单 spec 自包含）。         -> warning
    issues.extend(_self_contained_checks(groups=groups))
    # 10. e2e 粗规划块（声明才校验）：form 合法 / intent 非空 / acceptance≥1。 -> error
    issues.extend(_e2e_checks(groups=groups))

    ok = not any(issue.level == _ERROR for issue in issues)
    return ValidationReport(ok=ok, issues=issues)


def _e2e_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Spec-0039/T1：组级 e2e 粗规划的硬化——**存在才校验**（不存在零回归，向后兼容）。

    e2e 块声明时：form 必须落在 E2E_FORM_VALUES（ui/api/cli/backend）、intent 去空白后非空、
    acceptance 至少 1 条。三者各报一条 error。schema 已保证键存在与类型，这里补 whitespace-only /
    空数组 / 枚举这三个 schema 拦不住的语义门槛（与 _summary_checks 同风格）。
    """
    issues: list[ValidationIssue] = []
    for group in groups:
        e2e = group.metadata.e2e
        if e2e is None:
            continue
        where = f"{group.number}/e2e"
        if e2e.form not in E2E_FORM_VALUES:
            issues.append(
                ValidationIssue(
                    level=_ERROR,
                    where=where,
                    message=(
                        f"e2e.form 非法：{e2e.form!r}（应为 {'/'.join(E2E_FORM_VALUES)} 之一）"
                    ),
                )
            )
        if not e2e.intent.strip():
            issues.append(
                ValidationIssue(
                    level=_ERROR, where=where, message="e2e.intent 为空（须声明成果验证意图）"
                )
            )
        if not [item for item in e2e.acceptance if item.strip()]:
            issues.append(
                ValidationIssue(
                    level=_ERROR,
                    where=where,
                    message="e2e.acceptance 为空（至少声明 1 条可验证的验收行为）",
                )
            )
    return issues


def _overview_required_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """issue #69：每个组的必填总览段去空白后非空，否则 error（总览先行、读完即懂）。"""
    issues: list[ValidationIssue] = []
    for group in groups:
        for attr, label in _REQUIRED_SECTIONS:
            if not getattr(group.overview, attr).strip():
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=f"{group.number}/overview",
                        message=f"必填总览段「{label}」为空（单 spec 自包含、总览先行）",
                    )
                )
    return issues


def _self_contained_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """issue #69：扫总览 9 段，命中「见 Spec-NNNN」式裸引用 → warning（提示就地复述）。"""
    issues: list[ValidationIssue] = []
    for group in groups:
        for _, attr in model._OVERVIEW_SECTIONS:
            text = getattr(group.overview, attr)
            for match in _BARE_REF_RE.finditer(text):
                issues.append(
                    ValidationIssue(
                        level=_WARNING,
                        where=f"{group.number}/overview/{attr}",
                        message=(
                            f"疑似跨 spec 裸引用 {match.group(0)!r}："
                            "确认理解本 spec 的必要信息已就地复述（issue #69）"
                        ),
                    )
                )
    return issues


def _summary_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Spec-0015/T3：每个组的 metadata.summary 去空白后非空，否则 error。"""
    issues: list[ValidationIssue] = []
    for group in groups:
        if not group.metadata.summary.strip():
            issues.append(
                ValidationIssue(
                    level=_ERROR,
                    where=f"{group.number}/frontmatter",
                    message="metadata.summary 为空（每个 feature 必须有人话 TL;DR）",
                )
            )
    return issues


def _schema_checks(*, specs_root: Path) -> list[ValidationIssue]:
    """JSON Schema 校验每个组 markdown 文件的 frontmatter；每个错误一条 error。"""
    issues: list[ValidationIssue] = []
    if not specs_root.is_dir():
        return issues

    for md_path in sorted(specs_root.glob("*.md")):
        if not model._is_group_file(name=md_path.name):
            continue
        meta, _body = model._split_frontmatter(text=md_path.read_text(encoding="utf-8"))
        number = md_path.name[:4]
        issues.extend(
            _validate_doc(
                data=meta,
                json_schema=GROUP_FRONTMATTER_SCHEMA,
                where=f"{number}/frontmatter",
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
