# Spec-0064/T1
"""Load and validate the project configuration in .openagents/openagents.yml."""

from __future__ import annotations

import importlib.resources
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from openagents.utils import github
from openagents.utils.forge import FORGE_GITEA, FORGE_GITHUB

# Spec-0081/T3: Stage allows only automatic execution or visible jump; manual owner is decommissioned.
OWNER_AGENT = "agent"  # Automation of this gate (red automatically calls back implementer, not "agent objective fact" see dividing line)
OWNER_SKIP = "skip"  # Do not set this gate (when PASS is released)

# Spec-0064/T1: Seven** entangible ** stage names + each of the lawful values (not all gates are in 3 states) - see spec Reference-level
# "Legally takes value" column. conflict/merge is always automated and therefore cannot be sskip; refc drafts only agent or not (skip).
STAGE_TRIAGE = "triage"
STAGE_RFC = "rfc"
STAGE_ARCHITECTURE = "architecture"
STAGE_CONFLICT = "conflict"
STAGE_CI = "ci"
STAGE_E2E = "e2e"
STAGE_REVIEW = "review"
STAGE_MERGE = "merge"

_STAGE_VALID_OWNERS: dict[str, tuple[str, ...]] = {
    STAGE_TRIAGE: (OWNER_AGENT, OWNER_SKIP),
    STAGE_RFC: (OWNER_AGENT, OWNER_SKIP),
    STAGE_ARCHITECTURE: (OWNER_AGENT, OWNER_SKIP),
    STAGE_CONFLICT: (OWNER_AGENT,),
    STAGE_CI: (OWNER_AGENT, OWNER_SKIP),
    STAGE_E2E: (OWNER_AGENT, OWNER_SKIP),
    STAGE_REVIEW: (OWNER_AGENT, OWNER_SKIP),
    STAGE_MERGE: (OWNER_AGENT,),
}

# Spec-0064/T1: built-in defaults statuss -** all parties** (full automatic merger with merge=agent)
# Make users who do not write YaML feel zero (underdiggled Drawbacks' = hard-coding behavior today).
# The "no zero gate" guard (review in merge can stand up to it).
_DEFAULT_STAGES: dict[str, str] = {stage: OWNER_AGENT for stage in _STAGE_VALID_OWNERS}

# Spec-0064/T1: Default for known agent role  →  backend map (backends/ Currently only claude_code, concept 2 statement side
# Saves the schema bits, mixes codex/nexau. The role is all in one, and the `agents` section can be covered by the role-by-role back.
_ROLES = (
    "triager",
    "drafter",
    "architect",
    "spec_writer",
    "implementer",
    "executor",
    "acceptance",
    "reviewer",
    "replier",
    "deliver",
)
_DEFAULT_BACKEND = "claude_code"

# Spec-0082/T1: delivery profile.  Standard remains the compatibility default; minimal replaces
# only the subjective solve/review/merge decisions while reusing the same scheduler and hard gates.
FLOW_STANDARD = "standard"
FLOW_MINIMAL = "minimal"
FLOW_GENERATE_ONLY = "generate-only"

# Spec-0064/T1: Prefined Hardgate Name (`runtime.gates`) - Constant Machine, Constant, Skip Unable to Off (safe from #140
# See the bottom line in the second bound, where `stages` is written as a blunder, separates the term "compatible phase" from the word "hard bottom line" to reinforce the layer.
_HARDGATE_NAMES = ("head-advanced", "evidence-stamp", "round-cap")
# Spec-0064/T1: Constant agent, uncompatible phase (written/delivered forever agent, no "who takes the level" option), write in stages and reject.
_ALWAYS_AGENT_STAGES = ("implement", "deliver")

# Spec-0064/T1: Top-up development policy - manual (people decide when to use the most secure version, default)/ auto (main green+no BLONKED)
# Auto-animal, we'll have another deal. See. Future）。No, I'm not. `stages`：release It's a cross. issue A warehouse-level move, not a particular issue The waterline phase.
RELEASE_MANUAL = "manual"
RELEASE_AUTO = "auto"

# Spec-0064/T1: defaults Default for building a section——With single warehouse vigil / fleet_config Co-source (%)interval 60 / base main /
# The labels find a single real source) to avoid the "this configuration default" and the existing default drift.
_DEFAULT_INTERVAL = 60
_DEFAULT_BASE = "main"
_DEFAULT_LABELS = (github.DISCOVERY_LABEL,)

