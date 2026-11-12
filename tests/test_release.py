"""Spec-0023/T3: test the unit of the module (pre-check + PHP branch/tag + version incremental).

Prick a gitthub.* / state / subproces (git tag/push), keep hermetic (untouching the real gh/git).
Coverage: BLONKED run  →  False; needs-human PR  →  False; Main CI non-green  →  False;
 →  Build release/vX.Y.Z branch + hit tag + push and released =True (enhancement of version numbers);
No tag v0.1.0; bump=minor/major effective; semantic sorting (v0.10.0 > v0.9.0 > ); push failed to drop the error.
"""

import subprocess
from types import SimpleNamespace

import pytest

# Spec-0063/T3: STATUS_* From Runtime authoritative vocabulary, StateQruntestate (set_run writing dict records).
from openagents.runtime.state import STATUS_FAILED, STATUS_PR_OPEN, RuntimeState
from openagents.utils import release as release_module
from openagents.utils.github import PR
from openagents.utils.release import ReleaseResult, _next_version, release


def _state(tmp_path, *, runs=()):
    # Spec-0063/T3: Write run logs (status/branch/pr_number) in RuntimeState.set_run.
    state = RuntimeState(path=tmp_path / ".openagents" / "runtime-state.json")
    for issue_number, status in runs:
        state.set_run(
            issue_number=issue_number,
            branch=f"openagents/issue-{issue_number}",
            pr_number=issue_number * 10,
            status=status,
        )
    return state


def _patch_github(monkeypatch, *, open_prs=(), labeled=(), ci_green=True):
    """Pocket g Thub: open PR list, PR collection with needs-human, branch CI Green."""
    monkeypatch.setattr(
        release_module.github,
        "list_open_prs",
        lambda: [PR(number=n, url=f"u/pull/{n}") for n in open_prs],
    )
    monkeypatch.setattr(
        release_module.github,
        "has_label",
        lambda *, pr_number, name: pr_number in labeled,
    )
    monkeypatch.setattr(release_module.github, "branch_ci_green", lambda *, branch: ci_green)
    bootstrapped = []
    monkeypatch.setattr(
        release_module.github,
        "ensure_prerequisites",
        lambda: bootstrapped.append(True),
    )
    return bootstrapped


def _patch_git(monkeypatch, *, tags=(), push_returncode=0, stderr=""):
    """Pile subprocess.run: `git tag --list v*` returns tags, the rest (push/tag) records and returns as a result.

    Returns the calles list for the claim which git calls in turn.
    """
    calls = []

    def runner(args, **kwargs):
        calls.append(list(args))

        class _Proc:
            pass

        # Read published tags: returns separated tags (always successful).
        if args[:3] == ["git", "tag", "--list"]:
            _Proc.returncode = 0
            _Proc.stdout = "\n".join(tags)
            _Proc.stderr = ""
            return _Proc()
        # Graphical action (push branch / punch tag / push tag): returns with the preset result.
        _Proc.returncode = push_returncode
        _Proc.stdout = ""
        _Proc.stderr = stderr
        return _Proc()

    monkeypatch.setattr(subprocess, "run", runner)
    return calls


# --------------------------------------------------------------------------- #
# _next_version: An incremental purity function for version
# --------------------------------------------------------------------------- #


def test_next_version_no_tag_starts_at_initial():
    # No version available tag → Start v0.1.0(neglect) bump）。
    assert _next_version(latest=None, bump="patch") == "v0.1.0"
    assert _next_version(latest=None, bump="major") == "v0.1.0"


def test_next_version_patch_minor_major():
    assert _next_version(latest=(1, 2, 3), bump="patch") == "v1.2.4"
    assert _next_version(latest=(1, 2, 3), bump="minor") == "v1.3.0"
    assert _next_version(latest=(1, 2, 3), bump="major") == "v2.0.0"


def test_next_version_rejects_unknown_bump():
    with pytest.raises(ValueError):
        _next_version(latest=(1, 0, 0), bump="huge")


# --------------------------------------------------------------------------- #
# Pre-screen intercept.
# --------------------------------------------------------------------------- #


def test_failed_run_blocks_release(tmp_path, monkeypatch):
    state = _state(tmp_path, runs=[(3, STATUS_FAILED)])
    _patch_github(monkeypatch)
    git_calls = _patch_git(monkeypatch, tags=["v1.0.0"])

    result = release(state=state)

    assert isinstance(result, ReleaseResult)
    assert result.released is False
    assert result.version == ""
    assert "#3" in result.reason
    assert git_calls == []  # No pre-test. No touch.


