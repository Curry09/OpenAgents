"""Spec-0035/T4: Found a slow check progress log - `_intake` pull tag issue before + `_admit` turn tracker LLLM in the previous rows of stderr.

The discovery section is currently only log-checked when ** results** are available. The web/LLM is all mute.
Socket / Slow Model hangs, last line log stops at the last ** result** line, does not see which one of the positive cards is. Here only two things are nailed:

1. `_intake` before `github.list_issues`** ** ”Performance Discovery: Pull Label Issue...”;
2. `_admit` (agonal) before `stages.triage`****, ** ”...issue #N self-diagnosis orientation (LLLM)...”.

Progress line only stderr,** does not change any return values / side effects / control flow** - This document is also pinned to ”no change in existing behaviour by by bytes”.
The sister file `test_recipe_vigil_admit.py` is the main entry dialogue, which is not linked to this document (only this article in the progress log).
github/stages, untouched real network / LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime

from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import _admit, _intake
from openagents.utils import agent_config, github

_NOW = datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC)


def _stages(**owners) -> agent_config.StagePolicy:
    return agent_config.StagePolicy(owners=owners)


def _config(**overrides) -> agent_config.AgentConfig:
    defaults = {
        "version": 1,
        "agents": agent_config.AgentPolicy(backends={}),
        "stages": _stages(triage="agent"),
        "release": agent_config.ReleasePolicy(),
        "interval": 1,
        "base": "main",
        "labels": ["openagents"],
        "repos": [],
    }
    return agent_config.AgentConfig(**(defaults | overrides))


def _issue(*, number: int) -> github.Issue:
    return github.Issue(number=number, title="Title", body="Text", labels=())


def _keep_discovered(monkeypatch) -> None:
    """# Spec-0074/T1: The latest access test still has its full label."""
    monkeypatch.setattr(
        vigil_module.github,
        "get_issue",
        lambda *, number: github.Issue(
            number=number, title="Title", body="Text", labels=("openagents",)
        ),
    )


# --------------------------------------------------------------------------------------------------
# T4-A: `_intake` before Zalong Label issue** **  →  — The output stopped in this line while the Laissue was stuck.
# --------------------------------------------------------------------------------------------------


def test_intake_logs_progress_before_listing_issues(monkeypatch, tmp_path, capsys):
    order: list[str] = []
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)

    def _list_issues(*, labels):
        order.append("list_issues")
        return []

    monkeypatch.setattr(vigil_module.github, "list_issues", _list_issues)

    def _spy_log(*, message):
        if "Discovering issues with the configured labels" in message:
            order.append("log")

    monkeypatch.setattr(vigil_module, "_log", _spy_log)

    _intake(backend=object(), work_dir=tmp_path, config=_config(), agent_id="vigil-1", now=_NOW)

    assert order == ["log", "list_issues"], (
        "The progress line has to be played before the issue or it’s stuck without seeing it stop."
    )


def test_intake_progress_line_lands_on_stderr(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)
    monkeypatch.setattr(vigil_module.github, "list_issues", lambda *, labels: [])

    _intake(backend=object(), work_dir=tmp_path, config=_config(), agent_id="vigil-1", now=_NOW)

    captured = capsys.readouterr()
    assert "Discovering issues with the configured labels" in captured.err
    assert "Discovering issues with the configured labels" not in captured.out, (
        "Progress log only stderr, not contaminated stdout"
    )


def test_intake_behaviour_unchanged_admits_and_orders_edges(monkeypatch, tmp_path):
    # The byte is the same: progress does not change the flow - issue passes triager access, plays ready, ranks >0.
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)
    monkeypatch.setattr(vigil_module.github, "list_issues", lambda *, labels: [_issue(number=5)])
    _keep_discovered(monkeypatch)
    labels: list[tuple[int, str]] = []
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: labels.append((number, name)),
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "triage",
        lambda *, backend, work_dir, issue: {"actionable": True, "reason": ""},
    )
    ordered: list[object] = []
    monkeypatch.setattr(
        vigil_module,
        "_order_edges",
        lambda *, backend, work_dir, config, agent_id: ordered.append(True),
    )

    _intake(backend=object(), work_dir=tmp_path, config=_config(), agent_id="vigil-1", now=_NOW)

    assert (5, vigil_module._LABEL_READY) in labels
    assert ordered == [True], (
        "admitted>0 → As usual. curator Line dependence edge (control flow is not changed by progress line)"
    )