# Spec-0064/T1: The default for single warehouse management - to keep the current directory (path=.) without `repos`, and to give the "one warehouse whole" message.
_DEFAULT_REPO_PATH = "."

# Spec-0064/T1: Default Droppoint for Profiles (enable.openages/ Naming Space; single repository as a whole saves built-in default).
DEFAULT_CONFIG_PATH = ".openagents/openagents.yml"

# Spec-0067/T1: Default Configuration Comment Template for Packing in Package - `oa init` From It Generates Disk. openagents/openagents.yml
# . Place openagents/data/ to align source tree (editable) with the wiel path, both installation modes being the same source
# (See Spec-0067 Rationale）。DIVING:tests It's a story. load_agent_config Parsing syntax equivalent default_config()。
_TEMPLATE_RESOURCE = "openagents.yml.template"

_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# Spec-0064/T1: `stages` segment schema - only seven compatible stages, each one own go enum (per-stage valid value)
# The project is based on a series of projects, including the “Appendix” project, which is designed to provide a “Pilot for the U.S.,” and “Applicable” project.
# Here's the schema under.
_STAGES_SCHEMA: dict = {
    "type": "object",
    "properties": {stage: {"enum": list(owners)} for stage, owners in _STAGE_VALID_OWNERS.items()},
    "additionalProperties": False,
}

# Spec-0064/T1: `agents` segment schema - role { backend: str }, only known characters (additional Projects = False).
_AGENTS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        role: {
            "type": "object",
            "properties": {"backend": {"type": "string"}},
            "required": ["backend"],
            "additionalProperties": False,
        }
        for role in _ROLES
    },
    "additionalProperties": False,
}

# Spec-0074/T1: `gitea` segment schema-forge=gitea connects to four-dimensional groups. Token body is read only from environmental variables
# （token_env Declares variable name, default GITEA_TOKEN）——Continue OpenAgents Not token」Discipline (gh Commissioning change env (a) Commissioning).
_GITEA_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "base_url": {"type": "string"},
        "owner": {"type": "string"},
        "repo": {"type": "string"},
        "token_env": {"type": "string"},
    },
    "required": ["base_url", "owner", "repo"],
    "additionalProperties": False,
}

# Spec-0064/T1: Single `repos[]` Item - Fill in path + optional name/base/interval/labels + cover per warehouse stages.
_REPO_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "name": {"type": "string"},
        "base": {"type": "string"},
        "interval": {"type": "integer"},
        "labels": {"type": "array", "items": {"type": "string"}},
        "stages": _STAGES_SCHEMA,
    },
    "required": ["path"],
    "additionalProperties": False,
}

