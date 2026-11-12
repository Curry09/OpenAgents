"""Spec Validate unit test - markdown single file form (2026-06-24).

Covers positive and negative examples of each rule: non-compliant / group files overlap / DAG ring / cross-group references do not exist
 → eror; cross group files overlap  → warning and ok=True; full compliance  →  no issue. Hastory mechanism retired.
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
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
from openagents.spec.validate import validate


def _overview(**overrides: str) -> Overview:
    """Compliance Overview: Four sections (summary/motivation/reference_level/rationale_alternatives) are not empty."""
    base = dict(summary="s", motivation="m", reference_level="r", rationale_alternatives="ra")
    base.update(overrides)
    return Overview(**base)


def _group(
    *,
    root: Path,
    number: str,
    slug: str,
    issue: int,
    tasks: list[Task],
    overview: Overview | None = None,
) -> Path:
    group = Group(
        number=number,
        metadata=Metadata(title=slug, issue=issue, slug=slug, summary=f"{slug} TL;DR"),
        tasks=tasks,
        overview=overview if overview is not None else _overview(),
    )
    path = model.group_path(specs_root=root, number=number, slug=slug)
    model.dump_group(group=group, path=path)
    return path


def _task(**overrides: object) -> Task:
    base: dict[str, object] = dict(id="T1", title="t", status="pending", priority="P1")
    base.update(overrides)
    # Assue #69: Every Task must have a file (single Writer)+ acceptance (verifiable).
    base.setdefault("files", [f"{base['id']}.py"])
    base.setdefault("acceptance", "Validated.")
    return Task(**base)  # type: ignore[arg-type]


def _errors(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "error"]


def _warnings(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "warning"]


def test_all_valid_reports_ok_no_issues(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(id="T1", files=["a.py"]),
            _task(id="T2", depends_on=["T1"], files=["b.py"]),
        ],
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert report.issues == []


def test_schema_violation_is_error(tmp_path: Path) -> None:
    # Illegal status count, handwritten frontmatter.
    (tmp_path / "0001-alpha.md").write_text(
        "---\n"
        'number: "0001"\n'
        "title: alpha\n"
        "issue: 1\n"
        "slug: alpha\n"
        "tasks:\n"
        "  - id: T1\n"
        "    title: t\n"
        "    status: bogus\n"
        "    priority: P1\n"
        "---\n\n# 0001 · alpha\n",
        encoding="utf-8",
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("bogus" in m for m in _errors(report))


def test_missing_required_frontmatter_is_error(tmp_path: Path) -> None:
    # Missing title（GROUP_FRONTMATTER_SCHEMA required）。
    (tmp_path / "0001-alpha.md").write_text(
        '---\nnumber: "0001"\nissue: 1\nslug: alpha\ntasks: []\n---\n\n# 0001 · alpha\n',
        encoding="utf-8",
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("title" in m for m in _errors(report))


def test_intra_group_file_overlap_is_error(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["shared.py"]), _task(id="T2", files=["shared.py"])],
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("claimed by multiple tasks" in m for m in _errors(report))


def test_cross_group_file_overlap_is_warning_only(tmp_path: Path) -> None:
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["x.py"])]
    )
    _group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["x.py"])]
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is True  # Wwarning doesn't affect ok
    assert any("Overlapping file ownership" in m for m in _warnings(report))
    assert _errors(report) == []


def test_dependency_cycle_is_error(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(id="T1", depends_on=["T2"], files=["a.py"]),
            _task(id="T2", depends_on=["T1"], files=["b.py"]),
        ],
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("Dependency cycle" in m for m in _errors(report))


def test_cross_group_dependency_to_missing_task_is_error(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", depends_on=["0002/T9"], files=["a.py"])],
    )
    _group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["b.py"])]
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("0002/T9" in m for m in _errors(report))


def test_relates_to_resolves_to_existing_task(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(id="T1", files=["a.py"], relates_to=[RelatesTo(ref="0002/T1", type="extends")])
        ],
    )
    _group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["b.py"])]
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is True


def test_status_abandoned_in_snapshot_is_error(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", status="abandoned", files=["a.py"])],
    )
    report = validate(specs_root=tmp_path)
    assert any("abandoned" in m for m in _errors(report))


def test_empty_summary_is_error(tmp_path: Path) -> None:
    """Spec-0015/T3: Group metadata.summary is empty error."""
    group = Group(
        number="0001",
        metadata=Metadata(title="alpha", issue=1, slug="alpha", summary="  "),
        tasks=[_task(id="T1", files=["a.py"])],
    )
    model.dump_group(
        group=group, path=model.group_path(specs_root=tmp_path, number="0001", slug="alpha")
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("metadata.summary is empty" in m for m in _errors(report))


def test_empty_specs_root_is_ok(tmp_path: Path) -> None:
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert report.issues == []


def test_missing_required_overview_section_is_error(tmp_path: Path) -> None:
    """Assue #69: Filling in a mandatory overview (e.g. Reference-level) is empty — error (sing specs contains / overview first)."""
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["a.py"])],
        overview=_overview(reference_level=""),
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("Reference-level" in m for m in _errors(report))


def test_bare_cross_spec_ref_is_warning(tmp_path: Path) -> None:
    """The following is a list of the ”see Spec-0012 Decision 8” strip-tickings in the overview:"""
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["a.py"])],
        overview=_overview(motivation="For further background, see Decision 8 for Spec-0012."),
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is True  # Only warning, no broken ok
    assert any("Spec-0012" in m for m in _warnings(report))


# --------------------------------------------------------------------------- #
# Spec-0040/T1: Group level e2e rough plan scrutinization (declaration only, rear compatibility)
# --------------------------------------------------------------------------- #


