# Spec-0070/T1
"""Check whether OpenAgents can safely update from its source checkout.

Update only the recorded branch with a clean worktree and a fast-forward.
Installation or preflight errors leave the current command usable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Spec-0070/T1: DISABLE skips the check, DONE prevents a restart loop, and HOME overrides the state directory.
DISABLE_ENV = "OPENAGENTS_NO_SELF_UPDATE"
DONE_ENV = "OPENAGENTS_SELFUPDATE_DONE"
HOME_ENV = "OPENAGENTS_HOME"

# Spec-0070/T1: Bound network Git operations so update checks cannot hang a command.
_GIT_NET_TIMEOUT_SECONDS = 30

# Spec-0070/T1: Identify the source checkout using both the CLI file and its declared entry point.
_SOURCE_MARKER_CLI = Path("openagents") / "cli.py"
_SOURCE_MARKER_PYPROJECT = "pyproject.toml"

__all__ = [
    "DISABLE_ENV",
    "DONE_ENV",
    "HOME_ENV",
    "SourceConfig",
    "detect_source_repo",
    "home_dir",
    "load_source_config",
    "precheck",
    "save_source_config",
    "source_config_path",
]

# Injection points for subprocess execution and restarting the command.
_Runner = Callable[..., subprocess.CompletedProcess[str]]
_Execvp = Callable[[str, Sequence[str]], Any]


@dataclass(frozen=True)
class SourceConfig:
    """Locate the source checkout from commands running in a target repository.

    Only update the configured branch when the worktree is clean.
    """

    repo_path: str
    remote: str = "origin"
    branch: str = "main"


def home_dir(*, environ: Mapping[str, str]) -> Path:
    """Return OPENAGENTS_HOME or the default ~/.openagents directory."""
    override = environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".openagents"


def source_config_path(*, environ: Mapping[str, str]) -> Path:
    """Return the path to the source repository record."""
    return home_dir(environ=environ) / "source.json"


def load_source_config(*, environ: Mapping[str, str]) -> SourceConfig | None:
    """Read source configuration, or return None when absent or invalid."""
    path = source_config_path(environ=environ)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    repo_path = raw.get("repo_path") if isinstance(raw, dict) else None
    if not repo_path:
        return None
    return SourceConfig(
        repo_path=str(repo_path),
        remote=str(raw.get("remote") or "origin"),
        branch=str(raw.get("branch") or "main"),
    )


def save_source_config(*, config: SourceConfig, environ: Mapping[str, str]) -> None:
    """Write the source configuration, creating its parent directory if needed."""
    path = source_config_path(environ=environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"repo_path": config.repo_path, "remote": config.remote, "branch": config.branch}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def detect_source_repo(*, cwd: Path, run: _Runner, environ: Mapping[str, str]) -> Path | None:
    """Record the Git root if it contains the OpenAgents source package.

    Use origin/main by default. Do not write configuration for unrelated or unreadable repositories.
    """
    try:
        result = run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=_GIT_NET_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    toplevel = Path(result.stdout.strip())
    if not _looks_like_source_repo(toplevel=toplevel):
        return None
    save_source_config(config=SourceConfig(repo_path=str(toplevel)), environ=environ)
    return toplevel


def _looks_like_source_repo(*, toplevel: Path) -> bool:
    """Identify the checkout by its CLI file and project entry point."""
    if not (toplevel / _SOURCE_MARKER_CLI).is_file():
        return False
    pyproject = toplevel / _SOURCE_MARKER_PYPROJECT
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    # An openagents directory alone does not identify this repository.
    return "openagents.cli:main" in text


def precheck(
    *,
    argv: Sequence[str],
    environ: Any = None,
    run: _Runner | None = None,
    execvp: _Execvp | None = None,
    stderr: Any = None,
) -> None:
    """Check for a safe source update before parsing command arguments.

    Fetch and compare the configured branch, then fast-forward, reinstall, and restart if safe. Use the full argv for restart. A failed check leaves the original command usable.
    """
    environ = environ if environ is not None else _os_environ()
    run = run if run is not None else subprocess.run
    execvp = execvp if execvp is not None else _os_execvp()
    stderr = stderr if stderr is not None else sys.stderr

    # Skip when disabled or when this command was already restarted.
    if environ.get(DISABLE_ENV):
        return
    if environ.get(DONE_ENV):
        return

    try:
        # A successful exec replaces the process. If it raises, warn and continue.
        _precheck_inner(argv=argv, environ=environ, run=run, execvp=execvp, stderr=stderr)
    except Exception as exc:  # noqa: BLE001 - An update error must not block the requested command.
        _warn(stderr=stderr, message=f"Skipped automatic update check: {exc}")


def _precheck_inner(
    *,
    argv: Sequence[str],
    environ: Mapping[str, str],
    run: _Runner,
    execvp: _Execvp,
    stderr: Any,
) -> None:
    # Record the source checkout when the command runs inside it.
    detect_source_repo(cwd=Path.cwd(), run=run, environ=environ)

    # No recorded source checkout means there is nothing to update.
    config = load_source_config(environ=environ)
    if config is None:
        return
    src = Path(config.repo_path)

    # Fetch the tracking ref with a timeout; offline commands still work.
    fetched = _git(
        run=run,
        cwd=src,
        args=["fetch", config.remote, config.branch],
    )
    if fetched is None or fetched.returncode != 0:
        _warn(stderr=stderr, message="Could not fetch the source branch; skipped automatic update.")
        return

    # Return silently if the configured branch is already current.
    if not _is_behind(run=run, cwd=src, remote=config.remote, branch=config.branch):
        return

    # Update only the configured branch with a clean worktree.
    if not _is_safe_to_update(run=run, cwd=src, branch=config.branch):
        _warn(stderr=stderr, message=_manual_update_hint(config=config))
        return

    # Fast-forward without creating a merge commit.
    pulled = _git(run=run, cwd=src, args=["pull", "--ff-only", config.remote, config.branch])
    if pulled is None or pulled.returncode != 0:
        _warn(stderr=stderr, message=_manual_update_hint(config=config))
        return

    # Reinstall the tool from the updated checkout.
    installed = _uv_reinstall(run=run, src=src)
    if installed is None or installed.returncode != 0:
        _warn(stderr=stderr, message=_manual_update_hint(config=config))
        return

    # Restart with DONE set to avoid a second update check.
    _warn(stderr=stderr, message="✓ Updated OpenAgents; restarting the command…")
    _reexec(argv=argv, environ=environ, execvp=execvp)


def _is_behind(*, run: _Runner, cwd: Path, remote: str, branch: str) -> bool:
    """Return whether the configured local branch is behind its tracking ref."""
    upstream = f"{remote}/{branch}"
    result = _git(run=run, cwd=cwd, args=["rev-list", "--count", f"{branch}..{upstream}"])
    if result is None or result.returncode != 0:
        return False
    try:
        return int(result.stdout.strip() or "0") > 0
    except ValueError:
        return False


def _is_safe_to_update(*, run: _Runner, cwd: Path, branch: str) -> bool:
    """Allow updates only on the configured branch with a clean worktree."""
    head = _git(run=run, cwd=cwd, args=["rev-parse", "--abbrev-ref", "HEAD"])
    if head is None or head.returncode != 0 or head.stdout.strip() != branch:
        return False
    porcelain = _git(run=run, cwd=cwd, args=["status", "--porcelain"])
    if porcelain is None or porcelain.returncode != 0:
        return False
    return porcelain.stdout.strip() == ""


def _git(*, run: _Runner, cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run Git with a timeout, returning None when execution fails."""
    try:
        return run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_NET_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _uv_reinstall(*, run: _Runner, src: Path) -> subprocess.CompletedProcess[str] | None:
    """Reinstall OpenAgents from the source checkout or return None on failure."""
    try:
        return run(
            ["uv", "tool", "install", "--force", "--from", str(src), "openagents"],
            capture_output=True,
            text=True,
            timeout=_GIT_NET_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _reexec(*, argv: Sequence[str], environ: Mapping[str, str], execvp: _Execvp) -> None:
    """Restart the command with the guard set in the inherited environment."""
    # execvp inherits the current environment.
    try:
        environ[DONE_ENV] = "1"  # type: ignore[index] - The runtime and test environment mappings are mutable.
    except TypeError:
        pass
    argv = list(argv)
    if not argv:
        return
    execvp(argv[0], argv)


def _manual_update_hint(*, config: SourceConfig) -> str:
    """Show manual update commands when automatic update is unsafe."""
    return (
        "⚠ OpenAgents is behind its source repository. Automatic update requires the configured branch and a clean worktree.\n"
        f"  Update manually: git -C {config.repo_path} pull --ff-only && "
        f"uv tool install --force --from {config.repo_path} openagents\n"
        f"  (or set {DISABLE_ENV}=1 to disable this check)"
    )


def _warn(*, stderr: Any, message: str) -> None:
    """Write an advisory message without stopping the command."""
    print(message, file=stderr, flush=True)


def _os_environ() -> Any:
    # Read the environment lazily so tests can inject a mapping.
    import os

    return os.environ


def _os_execvp() -> _Execvp:
    import os

    return os.execvp
