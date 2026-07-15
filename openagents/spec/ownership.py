# Spec-0071/T1: spec.ownership —— 单一 writer 文件所有权索引 + 越权写守卫（设计期声明→运行期可执行）

"""Resolve the single-writer owner of each spec-declared file and flag unowned writes.

借鉴 Rust 所有权模型（aliasing XOR mutability）：一个文件在一个 spec 组内**至多一个 owner
Task**——`spec validate` 的「同组 files 不重叠」error 已在设计期保证这份唯一性。本模块把那份
**设计期声明**读成一个可查询的单一 writer 索引，并据它判定「一个 changeset 里有哪些写落在
无主文件上」——即 issue #71 说的「越权写」（写了不属于任何 Task 的文件）。纯函数、零 IO，
不碰 git / GitHub（理念 10 解耦）；raise 版硬闸留在 `runtime.gates`（harness 侧的拒绝原语）。

调用示例：
    >>> index = build_index(group=group)
    >>> index.owner_of(path="openagents/spec/ownership.py")
    '0071/T1'
    >>> unowned_writes(group=group, changed_paths=["evil.py"])
    ['evil.py']

Exports:
    OwnerIndex -- path → 单一 owner Task 限定 ID（如 "0071/T1"）的不可变索引，附 owner_of 查询。
    build_index -- 从一个 Group 建单一 writer 索引（首个声明者胜，确定性）。
    generated_artifacts -- 一个 Group 恒允许写的生成物集合（本组 spec md / OVERVIEW / ARCHITECTURE）。
    unowned_writes -- 一个 changeset 里落在无主文件（且非生成物）上的写，排序去重返回。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Group

# 默认 specs 根目录（与 spec CLI 一致）；生成物路径据此拼出。
_DEFAULT_SPECS_ROOT = Path("docs/specs")


@dataclass(frozen=True)
class OwnerIndex:
    """Spec-0071/T1：一个 spec 组的单一 writer 索引——path → 唯一 owner Task 的限定 ID。

    `by_path` 的每个键是一个 Task 在 frontmatter `files` 里声明的文件路径（仓库相对），值是它的
    唯一 owner（`"0071/T1"` 式限定 ID）。同组不重叠由 `spec validate` 保证，故一个 path 只有一个
    owner；`build_index` 万一遇到重复声明取**首个**（确定性、不 raise，重叠本身另由 validate 报 error）。
    """

    by_path: dict[str, str]

    def owner_of(self, *, path: str) -> str | None:
        """返回 `path` 的 owner Task 限定 ID；无主（未被任何 Task 声明）返回 None。"""
        return self.by_path.get(path)


def build_index(*, group: Group) -> OwnerIndex:
    """Build the single-writer ownership index for one spec group.

    Spec-0071/T1: 遍历组内当前版 Task，把每个 `files` 项映射到其 owner 的限定 ID（`build` 时首个
    声明者胜，保证确定性）。同组内一个文件被多个 Task 声明本身是 `spec validate` 的 error，本索引
    不复述该校验、只取首个 owner 供查询。

    Args:
        group: 一个已加载的 spec 组（`spec.model.Group`）。

    Returns:
        OwnerIndex：path → owner 限定 ID 的不可变索引。
    """
    by_path: dict[str, str] = {}
    for task in group.tasks:
        owner = model.qualified_id(group=group.number, task_id=task.id)
        for path in task.files:
            # 首个声明者胜：重复声明（validate 的 error）不改写已记录的 owner，保持确定性。
            by_path.setdefault(path, owner)
    return OwnerIndex(by_path=by_path)


def generated_artifacts(*, group: Group, specs_root: Path = _DEFAULT_SPECS_ROOT) -> set[str]:
    """Return the set of generated/spec artifacts a group is always allowed to write.

    Spec-0071/T1: 解决 issue #71 时，一个 changeset 除了各 Task 声明的 `files`，还必然会碰三类
    **生成物**——本组的 spec markdown（`NNNN-slug.md`）、以及 `spec render` / `spec graph` 重渲的
    `OVERVIEW.md` / `ARCHITECTURE.md`。这些不写进 `tasks[].files`（约定），但绝非越权写，故恒放行。

    Args:
        group: 目标 spec 组。
        specs_root: specs 根目录（默认 docs/specs），用于拼出生成物的仓库相对路径。

    Returns:
        三个仓库相对路径的集合：本组 spec md + OVERVIEW.md + ARCHITECTURE.md。
    """
    spec_md = model.group_path(specs_root=specs_root, number=group.number, slug=group.metadata.slug)
    return {
        str(spec_md),
        str(specs_root / "OVERVIEW.md"),
        str(specs_root / "ARCHITECTURE.md"),
    }


def unowned_writes(
    *,
    group: Group,
    changed_paths: Iterable[str],
    specs_root: Path = _DEFAULT_SPECS_ROOT,
) -> list[str]:
    """Return the changed paths that no Task in the group owns and that aren't generated artifacts.

    Spec-0071/T1: issue #71 的「越权写」检测——把「单一 writer」从设计期声明推到运行期可执行判定。
    允许写的文件集 = 本组单一 writer 索引里的全部 path ∪ 本组生成物（spec md / OVERVIEW /
    ARCHITECTURE）。落在这个并集之外的改动即无主写，排序去重后返回（空列表 = 全部合规）。

    Args:
        group: 目标 spec 组（提供 `files` 声明与生成物集合）。
        changed_paths: 实际改动的文件路径（仓库相对，通常由 harness 从 `git diff --name-only` 得到）。
        specs_root: specs 根目录（默认 docs/specs），透传给 `generated_artifacts`。

    Returns:
        排序去重的无主写路径列表；空列表表示无越权写。
    """
    index = build_index(group=group)
    allowed = set(index.by_path) | generated_artifacts(group=group, specs_root=specs_root)
    return sorted({path for path in changed_paths if path not in allowed})
