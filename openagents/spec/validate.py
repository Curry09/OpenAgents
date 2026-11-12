"""Validate Spec structure, task dependencies, and file ownership.

Check frontmatter schema, snapshot consistency, disjoint ownership within a
group, global dependency cycles, and task references. Cross-group ownership
overlaps are warnings. Validation does not read Git or forge state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from openagents.spec import model
from openagents.spec.model import Group
from openagents.spec.schema import GROUP_FRONTMATTER_SCHEMA

_ERROR = "error"
_WARNING = "warning"

# Spec-0072/T2: **Land ceiling for readability** (non-hard variable) for single group Task ** and undeclared oversized-range
# A Warning Active (non-error, large feature a spec/ a PR without CI). Different from groups
# The true variable of the cross-reference (_file_overlap_checks, error) - that is the root of parallel security, and this article is only a readable empirical value.
_TASK_SOFT_CAP = 6

# Assue #69: Single specs contains + a quality threshold for the header.
# The four lines are "read and understand without going through other specs" and are then added to the general section (attr, headline read) which is now available to the public.
_REQUIRED_SECTIONS: tuple[tuple[str, str], ...] = (
    ("summary", "Summary"),
    ("motivation", "Motivation"),
    ("reference_level", "Reference-level explanation"),
    ("rationale_alternatives", "Rationale and alternatives"),
)
# Suspected crossover. spec Bare reference:`Spec-0012`、`Spec-0012 Decision-making 8`、`Spec-0012/T2`。The call is repeated in the spot.
_BARE_REF_RE = re.compile(r"Spec-\d{4}(?:\s+(?i:decision)\s+\d+|/T\w+)?")


@dataclass(frozen=True)
class ValidationIssue:
    """Spec-0014/T2: Single verification problem."""

    # Spec-0014/T2：error | warning
    level: str
    # Spec-0014/T2: Positioning Thread, "0009/T3" or File Path
    where: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """Spec-0014/T2: A summary of a check. No error, no ok (warning does not affect ok)."""

    ok: bool
    issues: list[ValidationIssue]


def validate(*, specs_root: Path) -> ValidationReport:
    """Run the full schema + semantic validation chain over a specs tree.

    Spec-0014/T2: Run six chains in sequence, issues; no error, ok=True.
    """
    issues: list[ValidationIssue] = []

    # 1. JSON Schema: Validation of the structure and count of original YAML files (before model easing is standardized).
    issues.extend(_schema_checks(specs_root=specs_root))

    # The subsequent semantic verification is based on the structured object loaded by model.
    groups = model.load_all(specs_root=specs_root)

    issues.extend(_identity_checks(groups=groups))
    issues.extend(_architecture_checks(groups=groups))

    # 2. Status with history.
    issues.extend(_status_checks(groups=groups))
    # 3. No overlap between groups (error); 6. Overlap between groups (warning).
    issues.extend(_file_overlap_checks(groups=groups))
    # 4. Global depends-on DAG ringless.
    issues.extend(_dag_acyclic_checks(groups=groups))
    # 5. Blood / cross-group reference points to the existence of a Task.
    issues.extend(_reference_checks(groups=groups))
    # 7. metadata.summary is empty (Spec-0015/T3: every feature must be spoken to TL; DR).
    issues.extend(_summary_checks(groups=groups))
    # 8. The summary section will not be empty (issue #69: overview first line). ->error
    issues.extend(_overview_required_checks(groups=groups))
    # 9. The overview appears to be transposed to the spec bare reference (issue #69: single spec self-incorporated). ->warning
    issues.extend(_self_contained_checks(groups=groups))
    # 10. e2e rough planner block (declaration only): valid / incent non-empty / acceptance  → oror.
    issues.extend(_e2e_checks(groups=groups))
    # Single group Task Numeric Upper limit (Spec-0072: > 6 and undeclared oversized-rationale). -warning
    issues.extend(_task_count_checks(groups=groups))

    ok = not any(issue.level == _ERROR for issue in issues)
    return ValidationReport(ok=ok, issues=issues)


def _identity_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Reject duplicate group numbers and slugs in the candidate tree."""
    issues: list[ValidationIssue] = []
    for attr in ("number", "slug"):
        seen: dict[str, list[str]] = {}
        for group in groups:
            value = group.number if attr == "number" else group.metadata.slug
            seen.setdefault(value, []).append(f"{group.number}-{group.metadata.slug}")
        for value, identities in seen.items():
            if len(identities) > 1:
                issues.append(
                    ValidationIssue(_ERROR, "repository", f"Repeat {attr} {value!r}：{identities}")
                )
    return issues


