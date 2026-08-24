"""spec 数据层（model + schema）单元测试 —— rust-RFC 形态（issue #69）。

覆盖：组级 Overview 9 段 + frontmatter tasks（scope/acceptance）的 render_group→load_group
round-trip、可选字段默认、load_all 聚合多组并忽略生成物/dated 文档、组文件辨识、
qualified_id、schema 合法。
"""

from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from openagents.spec import model, schema
from openagents.spec.model import (
    ArchitectureCandidate,
    ArchitectureDecision,
    BehaviorCase,
    E2EPlan,
    Group,
    Metadata,
    Overview,
    RelatesTo,
    Task,
    VerificationPlan,
)


def _sample_overview() -> Overview:
    return Overview(
        summary="一句话讲清这个 feature 是什么。",
        motivation="现状 X，问题 Y，所以要改（背景就地复述，不甩跨 spec 引用）。",
        guide_level="当它已存在，这样向人讲解：示例……",
        reference_level="技术方案细节。\n\nTask 分解：T3 改 render.py。\n```mermaid\ngraph TD\n```",
        drawbacks="为什么不该做：成本 Z。",
        rationale_alternatives="备选 A 被否决，因为……",
        prior_art="rust-lang/rfcs 的 0000-template.md。",
        unresolved_questions="仍待解决：W。",
        future_possibilities="后续可扩展到运行期 owner 强制（issue #71）。",
    )


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
        scope="把源数据派生成 OVERVIEW.md。",
        acceptance="渲染幂等。",
    )


def _sample_group() -> Group:
    return Group(
        number="0014",
        metadata=Metadata(title="spec 快照", issue=35, slug="spec-snapshot", summary="一句话人话"),
        tasks=[_sample_task()],
        overview=_sample_overview(),
        history={},
    )


def _write_group(*, root: Path, group: Group) -> Path:
    path = model.group_path(specs_root=root, number=group.number, slug=group.metadata.slug)
    model.dump_group(group=group, path=path)
    return path


def test_round_trip_preserves_overview_and_tasks(tmp_path: Path) -> None:
    """render_group→load_group：组级 9 段 Overview + task 结构化字段全部保真。"""
    group = _sample_group()
    path = _write_group(root=tmp_path, group=group)
    reloaded = model.load_group(path=path)

    assert reloaded.number == "0014"
    assert reloaded.metadata == group.metadata
    assert reloaded.overview == group.overview
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
        "scope",
        "acceptance",
    ):
        assert getattr(task, attr) == getattr(original, attr), attr
    # 二次序列化字节级一致（确定性）。
    assert model.render_group(group=group) == model.render_group(group=reloaded)


def test_oversized_rationale_round_trips_and_defaults_empty(tmp_path: Path) -> None:
    """Spec-0072/T1：oversized-rationale 声明时 round-trip 保真、写入 frontmatter；未声明默认空串且整键不出现。"""
    # 声明 → 保真 + 写入 frontmatter（夹在 summary 后、tasks 前）。
    declared = Group(
        number="0072",
        metadata=Metadata(
            title="big", issue=156, slug="big", summary="TL;DR", oversized_rationale="一次原子交付"
        ),
        tasks=[Task(id="T1", title="x", status="pending", priority="P1")],
        overview=_sample_overview(),
    )
    path = _write_group(root=tmp_path, group=declared)
    reloaded = model.load_group(path=path)
    assert reloaded.metadata.oversized_rationale == "一次原子交付"
    head = path.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    assert "oversized-rationale:" in head
    assert model.render_group(group=declared) == model.render_group(group=reloaded)

    # 未声明 → 默认空串，且 frontmatter 整键不出现（既有 spec 零回归、逐字节不变）。
    plain = Group(
        number="0001",
        metadata=Metadata(title="m", issue=1, slug="min"),
        tasks=[Task(id="T1", title="x", status="pending", priority="P1")],
    )
    plain_path = _write_group(root=tmp_path, group=plain)
    assert model.load_group(path=plain_path).metadata.oversized_rationale == ""
    assert "oversized-rationale" not in plain_path.read_text(encoding="utf-8")


def test_body_holds_overview_frontmatter_holds_scope(tmp_path: Path) -> None:
    """正文放 rust 9 段组级 prose；scope/acceptance 进 frontmatter；正文无 Task 小节。"""
    path = _write_group(root=tmp_path, group=_sample_group())
    text = path.read_text(encoding="utf-8")
    head, body = text.split("\n---\n", 1)
    assert "## Summary" in body
    assert "## Reference-level explanation" in body
    assert "## Future possibilities" in body
    assert "mermaid" in body
    # scope/acceptance 现在是 frontmatter 结构化字段。
    assert "scope:" in head and "acceptance:" in head
    # 不再有 per-Task 正文小节。
    assert "## T3" not in body
    # 组级 prose 不应出现在 frontmatter。
    assert "背景就地复述" not in head


