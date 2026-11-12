"""Spec-0042/T2: github.is_open / is_draft only read the compact test for thin wrapping.

All gh subprocesses are always mock (monkeypact subprocess.run), not called gh.
Overwhelming: is_open decision on OPEN/CLOSED/MERGED; is_draft decision on draft/ conversion to PR;
Unexpected structure  →  GithubError.
"""

import json
import subprocess
from dataclasses import dataclass

import pytest

from openagents.utils.github import GithubError, is_draft, is_open


@dataclass
class _FakeProc:
    """Hypothetical subprocess.CompletedProcess."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    """returns a subprocess.run double."""

    def runner(args, **kwargs):
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    return runner


# --------------------------------------------------------------------------- #
# is_open (Spec-0042:reopen recognition)
# --------------------------------------------------------------------------- #


def test_is_open_true_when_state_open(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "OPEN"})))
    assert is_open(pr_number=7) is True


def test_is_open_false_when_closed(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "CLOSED"})))
    assert is_open(pr_number=7) is False


def test_is_open_false_when_merged(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "MERGED"})))
    assert is_open(pr_number=7) is False


def test_is_open_gh_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not found"))
    with pytest.raises(GithubError):
        is_open(pr_number=7)


def test_is_open_non_dict_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps(["oops"])))
    with pytest.raises(GithubError):
        is_open(pr_number=7)


# --------------------------------------------------------------------------- #
# is_draft (Spec-0042: Distinguishing draft → rfc-review with Twir-open)
# --------------------------------------------------------------------------- #


def test_is_draft_true_when_draft(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"isDraft": True})))
    assert is_draft(pr_number=7) is True


def test_is_draft_false_when_ready(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"isDraft": False})))
    assert is_draft(pr_number=7) is False


def test_is_draft_gh_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not found"))
    with pytest.raises(GithubError):
        is_draft(pr_number=7)


def test_is_draft_missing_field_raises(monkeypatch):
    # Is Draft's missing is structural abnormal (non-breble) GithubError.
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "OPEN"})))
    with pytest.raises(GithubError):
        is_draft(pr_number=7)


def test_is_draft_non_dict_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps(["oops"])))
    with pytest.raises(GithubError):
        is_draft(pr_number=7)
