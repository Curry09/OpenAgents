"""Spec-0053/T2: github.code_fingerprint (PR net diff fingerprints) contract test.

All gh subprocesses are always mock (monkeywatch subprocess.run), not actually called gh. Overwrite:
- Same diff input of a stable and equal length for Hash (sha256 hexdigest = 64-bit hexadecimal);
- gh failed (not zero exit throw GithubError) returns ”fail-open”;
- gh, empty output returns ””;
- Same Diff fingerprints twice, different fingerprints after diff changes.
"""

import hashlib
import subprocess
from dataclasses import dataclass

from openagents.utils.github import code_fingerprint


@dataclass
class _FakeProc:
    """Hypothetical subprocess.CompletedProcess."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    """Returns a subprocess.run double and records the parameters for each call."""
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    runner.calls = calls
    return runner


_DIFF = "diff --git a/openagents/foo.py b/openagents/foo.py\n@@ -1,1 +1,2 @@\n x = 1\n+y = 2\n"


def test_code_fingerprint_matches_sha256_of_diff(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_DIFF))
    fp = code_fingerprint(pr_number=5)
    # Consistent with direct Sha256(diff); hexdigest fixed length 64.
    assert fp == hashlib.sha256(_DIFF.encode("utf-8")).hexdigest()
    assert len(fp) == 64


def test_code_fingerprint_invokes_gh_pr_diff(monkeypatch):
    runner = _fake_run(stdout=_DIFF)
    monkeypatch.setattr(subprocess, "run", runner)
    code_fingerprint(pr_number=42)
    assert runner.calls[-1] == ["gh", "pr", "diff", "42"]


def test_code_fingerprint_stable_across_calls(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_DIFF))
    first = code_fingerprint(pr_number=5)
    second = code_fingerprint(pr_number=5)
    assert first == second


def test_code_fingerprint_changes_when_diff_changes(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_DIFF))
    before = code_fingerprint(pr_number=5)
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_DIFF + "+z = 3\n"))
    after = code_fingerprint(pr_number=5)
    assert before != after


def test_code_fingerprint_empty_output_returns_empty(monkeypatch):
    # gh returns empty stdout (no diff)  →  (fail-open, caller back to normal evaluation).
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=""))
    assert code_fingerprint(pr_number=5) == ""


def test_code_fingerprint_gh_failure_returns_empty(monkeypatch):
    # gh Non-zero exit (business error, non-immediate) _run_gh throw GithubError Zi Zill into "fail-open".
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="pr not found"))
    assert code_fingerprint(pr_number=5) == ""