def _architecture_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Validate architecture/verification cross-field invariants."""
    issues: list[ValidationIssue] = []
    for group in groups:
        architecture = group.metadata.architecture
        verification = group.metadata.verification
        if architecture is None and verification is None:
            continue
        if architecture is None or verification is None:
            issues.append(
                ValidationIssue(
                    _ERROR,
                    f"{group.number}/architecture",
                    "Declare architecture and verification together",
                )
            )
            continue
        ids = [candidate.id for candidate in architecture.candidates]
        if len(ids) != len(set(ids)):
            issues.append(
                ValidationIssue(
                    _ERROR, f"{group.number}/architecture", "Duplicate architecture candidate ID"
                )
            )
        if architecture.selected not in ids:
            issues.append(
                ValidationIssue(
                    _ERROR,
                    f"{group.number}/architecture",
                    "architecture.selected must reference a declared candidate ID",
                )
            )
        polarities = {case.polarity for case in verification.behavior_cases}
        if not verification.exemptions and polarities != {"positive", "negative"}:
            issues.append(
                ValidationIssue(
                    _ERROR,
                    f"{group.number}/verification",
                    "positive/negative case, or give reasons for exemption",
                )
            )
        if any(not reason.strip() for reason in verification.exemptions):
            issues.append(
                ValidationIssue(
                    _ERROR, f"{group.number}/verification", "Exemption Reasons Not Empty"
                )
            )
    return issues


def _e2e_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Spec-0055/T2: Stabilization of the group e2e measurements - ** There is no validation until ** (no no behavior change, backward compatibility).

    e2e block statement: incent goes to empty after blank, method goes empty after blank, and each newspaper is empty.
    Type (intent/method is string), which adds the semantic threshold (and with) of the whitespace-only schema that cannot be stopped
    _summary_checks Same style. form/acceptance has been decommissioned with Spec-0055 and no longer verified.
    """
    issues: list[ValidationIssue] = []
    for group in groups:
        e2e = group.metadata.e2e
        if e2e is None:
            continue
        where = f"{group.number}/e2e"
        if not e2e.intent.strip():
            issues.append(
                ValidationIssue(
                    level=_ERROR,
                    where=where,
                    message="e2e.intent is empty (the intent to verify the results must be stated)",
                )
            )
        if not e2e.method.strip():
            issues.append(
                ValidationIssue(
                    level=_ERROR,
                    where=where,
                    message="e2e.method is empty (the prose measurement step to be stated)",
                )
            )
    return issues


def _task_count_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Spec-0072/T2: Single group Task > soft ceiling (6) and undeclared oversized-rationale  →  warning (non-error).

    6 It’s just readability./The value of the assessable experience is not a parallel security variable. files Crust, see. _file_overlap_checks）。
    So >6 only one warning tip ”confirms atom delivery or grouping” does not affect the ok- natural > 6 work unit
    Large feature legally stays in a spec/ a PR. Author in group frontmatter declare oversized-range
    That is, it is confirmed that this is an atom delivery and silently the hint (softly agreed stylization: a mark must be left over the soft ceiling, not passed quietly).
    """
    issues: list[ValidationIssue] = []
    for group in groups:
        if len(group.tasks) <= _TASK_SOFT_CAP:
            continue
        if group.metadata.oversized_rationale.strip():
            continue
        issues.append(
            ValidationIssue(
                level=_WARNING,
                where=f"{group.number}/tasks",
                message=(
                    f"Group Task Number {len(group.tasks)} > {_TASK_SOFT_CAP} (readability soft cap): "
                    "set oversized-rationale for an atomic delivery or split the group"
                ),
            )
        )
    return issues


def _overview_required_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Assue #69: Each group must fill in a summary section to leave blank, otherwise error (take first, read and understand)."""
    issues: list[ValidationIssue] = []
    for group in groups:
        for attr, label in _REQUIRED_SECTIONS:
            if not getattr(group.overview, attr).strip():
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=f"{group.number}/overview",
                        message=f"”Was to fill in the overview session”{label}* Empty (sing sec contains itself, overview first)",
                    )
                )
    return issues


def _self_contained_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Warn when a Spec may depend on a bare reference to another Spec."""
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
                            f"Possible bare Spec reference {match.group(0)!r}. "
                            "Restate any context required to understand this Spec (issue #69)."
                        ),
                    )
                )
    return issues


def _summary_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Spec-0015/T3: metadata.summary for each group goes empty after empty, otherwise error."""
    issues: list[ValidationIssue] = []
    for group in groups:
        if not group.metadata.summary.strip():
            issues.append(
                ValidationIssue(
                    level=_ERROR,
                    where=f"{group.number}/frontmatter",
                    message="metadata.summary is empty; add a short group summary",
                )
            )
    return issues


