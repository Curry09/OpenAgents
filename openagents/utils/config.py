# RFC-0001
"""Bind the current Git checkout to its OpenAgents project configuration."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class ProjectNotReady(Exception):
    """cwd is not a ready OpenAgents project (lack of guit warehouse or origin remote)."""


@dataclass(frozen=True)
class ProjectContext:
    """The context of the item is ready. Remote may be None when it is only a local warehouse."""

    repo_root: Path
    remote: str | None


def _git_output(args: list[str]) -> str | None:
    """Runs the git sub-command, successfully returns to the empty stdout, failed to return None."""
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def resolve_project() -> ProjectContext | None:
    """Parsing the context of the cwd project; not a guit warehouse returns None."""
    root = _git_output(["rev-parse", "--show-toplevel"])
    if root is None:
        return None
    # Read original configuration values with `config --get` instead of `remote get-url`: the latter will expand intosteadof
    # Rewrite, possibly token of the evidence injected into the global guit configuration to bring in the URL and leak it to the State/Paint.
    remote = _git_output(["config", "--get", "remote.origin.url"])
    return ProjectContext(repo_root=Path(root), remote=remote or None)


def _confirm(question: str) -> bool:
    """Interactive yes/no tip, default no."""
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def _prompt(question: str) -> str:
    return input(question).strip()


def _bootstrap(ctx: ProjectContext | None) -> ProjectContext:
    """Interactively fills the missing guit repository / remote (decision 10)."""
    if ctx is None:
        if not _confirm("Current directory is not a guit repository, do you execute a guit init?"):
            raise ProjectNotReady("User Cancel: Uninitialized guit repository")
        subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
        ctx = resolve_project()
    if ctx is None:
        raise ProjectNotReady("glit init still unable to parse the repository")
    if not ctx.remote:
        if not _confirm(
            "There is no origin remote in the current warehouse. Are you going to create a new GitHub repository?"
        ):
            raise ProjectNotReady("User Cancel: No Remote Configuration")
        try:
            from openagents.utils.github import create_repo
        except ImportError as exc:
            raise ProjectNotReady(
                "New remote requires GitHub integration (RFC-0001 T3) not yet achieved"
            ) from exc
        name = _prompt("Remote repository name (owner/repo):")
        private = _confirm("Private warehouse?")
        remote = create_repo(name=name, private=private)
        # Spec-0033/T1: Write back the new remote to the local guit config, otherwise the gh command cannot be found
        # Target repository (nogentremes found). Repeat check=True verification for git init
        # Subprocess: Git failed immediately, tumbled and mistook. It must return to the ctx after create_repo has succeeded.
        subprocess.run(["git", "remote", "add", "origin", remote], check=True, capture_output=True)
        ctx = ProjectContext(repo_root=ctx.repo_root, remote=remote)
    return ctx


def ensure_project(*, interactive: bool) -> ProjectContext:
    """Preflight: returns the context of the item(s) already in place, otherwise decide to create or toss a new or misdeed by using an inteactive basis."""
    ctx = resolve_project()
    if ctx is not None and ctx.remote:
        return ctx
    if not interactive:
        reason = (
            "Current directory is not a guit repository"
            if ctx is None
            else "Current repository lacks origin remote"
        )
        raise ProjectNotReady(reason)
    return _bootstrap(ctx)