def _group_with_e2e(*, root: Path, e2e: E2EPlan | None) -> Path:
    """Put down a (or not) e2e-planned compliance group to facilitate the positive and negative example of _e2e_checks."""
    group = Group(
        number="0001",
        metadata=Metadata(title="alpha", issue=1, slug="alpha", summary="alpha TL;DR", e2e=e2e),
        tasks=[_task(id="T1", files=["a.py"])],
        overview=_overview(),
    )
    path = model.group_path(specs_root=root, number="0001", slug="alpha")
    model.dump_group(group=group, path=path)
    return path


def test_valid_e2e_block_is_ok(tmp_path: Path) -> None:
    """Spec-0055/T2: valid e2e (intent non-empty + method non-empty)  → no e2e associated error."""
    _group_with_e2e(
        root=tmp_path,
        e2e=E2EPlan(
            intent="Init no origin must be erroneously reported",
            method="Run init, assert non-zero exit + hint",
        ),
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert not any("e2e" in m for m in _errors(report))


def test_e2e_empty_intent_is_error(tmp_path: Path) -> None:
    _group_with_e2e(root=tmp_path, e2e=E2EPlan(intent="  ", method="Run."))
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("e2e.intent is empty" in m for m in _errors(report))


def test_e2e_empty_method_is_error(tmp_path: Path) -> None:
    _group_with_e2e(root=tmp_path, e2e=E2EPlan(intent="x", method="   "))
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("e2e.method is empty" in m for m in _errors(report))


def test_no_e2e_block_is_ok_zero_regression(tmp_path: Path) -> None:
    """No e2e already existing group: Validate does not report any e2e-related error (reward compatible)."""
    _group_with_e2e(root=tmp_path, e2e=None)
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert not any("e2e" in m for m in _errors(report))


def test_task_without_acceptance_is_schema_error(tmp_path: Path) -> None:
    """#69: Frontmatter missing acceptance #schema stopped."""
    (tmp_path / "0001-alpha.md").write_text(
        "---\n"
        'number: "0001"\n'
        "title: alpha\n"
        "issue: 1\n"
        "slug: alpha\n"
        "summary: x\n"
        "tasks:\n"
        "  - id: T1\n"
        "    title: t\n"
        "    status: pending\n"
        "    priority: P1\n"
        "    files: [a.py]\n"
        "---\n\n# 0001 · alpha\n",
        encoding="utf-8",
    )
    report = validate(specs_root=tmp_path)
    assert report.ok is False
    assert any("acceptance" in m for m in _errors(report))


def _n_tasks(n: int) -> list[Task]:
    """n Files 2-to-do minimum Task (estapping the same group of files overlaper, segregating the Task soft-number ceiling)."""
    return [_task(id=f"T{i}", files=[f"f{i}.py"]) for i in range(1, n + 1)]


def test_six_tasks_no_soft_cap_warning(tmp_path: Path) -> None:
    """Spec-0072/T2: Just like 6 Task (soft ceiling) cannot reach the number of times."""
    _group(root=tmp_path, number="0001", slug="alpha", issue=1, tasks=_n_tasks(6))
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert not any("readability soft cap" in m for m in _warnings(report))


def test_seven_tasks_warns_but_ok(tmp_path: Path) -> None:
    """Spec-0072/T2:7 Task and undeclared oversized-rationale  →  a warning but ok=True (non-stop)."""
    _group(root=tmp_path, number="0001", slug="alpha", issue=1, tasks=_n_tasks(7))
    report = validate(specs_root=tmp_path)
    assert report.ok is True  # Wwarning doesn't affect the big, feature a spec without the CI
    cap_warnings = [m for m in _warnings(report) if "readability soft cap" in m]
    assert len(cap_warnings) == 1
    assert "7 > 6" in cap_warnings[0]


def test_seven_tasks_with_rationale_is_silent(tmp_path: Path) -> None:
    """Spec-0072/T2:7 Task and a statement of oversized-rationale (atom delivery) silent, no number Task warning."""
    group = Group(
        number="0001",
        metadata=Metadata(
            title="alpha",
            issue=1,
            slug="alpha",
            summary="alpha TL;DR",
            oversized_rationale="One atomic delivery: breakup group e2e acceptance",
        ),
        tasks=_n_tasks(7),
        overview=_overview(),
    )
    path = model.group_path(specs_root=tmp_path, number="0001", slug="alpha")
    model.dump_group(group=group, path=path)
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert not any("readability soft cap" in m for m in _warnings(report))


def test_architecture_requires_selected_candidate_and_opposite_cases(tmp_path: Path) -> None:
    group = Group(
        number="0001",
        metadata=Metadata(
            title="a",
            issue=1,
            slug="a",
            summary="s",
            architecture=ArchitectureDecision(
                objective="o",
                candidates=[ArchitectureCandidate("runtime", "runtime")],
                selected="prompt",
            ),
            verification=VerificationPlan(
                behavior_cases=[BehaviorCase("p", "positive", "x", "y", "replay")]
            ),
        ),
        tasks=[_task()],
        overview=_overview(),
    )
    model.dump_group(
        group=group, path=model.group_path(specs_root=tmp_path, number="0001", slug="a")
    )
    errors = _errors(validate(specs_root=tmp_path))
    assert any("selected" in item for item in errors)
    assert any("positive/negative" in item for item in errors)


def test_duplicate_group_number_is_repository_error(tmp_path: Path) -> None:
    _group(root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task()])
    _group(root=tmp_path, number="0001", slug="beta", issue=2, tasks=[_task(id="T2")])
    assert any("Repeat" in item for item in _errors(validate(specs_root=tmp_path)))