# Spec-0064/T1: Top-level schema - Full button option (full omitted & built-in default), additionalProperties = False Hand-Slide.
AGENT_CONFIG_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "object",
    "properties": {
        "version": {"type": "integer"},
        "flow": {"enum": [FLOW_STANDARD, FLOW_MINIMAL, FLOW_GENERATE_ONLY]},
        "coordination": {"enum": ["dependencies", "soft", "off"]},
        # Spec-0093/T1: trusted project policy, independent of deletable issue markers.
        "execution_evidence": {
            "type": "object",
            "properties": {"required": {"type": "boolean"}},
            "required": ["required"],
            "additionalProperties": False,
        },
        # Spec-0074/T1: Host Platform Selection (in default gethub, stock zero perception); gitea must be accompanied by a gitea connection at the same level.
        "forge": {"enum": [FORGE_GITHUB, FORGE_GITEA]},
        "gitea": _GITEA_SCHEMA,
        "agents": _AGENTS_SCHEMA,
        "stages": _STAGES_SCHEMA,
        "release": {"enum": [RELEASE_MANUAL, RELEASE_AUTO]},
        "defaults": {
            "type": "object",
            "properties": {
                "interval": {"type": "integer"},
                "base": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "repos": {"type": "array", "minItems": 1, "items": _REPO_SCHEMA},
    },
    "additionalProperties": False,
}

_yaml = YAML(typ="safe")


class AgentConfigError(Exception):
    """# Spec-0064/T1: `.openagents/openagents.yml` cannot read or throw when it is not valid (structure error/ invalid value/
    The hard-barrel name goes into the stages / review: skip+merge:agent Zerogates, etc. The upper CLI turns a line of tips (scrutinizing fleet_config)."""


@dataclass(frozen=True)
class AgentPolicy:
    """# Spec-0064/T1: Role backend resolved map (ideology 2 goes to centralised statement surface)."""

    backends: dict[str, str] = field(default_factory=dict)

    def backend_for(self, *, role: str) -> str:
        """Return the configured backend for a role or the built-in default."""
        return self.backends.get(role, _DEFAULT_BACKEND)


@dataclass(frozen=True)
class StagePolicy:
    """# Spec-0081/T3: Phase # of the agent/skip map of the owner"""

    owners: dict[str, str] = field(default_factory=dict)

    def owner_of(self, *, stage: str) -> str:
        """Return the stage owner or the default agent owner."""
        return self.owners.get(stage, _DEFAULT_STAGES.get(stage, OWNER_AGENT))


@dataclass(frozen=True)
class ReleasePolicy:
    """# Spec-0064/T1: Top-level hair-out policy (manual/auto)."""

    mode: str = RELEASE_MANUAL


@dataclass(frozen=True)
class RepoPlan:
    """Hold one repository’s resolved defaults, stage owners, and checkout path.
    Spec-0064/T1.
    """

    path: Path
    name: str
    interval: int
    base: str
    labels: list[str]
    stages: StagePolicy
    flow: str = FLOW_STANDARD
    coordination: str = "dependencies"
    execution_evidence_required: bool = False


@dataclass(frozen=True)
class AgentConfig:
    """Hold the resolved project-wide configuration and repository plans.
    Spec-0064/T1.
    """

    version: int
    agents: AgentPolicy
    stages: StagePolicy
    release: ReleasePolicy
    interval: int
    base: str
    labels: list[str]
    repos: list[RepoPlan]
    # Spec-0074/T1: Host Platform Declaration (this is the selected driver; gitea for the driver interface).
    # Places the default at the end - Zero changes to the existing default_config/_build_config/ test can still be demonstrated.
    forge: str = FORGE_GITHUB
    gitea: dict | None = None
    flow: str = FLOW_STANDARD
    coordination: str = "dependencies"
    execution_evidence_required: bool = False


def default_config() -> AgentConfig:
    """Return the built-in configuration without reading a project file."""
    stages = StagePolicy(owners=dict(_DEFAULT_STAGES))
    return AgentConfig(
        version=1,
        agents=AgentPolicy(backends={}),
        stages=stages,
        release=ReleasePolicy(mode=RELEASE_MANUAL),
        interval=_DEFAULT_INTERVAL,
        base=_DEFAULT_BASE,
        labels=list(_DEFAULT_LABELS),
        repos=[
            RepoPlan(
                path=Path(_DEFAULT_REPO_PATH).resolve(),
                name=Path(_DEFAULT_REPO_PATH).resolve().name,
                interval=_DEFAULT_INTERVAL,
                base=_DEFAULT_BASE,
                labels=list(_DEFAULT_LABELS),
                stages=stages,
                flow=FLOW_STANDARD,
            )
        ],
    )


def _default_template_text() -> str:
    """Read the default configuration comment template text (Spec-0067/T1) in the package.

    Let’s go. `importlib.resources.files("openagents")` The package catalog again. joinpath Present. data/ .
    `openagents` is a package (consistent) without requiring the data subdirectories to be a package; editable and wheel
    Installation mode is available (source tree with openagents/data/ as the path inside .
    """
    resource = importlib.resources.files("openagents").joinpath("data", _TEMPLATE_RESOURCE)
    return resource.read_text(encoding="utf-8")


def scaffold_default_config(*, path: Path, force: bool) -> bool:
    """Write the packaged template without replacing existing configuration unless requested.
    Spec-0067/T1.
    """
    resolved = Path(path)
    if resolved.exists() and not force:
        return False
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(_default_template_text(), encoding="utf-8")
    return True


def load_agent_config(*, path: Path) -> AgentConfig:
    """Read and validate project configuration, then apply defaults and overrides."""
    resolved_path = Path(path)
    if not resolved_path.exists():
        return default_config()
    data = _load_yaml(path=resolved_path)
    if data is None:
        return default_config()  # Empty file (YAML parsing Noone)  → All defaults.
    _check_retired_human_owners(data=data)
    _check_reserved_stage_names(data=data)
    _validate(data=data)
    return _build_config(data=data, base_dir=resolved_path.resolve().parent)


def _load_yaml(*, path: Path) -> dict | None:
    """Read a configuration mapping or report an unreadable or invalid file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentConfigError(f"Could not read opengents configuration {path}：{exc}") from exc
    try:
        data = _yaml.load(text)
    except YAMLError as exc:
        raise AgentConfigError(f"Openagents Configuration {path} Not legal Yaml:{exc}") from exc
    if data is None:
        return None
    if not isinstance(data, dict):
        raise AgentConfigError(
            f"Openagents Configuration {path} Top layer must be map (version / representatives / statuss / release / ...)"
        )
    return data


def _check_reserved_stage_names(*, data: dict) -> None:
    """Reject attempts to configure deterministic gates or mandatory role calls."""
    blocks = [data.get("stages")]
    for repo in data.get("repos") or []:
        if isinstance(repo, dict):
            blocks.append(repo.get("stages"))
    for stages in blocks:
        if not isinstance(stages, dict):
            continue
        for name in stages:
            if name in _HARDGATE_NAMES:
                raise AgentConfigError(
                    f"Hard gate names are not allowed in stages: {name!r}."
                    "Head advancement, evidence stamps, and round limits cannot be disabled."
                )
            if name in _ALWAYS_AGENT_STAGES:
                raise AgentConfigError(
                    f"Settings does not allow configuration phase {name!r}- Write/Deliver Constants agent, no ”who takes the turn” option"
                )


def _check_retired_human_owners(*, data: dict) -> None:
    """Reject retired human stage ownership with an actionable replacement."""
    blocks: list[tuple[str, object]] = [("stages", data.get("stages"))]
    for index, repo in enumerate(data.get("repos") or []):
        if isinstance(repo, dict):
            blocks.append((f"repos/{index}/stages", repo.get("stages")))
    retired = "hu" + "man"
    for prefix, stages in blocks:
        if not isinstance(stages, dict):
            continue
        for stage, owner in stages.items():
            if owner == retired:
                raise AgentConfigError(
                    f"{prefix}/{stage}: owner={retired} retired; set the owner to agent"
                    + (" or skip" if OWNER_SKIP in _STAGE_VALID_OWNERS.get(stage, ()) else "")
                )


def _validate(*, data: dict) -> None:
    """jsonschema Structure/Type/Validation of values per gate + Manual ”No Zero-Clock” guards; any errors are grouped into AgentConfigError。"""
    validator = Draft202012Validator(AGENT_CONFIG_SCHEMA)
    errors = sorted(validator.iter_errors(data), key=str)
    if errors:
        lines = []
        for error in errors:
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            lines.append(f"  {location}: {error.message}")
        raise AgentConfigError("Could not close temporary folder: %s\n" + "\n".join(lines))
    # Spec-0074/T1: forge=gitea must take gitea links - missing a river, unable to hit API, during loading period (fail-loud, Zail-loud, Zalig-Lutha)
    # Never quietly gh hits a Gitea project. The schema pipe shape, here is the trans-field dependent.
    if data.get("forge") == FORGE_GITEA and not data.get("gitea"):
        raise AgentConfigError(
            "Forge=gitea requires a gitea segment (base_url/owner/repo, optional token_env)"
        )
    # The "No Zero Gate" cross-field guard -- top level and stasis combined with each warehouse (override is still not allowed to leave the Zero Gate).
    _guard_no_zero_gate(
        stages=_merge_stages(base=None, override=data.get("stages")), scope="<root>"
    )
    for repo in data.get("repos") or []:
        merged = _merge_stages(base=data.get("stages"), override=repo.get("stages"))
        _guard_no_zero_gate(stages=merged, scope=f"repos/{repo.get('path')}")


def _guard_no_zero_gate(*, stages: dict[str, str], scope: str) -> None:
    """Require code review before automatic merge and architecture review for drafted Specs."""
    review = stages.get(STAGE_REVIEW, _DEFAULT_STAGES[STAGE_REVIEW])
    merge = stages.get(STAGE_MERGE, _DEFAULT_STAGES[STAGE_MERGE])
    rfc = stages.get(STAGE_RFC, _DEFAULT_STAGES[STAGE_RFC])
    architecture = stages.get(STAGE_ARCHITECTURE, _DEFAULT_STAGES[STAGE_ARCHITECTURE])
    if rfc != OWNER_SKIP and architecture == OWNER_SKIP:
        raise AgentConfigError(
            f"{scope}: architecture:skip requires rfc:skip; review a drafted Spec before implementation"
        )
    if review == OWNER_SKIP and merge == OWNER_AGENT:
        raise AgentConfigError(f"{scope}: Automatic merge requires agent review; set review: agent")


def _merge_stages(*, base: dict | None, override: dict | None) -> dict[str, str]:
    """Resolve stage owners in built-in, project, then repository order."""
    merged = dict(_DEFAULT_STAGES)
    if base:
        merged.update(base)
    if override:
        merged.update(override)
    explicitly_set = STAGE_ARCHITECTURE in (base or {}) or STAGE_ARCHITECTURE in (override or {})
    if not explicitly_set:
        rfc_owner = merged[STAGE_RFC]
        merged[STAGE_ARCHITECTURE] = OWNER_SKIP if rfc_owner == OWNER_SKIP else OWNER_AGENT
    return merged


def _build_config(*, data: dict, base_dir: Path) -> AgentConfig:
    """Build the resolved project configuration from validated input."""
    _warn_rfc_skip(stages=_merge_stages(base=None, override=data.get("stages")))

    agents = _build_agents(raw=data.get("agents") or {})
    top_stages = StagePolicy(owners=_merge_stages(base=None, override=data.get("stages")))
    release = ReleasePolicy(mode=data.get("release", RELEASE_MANUAL))

    defaults = data.get("defaults") or {}
    interval = defaults.get("interval", _DEFAULT_INTERVAL)
    base = defaults.get("base", _DEFAULT_BASE)
    labels = list(defaults.get("labels", list(_DEFAULT_LABELS)))

    raw_repos = data.get("repos")
    if not raw_repos:
        raw_repos = [{"path": _DEFAULT_REPO_PATH}]
    repos = [
        _build_repo(
            repo=repo,
            base_dir=base_dir,
            top_stages=data.get("stages"),
            interval=interval,
            base=base,
            labels=labels,
            flow=data.get("flow", FLOW_STANDARD),
            coordination=data.get("coordination", "dependencies"),
            execution_evidence_required=data.get("execution_evidence", {}).get("required", False),
        )
        for repo in raw_repos
    ]
    return AgentConfig(
        version=data.get("version", 1),
        agents=agents,
        stages=top_stages,
        release=release,
        interval=interval,
        base=base,
        labels=labels,
        repos=repos,
        # Spec-0074/T1: A hosting platform declaration is trans-telecuted (forge distribution layer and consumer loading; default gitthub).
        forge=data.get("forge", FORGE_GITHUB),
        gitea=data.get("gitea"),
        flow=data.get("flow", FLOW_STANDARD),
        coordination=data.get("coordination", "dependencies"),
        execution_evidence_required=data.get("execution_evidence", {}).get("required", False),
    )


def _build_agents(*, raw: dict) -> AgentPolicy:
    """Read per-role backend declarations and keep defaults for missing roles."""
    backends = {role: spec["backend"] for role, spec in raw.items()}
    return AgentPolicy(backends=backends)


def _build_repo(
    *,
    repo: dict,
    base_dir: Path,
    top_stages: dict | None,
    interval: int,
    base: str,
    labels: list[str],
    flow: str,
    coordination: str,
    execution_evidence_required: bool,
) -> RepoPlan:
    """Merges the single repo defaults/override into RepoPlan -Path Absoluteization, Stages Level 3 Merge, and the rest fall backs."""
    path = _absolutize(raw_path=repo["path"], base_dir=base_dir)
    stages = StagePolicy(owners=_merge_stages(base=top_stages, override=repo.get("stages")))
    return RepoPlan(
        path=path,
        name=repo.get("name") or path.name,
        interval=repo.get("interval", interval),
        base=repo.get("base", base),
        labels=list(repo.get("labels", labels)),
        stages=stages,
        flow=flow,
        coordination=coordination,
        execution_evidence_required=execution_evidence_required,
    )


def _warn_rfc_skip(*, stages: dict[str, str]) -> None:
    """Warn when configuration explicitly skips Spec drafting."""
    if stages.get(STAGE_RFC) == OWNER_SKIP:
        warnings.warn(
            "stages.rfc=skip: implementation will proceed without drafting a Spec. "
            "Use only when using a visible selection of the size of the assue particle, do not put it in the global default to turn down the RFC selling point (Spec-0064 limit 1)",
            stacklevel=2,
        )


def _absolutize(*, raw_path: str, base_dir: Path) -> Path:
    """`~` Expand + Relative Path based on the directory where the profile is located absolute (not related to cwd, portable; fleet_config)."""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()
