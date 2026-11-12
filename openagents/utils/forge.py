# Spec-0074/T1: utils.forge  —  Host Platform (Platform)forge）Distribution level: by configuration github.py The same name is entrusted to the public. driver。

"""Dispatch forge operations to the configured GitHub or Gitea driver."""

from __future__ import annotations

import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

# Spec-0074/T1: neutral constant and error type - static re-export (zero IO) for Import, no __getattr__.
from openagents.utils.github import (  # noqa: F401  re-export for consumer access
    APPROVAL_LABEL,
    AUTOMATION_FAILED_LABEL,
    DISCOVERY_LABEL,
    DISPATCH_LABEL,
    PROCESS_LABELS,
    GithubError,
)

FORGE_GITHUB = "github"
FORGE_GITEA = "gitea"
_VALID_FORGES = (FORGE_GITHUB, FORGE_GITEA)

# Inert finds the profile to read. agent_config.DEFAULT_CONFIG_PATH Value equal but not import It's... —
# agent_config Inverse Reference to this module (ForGE_* constant) this module must stop at a lower point on the dependent map to avoid circulation.
_CONFIG_RELPATH = Path(".openagents") / "openagents.yml"

_lock = threading.Lock()
_active: str | None = (
    None  # None = not yet established  →  Initial function access to inertia discovery
)
_yaml = YAML(typ="safe")


def configure(*, name: str, settings: dict[str, Any] | None = None) -> None:
    """Visible loading forge selection; settings (base_url/owner/repo/token_env) passed to driver verification when `gitea` is available.

    & & Reinsert (fleet multi-silo process/ test each assembly). Illegal forge or gitea settings are incomplete  →  GithubError
    (The type of error does not distinguish fork, the error of cli is standardized and zero changes).
    """
    global _active
    if name not in _VALID_FORGES:
        raise GithubError(f"Unknown {name!r}(Optional:{'/'.join(_VALID_FORGES)}）")
    with _lock:
        if name == FORGE_GITEA:
            from openagents.utils import (
                gitea,  # noqa: PLC0415  Inertity: Github users do not pay gitea import fees
            )

            gitea.configure(settings=dict(settings or {}))
        _active = name


def reset() -> None:
    """Clear cached forge selection so the next access discovers it again."""
    global _active
    with _lock:
        _active = None


def active_forge() -> str:
    """The forge name currently in effect; a inert discovery (cache of results) is performed first when unobserved configuration is available."""
    if _active is None:
        _discover()
    return _active or FORGE_GITHUB


def _discover() -> None:
    """Inertity found: Search up from cwd for `.openagents/openagents.yml`, read forge/gitea after two keys

    File missing/ bad YaML/ top level non-magnification/ value unknown gethub (fail-open, old item zero perception).
    Forge=gitea but the gitea section is incomplete  → configure throw GithubError as it is (fail-loud, see module doingcstring).
    """
    name, settings = _read_config(start=Path.cwd())
    configure(name=name, settings=settings)


def _read_config(*, start: Path) -> tuple[str, dict[str, Any]]:
    """Looking up from start to the configuration file; no more up to the guit repository (with .git layers)."""
    for base in (start, *start.parents):
        candidate = base / _CONFIG_RELPATH
        if candidate.is_file():
            return _parse_forge(path=candidate)
        linked_root = _linked_main_worktree(git_file=base / ".git")
        if linked_root is not None:
            linked_config = linked_root / _CONFIG_RELPATH
            if linked_config.is_file():
                return _parse_forge(path=linked_config)
        # Linked worktrees contain a `.git` *file*, not a directory.  Stopping on
        # that file prevents commands executed inside the worktree from finding
        # the main worktree's `.openagents/openagents.yml`, and silently selects
        # the GitHub driver for a Gitea repository.  Continue through a linked
        # worktree; only a real repository root terminates discovery.
        if (base / ".git").is_dir():
            break  # Repository root has reached - Configure only the home warehouse (in the same words as the cwd-repository in gh)
    return FORGE_GITHUB, {}


def _linked_main_worktree(*, git_file: Path) -> Path | None:
    """Resolve the main worktree root from a linked worktree's `.git` pointer."""
    if not git_file.is_file():
        return None
    try:
        marker = git_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    prefix = "gitdir:"
    if not marker.lower().startswith(prefix):
        return None
    raw = marker[len(prefix) :].strip()
    if not raw:
        return None
    gitdir = Path(raw)
    if not gitdir.is_absolute():
        gitdir = (git_file.parent / gitdir).resolve()
    # `git worktree add` points at <main>/.git/worktrees/<name>.
    if gitdir.parent.name != "worktrees" or gitdir.parent.parent.name != ".git":
        return None
    return gitdir.parent.parent.parent


def _parse_forge(*, path: Path) -> tuple[str, dict[str, Any]]:
    """Light reading of forge/gitea two keys (the rest of the key is not subject to full verification of agent_config); non-readable/ unconformable gitthub."""
    try:
        data = _yaml.load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        return FORGE_GITHUB, {}
    if not isinstance(data, dict):
        return FORGE_GITHUB, {}
    name = data.get("forge") or FORGE_GITHUB
    if name not in _VALID_FORGES:
        return FORGE_GITHUB, {}
    raw_settings = data.get("gitea")
    settings = dict(raw_settings) if isinstance(raw_settings, dict) else {}
    return str(name), settings


def _driver_module() -> ModuleType:
    """The current forge corresponding driver module (github.py public face is a de facto contract, driver is realized by the same name)."""
    if active_forge() == FORGE_GITEA:
        from openagents.utils import gitea  # noqa: PLC0415  Inertity Report (see configure)

        return gitea
    from openagents.utils import github  # noqa: PLC0415  symmetry with the gitea branch

    return github


def __getattr__(name: str) -> Any:
    """PEP 562: Delegate access to properties not defined in this module to the current driver (both functions/data classes go through here)."""
    if name.startswith("_"):
        raise AttributeError(name)
    module = _driver_module()
    try:
        return getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(
            f"forge driver {module.__name__} does not expose {name!r} — "
            f"implement public operations in both drivers (Spec-0074)."
        ) from exc