def test_needs_human_pr_blocks_release(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch, open_prs=[8], labeled=[8])
    git_calls = _patch_git(monkeypatch)

    result = release(state=state)

    assert result.released is False
    assert "#8" in result.reason
    assert git_calls == []


def test_main_ci_not_green_blocks_release(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch, ci_green=False)
    git_calls = _patch_git(monkeypatch)

    result = release(state=state)

    assert result.released is False
    assert "CI" in result.reason
    assert "main" in result.reason
    assert git_calls == []


# --------------------------------------------------------------------------- #
# Pre-inspection complete.
# --------------------------------------------------------------------------- #


def test_all_checks_pass_materializes_branch_and_tag(tmp_path, monkeypatch):
    state = _state(tmp_path, runs=[(3, STATUS_PR_OPEN)])
    bootstrapped = _patch_github(monkeypatch, open_prs=[8], labeled=[])
    git_calls = _patch_git(monkeypatch, tags=["v1.2.3"])

    result = release(state=state)  # Default butmp=Patch

    assert result.released is True
    assert result.version == "v1.2.4"
    assert result.reason == "ok"
    assert bootstrapped == [True]  # Run a process label before you can get anything.
    # In turn: Read tag poush distribution branch jab tag poush tag.
    assert git_calls == [
        ["git", "tag", "--list", "v*"],
        ["git", "push", "origin", "main:refs/heads/release/v1.2.4"],
        ["git", "tag", "v1.2.4", "main"],
        ["git", "push", "origin", "v1.2.4"],
    ]


def test_first_release_without_tags_is_v0_1_0(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    git_calls = _patch_git(monkeypatch, tags=[])  # There's no tag in the warehouse.

    result = release(state=state)

    assert result.version == "v0.1.0"
    assert ["git", "push", "origin", "main:refs/heads/release/v0.1.0"] in git_calls


def test_bump_minor_and_semantic_ordering(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    # Semantic Sorting: The latest v0.10.0 (rather than v0.9.0 for dictionary).
    _patch_git(monkeypatch, tags=["v0.9.0", "v0.10.0"])

    result = release(state=state, bump="minor")

    assert result.version == "v0.11.0"


def test_bump_major(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    _patch_git(monkeypatch, tags=["v1.4.2"])

    result = release(state=state, bump="major")

    assert result.version == "v2.0.0"


def test_push_failure_raises(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    _patch_git(monkeypatch, tags=["v1.0.0"], push_returncode=1, stderr="protected branch")

    with pytest.raises(RuntimeError):
        release(state=state)


# --------------------------------------------------------------------------- #
# Spec-0035/T3: Network git(push) timeout  →  RuntemeError (with action); _git pass timeout=
# --------------------------------------------------------------------------- #


def test_push_timeout_raises_runtime_error_with_action(tmp_path, monkeypatch):
    # Push-on-line: Tag --list returns normally, Push-on TimeoutExpired  →  RuntimeError (with action)
    state = _state(tmp_path)
    _patch_github(monkeypatch)

    def runner(args, **kwargs):
        if args[:3] == ["git", "tag", "--list"]:
            return SimpleNamespace(returncode=0, stdout="v1.0.0", stderr="")
        raise subprocess.TimeoutExpired(cmd=args, timeout=30)

    monkeypatch.setattr(subprocess, "run", runner)
    with pytest.raises(RuntimeError) as excinfo:
        release(state=state)
    assert "Publish release branch" in str(excinfo.value)
    assert "timeout" in str(excinfo.value)


def test_release_git_passes_net_timeout(tmp_path, monkeypatch):
    # _git (push branch /tag/push tag) must pass timeout = _GIT_NET_TIMEOUT_SECONDS to subprocess.run.
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    seen = []

    def runner(args, **kwargs):
        if args[:3] == ["git", "tag", "--list"]:
            return SimpleNamespace(returncode=0, stdout="v1.0.0", stderr="")
        seen.append(kwargs.get("timeout"))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", runner)
    release(state=state)
    assert seen  # At least once.
    assert all(t == release_module._GIT_NET_TIMEOUT_SECONDS for t in seen)
