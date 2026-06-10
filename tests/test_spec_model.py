"""Spec-0014/T1: spec 数据层（model + schema）单元测试。

覆盖：load→dump→load round-trip 保真（块标量 / 键序 / relates-to）、可选字段默认、
load_all 聚合多组、qualified_id、以及三个 JSON Schema 自身合法（jsonschema 可编译）。
"""

from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from openagents.spec import model, schema
from openagents.spec.model import Metadata, RelatesTo, Task


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
        version=2,
        updated="2026-06-10",
        change_reason="拆出鉴权",
        supersedes=[],
        split_from="T2",
        merged_from=[],
        derived_from=[],
        summary="把源数据派生成 OVERVIEW.md",
        design="第一行\n第二行\n```mermaid\ngraph TD\n```",
    )


def _write_group(root: Path) -> Path:
    """在 root 下写一个最小 spec 组，返回组目录。"""
    group_dir = root / "0014-spec-snapshot"
    (group_dir / "tasks").mkdir(parents=True)
    (group_dir / "history").mkdir(parents=True)
    model.dump_task(task=_sample_task(), path=group_dir / "tasks" / "T3.yaml")
    metadata_path = group_dir / "metadata.yaml"
    metadata_path.write_text("title: spec 快照\nissue: 35\nslug: spec-snapshot\n", encoding="utf-8")
    return group_dir


def test_round_trip_preserves_content(tmp_path: Path) -> None:
    """load→dump→load 内容保真：块标量、列表、relates-to 都稳定。"""
    path = tmp_path / "T3.yaml"
    original = _sample_task()
    model.dump_task(task=original, path=path)
    reloaded = model.task_from_mapping(data=_round_trip_load(path=path))

    assert reloaded == original
    # 二次 dump 应与首次字节级一致（确定性，render 幂等前提）。
    second = tmp_path / "T3-again.yaml"
    model.dump_task(task=reloaded, path=second)
    assert path.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_block_scalar_style_used_for_prose(tmp_path: Path) -> None:
    """多行 prose 字段以块标量 `|` 落盘，而非折行/引号。"""
    path = tmp_path / "T3.yaml"
    model.dump_task(task=_sample_task(), path=path)
    text = path.read_text(encoding="utf-8")
    assert "design: |" in text
    assert "mermaid" in text


def test_key_order_is_canonical(tmp_path: Path) -> None:
    """落盘键序固定：id 在 title 之前、status 在 priority 之前。"""
    path = tmp_path / "T3.yaml"
    model.dump_task(task=_sample_task(), path=path)
    lines = [ln.split(":")[0] for ln in path.read_text(encoding="utf-8").splitlines()]
    top_keys = [k for k in lines if k and not k.startswith(" ")]
    assert top_keys.index("id") < top_keys.index("title")
    assert top_keys.index("status") < top_keys.index("priority")
    assert top_keys.index("depends-on") < top_keys.index("files")


def test_optional_fields_default(tmp_path: Path) -> None:
    """仅必填字段的 Task 加载后，可选字段取合理默认。"""
    path = tmp_path / "Tmin.yaml"
    path.write_text("id: T9\ntitle: 最小\nstatus: pending\npriority: P2\n", encoding="utf-8")
    task = model.task_from_mapping(data=_round_trip_load(path=path))
    assert task.tags == []
    assert task.depends_on == []
    assert task.relates_to == []
    assert task.parallel is False
    assert task.version == 1
    assert task.split_from is None
    assert task.tests == ""


def test_load_group_and_history(tmp_path: Path) -> None:
    """load_group 读出 metadata + 当前 task + 历史版本。"""
    group_dir = _write_group(tmp_path)
    # 写一个历史版本列表。
    model.dump_history(
        versions=[Task(id="T3", title="渲染 OVERVIEW", status="done", priority="P1", version=1)],
        path=group_dir / "history" / "T3.yaml",
    )
    group = model.load_group(group_dir=group_dir)
    assert group.number == "0014"
    assert group.metadata == Metadata(title="spec 快照", issue=35, slug="spec-snapshot")
    assert [t.id for t in group.tasks] == ["T3"]
    assert group.history["T3"][0].version == 1


def test_load_all_aggregates_groups(tmp_path: Path) -> None:
    """load_all 聚合多组并按编号排序；非组目录被忽略。"""
    _write_group(tmp_path)
    other = tmp_path / "0009-auto-rebase"
    (other / "tasks").mkdir(parents=True)
    other.joinpath("metadata.yaml").write_text(
        "title: rebase\nissue: 24\nslug: auto-rebase\n", encoding="utf-8"
    )
    model.dump_task(
        task=Task(id="T1", title="x", status="done", priority="P1"),
        path=other / "tasks" / "T1.yaml",
    )
    # 干扰项：OVERVIEW.md / README.md 不是组目录。
    (tmp_path / "OVERVIEW.md").write_text("x", encoding="utf-8")

    groups = model.load_all(specs_root=tmp_path)
    assert [g.number for g in groups] == ["0009", "0014"]


def test_load_all_empty_root(tmp_path: Path) -> None:
    """空 / 不存在的 specs 根返回空列表，不报错。"""
    assert model.load_all(specs_root=tmp_path / "nope") == []
    assert model.load_all(specs_root=tmp_path) == []


def test_qualified_id() -> None:
    assert model.qualified_id(group="0009", task_id="T3") == "0009/T3"


@pytest.mark.parametrize("doc", [schema.TASK_SCHEMA, schema.METADATA_SCHEMA, schema.HISTORY_SCHEMA])
def test_schemas_are_valid_jsonschema(doc: dict) -> None:
    """三个 schema 本身是合法 JSON Schema（draft 2020-12 可编译）。"""
    jsonschema.Draft202012Validator.check_schema(doc)


def test_sample_task_passes_task_schema(tmp_path: Path) -> None:
    """落盘后的 Task 数据满足 TASK_SCHEMA。"""
    path = tmp_path / "T3.yaml"
    model.dump_task(task=_sample_task(), path=path)
    data = _round_trip_load(path=path)
    jsonschema.validate(instance=_plain(data), schema=schema.TASK_SCHEMA)


def _round_trip_load(*, path: Path) -> object:
    """用 model 的 YAML 实例加载（与生产路径一致）。"""
    return model._yaml.load(path)


def _plain(data: object) -> object:
    """把 ruamel 容器转成纯 dict/list/标量，供 jsonschema 校验。"""
    if hasattr(data, "items"):
        return {str(k): _plain(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_plain(v) for v in data]
    if isinstance(data, str):
        return str(data)
    return data