def _schema_checks(*, specs_root: Path) -> list[ValidationIssue]:
    """JSON Schema validates the frontmatter of each group markdown file; one error per error."""
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
    """Scattershots should not contain abandoned; there are historical version numbers that are strictly incremental and the current version is higher than the last edition of history."""
    issues: list[ValidationIssue] = []
    for group in groups:
        for task in group.tasks:
            where = model.qualified_id(group=group.number, task_id=task.id)
            # Abandoned can only remain in history and cannot remain in the snapshot (decision D2).
            if task.status == "abandoned":
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=where,
                        message="The status=abandoned Task should go to history instead of a snapshot",
                    )
                )
            history = group.history.get(task.id, [])
            if not history:
                continue
            versions = [item.version for item in history]
            # The historical version is strictly incremental.
            if any(b <= a for a, b in zip(versions, versions[1:], strict=False)):
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=where,
                        message=f"History version number is not strictly incremental:{versions}",
                    )
                )
            # The current edition must be higher than the last edition of history.
            if task.version <= max(versions):
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=where,
                        message=f"Current V{task.version} Not higher than the last of history v{max(versions)}",
                    )
                )
    return issues


def _file_overlap_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Group of Fields overlap  →  error; cross group of Fields overlap  →  warning (decision D7)."""
    issues: list[ValidationIssue] = []
    # file -> {group_number -> [task_id, ...]}
    owners: dict[str, dict[str, list[str]]] = {}
    for group in groups:
        for task in group.tasks:
            for path in task.files:
                owners.setdefault(path, {}).setdefault(group.number, []).append(task.id)

    for path, by_group in sorted(owners.items()):
        # A file must have a single owning task within a group.
        for number, task_ids in sorted(by_group.items()):
            if len(task_ids) > 1:
                joined = ", ".join(sorted(task_ids))
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=number,
                        message=f"File {path} is claimed by multiple tasks in this group: {joined}",
                    )
                )
        # Overlaps between groups are advisory.
        if len(by_group) > 1:
            groups_str = ", ".join(sorted(by_group))
            issues.append(
                ValidationIssue(
                    level=_WARNING,
                    where=path,
                    message=f"Overlapping file ownership for {path}: groups {groups_str}",
                )
            )
    return issues


def _dag_acyclic_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Global depends-on (including cross-group) are unringed; there is a narration error."""
    # 1. Structure: Node = current version of Task-limit ID; Edge = depends-on (desolation to quant ID).
    current_ids = _current_ids(groups=groups)
    adjacency: dict[str, list[str]] = {}
    for group in groups:
        for task in group.tasks:
            node = model.qualified_id(group=group.number, task_id=task.id)
            targets = [_resolve_ref(ref=ref, group=group.number) for ref in task.depends_on]
            # Only the existing nodes are sided; reference verification reports are pointed to non-existent.
            adjacency[node] = [t for t in targets if t in current_ids]

    # 2. DFS detection ring.
    cycle = _find_cycle(adjacency=adjacency)
    if cycle is None:
        return []
    return [
        ValidationIssue(
            level=_ERROR,
            where=cycle[0],
            message=f"Dependency cycle: {' -> '.join(cycle)}",
        )
    ]


def _reference_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Task (current or historical) must exist, as quoted in the depends-on / relates-to / blood fields."""
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
                            message=f"{field_name} Task:{ref}",
                        )
                    )
    return issues


def _validate_doc(*, data: object, json_schema: dict, where: str) -> list[ValidationIssue]:
    """Runs for a single document, JSON Schema, and each error yields one error issue."""
    validator = Draft202012Validator(json_schema)
    issues: list[ValidationIssue] = []
    for error in sorted(validator.iter_errors(data), key=str):
        location = "/".join(str(part) for part in error.absolute_path)
        prefix = f"{where}:{location}" if location else where
        issues.append(ValidationIssue(level=_ERROR, where=prefix, message=error.message))
    return issues


def _current_ids(*, groups: list[Group]) -> set[str]:
    """The limited ID collection of all current versions of Task."""
    return {
        model.qualified_id(group=group.number, task_id=task.id)
        for group in groups
        for task in group.tasks
    }


def _known_ids(*, groups: list[Group]) -> set[str]:
    """Task = current version of the  →  history version (blood can point to abandoned/old version of the Task)."""
    known = _current_ids(groups=groups)
    for group in groups:
        for task_id in group.history:
            known.add(model.qualified_id(group=group.number, task_id=task_id))
    return known


def _resolve_ref(*, ref: str, group: str) -> str:
    """T3  →  Limit group/T3; already containing ’/ ’is considered as cross-group limited ID returns as it is."""
    return ref if "/" in ref else model.qualified_id(group=group, task_id=ref)


def _find_cycle(*, adjacency: dict[str, list[str]]) -> list[str] | None:
    """DFS search a ring path (node sequence, end of end); return None unringed."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in adjacency}
    stack: list[str] = []

    def _dfs(node: str) -> list[str] | None:
        color[node] = GRAY
        stack.append(node)
        for nxt in adjacency.get(node, []):
            if color.get(nxt, BLACK) == GRAY:
                # Strikes a gray node ring; intercepts a segment from the node in the cage.
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
