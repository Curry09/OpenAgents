"""Spec Data Layer (model + schema) module test - rust-RFC form (issue #69).

Overwrite: Group Overview 9 + frontmatr matter tasks (scope/acceptance) render_group load_group
round-trip, default for optional fields, load_all grouping and ignoring the generator/daded document, group file identification,
qualified_id, schema is legal.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
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
        summary="One word to explain what this feature is.",
        motivation="Status X, question Y, so change (backgrounds are repeated in place, without spec references).",
        guide_level="When it already exists, so tell people: Example...",
        reference_level="Technical programme details.\n\nTask breakdown: T3 to render.py.\n```mermaid\ngraph TD\n```",
        drawbacks="Why not do it: cost Z.",
        rationale_alternatives="Option A was rejected because ...",
        prior_art="rust-lang/rfcs ’000-template.md.",
        unresolved_questions="Still to be resolved: W.",
        future_possibilities="Follow-up can extend to run-time owner enforcement (issue #71).",
    )


def _sample_task() -> Task:
    return Task(
        id="T3",
        title="Render Oferview",
        status="in-progress",
        priority="P1",
        tags=["cli", "render"],
        depends_on=["T1", "0012/T2"],
        relates_to=[RelatesTo(ref="0012/T2", type="extends")],
        parallel=True,
        files=["openagents/spec/render.py"],
        scope="Dissociate source data into OVERVIEW.md.",
        acceptance="Rendering the tatters and so on.",
    )


def _sample_group() -> Group:
    return Group(
        number="0014",
        metadata=Metadata(
            title="Spec, come on.",
            issue=35,
            slug="spec-snapshot",
            summary="A word of a man’s word.",
        ),
        tasks=[_sample_task()],
        overview=_sample_overview(),
        history={},
    )


def _write_group(*, root: Path, group: Group) -> Path:
    path = model.group_path(specs_root=root, number=group.number, slug=group.metadata.slug)
    model.dump_group(group=group, path=path)
    return path


def test_round_trip_preserves_overview_and_tasks(tmp_path: Path) -> None:
    """render_group→load_group: Group 9 Paragraph Overview + task Structured fields to be fully authentic."""
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
    # (b) Consistency of the secondary serial byte level (certainty).
    assert model.render_group(group=group) == model.render_group(group=reloaded)


def test_oversized_rationale_round_trips_and_defaults_empty(tmp_path: Path) -> None:
    """Spec-0072/T1：oversized-rationale On declaration round-trip Pouch, Write frontmatter;no default empty string declared and no whole key appears."""
    # Declare  →  Write Frontmatter (plugged in after summy, before tasks).
    declared = Group(
        number="0072",
        metadata=Metadata(
            title="big",
            issue=156,
            slug="big",
            summary="TL;DR",
            oversized_rationale="One atomic delivery",
        ),
        tasks=[Task(id="T1", title="x", status="pending", priority="P1")],
        overview=_sample_overview(),
    )
    path = _write_group(root=tmp_path, group=declared)
    reloaded = model.load_group(path=path)
    assert reloaded.metadata.oversized_rationale == "One atomic delivery"
    head = path.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    assert "oversized-rationale:" in head
    assert model.render_group(group=declared) == model.render_group(group=reloaded)

    # No default empty string declared and frontmatter is not shown (spec no behavior change, bytes unchanged).
    plain = Group(
        number="0001",
        metadata=Metadata(title="m", issue=1, slug="min"),
        tasks=[Task(id="T1", title="x", status="pending", priority="P1")],
    )
    plain_path = _write_group(root=tmp_path, group=plain)
    assert model.load_group(path=plain_path).metadata.oversized_rationale == ""
    assert "oversized-rationale" not in plain_path.read_text(encoding="utf-8")


def test_body_holds_overview_frontmatter_holds_scope(tmp_path: Path) -> None:
    """Text places the rust 9-part group level prose; scope/acceptance into frontmatter; text without Task subsections."""
    path = _write_group(root=tmp_path, group=_sample_group())
    text = path.read_text(encoding="utf-8")
    head, body = text.split("\n---\n", 1)
    assert "## Summary" in body
    assert "## Reference-level explanation" in body
    assert "## Future possibilities" in body
    assert "mermaid" in body
    # scope/acceptance is now a frontmatter structured field.
    assert "scope:" in head and "acceptance:" in head
    # There are no more per-Task body subsections.
    assert "## T3" not in body
    # Group prose should not appear in frontmatter.
    assert "We’ll repeat it in the background." not in head


def test_optional_fields_default(tmp_path: Path) -> None:
    """Only fill field with a Task / empty Overview load to get a reasonable default."""
    group = Group(
        number="0001",
        metadata=Metadata(title="m", issue=1, slug="min"),
        tasks=[Task(id="T9", title="Min", status="pending", priority="P2")],
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
    # The Overview 9 segment of the empty group is all empty (the place is one).
    assert reloaded.overview == Overview()


def test_load_all_aggregates_groups(tmp_path: Path) -> None:
    """load_all grouping and sorting by number; the generator/ README/ daded document is ignored."""
    _write_group(root=tmp_path, group=_sample_group())
    _write_group(
        root=tmp_path,
        group=Group(
            number="0009",
            metadata=Metadata(title="rebase", issue=24, slug="auto-rebase"),
            tasks=[Task(id="T1", title="x", status="done", priority="P1")],
        ),
    )
    # Interference items: None should be treated as group documents.
    (tmp_path / "OVERVIEW.md").write_text("x", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / "2026-06-24-some-design.md").write_text("x", encoding="utf-8")

    groups = model.load_all(specs_root=tmp_path)
    assert [g.number for g in groups] == ["0009", "0014"]


def test_load_all_empty_root(tmp_path: Path) -> None:
    """Empty/ non-existent root returns empty list, no error."""
    assert model.load_all(specs_root=tmp_path / "nope") == []
    assert model.load_all(specs_root=tmp_path) == []


def test_is_group_file() -> None:
    """Group file identification: NNNN-slug.md is group; deded / generator / README is not."""
    assert model._is_group_file(name="0014-spec-snapshot.md")
    assert not model._is_group_file(name="2026-06-24-design.md")
    assert not model._is_group_file(name="OVERVIEW.md")
    assert not model._is_group_file(name="README.md")


def test_qualified_id() -> None:
    assert model.qualified_id(group="0009", task_id="T3") == "0009/T3"


@pytest.mark.parametrize("doc", [schema.TASK_SCHEMA, schema.GROUP_FRONTMATTER_SCHEMA])
def test_schemas_are_valid_jsonschema(doc: dict) -> None:
    """Schema is itself legal JSON Schema (draft 2020-12 circulated)."""
    jsonschema.Draft202012Validator.check_schema(doc)


# --------------------------------------------------------------------------- #
# Spec-0040/T1: Group e2e rough plan field round-trip/ optional/ unified
# --------------------------------------------------------------------------- #


def test_e2e_plan_round_trip(tmp_path: Path) -> None:
    """Spec-0055/T2: Group for declaration of e2e measurement: render_group  →  load_group Pertify intent/method."""
    group = _sample_group()
    group = Group(
        number=group.number,
        metadata=Metadata(
            title=group.metadata.title,
            issue=group.metadata.issue,
            slug=group.metadata.slug,
            summary=group.metadata.summary,
            e2e=E2EPlan(
                intent="Init no origin must be visible failure.",
                method="1. None origin Run! init → The claim is not zero.\n2. Fill origin Run again. → We're gonna be successful.",
            ),
        ),
        tasks=group.tasks,
        overview=group.overview,
    )
    path = _write_group(root=tmp_path, group=group)
    reloaded = model.load_group(path=path)
    assert reloaded.metadata.e2e == group.metadata.e2e
    # Frontmatter dropped e2e (intent/method), which is not included in the body.
    head, _body = path.read_text(encoding="utf-8").split("\n---\n", 1)
    assert "e2e:" in head and "intent:" in head and "method:" in head
    # Byte level certainty.
    assert model.render_group(group=group) == model.render_group(group=reloaded)


def test_e2e_absent_defaults_none_and_omitted(tmp_path: Path) -> None:
    """Undeclared group: metadata.e2e is None and frontmotter does not appear e2e (zero returns)."""
    path = _write_group(root=tmp_path, group=_sample_group())
    reloaded = model.load_group(path=path)
    assert reloaded.metadata.e2e is None
    assert "e2e:" not in path.read_text(encoding="utf-8")


def test_e2e_from_mapping_none_returns_none() -> None:
    assert model.e2e_from_mapping(data=None) is None
    plan = model.e2e_from_mapping(data={"intent": "x", "method": "Run and see the results."})
    assert plan == E2EPlan(intent="x", method="Run and see the results.")


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


def test_self_reference_renumber_preserves_semantics_not_raw_digest() -> None:
    """Spec-0088/T1: mimic the live 0002 → 0004/0005 task-prose renumbering."""
    group = _sample_group()
    group.tasks[0].scope = "Implement Spec-0014/T3; preserve all constraints."
    group.tasks[0].acceptance = "Spec-0014/T3: verify delivered behavior."
    group = replace(
        group,
        overview=replace(
            group.overview, reference_level="See Spec-0014/T3. Keep foreign Spec-0012/T2."
        ),
    )
    approved = model.design_digest(group=group)
    raw = model.legacy_design_digest(group=group)
    renamed = replace(deepcopy(group), number="0015")
    renamed.tasks[0].scope = renamed.tasks[0].scope.replace("0014", "0015")
    renamed.tasks[0].acceptance = renamed.tasks[0].acceptance.replace("0014", "0015")
    renamed = replace(
        renamed,
        overview=replace(
            renamed.overview,
            reference_level=renamed.overview.reference_level.replace("0014", "0015"),
        ),
    )
    assert approved.startswith("v2:")
    assert model.design_digest(group=renamed) == approved
    assert model.legacy_design_digest(group=renamed) != raw
    assert group.number == "0014"  # canonicalization is read-only


@pytest.mark.parametrize(
    "text",
    [
        "Spec-0014/T99",  # nonexistent local task
        "Spec-0012/T3",  # foreign Spec
        "capacity=0014",  # arbitrary number
        "OtherSpec-0014/T3",  # not a standalone reference
        "Spec-0014/T3-extra",  # suffix must not be swallowed
        "docs/Spec-0014/T3",  # path, not prose identity
        "Spec-0014/T3.py",
    ],
)
def test_non_self_references_are_not_normalized(text: str) -> None:
    """Spec-0088/T1: fail closed for numeric edits outside the explicit grammar."""
    group = _sample_group()
    group.tasks[0].scope = text
    approved = model.design_digest(group=group)
    group = replace(group, number="0015")
    group.tasks[0].scope = text.replace("0014", "0015").replace("0012", "0015")
    assert model.design_digest(group=group) != approved


@pytest.mark.parametrize("field", ["files", "depends_on", "scope", "acceptance", "title"])
def test_material_task_changes_still_invalidate_approval(field: str) -> None:
    """Spec-0088/T1: real constraints and ownership changes cannot inherit approval."""
    group = _sample_group()
    setattr(group.tasks[0], field, ["Spec-0014/T3"] if field in {"files", "depends_on"} else "keep")
    approved = model.design_digest(group=group)
    group = replace(group, number="0015")
    setattr(group.tasks[0], field, ["Spec-0015/T3"] if field in {"files", "depends_on"} else "drop")
    assert model.design_digest(group=group) != approved


def test_literal_self_placeholder_cannot_impersonate_reference() -> None:
    """Spec-0088/T1: normalization uses typed segments, not an editable sentinel."""
    group = _sample_group()
    group.tasks[0].scope = "Spec-0014/T3"
    approved = model.design_digest(group=group)
    group.tasks[0].scope = 'Spec-<self>/T3 {"self-task": "T3"}'
    assert model.design_digest(group=group) != approved