# --------------------------------------------------------------------------------------------------
# T4-B: `_admit` (agent state) before the triager LLM** ** ** ** — output stopped in this line while stuck in the LLM ' s consultation.
# --------------------------------------------------------------------------------------------------


def test_admit_logs_progress_before_triage_llm(monkeypatch, tmp_path):
    order: list[str] = []
    _keep_discovered(monkeypatch)
    monkeypatch.setattr(vigil_module.github, "issue_add_label", lambda *, number, name: None)

    def _triage(*, backend, work_dir, issue):
        order.append("triage")
        return {"actionable": True, "reason": ""}

    monkeypatch.setattr(vigil_module.stages, "triage", _triage)

    def _spy_log(*, message):
        if "triaging with the model" in message:
            order.append("log")

    monkeypatch.setattr(vigil_module, "_log", _spy_log)

    admitted = _admit(
        owner="agent",
        backend=object(),
        work_dir=tmp_path,
        config=_config(),
        issue=_issue(number=9),
        agent_id="vigil-1",
        discovery_labels=("openagents",),
    )

    assert admitted == 1, "Existing return value remains unchanged: actionable poaching (return 1)"
    assert order == ["log", "triage"], (
        "The progress line must be called before the LLM is transferred, otherwise the card does not stop at this point in the session."
    )


def test_admit_progress_line_carries_issue_number_on_stderr(monkeypatch, tmp_path, capsys):
    _keep_discovered(monkeypatch)
    monkeypatch.setattr(vigil_module.github, "issue_add_label", lambda *, number, name: None)
    monkeypatch.setattr(
        vigil_module.stages,
        "triage",
        lambda *, backend, work_dir, issue: {"actionable": True, "reason": ""},
    )

    _admit(
        owner="agent",
        backend=object(),
        work_dir=tmp_path,
        config=_config(),
        issue=_issue(number=42),
        agent_id="vigil-1",
        discovery_labels=("openagents",),
    )

    err = capsys.readouterr().err
    assert "issue #42 triaging with the model" in err, (
        "The progress line must be marked with the issue number, which one is the one when it’s stuck?"
    )


def test_admit_skip_route_does_not_log_triage_progress(monkeypatch, tmp_path, capsys):
    # Return: The kip state is released and does not match the triager, so it is not appropriate to hit the "lLM" progress line (the progress is only a real, slow agnant).
    _keep_discovered(monkeypatch)
    monkeypatch.setattr(vigil_module.github, "issue_add_label", lambda *, number, name: None)

    admitted = _admit(
        owner="skip",
        backend=object(),
        work_dir=tmp_path,
        config=_config(),
        issue=_issue(number=7),
        agent_id="vigil-1",
        discovery_labels=("openagents",),
    )

    assert admitted == 1
    assert "triaging with the model" not in capsys.readouterr().err, "Skip, not LLM."


def test_intake_does_not_grant_ready_after_discovery_label_is_removed(monkeypatch, tmp_path):
    """# Spec-0074/T1: list before Grant, the old snapshot cannot continue to be sent, nor can it trigger the Curator."""
    discovered = github.Issue(number=5, title="Title", body="Text", labels=("openagents",))
    removed = github.Issue(number=5, title="Title", body="Text", labels=("bug",))
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)
    monkeypatch.setattr(vigil_module.github, "list_issues", lambda *, labels: [discovered])
    monkeypatch.setattr(vigil_module.github, "get_issue", lambda *, number: removed)
    granted: list[tuple[int, str]] = []
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: granted.append((number, name)),
    )
    ordered: list[bool] = []
    monkeypatch.setattr(
        vigil_module, "_order_edges", lambda *, backend, work_dir, agent_id: ordered.append(True)
    )

    _intake(
        backend=object(),
        work_dir=tmp_path,
        config=_config(stages=_stages(triage="skip")),
        agent_id="vigil-1",
        now=_NOW,
    )

    assert granted == [], "  Discovery label removed and yet ready  "
    assert ordered == [], "Zero access should not trigger a curator."