def test_optional_fields_default(tmp_path: Path) -> None:
    """仅必填字段的 Task / 空 Overview 加载后取合理默认。"""
    group = Group(
        number="0001",
        metadata=Metadata(title="m", issue=1, slug="min"),
        tasks=[Task(id="T9", title="最小", status="pending", priority="P2")],
    )
    path = _write_group(root=tmp_path, group=group)
    reloaded = model.load_group(path=path)
    task = reloaded.tasks[0]
    assert task.tags == []
    assert task.depends_on == []
    assert task.relates_to == []
    assert task.parallel is False
    assert task.scope == ""
    assert task.acceptance == ""
    # 空组的 Overview 9 段全为空串（占位被归一）。
    assert reloaded.overview == Overview()


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


# --------------------------------------------------------------------------- #
# Spec-0040/T1: 组级 e2e 粗规划字段 round-trip / 可选 / 归一化
# --------------------------------------------------------------------------- #


def test_e2e_plan_round_trip(tmp_path: Path) -> None:
    """Spec-0055/T2：声明 e2e 测法的组：render_group→load_group 保真 intent/method。"""
    group = _sample_group()
    group = Group(
        number=group.number,
        metadata=Metadata(
            title=group.metadata.title,
            issue=group.metadata.issue,
            slug=group.metadata.slug,
            summary=group.metadata.summary,
            e2e=E2EPlan(
                intent="init 无 origin 必须显式失败。",
                method="1. 无 origin 跑 init → 断言非零退出\n2. 补 origin 再跑 → 断言成功",
            ),
        ),
        tasks=group.tasks,
        overview=group.overview,
    )
    path = _write_group(root=tmp_path, group=group)
    reloaded = model.load_group(path=path)
    assert reloaded.metadata.e2e == group.metadata.e2e
    # frontmatter 落了 e2e 块（intent/method），正文不含它。
    head, _body = path.read_text(encoding="utf-8").split("\n---\n", 1)
    assert "e2e:" in head and "intent:" in head and "method:" in head
    # 字节级确定性。
    assert model.render_group(group=group) == model.render_group(group=reloaded)


def test_e2e_absent_defaults_none_and_omitted(tmp_path: Path) -> None:
    """未声明 e2e 的组：metadata.e2e 为 None，且 frontmatter 不出现 e2e 键（零回归）。"""
    path = _write_group(root=tmp_path, group=_sample_group())
    reloaded = model.load_group(path=path)
    assert reloaded.metadata.e2e is None
    assert "e2e:" not in path.read_text(encoding="utf-8")


def test_e2e_from_mapping_none_returns_none() -> None:
    assert model.e2e_from_mapping(data=None) is None
    plan = model.e2e_from_mapping(data={"intent": "x", "method": "跑一下看结果"})
    assert plan == E2EPlan(intent="x", method="跑一下看结果")


def test_architecture_round_trip_and_design_digest_ignore_status(tmp_path: Path) -> None:
    group = _sample_group()
    architecture = ArchitectureDecision(
        objective="preserve user-visible output",
        constraints=["compatible"],
        non_goals=[],
        candidates=[ArchitectureCandidate("runtime", "runtime", ["entry"], ["entry.py"], "cost")],
        selected="runtime",
        affected_components=["entry"],
        failure_modes=["concurrency"],
    )
    verification = VerificationPlan(
        behavior_cases=[
            BehaviorCase("p", "positive", "input", "output", "replay"),
            BehaviorCase("n", "negative", "other", "unchanged", "replay"),
        ],
        repository_invariants=["unique ids"],
        exemptions=[],
    )
    group = Group(
        number=group.number,
        metadata=Metadata(
            title=group.metadata.title,
            issue=group.metadata.issue,
            slug=group.metadata.slug,
            summary=group.metadata.summary,
            architecture=architecture,
            verification=verification,
        ),
        tasks=group.tasks,
        overview=group.overview,
    )
    path = _write_group(root=tmp_path, group=group)
    loaded = model.load_group(path=path)
    assert loaded.metadata.architecture == architecture
    assert loaded.metadata.verification == verification
    before = model.design_digest(group=loaded)
    loaded.tasks[0].status = "done"
    assert model.design_digest(group=loaded) == before
    loaded.tasks[0].acceptance = "different behavior"
    assert model.design_digest(group=loaded) != before
