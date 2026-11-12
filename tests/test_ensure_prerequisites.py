"""RFC-0015 / Spec-0023/T1: ensure_prerequisites (Union Cold Start Wall)+ Unit Test for Single Source Alien

Coverage:
  - ensure_prerequisites vs PROCESS_LABELS, one by one ensure_label, one by one (Spec-0023/T1:test branch)
    No more test branch after the door control has been decommissioned, constricted to pre-form process labels only);
  - Repeating call to existing tag no-op (subproces layer simulation of ”already names” without error);
  - Single source for labels: cli has a constant of github (is the same object) as the existing public aliases.
    Spec-0062/T6:messages used to be removed and its APPROVAL_LABEL aliases asserted that it was subsequently decommissioned.
    Spec-0063/T5: state delete state.py, with its BLOCKED_LABEL aliases assert that it is retired
    (BLOCKED_LABEL authoritative source is gethub, release/board is directly connected).
All gh subprocesses are always mock, not really calling gh.
"""

import subprocess
from dataclasses import dataclass

from openagents import cli
from openagents.utils import github
from openagents.utils.github import (
    APPROVAL_LABEL,
    AUTOMATION_FAILED_LABEL,
    DISCOVERY_LABEL,
    DISPATCH_LABEL,
    PROCESS_LABELS,
    ensure_prerequisites,
)


@dataclass
class _FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


# --------------------------------------------------------------------------- #
# Organization: ensure_label x PROCESS_LABELS (Spec-0023/T1: no more test branch)
# --------------------------------------------------------------------------- #


def test_ensure_prerequisites_orchestrates_labels_only(monkeypatch):
    # The reused jar function, the assertion ensure_prerequisites Only labels, no branches.
    label_calls = []
    monkeypatch.setattr(github, "ensure_label", lambda *, name: label_calls.append(name))

    ensure_prerequisites()

    # Yeah. PROCESS_LABELS One for each label ensure_label(The order is consistent).
    assert label_calls == list(PROCESS_LABELS)
    # test branch has been removed: github is no longer exposed ensure_branch.
    assert not hasattr(github, "ensure_branch")


# --------------------------------------------------------------------------- #
# Query: Tag already exists Query Repeat Call Equities No-op, Do Not Drop
# --------------------------------------------------------------------------- #


def test_ensure_prerequisites_idempotent_when_all_exist(monkeypatch):
    # Simulates the "already exits" on subprocess, and repeats the assertion twice that it is not wrong:
    # The uniform is reused ensure_label Take it.
    def runner(args, **kwargs):
        # gh label create...  →  Simulate already existy exists (ensure_label swallowing is considered successful).
        if args[:3] == ["gh", "label", "create"]:
            return _FakeProc(returncode=1, stderr="label already exists")
        return _FakeProc(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", runner)

    ensure_prerequisites()
    ensure_prerequisites()  # The second time, no-op, no anomaly.


# --------------------------------------------------------------------------- #
# Single source for labels: three aliases with a common name gethub constant (is the same object)
# --------------------------------------------------------------------------- #


def test_label_constants_are_aliases_of_github():
    assert cli.DISCOVERY_LABEL is github.DISCOVERY_LABEL


def test_process_labels_cover_all_four():
    # Spec-0039/T1: Recognize the labels openagents-dispatching to be added to PROCESS_LABELS (Fourth Process Label)
    # Initialization must not create or switch a branch.
    assert PROCESS_LABELS == (
        DISCOVERY_LABEL,
        APPROVAL_LABEL,
        AUTOMATION_FAILED_LABEL,
        DISPATCH_LABEL,
    )
    assert (DISCOVERY_LABEL, APPROVAL_LABEL, AUTOMATION_FAILED_LABEL, DISPATCH_LABEL) == (
        "openagents",
        "rfc-approved",
        "automation-failed",
        "openagents-dispatching",
    )
