"""spec.ownership 单元测试 —— 单一 writer 索引 + 越权写守卫（Spec-0071/T1）。

覆盖：build_index 把 files 声明映射到唯一 owner（首个声明者胜）；generated_artifacts 恒含本组
spec md + OVERVIEW + ARCHITECTURE；unowned_writes 判无主写（放行声明文件与生成物、拦无主文件、
排序去重、空 changeset 返空）。纯函数、零 IO。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import ownership
from openagents.spec.model import Group, Metadata, Task


def _group(*, number: str = "0071", slug: str = "single-writer-ownership-guard") -> Group:
    """一个双 Task 组：T1 占 a.py/b.py，T2 占 c.py。"""
    return Group(
        number=number,
        metadata=Metadata(title=slug, issue=71, slug=slug, summary="tl;dr"),
        tasks=[
            Task(id="T1", title="t1", status="pending", priority="P1", files=["a.py", "b.py"]),
            Task(id="T2", title="t2", status="pending", priority="P1", files=["c.py"]),
        ],
    )


def test_build_index_maps_each_file_to_single_owner() -> None:
    index = ownership.build_index(group=_group())
    assert index.owner_of(path="a.py") == "0071/T1"
    assert index.owner_of(path="b.py") == "0071/T1"
    assert index.owner_of(path="c.py") == "0071/T2"


def test_owner_of_unknown_path_is_none() -> None:
    index = ownership.build_index(group=_group())
    assert index.owner_of(path="nowhere.py") is None


def test_build_index_first_declarer_wins_on_duplicate() -> None:
    """同文件被两个 Task 声明（validate 的 error）时，索引取首个 owner，确定性、不 raise。"""
    group = Group(
        number="0071",
        metadata=Metadata(title="s", issue=71, slug="s", summary="x"),
        tasks=[
            Task(id="T1", title="t1", status="pending", priority="P1", files=["dup.py"]),
            Task(id="T2", title="t2", status="pending", priority="P1", files=["dup.py"]),
        ],
    )
    assert ownership.build_index(group=group).owner_of(path="dup.py") == "0071/T1"


def test_generated_artifacts_covers_spec_md_and_rendered_docs() -> None:
    arts = ownership.generated_artifacts(group=_group(), specs_root=Path("docs/specs"))
    assert "docs/specs/0071-single-writer-ownership-guard.md" in arts
    assert "docs/specs/OVERVIEW.md" in arts
    assert "docs/specs/ARCHITECTURE.md" in arts


def test_unowned_writes_allows_declared_files() -> None:
    assert ownership.unowned_writes(group=_group(), changed_paths=["a.py", "b.py", "c.py"]) == []


def test_unowned_writes_allows_generated_artifacts() -> None:
    changed = [
        "docs/specs/0071-single-writer-ownership-guard.md",
        "docs/specs/OVERVIEW.md",
        "docs/specs/ARCHITECTURE.md",
    ]
    assert ownership.unowned_writes(group=_group(), changed_paths=changed) == []


def test_unowned_writes_flags_files_no_task_owns() -> None:
    offenders = ownership.unowned_writes(
        group=_group(), changed_paths=["a.py", "evil.py", "other/steal.py"]
    )
    assert offenders == ["evil.py", "other/steal.py"]


def test_unowned_writes_sorts_and_dedupes() -> None:
    offenders = ownership.unowned_writes(group=_group(), changed_paths=["z.py", "z.py", "m.py"])
    assert offenders == ["m.py", "z.py"]


def test_unowned_writes_empty_changeset_is_clean() -> None:
    assert ownership.unowned_writes(group=_group(), changed_paths=[]) == []


def test_unowned_writes_respects_custom_specs_root() -> None:
    """specs_root 变了，生成物路径随之变；旧默认路径就不再被当生成物放行。"""
    offenders = ownership.unowned_writes(
        group=_group(),
        changed_paths=["docs/specs/OVERVIEW.md"],
        specs_root=Path("other/specs"),
    )
    assert offenders == ["docs/specs/OVERVIEW.md"]
