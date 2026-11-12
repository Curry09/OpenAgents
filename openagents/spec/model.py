"""Read and write numbered Markdown Specs with structured YAML frontmatter.

The frontmatter stores group metadata and Tasks. Nine canonical RFC-style
headings divide the design overview. Dated design records and generated views
are not numbered groups.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

# Uniform YaML round-trip example (for frontmotter).
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096
_yaml.indent(mapping=2, sequence=4, offset=2)

# frontmatter Every one of them. Task Structure field order (yaml_key, attr）。dump always follow this order, and the key is stable.
# Note: version/lineage/change-reason, etc., retired from the historical mechanism (decision D3), no longer going to frontmotter.
# The scope/acceptance is changed from text prose to frontmatter (Task is degraded into a task breakup).
# Heavy prose up to group Overview.
_TASK_FM_ORDER: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("title", "title"),
    ("status", "status"),
    ("priority", "priority"),
    ("tags", "tags"),
    ("depends-on", "depends_on"),
    ("relates-to", "relates_to"),
    ("parallel", "parallel"),
    ("files", "files"),
    ("scope", "scope"),
    ("acceptance", "acceptance"),
)

# Assue #69: The body of the group = rust-RFC 9 paragraph overview (markdown title, Overview property), dump in this order.
# A single read-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-up-out-out-up-out-out-up-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-out-
_OVERVIEW_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Summary", "summary"),
    ("Motivation", "motivation"),
    ("Guide-level explanation", "guide_level"),
    ("Reference-level explanation", "reference_level"),
    ("Drawbacks", "drawbacks"),
    ("Rationale and alternatives", "rationale_alternatives"),
    ("Prior art", "prior_art"),
    ("Unresolved questions", "unresolved_questions"),
    ("Future possibilities", "future_possibilities"),
)
_SECTION_BY_HEADING = {heading: attr for heading, attr in _OVERVIEW_SECTIONS}

# Body-toe split: group header `## Summary` / `## Reference-level explanation`...
_SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")

# Spec new scaffolding: non-empty (to make a paragraph title), but _strip_placeholder is one empty string.
_PLACEHOLDER = "<!-- TODO -->"


@dataclass(frozen=True)
class RelatesTo:
    """Non-blocked crossfeature association (render drawing of a dash)."""

    # Cross-group restricted ID, e. g. "0012/T2"
    ref: str
    # Association type
    type: str


@dataclass
class Task:
    """A single spec Task — a breakout line for DAG+ file distribution (issue #69 has been reduced to structuralized).

    Structured fields (status/priority/depends-on/files...) with frontmatter, machine-readable;
    Asset #69, feature design description up to group Overview, Task leaves only two short lines prose
    (scope/acceptance) and both also put frontmotter -- `files` is a single Writer ownership declaration
    (Structural source of 6 /issue #71 run-time owner check).

    version/lineage Fields to be kept in the data class (with default values) to minimize render Change (decision-making) D2），
    But the historical mechanism is no longer written by frontmatter, Group.history.
    """

    # Identities and status ─
    id: str
    title: str
    status: str
    priority: str
    tags: list[str] = field(default_factory=list)
    # ─ Relationship ─ ─
    depends_on: list[str] = field(default_factory=list)
    relates_to: list[RelatesTo] = field(default_factory=list)
    parallel: bool = False
    files: list[str] = field(default_factory=list)
    # ─ Evolution / blood (retain default, D3 decision not active) _
    version: int = 1
    updated: str = ""
    change_reason: str = ""
    supersedes: list[str] = field(default_factory=list)
    split_from: str | None = None
    merged_from: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    # ─ Work decomposition short prose (in front matter; re-design description in group Overview) -
    scope: str = ""
    acceptance: str = ""


@dataclass(frozen=True)
class Overview:
    """Group Rust-RFC 9 Summary (issue #69) - full self-inclusion description of feature, in markdown text.

    Single spec self: read this 9 paragraph to understand this feature without opening other specs; DAG+file distribution
    reference_level. Field names correspond to the attr of `_OVERVIEW_SECTIONS`.
    """

    summary: str = ""
    motivation: str = ""
    guide_level: str = ""
    reference_level: str = ""
    drawbacks: str = ""
    rationale_alternatives: str = ""
    prior_art: str = ""
    unresolved_questions: str = ""
    future_possibilities: str = ""


@dataclass(frozen=True)
class E2EPlan:
    """Spec-0055/T2: Group e2e Measurement - RFC stage states ”What + How to do it”, and executo runs directly following it.

    The `intent` message (freezing after the RFC gate, tautology gard feed point) is a ”dating, checking, what, how”:
    `method` a prose measurement (how to measure human voice steps,** does not contain precise orders** - orders are to be knocked by executor when running).
    Skinned from {form,intent,acceptance[]}: cut off form
    Acceptance (and go to method). The whole block is optional (Metadata.e2e default None) - Non-interactive PR does not declare or zero returns.
    """

    intent: str = ""
    method: str = ""


@dataclass(frozen=True)
class ArchitectureCandidate:
    """Represent one technically viable intervention candidate."""

    id: str
    layer: str
    boundary: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    tradeoffs: str = ""


@dataclass(frozen=True)
class ArchitectureDecision:
    """Capture the implementation-side architecture decision."""

    objective: str = ""
    constraints: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    candidates: list[ArchitectureCandidate] = field(default_factory=list)
    selected: str = ""
    affected_components: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BehaviorCase:
    """Describe one positive or negative observable behavior case."""

    id: str
    polarity: str
    stimulus: str
    expected: str
    observation: str


@dataclass(frozen=True)
class VerificationPlan:
    """Index behavioral evidence and repository invariants."""

    behavior_cases: list[BehaviorCase] = field(default_factory=list)
    repository_invariants: list[str] = field(default_factory=list)
    exemptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Metadata:
    """Group metadata (a spec group = a issue/feature)."""

    title: str
    issue: int
    slug: str
    # Spec-0015: Summarize the feature in plain language for the overview.
    # Default empty string compatible with old call points; non-empty validate It's... _summary_checks Forced.
    summary: str = ""
    # Spec-0072/T1: Group-level "Atom Delivery" declaration (optional). Default empty string = undeclared (existing spec no behavior change);
    # The non-empty-estate declaration group is an atomic delivery, exempting >6 Task soft caps from the warning (validate._task_count_checks).
    oversized_rationale: str = ""
    # Spec-0040/T1: Group e2e rough plan (optional). None = undeclared (spec zero returns); non-None by
    # validate._e2e_checks forces form/ inent non-empty/ acceptance1.
    e2e: E2EPlan | None = None
    architecture: ArchitectureDecision | None = None
    verification: VerificationPlan | None = None


@dataclass(frozen=True)
class Group:
    """All source data for a spec group. Always empty in the markdown form (decision D3)."""

    # Four-digit "0009" (compatible with old RFC number 1:1)
    number: str
    metadata: Metadata
    # Current Task Scatter
    tasks: list[Task]
    # Missue #69: Group Rust-RFC 9 Summary (feature full, text)
    overview: Overview = field(default_factory=Overview)
    # Decommission: Keep field to keep render/validate unchanged, always empty
    history: dict[str, list[Task]] = field(default_factory=dict)


def qualified_id(*, group: str, task_id: str) -> str:
    """Build a cross-group qualified task id like "0009/T3"."""
    return f"{group}/{task_id}"


def group_path(*, specs_root: Path, number: str, slug: str) -> Path:
    """Group markdown file path docs/specs/NNNN-slug.md."""
    return specs_root / f"{number}-{slug}.md"


def load_group(*, path: Path) -> Group:
    """Load one spec group from a markdown file (frontmatter + body).

    frontmatter Provide cluster metadata and other data Task structured fields; text by ’## <rust Section Name>’ Cut out the group
    Overview, paragraph 9 (issue #69).
    """
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text=text)
    number = str(meta.get("number") or path.name[:4]).zfill(4)
    metadata = Metadata(
        title=str(meta.get("title", "")),
        issue=int(meta.get("issue", 0)),
        slug=str(meta.get("slug", "")),
        summary=str(meta.get("summary", "")),
        # Spec-0072/T1: Missing or empty string (established spec zero returns).
        oversized_rationale=str(meta.get("oversized-rationale", "")),
        e2e=e2e_from_mapping(data=meta.get("e2e")),  # Spec-0040/T1: No e2e block none.
        architecture=architecture_from_mapping(data=meta.get("architecture")),
        verification=verification_from_mapping(data=meta.get("verification")),
    )

    overview = _parse_body(body=body)
    tasks = [task_from_mapping(data=raw) for raw in meta.get("tasks") or []]

    return Group(number=number, metadata=metadata, tasks=tasks, overview=overview, history={})


def load_all(*, specs_root: Path) -> list[Group]:
    """Load every spec group markdown file under specs_root (sorted by number).

    Only group files `NNNN-slug.md` (slug as letter, exclude deded design document `YYYY-MM-DD-*.md`
    With OVERVIEW.md / ARCHITECTURE.md / README.md; empty warehouse returns [].
    """
    if not specs_root.is_dir():
        return []
    groups: list[Group] = []
    for md_path in sorted(specs_root.glob("*.md")):
        if _is_group_file(name=md_path.name):
            groups.append(load_group(path=md_path))
    return groups


def dump_group(*, group: Group, path: Path) -> None:
    """Write a Group to a markdown file (frontmatter + body), deterministically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_group(group=group), encoding="utf-8")


def render_group(*, group: Group) -> str:
    """Serialize a Group to markdown text (frontmatter + body). Pure."""
    fm = CommentedMap()
    fm["number"] = DoubleQuotedScalarString(group.number)
    fm["title"] = group.metadata.title
    fm["issue"] = group.metadata.issue
    fm["slug"] = group.metadata.slug
    fm["summary"] = group.metadata.summary
    # Spec-0072/T1: Oversized-rationale only writes at the time of the declaration (not empty), and is attached to e2e/tasks after the summy;
    # Do not declare or the whole key appears, keeping the spec byte and no behavior change.
    if group.metadata.oversized_rationale:
        fm["oversized-rationale"] = group.metadata.oversized_rationale
    # Spec-0040/T1:e2e Crude plan only writes frontmatter (None, whole block does not appear, maintains an existing spec byte) when making the statement
    # No change, no return. The group metadata identity is the same after the summary and before the tasks.
    if group.metadata.e2e is not None:
        fm["e2e"] = _e2e_frontmatter(e2e=group.metadata.e2e)
    if group.metadata.architecture is not None:
        fm["architecture"] = CommentedMap(_plain_architecture(value=group.metadata.architecture))
    if group.metadata.verification is not None:
        fm["verification"] = CommentedMap(_plain_verification(value=group.metadata.verification))
    fm["tasks"] = [_task_frontmatter(task=task) for task in group.tasks]

    buf = StringIO()
    _yaml.dump(fm, buf)
    fm_text = buf.getvalue()

    title = group.metadata.title or group.metadata.slug
    head = (
        f"---\n{fm_text}---\n\n"
        f"# {group.number} · {title}\n\n"
        "<!-- The spec CLI maintains this file. Frontmatter contains metadata and the task DAG; "
        "the body is a nine-section Rust RFC-style overview. -->\n"
    )
    body = _render_body(group=group)
    return head + ("\n" + body if body else "") + "\n"


def next_number(*, specs_root: Path) -> str:
    """Return the next free 4-digit group number (max existing + 1, "0001" if none)."""
    highest = 0
    for group in load_all(specs_root=specs_root):
        try:
            highest = max(highest, int(group.number))
        except ValueError:
            continue
    return f"{highest + 1:04d}"


def task_from_mapping(*, data: object) -> Task:
    """Build a Task from a frontmatter task mapping (structured fields only)."""
    raw = data or {}
    relates = [
        RelatesTo(ref=str(item.get("ref", "")), type=str(item.get("type", "")))
        for item in (raw.get("relates-to") or [])
    ]
    return Task(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        status=str(raw.get("status", "")),
        priority=str(raw.get("priority", "")),
        tags=_str_list(value=raw.get("tags")),
        depends_on=_str_list(value=raw.get("depends-on")),
        relates_to=relates,
        parallel=bool(raw.get("parallel", False)),
        files=_str_list(value=raw.get("files")),
        scope=str(raw.get("scope", "")),
        acceptance=str(raw.get("acceptance", "")),
    )


def e2e_from_mapping(*, data: object) -> E2EPlan | None:
    """Spec-0055/T2: FrontMatter e2e map  →  E2Eplan; Missing (None) returns None (both spec no behavior change).

    Easier integration (similar to task_from_mapping): intent/method rotation st; non-empty forced by validate._e2e_checks,
    This function does not render emptiness. The old {form,acceptance} key is ignored (additionalProperties =False reports in validate, moving to Spec-0056).
    """
    if data is None:
        return None
    raw = data or {}
    return E2EPlan(
        intent=str(raw.get("intent", "")),
        method=str(raw.get("method", "")),
    )


def architecture_from_mapping(*, data: object) -> ArchitectureDecision | None:
    """Parse an optional architecture decision from frontmatter."""
    if data is None:
        return None
    raw = data or {}
    return ArchitectureDecision(
        objective=str(raw.get("objective", "")),
        constraints=_str_list(value=raw.get("constraints")),
        non_goals=_str_list(value=raw.get("non-goals")),
        candidates=[
            ArchitectureCandidate(
                id=str(item.get("id", "")),
                layer=str(item.get("layer", "")),
                boundary=_str_list(value=item.get("boundary")),
                evidence=_str_list(value=item.get("evidence")),
                tradeoffs=str(item.get("tradeoffs", "")),
            )
            for item in raw.get("candidates") or []
        ],
        selected=str(raw.get("selected", "")),
        affected_components=_str_list(value=raw.get("affected-components")),
        failure_modes=_str_list(value=raw.get("failure-modes")),
    )


def verification_from_mapping(*, data: object) -> VerificationPlan | None:
    """Parse an optional behavioral verification plan from frontmatter."""
    if data is None:
        return None
    raw = data or {}
    return VerificationPlan(
        behavior_cases=[
            BehaviorCase(
                id=str(item.get("id", "")),
                polarity=str(item.get("polarity", "")),
                stimulus=str(item.get("stimulus", "")),
                expected=str(item.get("expected", "")),
                observation=str(item.get("observation", "")),
            )
            for item in raw.get("behavior-cases") or []
        ],
        repository_invariants=_str_list(value=raw.get("repository-invariants")),
        exemptions=_str_list(value=raw.get("exemptions")),
    )


def design_digest(*, group: Group) -> str:
    """Return versioned design semantics with explicit self-task references normalized.

    Spec-0088/T1: only prose self references are relocatable, not files or dependencies.
    """
    payload = _design_payload(group=group)
    # 1. Only explicit references to this group's existing tasks have identity semantics.
    pattern = re.compile(rf"(?<![\w/.-])Spec-{re.escape(group.number)}/(T[0-9]+)(?![\w/-]|\.\w)")
    task_ids = {task.id for task in group.tasks}
    for key in ("architecture", "verification", "overview"):
        payload[key] = _normalize_self_refs(value=payload[key], pattern=pattern, task_ids=task_ids)
    for task in payload["tasks"]:
        for key in ("title", "scope", "acceptance"):
            task[key] = _normalize_self_refs(value=task[key], pattern=pattern, task_ids=task_ids)
    return "v2:" + _payload_digest(payload=payload)


def legacy_design_digest(*, group: Group) -> str:
    """Retain the exact pre-v2 design hash for audit and old approvals (Spec-0088/T1)."""
    return _payload_digest(payload=_design_payload(group=group))


def _normalize_self_refs(*, value: object, pattern: re.Pattern[str], task_ids: set[str]) -> object:
    """Encode self references as typed segments, never a text sentinel (Spec-0088/T1)."""
    if isinstance(value, dict):
        return {
            key: _normalize_self_refs(value=item, pattern=pattern, task_ids=task_ids)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _normalize_self_refs(value=item, pattern=pattern, task_ids=task_ids) for item in value
        ]
    if not isinstance(value, str):
        return value
    parts: list[object] = []
    offset = 0
    for match in pattern.finditer(value):
        if match.group(1) in task_ids:
            parts.extend((value[offset : match.start()], {"self-task": match.group(1)}))
            offset = match.end()
    return {"prose": parts + [value[offset:]]} if parts else value


def _design_payload(*, group: Group) -> dict:
    """Build the original status-independent design payload (Spec-0088/T1)."""
    return {
        "architecture": _plain_architecture(value=group.metadata.architecture),
        "verification": _plain_verification(value=group.metadata.verification),
        "overview": {attr: getattr(group.overview, attr) for _, attr in _OVERVIEW_SECTIONS},
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "priority": t.priority,
                "depends-on": t.depends_on,
                "files": t.files,
                "scope": t.scope,
                "acceptance": t.acceptance,
            }
            for t in group.tasks
        ],
    }


def _payload_digest(*, payload: dict) -> str:
    """Hash a deterministic design representation (Spec-0088/T1)."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _plain_architecture(*, value: ArchitectureDecision | None) -> dict | None:
    if value is None:
        return None
    return {
        "objective": value.objective,
        "constraints": value.constraints,
        "non-goals": value.non_goals,
        "candidates": [
            {
                "id": c.id,
                "layer": c.layer,
                "boundary": c.boundary,
                "evidence": c.evidence,
                "tradeoffs": c.tradeoffs,
            }
            for c in value.candidates
        ],
        "selected": value.selected,
        "affected-components": value.affected_components,
        "failure-modes": value.failure_modes,
    }


def _plain_verification(*, value: VerificationPlan | None) -> dict | None:
    if value is None:
        return None
    return {
        "behavior-cases": [
            {
                "id": c.id,
                "polarity": c.polarity,
                "stimulus": c.stimulus,
                "expected": c.expected,
                "observation": c.observation,
            }
            for c in value.behavior_cases
        ],
        "repository-invariants": value.repository_invariants,
        "exemptions": value.exemptions,
    }


def _e2e_frontmatter(*, e2e: E2EPlan) -> CommentedMap:
    """E2Eplan  → frontmetter CommentedMap (fixed key order intent/method)."""
    out = CommentedMap()
    out["intent"] = e2e.intent
    out["method"] = e2e.method
    return out


def _task_frontmatter(*, task: Task) -> CommentedMap:
    """Task curtmetter CommentedMap (structured fields only, fixed keys)."""
    out = CommentedMap()
    for yaml_key, attr in _TASK_FM_ORDER:
        value = getattr(task, attr)
        if attr == "relates_to":
            out[yaml_key] = [
                CommentedMap([("ref", item.ref), ("type", item.type)]) for item in value
            ]
        else:
            out[yaml_key] = value
    return out


def _render_body(*, group: Group) -> str:
    """Group rust-RFC 9 Summary of paragraphs (%2)issue #69）: always output all ’## <Section Name>’, empty slot fills.

    The Scaffolding (spec new) is always in shape, and the ”sum-head” structure is acclaimable/verifiable.
    """
    chunks: list[str] = []
    for heading, attr in _OVERVIEW_SECTIONS:
        text = getattr(group.overview, attr).rstrip()
        chunks.append(f"## {heading}\n\n{text or _PLACEHOLDER}\n")
    return "\n".join(chunks)


def _split_frontmatter(*, text: str) -> tuple[dict, str]:
    """Removes the YaML frontmatter (first paragraph ---... ---) and the subsequent body. No frontmatter returns ((), text)."""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    meta = _yaml.load(fm_text) if fm_text.strip() else None
    return (meta or {}), body


def _parse_body(*, body: str) -> Overview:
    """Text → Group Overview（issue #69）。Press ’## <rust Section Name>’ Cut; placeholder is empty."""
    sections: dict[str, str] = {}
    current_attr: str | None = None
    buffer: list[str] = []

    def _flush() -> None:
        if current_attr is not None:
            sections[current_attr] = _strip_placeholder(text="\n".join(buffer).strip("\n"))

    for line in body.split("\n"):
        heading_match = _SECTION_HEADING_RE.match(line)
        if heading_match and heading_match.group(1) in _SECTION_BY_HEADING:
            _flush()
            current_attr = _SECTION_BY_HEADING[heading_match.group(1)]
            buffer = []
            continue
        buffer.append(line)
    _flush()
    return Overview(**sections)


def _strip_placeholder(*, text: str) -> str:
    """The slots of `<!-- TODO -->`-only are empty (spec new scaffolds and real empty segments)."""
    return "" if text.strip() == _PLACEHOLDER else text


def _is_group_file(*, name: str) -> bool:
    """Whether or not the filename groups the `NNNN-slug.md` files (slug from four-digit + ’-’+ letters).

    Exclude dated Design Document `YYYY-MM-DD-*.md`(No.) 6 Bits are numbers) and the generator/README。
    """
    return bool(re.match(r"^\d{4}-[A-Za-z][^/]*\.md$", name))


def _str_list(*, value: object) -> list[str]:
    """List fields are unified into list[str]; None  →  []."""
    if value is None:
        return []
    return [str(item) for item in value]
