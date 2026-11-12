"""Spec-0032/T2: github.remove_label encapsulation unit test.

All gh subprocesses are always mock (monkeywatch subprocess.run), not actually called gh. Overwrite:
- `gh pr edit <n> --remove-label <name>`;
- The label returns in its absence;
- Other gh mistakes routinely throw GithubError.
"""

import subprocess
from dataclasses import dataclass

import pytest

from openagents.utils.github import GithubError, remove_label


@dataclass
class _FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    runner.calls = calls
    return runner


def test_remove_label_invokes_gh_pr_edit(monkeypatch):
    runner = _fake_run(stdout="")
    monkeypatch.setattr(subprocess, "run", runner)

    assert remove_label(pr_number=7, name="needs-human") is None
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "edit"]
    assert "7" in cmd
    assert "--remove-label" in cmd
    assert "needs-human" in cmd


def test_remove_label_ignores_not_found(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(returncode=1, stderr="could not remove label: 'needs-human' not found"),
    )
    # The label was not in the t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t-t
    assert remove_label(pr_number=7, name="needs-human") is None


def test_remove_label_ignores_does_not_have_label(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(returncode=1, stderr="pull request does not have the label needs-human"),
    )
    assert remove_label(pr_number=7, name="needs-human") is None


def test_remove_label_ignores_does_not_exist(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(returncode=1, stderr="label 'needs-human' does not exist"),
    )
    assert remove_label(pr_number=7, name="needs-human") is None


def test_remove_label_reraises_other_errors(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401 must authenticate")
    )
    with pytest.raises(GithubError):
        remove_label(pr_number=7, name="needs-human")


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
