"""spec 数据层（model + schema）单元测试 —— markdown 单文件形态（2026-06-24）。

覆盖：render_group→load_group round-trip（frontmatter 结构化 + 正文 prose）、可选字段默认、
load_all 聚合多组并忽略生成物/dated 文档、组文件辨识、qualified_id、schema 合法。
"""

from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from openagents.spec import model, schema
from openagents.spec.model import Group, Metadata, RelatesTo, Task


def _sample_task() -> Task:
    return Task(
        id="T3",
        title="渲染 OVERVIEW",
        status="in-progress",
        priority="P1",
        tags=["cli", "render"],
        depends_on=["T1", "0012/T2"],
        relates_to=[RelatesTo(ref="0012/T2", type="extends")],
        parallel=True,
        files=["openagents/spec/render.py"],
        summary="把源数据派生成 OVERVIEW.md",
        design="第一行\n第二行\n```mermaid\ngraph TD\n```",
        acceptance="渲染幂等。",
    )


def _sample_group() -> Group:
    return Group(
        number="0014",
        metadata=Metadata(title="spec 快照", issue=35, slug="spec-snapshot", summary="一句话人话"),
        tasks=[_sample_task()],
        history={},
    )


def _write_group(*, root: Path, group: Group) -> Path:
    path = model.group_path(specs_root=root, number=group.number, slug=group.metadata.slug)
    model.dump_group(group=group, path=path)
    return path


def test_round_trip_preserves_content(tmp_path: Path) -> None:
    """render_group→load_group：结构化字段与 prose 全部保真。"""
    group = _sample_group()
    path = _write_group(root=tmp_path, group=group)
    reloaded = model.load_group(path=path)

    assert reloaded.number == "0014"
    assert reloaded.metadata == group.metadata
    task = reloaded.tasks[0]
    original = group.tasks[0]
    for attr in (
        "id",
        "title",
        "status",
        "priority",
        "tags",
        "depends_on",
        "relates_to",
        "parallel",
        "files",
        "summary",
        "design",
        "acceptance",
    ):
        assert getattr(task, attr) == getattr(original, attr), attr
    # 二次序列化字节级一致（确定性）。
    assert model.render_group(group=group) == model.render_group(group=reloaded)


def test_frontmatter_holds_structured_body_holds_prose(tmp_path: Path) -> None:
    """frontmatter 放结构化字段，正文放 prose 小节。"""
    path = _write_group(root=tmp_path, group=_sample_group())
    text = path.read_text(encoding="utf-8")
    head, body = text.split("\n---\n", 1) if "\n---\n" in text else (text, "")
    assert "number:" in head and "status: in-progress" in head
    assert "## T3 · 渲染 OVERVIEW" in body
    assert "### Design" in body and "mermaid" in body
    # prose 不应出现在 frontmatter。
    assert "把源数据派生成" not in head


def test_optional_fields_default(tmp_path: Path) -> None:
    """仅必填字段的 Task 加载后，可选字段取合理默认。"""
    group = Group(
        number="0001",
        metadata=Metadata(title="m", issue=1, slug="min"),
        tasks=[Task(id="T9", title="最小", status="pending", priority="P2")],
    )
    path = _write_group(root=tmp_path, group=group)
    task = model.load_group(path=path).tasks[0]
    assert task.tags == []
    assert task.depends_on == []
    assert task.relates_to == []
    assert task.parallel is False
    assert task.version == 1
    assert task.split_from is None
    assert task.tests == ""


def test_load_all_aggregates_groups(tmp_path: Path) -> None:
    """load_all 聚合多组并按编号排序；生成物 / README / dated 文档被忽略。"""
    _write_group(root=tmp_path, group=_sample_group())
    _write_group(
        root=tmp_path,
        group=Group(
            number="0009",
            metadata=Metadata(title="rebase", issue=24, slug="auto-rebase"),
            tasks=[Task(id="T1", title="x", status="done", priority="P1")],
        ),
    )
    # 干扰项：均不应被当成组文件。
    (tmp_path / "OVERVIEW.md").write_text("x", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / "2026-06-24-some-design.md").write_text("x", encoding="utf-8")

    groups = model.load_all(specs_root=tmp_path)
    assert [g.number for g in groups] == ["0009", "0014"]


def test_load_all_empty_root(tmp_path: Path) -> None:
    """空 / 不存在的 specs 根返回空列表，不报错。"""
    assert model.load_all(specs_root=tmp_path / "nope") == []
    assert model.load_all(specs_root=tmp_path) == []


def test_is_group_file() -> None:
    """组文件辨识：NNNN-slug.md 是组；dated / 生成物 / README 不是。"""
    assert model._is_group_file(name="0014-spec-snapshot.md")
    assert not model._is_group_file(name="2026-06-24-design.md")
    assert not model._is_group_file(name="OVERVIEW.md")
    assert not model._is_group_file(name="README.md")


def test_qualified_id() -> None:
    assert model.qualified_id(group="0009", task_id="T3") == "0009/T3"


@pytest.mark.parametrize("doc", [schema.TASK_SCHEMA, schema.GROUP_FRONTMATTER_SCHEMA])
def test_schemas_are_valid_jsonschema(doc: dict) -> None:
    """schema 本身是合法 JSON Schema（draft 2020-12 可编译）。"""
    jsonschema.Draft202012Validator.check_schema(doc)
