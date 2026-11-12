# Spec-0023/T3
"""Publish a versioned branch and tag after checking main for release readiness."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

# Spec-0063/T3: The automated failure of the pre-check from the runtime authoritative vocabulary.
# BLOCKED_LABEL is taken from utils.github authoritative source (old state.py is simply re-exported and removed from retirement).
from openagents.runtime.state import STATUS_FAILED, RuntimeState

# Spec-0074/T1: arias-import switch - Platform operations are configured by github/gitea driver to call zero changes.
from openagents.utils import forge as github
from openagents.utils.github import AUTOMATION_FAILED_LABEL

# Spec-0035/T3: The number of hours of time-out seconds for the sub-process network (coordinate github._GH_TIMEOUT_SECONDS = 30; only triggered when the real card is stuck).
# Each of the three modules has one (git.py/workspace.py/release.py) and is replaced by zero import coupling (see spec Nationale Option 1).
_GIT_NET_TIMEOUT_SECONDS = 30

# Spec-0023/T3: The starting point for a sumanized version of three paragraphs vX.Y.Z; a repository without any version of tag.
_INITIAL_VERSION = (0, 1, 0)
_VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_BUMPS = ("patch", "minor", "major")


@dataclass(frozen=True)
class ReleaseResult:
    """Spec-0023/T3: a result of a releasing.

    Released: Is the release complete (pre-screened and branch/tag successfully) completed?
    version: This release is ” vX.Y.Z ” ; not published as ””.
    Reason: Identify which pre-check stopped it (or why it failed); succeed as ”ok”.
    """

    released: bool
    version: str
    reason: str


def release(*, state: RuntimeState, bump: str = "patch", source: str = "main") -> ReleaseResult:
    """Spec-0023/T3: Pre-checking translates the current HEAD object of source (main) into a new version of branch + tag.

    Pre-check any but returning response = False and reason given, no branch/tag (decision-making = copy)
    RFC-0012 Decision 7, replaces green objects only from test with main.
    """
    # Spec-0063/T3: list_runs() returns the dict record (not RunRecord) and therefore uses the status/issue_number to mark it down;
    failed = [r for r in state.list_runs() if r["status"] == STATUS_FAILED]
    if failed:
        issues = ", ".join(f"#{r['issue_number']}" for r in failed)
        return ReleaseResult(
            released=False,
            version="",
            reason=f"There is automation failure (%1){STATUS_FAILED}* And I’m not gonna let you go *{issues}",
        )

    automation_failed = [
        pr.number
        for pr in github.list_open_prs()
        if github.has_label(pr_number=pr.number, name=AUTOMATION_FAILED_LABEL)
    ]
    if automation_failed:
        prs = ", ".join(f"#{n}" for n in automation_failed)
        return ReleaseResult(
            released=False,
            version="",
            reason=f"There is automation failure (%1){AUTOMATION_FAILED_LABEL})’s open PR:{prs}",
        )

    if not github.branch_ci_green(branch=source):
        return ReleaseResult(
            released=False, version="", reason=f"{source} branch has not passed CI"
        )

    version = _next_version(latest=_latest_version(), bump=bump)
    # Bottom flow label in position (with original) promote - Yes, sir. no-op）；test The branch is ready. Spec-0023 Remove.
    github.ensure_prerequisites()
    _materialize_release(source=source, version=version)
    return ReleaseResult(released=True, version=version, reason="ok")


def _latest_version() -> tuple[int, int, int] | None:
    """The largest sumanized version (X, Y, Z) has been published; the repository returns None when no vX.Y.Z tag is available.

    Compare max (synthic sorting) by integer tri-dimensional group, instead of string dictionaries -- otherwise v0.10.0 will be misjudged less than
    v0.9.0. All tags in non-vX.Y.Z form are ignored.
    """
    versions: list[tuple[int, int, int]] = []
    for tag in _list_version_tags():
        matched = _VERSION_RE.match(tag)
        if matched:
            versions.append((int(matched.group(1)), int(matched.group(2)), int(matched.group(3))))
    return max(versions) if versions else None


def _next_version(*, latest: tuple[int, int, int] | None, bump: str) -> str:
    """Press the button to add the next version string ” vX.Y.Z ” (purity function) from the last.

    latest=None (no version of the store is available atg) v0.1.0 (ignore bump: Start is the start).
    Butmp=Patch Z+1; Minor Z Z +1 and Z to zero; Major Z Z +1 and Y Z to zero.
    """
    if bump not in _BUMPS:
        raise ValueError(f"Unknown bmp:{bump!r}(renumbered {', '.join(_BUMPS)} One of them)")
    if latest is None:
        major, minor, patch = _INITIAL_VERSION
        return f"v{major}.{minor}.{patch}"
    major, minor, patch = latest
    if bump == "patch":
        patch += 1
    elif bump == "minor":
        minor, patch = minor + 1, 0
    else:  # major
        major, minor, patch = major + 1, 0, 0
    return f"v{major}.{minor}.{patch}"


def _list_version_tags() -> list[str]:
    """`git tag --list 'v*'`  →  non-empty tag list. Separating subprocess allows for the pegging."""
    result = subprocess.run(
        ["git", "tag", "--list", "v*"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        reason = result.stderr.strip() or f"git tag --list Return Code {result.returncode}"
        raise RuntimeError(f"Failed to read published tag:{reason}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _materialize_release(*, source: str, version: str) -> None:
    """Turn the current HEAD object into rebase/ <version> branch and play unchangeable tag <version>.

    Three steps glt (both go subproces, easy to stick; branches and tag are submitted on the same basis as source, ensuring consistency):
      1 gint push origin<source>: refs/heads/release/<version> - create a new distribution branch with source HEAD;
      2 gt tag <version> >_ play tag on source HEAD (local);
      3 gush origin <version> -- push tag, nail to the far end, and no scrambling.
    The CLI layer is a clean line of tips.
    """
    _git(
        args=["push", "origin", f"{source}:refs/heads/release/{version}"],
        action=f"Publish release branch {version}",
    )
    _git(args=["tag", version, source], action=f"Hit the tag. {version}")
    _git(args=["push", "origin", version], action=f"Pushing tag {version}")


def _git(*, args: list[str], action: str) -> None:
    """Run a guit sub-command; non-zero exit to RunmeError, with action context and stderr.

    #Spec-0035/T3: Pass = _GIT_NET_TIMEOUT_SECONDS — Internet git (push branch/ push tag) is broken and the #system #sympics are broken.
    # Add the old RuntimeError (with action, CLI layers into a clean line of tips without turning the process); local git(tag)
    # Only share the helper to get the no harm limit. _list_version_tags `tag --list` goes independent subproces, read locally, without timeout.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_NET_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"{action}while running  ”%s” {' '.join(args)} timeout after {_GIT_NET_TIMEOUT_SECONDS}s）"
        ) from None
    if result.returncode != 0:
        reason = result.stderr.strip() or f"git {' '.join(args)} Return Code {result.returncode}"
        raise RuntimeError(f"{action}Failed:{reason}")
