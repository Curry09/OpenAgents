"""Reserve spec numbers atomically in a shared Git remote before writing a group."""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path

_SPEC_PATH = re.compile(r"^docs/specs/(\d{4})-[^/]+\.md$")
_RESERVATION_REF = "refs/heads/spec-reservations/{number}"
_TIMEOUT_SECONDS = 45


def _git(
    repo: Path, *args: str, input_text: str | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
        env=env,
    )


def _checked(
    repo: Path, *args: str, input_text: str | None = None, env: dict[str, str] | None = None
) -> str:
    result = _git(repo, *args, input_text=input_text, env=env)
    if result.returncode:
        raise RuntimeError(
            f"Spec number reservation failed: git {' '.join(args)}：{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def _numbers_from_paths(paths: list[str]) -> set[int]:
    return {int(match.group(1)) for path in paths if (match := _SPEC_PATH.fullmatch(path))}


def _local_numbers(specs_root: Path) -> set[int]:
    return _numbers_from_paths(
        [f"docs/specs/{p.name}" for p in specs_root.glob("[0-9][0-9][0-9][0-9]-*.md")]
    )


def reserve_number(*, specs_root: Path, issue: int, slug: str, number: str | None) -> str:
    """Claim a number via a unique remote branch; fail closed when a shared remote is unavailable."""
    local = _local_numbers(specs_root)
    if number is not None:
        if not re.fullmatch(r"\d{4}", number) or int(number) == 0:
            raise ValueError("spec must be 0001-9999")
        if int(number) in local:
            raise FileExistsError(f"spec number {number} Used in this working area")

    probe_dir = specs_root
    while not probe_dir.exists():
        probe_dir = probe_dir.parent
    probe = _git(probe_dir, "rev-parse", "--show-toplevel")
    if probe.returncode:
        # A directory outside Git is a local-only spec workspace.
        return number or f"{max(local, default=0) + 1:04d}"
    repo = Path(probe.stdout.strip())
    remotes = _checked(repo, "remote").splitlines()
    if not remotes:
        return number or f"{max(local, default=0) + 1:04d}"
    if "origin" in remotes:
        remote = "origin"
    elif len(remotes) == 1:
        remote = remotes[0]
    else:
        raise RuntimeError("Spec number pre-set failed: multiple Git remotes exist but no origin")

    # Include the authoritative base branch. A stale worktree must not reuse a
    # number already merged since its checkout was created.
    _checked(repo, "fetch", "--no-tags", remote, "HEAD")
    base_paths = _checked(
        repo, "ls-tree", "-r", "--name-only", "FETCH_HEAD", "--", "docs/specs"
    ).splitlines()
    occupied = local | _numbers_from_paths(base_paths)
    refs = _checked(
        repo, "ls-remote", "--heads", remote, "refs/heads/spec-reservations/*"
    ).splitlines()
    for row in refs:
        ref = row.split()[-1]
        match = re.fullmatch(r"refs/heads/spec-reservations/(\d{4})", ref)
        if match:
            occupied.add(int(match.group(1)))

    if number is not None:
        candidates = [int(number)]
    else:
        candidates = range(max(occupied, default=0) + 1, 10000)

    # Marker refs must contain only the public base tree, never an in-progress
    # worktree's code or unmerged commits.
    tree = _checked(repo, "rev-parse", "FETCH_HEAD^{tree}")
    parent = _checked(repo, "rev-parse", "FETCH_HEAD")
    identity = os.environ.copy()
    identity.update(
        {
            "GIT_AUTHOR_NAME": "Spec Allocator",
            "GIT_AUTHOR_EMAIL": "spec-allocator@local.invalid",
            "GIT_COMMITTER_NAME": "Spec Allocator",
            "GIT_COMMITTER_EMAIL": "spec-allocator@local.invalid",
        }
    )
    for candidate in candidates:
        if candidate in occupied:
            if number is not None:
                raise FileExistsError(
                    f"spec number {number} is already used by the default branch or a reservation ref"
                )
            continue
        formatted = f"{candidate:04d}"
        marker = _checked(
            repo,
            "commit-tree",
            tree,
            "-p",
            parent,
            input_text=f"Reserve spec {formatted} for issue {issue} ({slug}); nonce={uuid.uuid4()}\n",
            env=identity,
        )
        ref = _RESERVATION_REF.format(number=formatted)
        pushed = _git(repo, "push", "--porcelain", remote, f"{marker}:{ref}")
        if pushed.returncode == 0:
            return formatted
        # A competing worker may have won the same number after ls-remote.
        # Check the remote before retrying; transport/auth failures stay fatal.
        current = _checked(repo, "ls-remote", remote, ref)
        if current:
            if number is not None:
                raise FileExistsError(f"spec number {formatted} Has been reserved for co-location")
            occupied.add(candidate)
            continue
        raise RuntimeError(
            f"Spec number reservation failed:get push {ref}：{pushed.stderr.strip() or pushed.stdout.strip()}"
        )
    raise RuntimeError("Spec number is beyond four places")


__all__ = ["reserve_number"]
