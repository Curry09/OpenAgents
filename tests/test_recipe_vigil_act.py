"""Spec-0065/T2: recipes.vigil** Action side** (`_act` and seven `_do_*` branches) is a single measurement.

`tests/test_recipe_vigil.py` covers ** sensory ** (sense/classify/fingerprint/watchdog/ queue/survival detection)
`_act` is taken off every corner -- so the section between ”declared dry X” and ”dry dry X” (routing + side effects of seven branches)
None of the lines have been executed. This document adds to that paragraph, which is the crucifying of four things:

- **Routes are mechanical.**：`verdict.action` → The only stage/agent One test each. worktree Which one?
  issue/PR. Three-state `human` is all down `_park_gate` (ticks needs-human,** zero anggent call**).
- **First-class export contracts are in place.**：`_NEEDS_HUMAN_CONTRACT` It has to be there.**Every one.**Pie. agent I’ll give you the branch. agent ..in the context of the
  (Incl. `_do_reply` / `_do_rebase` - without it, ”failed / undefended conflict” can only be used to support the main path on the spot.
  The claim is that `engine.run_agent`, the only **agent exit, **, so the stage is not able to escape from the rest of the placeholders.
-**worktree not shared**: two** different standalone PR** (no issue) must have **** worktree directory - all degraded to
  `issue-0` will change the code in the same directory for two working-time parties to push the change to another ’PR’ (flock cannot stop):
  They were two sub-projects, shared with ** resources**).
- ** Hard-timed kill-to-time process**: `_TimedBackend` timeout  →  `_ActTimeout` + Kill only **PID called this time in self-report** (others  →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →  ** ** ** This time-to-time kill PID called in self-report**
  No one touches -- the one who really hangs when the wrong process is going to go on and push, and double-digs just leak out of this hole.

Full time off backend + - Prick. engine/stages It’s... IO Border (Boundary)github/git/gates/identity/proc）  Don’t touch the truth   LLM/Network/The warehouse,
And it’s not really killing any process.

Spec-0056 / Spec-0017 Supplement: 2026-09-09-delivery-review-snapshot-tests-design.md
The prodigability of wrong approvals and normal deliveries is also covered; all returns after repair are performed as routine tests.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import (
    _ACT_E2E,
    _ACT_FIX_CI,
    _ACT_MERGE,
    _ACT_READY,
    _ACT_REBASE,
    _ACT_REPLY,
    _ACT_REVIEW_OR_FIX,
    _ACT_SOLVE,
    _AUTONOMOUS_CONTRACT,
    _ActTimeout,
    _classify,
    _Clock,
    _conflict_fingerprint,
    _Facts,
    _Observed,
    _pr_worktree,
    _TimedBackend,
)
from openagents.runtime import engine, gates
from openagents.runtime.gates import assert_merge_allowed
from openagents.utils import agent_config, git, github, identity, proc
from openagents.utils.workspace import Workspace, WorkspaceError

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_HEAD = "abc1234def5678901234567890123456789abcde"
_SHA7 = _HEAD[:7]

# Spec-0065/T2: A false decision (engine is a stake, so here is "agent says what") by OUTPUT_SCHEMA by each agent.
_AGENT_OUTPUTS: dict[str, dict] = {
    "spec_writer": {
        "status": "READY",
        "head_sha": _HEAD,
        "summary": "compact spec",
        "blocker": "",
        "objective_coverage": [{"scope_coverage": "FULL", "evidence_level": "STRUCTURAL"}],
        "candidate_assessments": [
            {
                "candidate": "one",
                "ownership": "runtime",
                "delivery": "wired",
                "control_effect": "guard",
                "evidence": "source",
                "assumptions": "none",
                "failure_modes": "bypass",
                "verdict": "selected",
            }
        ],
        "selected_intervention": {},
        "evidence_pack": [],
        "falsifiers": [],
    },
    "drafter": {
        "delivered": True,
        "head_sha": _HEAD,
        "summary": "spec drafted",
        "evidence_pack": [],
    },
    "implementer": {"summary": "Modified by feedback"},
    "executor": {
        "summary": "Achieved by means of a command spec",
        "head_sha": _HEAD,
        "lookup_exception_reason": "",
    },
    "acceptance": {
        "verdict": "PASS",
        "reason": "Original issue satisfied",
        "evidence": [
            {
                "case_id": "original",
                "source": "original_replay",
                "kind": "behavior",
                "observed": "original failure no longer reproduces",
                "expected": "original objective is satisfied",
                "path": "artifacts/original.log",
                "passed": True,
            },
            {
                "case_id": "variant",
                "source": "independent_variant",
                "kind": "behavior",
                "observed": "independent semantic variant passes",
                "expected": "implementation is not sample-specific",
                "path": "artifacts/variant.log",
                "passed": True,
            },
        ],
    },
    "reviewer": {"verdict": "PASS", "reason": "It looks good."},
    "tester": {
        "verdict": "PASS",
        "reason": "E2e Full green",
        "evidence": [
            {"case_id": "p", "kind": "behavior", "observed": "ok", "expected": "ok", "path": "log"}
        ],
    },
    "replier": {"reply": "I’ve answered your question.", "resolved": True},
    "deliver": {
        "delivered": True,
        "base_sha": "0" * 40,
        "head_sha": _HEAD,
        "summary": "Push already",
    },
    "merger": {"merged": True, "summary": "Merged"},  # Spec-0017/T3: merge action
}


# --------------------------------------------------------------------------------------------------
# Plugin: acts / config model (same as test_recipe_vigil.py)+ set of probes to record all external side effects `_Rig`.
# --------------------------------------------------------------------------------------------------


def _facts(**overrides) -> _Facts:
    """A ”all-in-all, all-in-all” fact sheet (subsection 11) is returned to one of the units on a single field-by-field basis."""
    base = _Facts(
        subject="issue:5",
        pr_number=12,
        head_sha=_HEAD,
        merged=False,
        closed=False,
        labels=frozenset({f"review-approved:{_SHA7}"}),
        deps_done=True,
        mergeable_state="clean",
        ci="success",
        e2e_head_sha=_HEAD,
        review_state="APPROVED",
        review_commit_id=_SHA7,
        latest_comment_is_ours=True,
    )
    return replace(base, **overrides)


def _stages_policy(**owners) -> agent_config.StagePolicy:
    return agent_config.StagePolicy(owners=owners)


def _config(**overrides) -> agent_config.AgentConfig:
    defaults = {
        "version": 1,
        "agents": agent_config.AgentPolicy(backends={}),
        "stages": _stages_policy(),
        "release": agent_config.ReleasePolicy(),
        "interval": 1,
        "base": "main",
        "labels": ["openagents"],
        "repos": [],
    }
    return agent_config.AgentConfig(**(defaults | overrides))


class _Rig:
    """All external side effects probes for `_act` at a time: Both `RuntimeState` doubles (set_run/ get_cursor/ set_cursor)."""

    def __init__(self) -> None:
        self.agents: list[
            tuple[str, dict]
        ] = []  # (agent module name, placeholder received by engine)
        self.backends: list[object] = []  # Back in every pie agent (consistent _timedback)
        self.gh: list[tuple] = []  # gthub to run water
        self.runs: list[tuple] = []  # state.set_run
        self.cursors: list[tuple] = []  # state.set_cursor
        self.comments: list[tuple] = []  # identity.post_signed_comment
        self.worktrees: list[tuple] = []  # Workspace.prepare / ensure
        self.run_records: dict[int, dict] = {}
        self.review_feedback: dict[int, dict[str, str]] = {}
        self.delivered = True  # Default fixture models an already-pushed candidate.

    # --- Runtimestate (vigil only) ---
    def set_run(
        self,
        *,
        issue_number: int,
        status: str,
        branch: str,
        pr_number: int,
        design_digest: str = "",
        design_raw_digest: str = "",
        evidence_pack: list | None = None,
    ) -> None:
        self.runs.append((issue_number, status, branch, pr_number))
        previous = self.run_records.get(issue_number, {})
        self.run_records[issue_number] = {
            "status": status,
            "branch": branch,
            "pr_number": pr_number,
            "design_digest": design_digest or previous.get("design_digest", ""),
            "design_raw_digest": design_raw_digest or previous.get("design_raw_digest", ""),
            "evidence_pack": (
                evidence_pack if evidence_pack is not None else previous.get("evidence_pack", [])
            ),
        }

    def get_run(self, *, issue_number: int) -> dict | None:
        return self.run_records.get(issue_number)

    def get_review_feedback(self, *, issue_number: int, head_sha: str) -> str | None:
        record = self.review_feedback.get(issue_number, {})
        return record.get("reason") if record.get("head_sha") == head_sha else None

    def set_review_feedback(self, *, issue_number: int, head_sha: str, reason: str) -> None:
        self.review_feedback[issue_number] = {"head_sha": head_sha, "reason": reason}

    def get_cursor(self, *, pr_number: int) -> str:
        return ""

    def set_cursor(self, *, pr_number: int, comment_id: str) -> None:
        self.cursors.append((pr_number, comment_id))

    # --- Easy Query ---
    def agent_names(self) -> list[str]:
        return [name for name, _ in self.agents]

    def context_of(self, *, agent: str) -> str:
        return next(place["context"] for name, place in self.agents if name == agent)

    def gh_names(self) -> list[str]:
        return [call[0] for call in self.gh]


class _FakeWorkspace:
    """`git.Workspace` double: Do not touch guit, produce worktree path and record key."""

    def __init__(self, *, work_dir: Path) -> None:
        self._work_dir = Path(work_dir)

    def prepare(self, *, issue_number: int, branch: str, base: str) -> Path:
        _RIG.worktrees.append(("prepare", issue_number, branch, base))
        return self._path(issue_number=issue_number)

    def ensure(self, *, issue_number: int, branch: str) -> Path:
        _RIG.worktrees.append(("ensure", issue_number, branch))
        return self._path(issue_number=issue_number)

    def assert_delivered(self, *, worktree: Path, branch: str) -> None:
        _RIG.worktrees.append(("assert-delivered", Path(worktree), branch))

    def delivery_heads(self, *, worktree: Path, branch: str) -> tuple[str, str]:
        _RIG.worktrees.append(("delivery-heads", Path(worktree), branch))
        return _HEAD, _HEAD

    def sync_delivered(self, *, worktree: Path, branch: str) -> bool:
        _RIG.worktrees.append(("sync-delivered", Path(worktree), branch))
        return _RIG.delivered

    def remote_branch_exists(self, *, branch: str) -> bool:
        return False

    def _path(self, *, issue_number: int) -> Path:
        return self._work_dir / ".openagents" / "worktrees" / f"issue-{issue_number}"


# `_FakeWorkspace` is constructed from the vigil internal `git.Workspace(...)`, untested closed  →  probe mounted module level, reset by fixture.
_RIG = _Rig()


class _Backend:
    """The fake backend-engine has been put on a stake and it should not be really run."""

    name = "fake"

    def run(self, *, work_dir, task, context):  # No cover - should not be transferred
        raise AssertionError("engine.run_agent staked, backend.run should not be called")


@pytest.fixture
def rig(monkeypatch) -> _Rig:
    """All IO boundaries for `_act` stakes: engine (single-source export)/ git /get /gates / education."""
    global _RIG
    _RIG = _Rig()
    probe = _RIG

    def _run_agent(agent_module, *, backend, **placeholders):
        name = agent_module.__name__.rsplit(".", 1)[-1]
        probe.agents.append((name, dict(placeholders)))
        probe.backends.append(backend)
        return dict(_AGENT_OUTPUTS[name])

    monkeypatch.setattr(engine, "run_agent", _run_agent)

    # gates: Three sets of certainty gates for the delivery class (rfc/deliver/conflict) - this document is unsuspected (T1 nailed) and release is sufficient.
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: "0" * 40)
    monkeypatch.setattr(gates, "assert_head_advanced", lambda *, before, workspace: _HEAD)
    monkeypatch.setattr(gates, "assert_evidence_stamp", lambda *, head_sha, claimed: None)
    monkeypatch.setattr(gates, "assert_repository_integrity", lambda *, workspace: None)
    monkeypatch.setattr(gates, "assert_design_approved", lambda **kwargs: None)
    monkeypatch.setattr(git, "head_sha", lambda *, work_dir: _HEAD)
    monkeypatch.setattr(
        github,
        "pr_snapshot",
        lambda *, pr_number: github.PRSnapshot(
            number=pr_number,
            state="OPEN",
            head_sha=_HEAD,
            labels=(),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            head_pushed_at="",
        ),
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "architecture",
        lambda **kwargs: {
            "verdict": "PASS",
            "reason": "ok",
            "design_digest": "d",
            "spec_path": "docs/specs/0001-x.md",
        },
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "design_snapshot",
        lambda **kwargs: {"design_digest": "minimal-digest", "spec_path": "docs/specs/0001-x.md"},
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "minimal_design_snapshot",
        lambda **kwargs: {
            "design_digest": "minimal-digest",
            "spec_path": "docs/objectives/issue-5.md",
        },
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "assert_minimal_design_approved",
        lambda **kwargs: None,
    )
    # Spec-0017/T3: Merge the hardlock - This document is unsuspected (T3 test_runtime_gates nailed), let go; only check for merger action to decentralize meger.
    monkeypatch.setattr(
        gates,
        "assert_merge_allowed",
        lambda *, pr_number, head_sha, require_ci=True: None,
    )

    monkeypatch.setattr(git, "Workspace", _FakeWorkspace)
    # ``recipes.stages`` imports Workspace directly, so patch that bound name too.
    # This keeps the recipe tests hermetic now that minimal_spec verifies remote
    # delivery before stamping the host-observed HEAD.
    monkeypatch.setattr(vigil_module.stages, "Workspace", _FakeWorkspace)
    # Spec-0074: refc:skip-state certainty id branch (empty commission+push) - Pile record, not real grate.
    monkeypatch.setattr(
        git,
        "seed_branch",
        lambda *, work_dir, branch, message: probe.worktrees.append(("seed", branch)),
    )

    def _gh(name: str, result=None):
        def _call(**kwargs):
            probe.gh.append((name, kwargs))
            return result

        monkeypatch.setattr(github, name, _call)

    _gh("get_issue", github.Issue(5, "Title", "- Yes, sir.", []))
    _gh("create_pr", github.PR(12, "https://example.invalid/pr/12"))
    _gh("mark_ready")
    _gh("merge_pr")
    _gh("close_issue")
    _gh("ensure_label")
    _gh("add_label")
    _gh("remove_label")
    _gh("issue_add_label")
    _gh("issue_comment")
    _gh("post_comment")
    # Park's reason comment book etc.: Read back the comment stream and re-heavy (no emptiness). The two stakes are missing, and the test will really be done with `gh`.
    _gh("list_issue_comments", [])
    _gh("list_comments", [])
    _gh("update_branch", False)  # Default "mechanical update-branch"
    _gh("check_logs", ["FAILED tests/test_x.py::test_y"])
    monkeypatch.setattr(github, "pr_head_branch", lambda *, pr_number: f"branch-of-pr-{pr_number}")

    monkeypatch.setattr(
        identity,
        "new_human_comments",
        lambda *, pr_number, since: [
            github.Comment(7, "human", "Why do you write that here?", "2026-07-14T11:00:00Z")
        ],
    )
    monkeypatch.setattr(
        identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: probe.comments.append((pr_number, body, agent_id)),
    )
    return probe


def _act(
    *, rig: _Rig, facts: _Facts, work_dir: Path, config=None, lock_fd: int | None = None
) -> str:
    """One run by `_act` - vedict from **Sin** `_classify`, it is impossible to say a word between route and branch table.

    `lock_fd` = the accepted flock fd, passed to `_TimedBackend` to allow the agent subprocess to inherit (survival certificate following the work process).
    These examples are only for route and side effects, and do not lend themselves to the real-son process, so the default is not passed on to fd.
    """
    return vigil_module._act(
        backend=_Backend(),
        state=rig,
        work_dir=Path(work_dir),
        config=config or _config(),
        observed=_Observed(facts=facts, clock=_Clock(last_progress_at=_NOW)),
        verdict=_classify(facts=facts, in_flight=False),
        agent_id="bot",
        now=_NOW,
        lock_fd=lock_fd,
    )


def _issue_worktree(work_dir: Path, number: int) -> Path:
    return Path(work_dir) / ".openagents" / "worktrees" / f"issue-{number}"


@pytest.mark.parametrize("votes", [["PASS"], ["REWORK", "PASS"], ["REWORK", "REWORK"]])
def test_design_recovery_requires_an_actual_pass(rig, tmp_path, monkeypatch, votes):
    """Spec-0090/T1: a validated/refined Spec does not approve itself."""
    rig.set_run(
        issue_number=5,
        status="pr-open",
        branch="openagents/issue-5",
        pr_number=12,
        design_digest="old",
        design_raw_digest="old-raw",
    )
    calls = []
    remaining = iter(votes)

    def review(**kwargs):
        calls.append(kwargs)
        return {
            "verdict": next(remaining),
            "reason": "retain original acceptance",
            "design_digest": "new",
            "design_raw_digest": "new-raw",
            "spec_path": "docs/specs/0001-x.md",
        }

    monkeypatch.setattr(vigil_module.stages, "architecture", review)
    monkeypatch.setattr(gates, "snapshot_head", lambda **kw: _HEAD)
    timed = _TimedBackend(inner=_Backend(), timeout_seconds=10, lock_fd=None)
    kwargs = dict(backend=timed, state=rig, work_dir=tmp_path, facts=_facts())
    if votes[-1] == "REWORK":
        with pytest.raises(gates.GateError, match="remains unapproved after revision"):
            vigil_module._refresh_design_approval(**kwargs)
        assert rig.get_run(issue_number=5)["design_digest"] == "old"
    else:
        vigil_module._refresh_design_approval(**kwargs)
        assert rig.get_run(issue_number=5)["design_digest"] == "new"
    assert len(calls) == len(votes)
    assert all(call["backend"] is timed for call in calls)
    assert all("old-raw" in call["context_text"] for call in calls)
    assert rig.agent_names() == (["drafter"] if len(votes) == 2 else [])
    assert "merger" not in rig.agent_names()


def test_design_recovery_does_not_approve_changed_candidate(rig, tmp_path, monkeypatch):
    """Spec-0090/T1: even a PASS is invalid after the published head changes."""
    rig.set_run(
        issue_number=5,
        status="pr-open",
        branch="openagents/issue-5",
        pr_number=12,
        design_digest="old",
    )

    def changed(**kwargs):
        raise gates.MergeNotReady("candidate changed during architecture")

    monkeypatch.setattr(vigil_module, "_verify_candidate", changed)
    with pytest.raises(gates.MergeNotReady):
        vigil_module._refresh_design_approval(
            backend=_Backend(), state=rig, work_dir=tmp_path, facts=_facts()
        )
    assert rig.get_run(issue_number=5)["design_digest"] == "old"


@pytest.mark.parametrize("fixed", [True, False])
def test_integrity_repair_rechecks_the_delivered_tree(rig, tmp_path, monkeypatch, fixed):
    """Spec-0090/T1: send precise gate evidence to the writer, then verify its result."""
    checks = []

    def verify(**kwargs):
        checks.append(kwargs)
        if not fixed:
            raise gates.RepositoryIntegrityStale("still inconsistent")

    monkeypatch.setattr(gates, "assert_repository_integrity", verify)
    kwargs = dict(
        backend=_Backend(),
        state=rig,
        work_dir=tmp_path,
        config=_config(),
        facts=_facts(),
        reason="0099/T1 has an invalid dependency",
    )
    if fixed:
        vigil_module._repair_repository_integrity(**kwargs)
    else:
        with pytest.raises(gates.RepositoryIntegrityStale, match="still inconsistent"):
            vigil_module._repair_repository_integrity(**kwargs)
    assert len(checks) == 1
    assert rig.agent_names() == ["implementer"]
    placeholders = rig.agents[0][1]
    assert "invalid dependency" in (str(placeholders.get("feedback", "")) + placeholders["context"])


@pytest.fixture
def delivery_snapshot(rig, tmp_path, monkeypatch):
    """Spec-0056/0017 Supplement: Restore real assert_delivered/merge_allowed, with the rest following Rig."""
    snapshot = {"head": _HEAD, "remote": _HEAD, "status": "", "effects": {}, "git": []}
    _issue_worktree(tmp_path, 5).mkdir(parents=True)
    compact = _issue_worktree(tmp_path, 5) / "docs" / "objectives" / "issue-5.md"
    compact.parent.mkdir(parents=True)
    compact.write_text("compact objective: finish original issue\n", encoding="utf-8")
    monkeypatch.setattr(
        vigil_module.stages,
        "minimal_design_snapshot",
        lambda **kwargs: {"design_digest": "minimal-digest", "spec_path": str(compact)},
    )

    def workspace_git(self, *, args, cwd, check):
        snapshot["git"].append(list(args))
        command = args[0]
        if command == "rev-parse":
            output = snapshot["head"] if args[1] == "HEAD" else snapshot["remote"]
        elif command == "status":
            output = snapshot["status"]
        elif command == "merge-base":
            behind = snapshot["head"] == _HEAD and snapshot["remote"] != _HEAD
            return SimpleNamespace(returncode=0 if behind else 1, stdout="", stderr="")
        elif command == "merge":
            snapshot["head"] = snapshot["remote"]
            output = ""
        elif command in {"fetch", "ls-remote", "worktree", "branch"}:
            output = ""
        else:
            # The new IO needs a visible modeling, and it is not allowed to be left silent for green.
            raise RuntimeError(f"snapshot test has no Git stub for {args!r}")
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(Workspace, "_git", workspace_git)
    monkeypatch.setattr(git, "Workspace", Workspace)
    monkeypatch.setattr(vigil_module.stages, "Workspace", Workspace)
    monkeypatch.setattr(git, "head_sha", lambda *, work_dir: snapshot["head"])
    monkeypatch.setattr(git, "porcelain", lambda *, work_dir: snapshot["status"])
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: snapshot["head"])
    monkeypatch.setattr(gates, "assert_merge_allowed", assert_merge_allowed)
    monkeypatch.setattr(
        github,
        "pr_snapshot",
        lambda *, pr_number: github.PRSnapshot(
            number=pr_number,
            state="OPEN",
            head_sha=snapshot["remote"],
            labels=tuple(_delivery_snapshot_labels(rig=rig)),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            head_pushed_at="",
        ),
    )
    monkeypatch.setattr(
        github,
        "check_snapshot",
        lambda *, pr_number: github.CheckSnapshot(state="pass", count=1, latest_started_at=""),
    )
    run_agent = engine.run_agent

    def run_with_effect(agent_module, *, backend, **placeholders):
        report = run_agent(agent_module, backend=backend, **placeholders)
        effect = snapshot["effects"].get(agent_module.__name__.rsplit(".", 1)[-1])
        if effect is not None:
            effect()
        return report

    monkeypatch.setattr(engine, "run_agent", run_with_effect)
    return snapshot


def _delivery_snapshot_labels(*, rig):
    """Spec-0017 supplements: Write projection labels from actual forge, which are approved without test assumptions."""
    labels = set()
    for name, call in rig.gh:
        if name == "add_label":
            labels.add(call["name"])
        elif name == "remove_label":
            labels.discard(call["name"])
    return labels


def _delivery_snapshot_finish(*, rig, snapshot, work_dir, config):
    """Spec-0017 Supplement: Only the actual approvals generated drive the next merger, without forging PASS."""
    labels = _delivery_snapshot_labels(rig=rig)
    head = snapshot["remote"]
    assert f"review-approved:{head[:7]}" in labels
    _act(
        rig=rig,
        facts=_facts(
            head_sha=head, e2e_head_sha=head, review_commit_id=head[:7], labels=frozenset(labels)
        ),
        work_dir=work_dir,
        config=config,
    )
    assert ("close_issue", {"number": 5}) in rig.gh
    assert rig.run_records[5]["status"] == "done"


@pytest.mark.parametrize(
    "flow", [agent_config.FLOW_STANDARD, agent_config.FLOW_MINIMAL, agent_config.FLOW_GENERATE_ONLY]
)
@pytest.mark.parametrize(
    "ignored_artifacts", [False, True], ids=["clean", "ignored-test-artifacts"]
)
def test_delivery_snapshot_normal_review_reaches_merge_without_extra_delivery(
    rig, delivery_snapshot, tmp_path, flow, ignored_artifacts
):
    """Spec-0017: Normal candidate is complete; Git’s neglected cache does not result in additional model calls."""
    if ignored_artifacts:
        # Simulates here Git has applied ignore and returns empty status without using file name as an exemption source.
        cache = _issue_worktree(tmp_path, 5) / ".pytest_cache"
        cache.mkdir()
        (cache / "lastfailed").write_text("{}\n")
    config = _config(flow=flow)
    _act(
        rig=rig,
        facts=_facts(review_state=None, review_commit_id=None, labels=frozenset()),
        work_dir=tmp_path,
        config=config,
    )
    _delivery_snapshot_finish(rig=rig, snapshot=delivery_snapshot, work_dir=tmp_path, config=config)

    expected = {
        agent_config.FLOW_STANDARD: ["reviewer", "merger"],
        agent_config.FLOW_MINIMAL: ["acceptance"],
        agent_config.FLOW_GENERATE_ONLY: [],
    }
    assert rig.agent_names() == expected[flow]
    assert delivery_snapshot["status"] == ""


@pytest.mark.parametrize("flow", [agent_config.FLOW_STANDARD, agent_config.FLOW_MINIMAL])
@pytest.mark.parametrize(
    "change",
    ["dirty-before", "unpushed-before", "dirty-during", "push-during", "remote-rebased-before"],
)
def test_delivery_snapshot_never_approves_a_different_candidate(
    rig, delivery_snapshot, tmp_path, flow, change
):
    """Spec-0017: The same HEAD code, the submission not pushed, and the review of the new editions cannot be used to pass on the PASS."""
    snapshot = delivery_snapshot
    newer = "b" * 40
    if change == "dirty-before":
        snapshot["status"] = " M entry.py\n"
    elif change == "unpushed-before":
        snapshot["head"] = newer
    elif change == "remote-rebased-before":
        snapshot["remote"] = newer

    reviewed = []

    def observe_review():
        reviewed.append((snapshot["head"], snapshot["status"]))
        if change == "dirty-during":
            snapshot["status"] = " M entry.py\n"
        elif change == "push-during":
            snapshot["head"] = snapshot["remote"] = newer

    reviewer = "reviewer" if flow == agent_config.FLOW_STANDARD else "acceptance"
    snapshot["effects"][reviewer] = observe_review
    try:
        _act(
            rig=rig,
            facts=_facts(
                head_sha=snapshot["remote"],
                e2e_head_sha=snapshot["remote"],
                review_state=None,
                review_commit_id=None,
                labels=frozenset(),
            ),
            work_dir=tmp_path,
            config=_config(flow=flow),
        )
    except (WorkspaceError, gates.GateError, gates.MergeNotReady):
        # This example is used only to ensure security: an express refusal is granted.
        pass
    approved = [
        label
        for label in _delivery_snapshot_labels(rig=rig)
        if label.startswith("review-approved:")
    ]
    # Reevaluation of recovery through synchronization/renewal of delivery is permitted, provided that the final clean candidate is truly reviewed.
    if approved:
        assert snapshot["head"] == snapshot["remote"] and not snapshot["status"]
        assert reviewed and reviewed[-1] == (snapshot["remote"], "")
        assert approved == [f"review-approved:{snapshot['remote'][:7]}"]
    assert "close_issue" not in rig.gh_names(), (
        "The evaluation shall not terminate delivery on its own."
    )


@pytest.mark.parametrize("action", ["fix-ci", "review-rework", "draft-ready"])
def test_delivery_snapshot_dirty_work_does_not_block_development_actions(
    rig, delivery_snapshot, tmp_path, action
):
    """Spec-0017 supplements: Failure to deliver is recoverable and cannot be refused at all action entry points."""
    delivery_snapshot["status"] = " M entry.py\n"

    def complete_existing_work():
        delivery_snapshot["status"] = ""

    delivery_snapshot["effects"]["implementer"] = complete_existing_work
    cases = {
        "fix-ci": (_facts(ci="failure"), ["implementer"]),
        "review-rework": (
            _facts(review_state="CHANGES_REQUESTED", review_commit_id=_SHA7),
            ["implementer"],
        ),
        # Gitea draft, even reporting DIRTY, must be able to get it straight first and not back to the old dead lock.
        "draft-ready": (_facts(is_draft=True, mergeable_state="dirty"), []),
    }
    facts, agents = cases[action]
    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == agents
    assert not _delivery_snapshot_labels(rig=rig)
    assert "close_issue" not in rig.gh_names()
    assert delivery_snapshot["status"] == (" M entry.py\n" if action == "draft-ready" else "")
    assert not any(
        command[0] in {"worktree", "reset", "clean"} for command in delivery_snapshot["git"]
    ), "Continued development of areas that cannot be forcibly rebuilt/cleaned"
    if action == "draft-ready":
        assert "mark_ready" in rig.gh_names()


@pytest.mark.parametrize("residue", ["uncommitted", "unpushed", "already-pushed"])
def test_delivery_snapshot_timeout_recovery_must_finish_not_just_block(
    rig, delivery_snapshot, tmp_path, residue
):
    """Spec-0056/0017 Supplement: Reuse the same PR and workspace after time has elapsed, and final approval of the latest delivery and consolidation."""
    snapshot = delivery_snapshot
    newer = "b" * 40

    def timeout_after_writing():
        if residue == "uncommitted":
            snapshot["status"] = " M entry.py\n"
        else:
            snapshot["head"] = newer
            if residue == "already-pushed":
                snapshot["remote"] = newer
        raise _ActTimeout("implementation invocation exceeded 1800s before returning")

    snapshot["effects"]["implementer"] = timeout_after_writing
    with pytest.raises(_ActTimeout):
        _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert rig.run_records[5]["pr_number"] == 12
    snapshot["git"].clear()
    rig.agents.clear()

    def finish_delivery():
        snapshot["head"] = snapshot["remote"] = newer
        snapshot["status"] = ""

    # Modeling of a double will succeed in delivery; only if the framework truly transfers the role already in place will it occur and the situation will not be corrected manually by testing.
    snapshot["effects"].update(implementer=finish_delivery, deliver=finish_delivery)
    facts = _facts(
        head_sha=snapshot["remote"],
        e2e_head_sha=snapshot["remote"],
        review_state=None,
        review_commit_id=None,
        labels=frozenset(),
        is_draft=True,
        mergeable_state="dirty",
    )
    _act(rig=rig, facts=facts, work_dir=tmp_path)
    assert "mark_ready" in rig.gh_names()

    for _ in range(4):
        _act(
            rig=rig,
            facts=_facts(
                head_sha=snapshot["remote"],
                e2e_head_sha=snapshot["remote"],
                review_state=None,
                review_commit_id=None,
                labels=frozenset(_delivery_snapshot_labels(rig=rig)),
            ),
            work_dir=tmp_path,
        )
        if any(
            label.startswith("review-approved:") for label in _delivery_snapshot_labels(rig=rig)
        ):
            break

    assert snapshot["remote"] == newer and snapshot["status"] == "", (
        "Blocked must be renewed instead of permanently suspended or approved Spec-only for submission"
    )
    assert sum(name == "create_pr" for name in rig.gh_names()) == 1
    assert not any(command[0] in {"worktree", "reset", "clean"} for command in snapshot["git"])
    if residue == "already-pushed":
        # A timeout lost the completion result. Verify once through the original developer;
        # the same commit is accepted and no extra delivery/empty commit is requested.
        assert rig.agent_names() == ["implementer", "reviewer"]
    else:
        assert any(name in {"implementer", "deliver"} for name in rig.agent_names())
    _delivery_snapshot_finish(rig=rig, snapshot=snapshot, work_dir=tmp_path, config=_config())


@pytest.mark.parametrize("implementation_result", ["uncommitted", "already-pushed", "commit-only"])
def test_delivery_snapshot_first_implementation_handoff_reaches_merge(
    rig, delivery_snapshot, tmp_path, monkeypatch, implementation_result
):
    """Spec-0056: The normal development of the interface not only captures the non-submission but also the submission but not the delivery."""
    snapshot = delivery_snapshot
    newer = "b" * 40

    def implement():
        if implementation_result == "uncommitted":
            snapshot["status"] = " M entry.py\n"
        else:
            snapshot["head"] = newer
            if implementation_result == "already-pushed":
                snapshot["remote"] = newer

    def deliver():
        snapshot["head"] = snapshot["remote"] = newer
        snapshot["status"] = ""

    snapshot["effects"].update(implementer=implement, deliver=deliver)
    monkeypatch.setitem(_AGENT_OUTPUTS, "deliver", _AGENT_OUTPUTS["deliver"] | {"head_sha": newer})
    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert snapshot["head"] == snapshot["remote"] == newer and not snapshot["status"]
    expected = ["drafter", "implementer"]
    if implementation_result != "already-pushed":
        expected.append("deliver")
    assert rig.agent_names() == expected
    _act(rig=rig, facts=_facts(is_draft=True), work_dir=tmp_path)
    _act(
        rig=rig,
        facts=_facts(
            head_sha=newer,
            e2e_head_sha=newer,
            review_state=None,
            review_commit_id=None,
            labels=frozenset(),
        ),
        work_dir=tmp_path,
    )
    _delivery_snapshot_finish(rig=rig, snapshot=snapshot, work_dir=tmp_path, config=_config())


@pytest.mark.parametrize(
    "change,in_flight,expected",
    [
        ({"ci": "pending"}, False, _ACT_SOLVE),
        ({"ci": "failure"}, False, _ACT_SOLVE),
        ({"mergeable_state": "unknown"}, False, _ACT_SOLVE),
        ({"merged": True}, False, None),
        ({"closed": True}, False, None),
        ({"labels": frozenset({"automation-failed"})}, False, None),
        ({"deps_done": False}, False, None),
        ({}, True, None),
        ({"latest_comment_is_ours": False}, False, _ACT_REPLY),
        ({"is_draft": True}, False, _ACT_READY),
    ],
)
def test_pending_delivery_priority_preserves_existing_stop_conditions(
    rig, change, in_flight, expected
):
    """Spec-0056: unfinished development precedes CI, not stop/reply/dependency rules."""
    rig.run_records[5] = {"status": "iterating", "pr_number": 12}
    facts = _facts(**change)
    verdict = _classify(facts=facts, in_flight=in_flight)
    resumed = vigil_module._resume_verdict(state=rig, facts=facts, verdict=verdict)
    assert resumed.action == expected
    if expected != _ACT_SOLVE:
        assert resumed == verdict


def test_merger_reports_failure_does_not_close_issue_or_mark_done(rig, tmp_path, monkeypatch):
    """Spec-0017: a rejected native merge must remain retryable, not become a false done."""
    monkeypatch.setitem(
        _AGENT_OUTPUTS, "merger", {"merged": False, "summary": "head changed before write"}
    )
    with pytest.raises(gates.MergeNotReady):
        _act(rig=rig, facts=_facts(), work_dir=tmp_path, config=_config())
    assert "close_issue" not in rig.gh_names()
    assert not any(record.get("status") == "done" for record in rig.run_records.values())


def test_producer_enqueues_pending_delivery_even_while_ci_waits(rig, tmp_path, monkeypatch):
    """Spec-0056: recovery must be reachable through the real producer, not just direct _act."""
    rig.run_records[5] = {"status": "iterating", "pr_number": 12}
    observed = _Observed(facts=_facts(ci="pending"), clock=_Clock(last_progress_at=_NOW))
    monkeypatch.setattr(vigil_module, "_sense", lambda **kw: observed)
    # A pre-existing no-progress stamp on this Git head must not suppress local phase recovery.
    monkeypatch.setattr(vigil_module, "_has_attempt_stamp", lambda **kw: True)
    conn = sqlite3.connect(":memory:")
    conn.executescript(vigil_module._SCHEMA)
    try:
        enqueued = vigil_module._consider(
            conn=conn,
            state=rig,
            subject="issue:5",
            config=_config(),
            work_dir=tmp_path,
            in_flight={},
            priority_fn=lambda **kw: 0,
            thresholds={},
            quiet_counts={},
            now=_NOW,
            agent_id="test",
        )
        assert enqueued == 1
        assert conn.execute("SELECT subject, status FROM work_queue").fetchall() == [
            ("issue:5", "queued")
        ]
    finally:
        conn.close()


@pytest.mark.parametrize("stage", ["review", "e2e", "merge"])
def test_skipped_reader_does_not_trigger_delivery_recovery(rig, tmp_path, stage):
    """Spec-0056: checking a candidate must not bypass an explicit skipped stage."""
    rig.delivered = False
    changes = {}
    if stage == "review":
        changes = {"review_state": None, "review_commit_id": None}
    elif stage == "e2e":
        changes = {"e2e_head_sha": None}
    _act(
        rig=rig,
        facts=_facts(**changes),
        work_dir=tmp_path,
        config=_config(stages=_stages_policy(**{stage: "skip"})),
    )
    assert not rig.agents
    assert not rig.worktrees


# --------------------------------------------------------------------------------------------------
# Route: verdict.action  →  the only stage/agent (one test per unit).
# --------------------------------------------------------------------------------------------------


def test_act_reply_dispatches_replier_and_posts_signed_comment(rig, tmp_path):
    """Branch 2: The latest comment is sent by a person who sent a copy of the replier + returned to a signed comment + advanced the cursor (** without any writing number agent**)."""
    facts = _facts(latest_comment_is_ours=False)
    assert _classify(facts=facts, in_flight=False).action == _ACT_REPLY

    summary = _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["replier"]
    placeholders = rig.agents[0][1]
    assert placeholders["pr_number"] == 12
    assert "comment_body" not in placeholders
    assert placeholders["context"].count("Why do you write that here?") == 1
    assert rig.comments == [(12, "I’ve answered your question.", "bot")]
    assert rig.cursors == [(12, "2026-07-14T11:00:00Z")]
    assert summary == "I’ve answered your question."


def test_act_solve_cuts_a_vertical_slice_and_never_blocks_on_ci(rig, tmp_path):
    """Branch 4: No PR  →  worktree  →  refc(drafter)  →  draft PR  →  effect – deliver.

    ** Not here to block CI/review**: Those are 710 of `_classify`, and the return to `_reconcile` cycle will naturally come -- so here.
    Never should reviewer/tester.

    Spec-0017/T2: `_do_solve`** no more certainty accurate `github.mark_ready`** -  ** - Revert to deliver agent (its completion of sentence)
    ”PR non-draft” ; draft from `_classify` 11 rounded straight. gh no longer calls `mark_ready` in current water.
    """
    rig.delivered = False  # Developer leaves changes for the existing delivery role.
    facts = _facts(pr_number=None)
    assert _classify(facts=facts, in_flight=False).action == _ACT_SOLVE

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["drafter", "implementer", "deliver"]
    assert [call for call in rig.worktrees if call[0] == "prepare"] == [
        ("prepare", 5, "openagents/issue-5", "main")
    ]
    worktree = _issue_worktree(tmp_path, 5)
    assert rig.agents[1][1]["work_dir"] == worktree  # Implementer in quarantine, worktree.
    assert rig.agents[1][1]["issue_number"] == 5
    assert rig.gh_names() == ["get_issue", "create_pr"]  # Spec-0017/T2: No more straight mark_ready
    assert "mark_ready" not in rig.gh_names()
    assert rig.runs[-1] == (5, "pr-open", "openagents/issue-5", 12)
    assert all(call[1] == "iterating" for call in rig.runs[:-1])


def test_soft_advice_reaches_developer_alongside_unchanged_original_issue(rig, tmp_path):
    from openagents.runtime import preflight

    issue = github.Issue(5, "Title", "- Yes, sir.", [])
    preflight.write(
        work_dir=tmp_path,
        data={
            "version": 1,
            "fingerprints": {"5": preflight.fingerprint(issue=issue)},
            "plan": {"notes": [{"issues": [5], "advice": "inspect shared loop before reuse"}]},
        },
    )
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(coordination="soft"),
    )
    draft = rig.context_of(agent="drafter")
    implementation = rig.context_of(agent="implementer")
    assert "- Yes, sir." in draft
    assert "inspect shared loop before reuse" in draft
    assert "inspect shared loop before reuse" in implementation
    assert implementation.count("- Yes, sir.") == 1
    assert "NOT requirements or blockers" in implementation


@pytest.mark.parametrize("body_repeats_title", [False, True])
def test_solve_keeps_long_issue_title_out_of_task(rig, tmp_path, monkeypatch, body_repeats_title):
    """Keep long issue text in context, including when the body repeats its title."""
    title = "diagnose workspace topology and recover historical evidence " * 2
    body = (
        f"Question:\n\n{title}\n\nEvidence required."
        if body_repeats_title
        else "Evidence required."
    )
    issue = github.Issue(5, title, body, [])
    monkeypatch.setattr(vigil_module.github, "get_issue", lambda *, number: issue)
    recording_run = engine.run_agent

    def validate_and_record(agent_module, *, backend, **placeholders):
        if agent_module.__name__.rsplit(".", 1)[-1] == "drafter":
            task = agent_module.PROMPT.substitute(**placeholders)
            assert placeholders["target"] == "issue #5"
            assert title not in task
            assert title in placeholders["context"]
            assert body in placeholders["context"]
            engine._assert_single_copy(
                task=task, context=placeholders["context"], values=placeholders, role="drafter"
            )
        return recording_run(agent_module, backend=backend, **placeholders)

    monkeypatch.setattr(engine, "run_agent", validate_and_record)
    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert "drafter" in rig.agent_names()


def test_act_solve_skips_delivery_agent_when_implementer_already_pushed(rig, tmp_path, monkeypatch):
    heads = iter(["draft-before", "draft-after", "impl-before", "impl-after"])
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: next(heads))

    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)

    assert rig.agent_names() == ["drafter", "implementer"]
    assert (
        "assert-delivered",
        _issue_worktree(tmp_path, 5),
        "openagents/issue-5",
    ) in rig.worktrees


def test_minimal_flow_role_sequence_is_exactly_three_subjective_calls(rig, tmp_path, monkeypatch):
    heads = iter(["spec-before", _HEAD, "impl-before", _HEAD])
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: next(heads))
    config = _config(flow=agent_config.FLOW_MINIMAL)

    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path, config=config)
    assert rig.agent_names() == ["spec_writer", "implementer"]
    assert "- Yes, sir." in rig.context_of(agent="implementer")
    assert "objective contract" in rig.context_of(agent="implementer")
    assert "Do not switch to /work/harness" in rig.context_of(agent="implementer")

    _act(
        rig=rig,
        facts=_facts(review_state=None, review_commit_id=None, labels=frozenset()),
        work_dir=tmp_path,
        config=config,
    )
    assert rig.agent_names() == ["spec_writer", "implementer", "acceptance"]

    _act(rig=rig, facts=_facts(), work_dir=tmp_path, config=config)
    assert rig.agent_names() == ["spec_writer", "implementer", "acceptance"]
    assert "merger" not in rig.agent_names()
    assert ("merge_pr", {"pr_number": 12, "head_sha": _HEAD}) in rig.gh


def test_generate_only_flow_specs_executes_and_merges_without_validation(
    rig, tmp_path, monkeypatch
):
    heads = iter(["spec-before", _HEAD, "exec-before", _HEAD])
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: next(heads))
    monkeypatch.setattr(
        gates,
        "assert_repository_integrity",
        lambda *, workspace: (_ for _ in ()).throw(
            AssertionError("generate-only must not run the repository-wide Spec gate")
        ),
    )
    config = _config(flow=agent_config.FLOW_GENERATE_ONLY)

    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path, config=config)
    assert rig.agent_names() == ["spec_writer", "executor"]
    assert "compact objective spec" in rig.context_of(agent="executor")
    assert "original issue" in rig.context_of(agent="executor")

    _act(
        rig=rig,
        facts=_facts(review_state=None, review_commit_id=None, labels=frozenset()),
        work_dir=tmp_path,
        config=config,
    )
    assert rig.agent_names() == ["spec_writer", "executor"]

    _act(rig=rig, facts=_facts(), work_dir=tmp_path, config=config)
    assert rig.agent_names() == ["spec_writer", "executor"]
    assert ("merge_pr", {"pr_number": 12, "head_sha": _HEAD}) in rig.gh


def test_minimal_spec_blocked_stops_before_pr_and_implementation(rig, tmp_path, monkeypatch):
    monkeypatch.setitem(
        _AGENT_OUTPUTS,
        "spec_writer",
        {
            "status": "BLOCKED",
            "head_sha": "",
            "summary": "cannot preserve objective",
            "blocker": "read-only boundary",
            "objective_coverage": [],
            "candidate_assessments": [],
            "selected_intervention": {},
            "evidence_pack": [],
            "falsifiers": [],
        },
    )
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(flow=agent_config.FLOW_MINIMAL),
    )
    assert rig.agent_names() == ["spec_writer"]
    assert "create_pr" not in rig.gh_names()
    assert ("issue_add_label", {"number": 5, "name": github.AUTOMATION_FAILED_LABEL}) in rig.gh


def test_minimal_spec_partial_stops_before_pr_and_implementation(rig, tmp_path, monkeypatch):
    monkeypatch.setitem(
        _AGENT_OUTPUTS,
        "spec_writer",
        {
            "status": "PARTIAL",
            "head_sha": _HEAD,
            "summary": "useful but incomplete",
            "blocker": "one objective is unclosed",
            "objective_coverage": [{"scope_coverage": "PARTIAL", "evidence_level": "HYPOTHESIS"}],
            "candidate_assessments": [
                {
                    "candidate": "one",
                    "ownership": "model",
                    "delivery": "unknown",
                    "control_effect": "unknown",
                    "evidence": "none",
                    "assumptions": "compliance",
                    "failure_modes": "ignored",
                    "verdict": "selected",
                }
            ],
            "selected_intervention": {},
            "evidence_pack": [],
            "falsifiers": [],
        },
    )
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(flow=agent_config.FLOW_MINIMAL),
    )
    assert rig.agent_names() == ["spec_writer"]
    assert "create_pr" not in rig.gh_names()
    assert ("issue_add_label", {"number": 5, "name": github.AUTOMATION_FAILED_LABEL}) in rig.gh


def test_minimal_partial_acceptance_never_reworks_or_merges(rig, tmp_path, monkeypatch):
    monkeypatch.setitem(
        _AGENT_OUTPUTS,
        "acceptance",
        {"verdict": "PARTIAL", "reason": "hard half missing", "evidence": ["replay"]},
    )
    _act(
        rig=rig,
        facts=_facts(review_state=None, review_commit_id=None, labels=frozenset()),
        work_dir=tmp_path,
        config=_config(flow=agent_config.FLOW_MINIMAL),
    )
    assert rig.agent_names() == ["acceptance"]
    assert "implementer" not in rig.agent_names()
    assert "merge_pr" not in rig.gh_names()
    assert ("issue_add_label", {"number": 5, "name": github.AUTOMATION_FAILED_LABEL}) in rig.gh


def test_minimal_ci_failure_stops_without_second_implementation(rig, tmp_path):
    _act(
        rig=rig,
        facts=_facts(ci="failure"),
        work_dir=tmp_path,
        config=_config(flow=agent_config.FLOW_MINIMAL),
    )
    assert rig.agent_names() == []
    assert ("issue_add_label", {"number": 5, "name": github.AUTOMATION_FAILED_LABEL}) in rig.gh


def test_act_solve_skips_rfc_when_that_stage_is_skipped(rig, tmp_path):
    """`rfc: skip` = No gate set  →  no daffer, but PR/implement/deliver as usual (`skip` is closed, not alive).

    Spec-0074 empirical fixation: no dragt ”first line + push” without draffer, no head branch create_pr
    404. The void branch (git.seed_branch empty line + push) must be filled before create_pr.
    """
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(stages=_stages_policy(rfc="skip")),
    )
    assert rig.agent_names() == ["implementer"]  # Fixture already pushed; no redundant deliver.
    assert ("seed", "openagents/issue-5") in rig.worktrees  # create_pr 404


def test_act_solve_agent_rfc_does_not_seed_branch(rig, tmp_path):
    """rifc=the first part of the state is the drafter delivery agreement - the feed branch should not be so much."""
    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert all(record[0] != "seed" for record in rig.worktrees)


def test_retired_architecture_owner_is_rejected_before_implementer(rig, tmp_path) -> None:
    with pytest.raises(ValueError, match="Unknown"):
        _act(
            rig=rig,
            facts=_facts(pr_number=None),
            work_dir=tmp_path,
            config=_config(stages=_stages_policy(architecture="human")),
        )
    assert rig.agent_names() == ["drafter"]


def test_architecture_rework_refines_before_implementer(rig, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        vigil_module.stages,
        "architecture",
        lambda **kwargs: {
            "verdict": "REWORK",
            "reason": "wrong layer",
            "design_digest": "a",
            "spec_path": "docs/specs/0001-x.md",
        },
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "design_snapshot",
        lambda **kwargs: {
            "design_digest": "b",
            "design_raw_digest": "raw-b",
            "spec_path": "docs/specs/0001-x.md",
        },
    )
    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert rig.agent_names()[:3] == ["drafter", "drafter", "implementer"]
    assert rig.run_records[5]["design_raw_digest"] == "raw-b"


def test_solve_reuses_drafter_evidence_for_architect_and_implementer(
    rig, tmp_path, monkeypatch
) -> None:
    evidence_pack = [
        {
            "fact": "timeout is polled",
            "path": "entry.py",
            "symbol": "_run_supervised",
            "verification": "read body",
        }
    ]
    monkeypatch.setitem(_AGENT_OUTPUTS["drafter"], "evidence_pack", evidence_pack)
    captured = {}

    def _architecture(**kwargs):
        captured.update(kwargs)
        return {
            "verdict": "PASS",
            "reason": "ok",
            "design_digest": "approved",
            "design_raw_digest": "raw-approved",
            "spec_path": "docs/specs/0001-x.md",
        }

    monkeypatch.setattr(vigil_module.stages, "architecture", _architecture)
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(stages=_stages_policy(architecture="agent")),
    )

    assert captured["evidence_pack"] == evidence_pack
    implement_call = next(payload for name, payload in rig.agents if name == "implementer")
    assert "timeout is polled" in implement_call["context"]
    assert rig.run_records[5]["evidence_pack"] == evidence_pack
    assert rig.run_records[5]["design_raw_digest"] == "raw-approved"


def test_act_rebase_tries_mechanical_update_branch_before_any_agent(rig, tmp_path, monkeypatch):
    """Branch 6: Only the case forward (no real conflict) mechanical `update_branch` is enough to call ** zero LLM**."""
    monkeypatch.setattr(github, "update_branch", lambda *, pr_number, rebase: True)
    facts = _facts(mergeable_state="dirty")
    assert _classify(facts=facts, in_flight=False).action == _ACT_REBASE

    summary = _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agents == [], "Mechanical update-branch."
    assert "update-branch" in summary


def test_act_rebase_falls_back_to_deliver_agent_when_update_branch_fails(rig, tmp_path):
    """Mechanical `update_branch` No (real conflict) Decentralisation deliver agent (`stages.conflict`)."""
    _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)

    assert rig.agent_names() == ["deliver"]
    placeholders = rig.agents[0][1]
    assert placeholders["pr_number"] == 12
    assert placeholders["branch"] == "branch-of-pr-12"
    assert placeholders["rebase_onto"] == "main"
    assert placeholders["work_dir"] == _issue_worktree(tmp_path, 5)
    assert [call for call in rig.worktrees if call[0] == "prepare"] == [
        ("prepare", 5, "branch-of-pr-12", "main")
    ]


def test_act_rebase_preserves_unpublished_worktree(rig, tmp_path):
    """Dirty/diverged local work is never destroyed by conflict preparation."""
    rig.delivered = False
    _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)

    assert [call for call in rig.worktrees if call[0] == "prepare"] == []
    assert [call for call in rig.worktrees if call[0] == "sync-delivered"]


def test_act_rebase_turns_unresolved_delivery_into_bounded_failure(rig, tmp_path, monkeypatch):
    """A resolver that did not publish must requeue/park; it cannot look like success."""
    monkeypatch.setattr(
        vigil_module.stages,
        "conflict",
        lambda **kwargs: {
            "delivered": False,
            "reason": "There are still semantic resources conflicts.",
        },
    )
    with pytest.raises(WorkspaceError, match="conflict_fp="):
        _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)


def test_conflict_context_contains_snapshot_and_deterministic_protocol(rig, tmp_path):
    """The resolver receives enough bounded evidence to inspect only this conflict."""
    _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)
    prompt = rig.context_of(agent="deliver")
    assert "conflict snapshot" in prompt
    assert "conflict_fingerprint" in prompt
    assert "If a Spec number collides" in prompt
    assert (
        _conflict_fingerprint(
            # Resolver attempts refresh the forge snapshot first, so this fixture's
            # dirty input is replaced by the mocked clean remote state.
            facts=_facts(mergeable_state="clean"),
            base="main",
            branch="branch-of-pr-12",
        )
        in prompt
    )


def test_act_fix_ci_feeds_failing_check_logs_to_implementer(rig, tmp_path):
    """Branch 8: Current Head CI Red Zoom Feed failed check logs to implementer to fix (in the PR worktree)."""
    facts = _facts(ci="failure")
    assert _classify(facts=facts, in_flight=False).action == _ACT_FIX_CI

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["implementer"]
    placeholders = rig.agents[0][1]
    assert "feedback" not in placeholders
    assert placeholders["context"].count("FAILED tests/test_x.py::test_y") == 1
    assert placeholders["pr_number"] == 12
    assert placeholders["work_dir"] == _issue_worktree(tmp_path, 5)
    assert [call for call in rig.worktrees if call[0] == "ensure"] == [
        ("ensure", 5, "openagents/issue-5")
    ]
    assert rig.run_records[5]["status"] == "pr-open"


def test_act_e2e_stamps_evidence_with_the_head_it_was_run_against(rig, tmp_path):
    """Branch 9: Pie tester; PASS  →  a review of evidence ** with head trace** (the head in this version of code)."""
    facts = _facts(e2e_head_sha=None)
    rig.run_records[5] = {"evidence_pack": [{"fact": "timeout is polled", "path": "entry.py"}]}
    assert _classify(facts=facts, in_flight=False).action == _ACT_E2E

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["tester"]
    assert rig.agents[0][1]["work_dir"] == _issue_worktree(tmp_path, 5)
    assert "timeout is polled" in rig.agents[0][1]["context"]
    assert len(rig.comments) == 1
    pr_number, body, agent_id = rig.comments[0]
    assert (pr_number, agent_id) == (12, "bot")
    assert body.startswith(f"{vigil_module._E2E_MARKER}{_HEAD} -->")


def test_act_e2e_never_stamps_evidence_when_the_run_failed(rig, tmp_path, monkeypatch):
    """tester sentenced ReWORK  →  ** without a stamp** (which is equivalent to a failed evidence - the other side of the crown Li)."""
    monkeypatch.setitem(
        _AGENT_OUTPUTS, "tester", {"verdict": "REWORK", "reason": "E2e, hang up.", "evidence": []}
    )
    _act(rig=rig, facts=_facts(e2e_head_sha=None), work_dir=tmp_path)
    assert rig.agent_names() == ["tester"]
    assert rig.comments == [], "A failed e2e run must not post an evidence stamp."


def test_act_review_dispatches_reviewer_and_binds_the_verdict_to_the_head_sha(rig, tmp_path):
    """Branch 10: No decision  →  reviewer; ** embedding the current head ssha7 into the name of the label** (decision bound to committee) when the award falls."""
    facts = _facts(review_state=None, review_commit_id=None, labels=frozenset())
    rig.run_records[5] = {"evidence_pack": [{"fact": "timeout is polled", "path": "entry.py"}]}
    assert _classify(facts=facts, in_flight=False).action == _ACT_REVIEW_OR_FIX

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["reviewer"]
    assert rig.agents[0][1]["work_dir"] == _issue_worktree(tmp_path, 5)
    assert "timeout is polled" in rig.agents[0][1]["context"]
    added = [call for call in rig.gh if call[0] == "add_label"]
    assert added == [("add_label", {"pr_number": 12, "name": f"review-approved:{_SHA7}"})]


def test_act_review_clears_stale_verdict_labels_before_landing_the_new_one(
    rig, tmp_path, monkeypatch
):
    """Take all old ones off before the new decision falls. `review-*:<sha7>`——Keep it unharmed.sha The decision is not recognized if it is not accepted) but it will be seen in a row of contradictory decisions."""
    monkeypatch.setitem(
        _AGENT_OUTPUTS, "reviewer", {"verdict": "REWORK", "reason": "I’m gonna change it."}
    )
    facts = _facts(
        review_state=None,
        review_commit_id=None,
        labels=frozenset({"review-approved:0000000", "openagents"}),
    )
    _act(rig=rig, facts=facts, work_dir=tmp_path)

    removed = [call[1]["name"] for call in rig.gh if call[0] == "remove_label"]
    assert removed == ["review-approved:0000000"], "Only extract-* award label, one more untouched"
    added = [call[1]["name"] for call in rig.gh if call[0] == "add_label"]
    assert added == [
        f"review-changes-requested:{_SHA7}"
    ]  # REWORK's ruling is also tied to the current head
    assert rig.review_feedback[5] == {"head_sha": _HEAD, "reason": "I’m gonna change it."}


def test_act_review_or_fix_sends_changes_requested_back_to_implementer(rig, tmp_path):
    """branch ⑩ The other half: yes ’CHANGES_REQUESTED@Current head’ → Pie. implementer Change Code**No more re-examination.**）。"""
    facts = _facts(
        review_state="CHANGES_REQUESTED",
        review_commit_id=_SHA7,
        labels=frozenset({f"review-changes-requested:{_SHA7}"}),
    )
    rig.run_records[5] = {"evidence_pack": [{"fact": "timeout is polled", "path": "entry.py"}]}
    rig.review_feedback[5] = {
        "head_sha": _HEAD,
        "reason": "Live GM must run BC1-BC3 authentication",
    }
    assert _classify(facts=facts, in_flight=False).action == _ACT_REVIEW_OR_FIX

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["implementer"]
    assert "feedback" not in rig.agents[0][1]
    assert "[review]" in rig.agents[0][1]["context"]
    assert "Live GM must run BC1-BC3" in rig.agents[0][1]["context"]
    assert "timeout is polled" in rig.agents[0][1]["context"]


def test_act_ready_promotes_residual_draft_via_mark_ready(rig, tmp_path):
    """Branch 11 (Spec-0017/T2): All green + applied@head but still draft  →  certainty `github.mark_ready` is back in order (level-triggered safety net).

    No mechanical action for zero judgement,** no anggen** (why not send a new promoter agent to Spec-0017 Rationale);
    Turn back to deliver agent, the head of the gun.
    """
    facts = _facts(is_draft=True)  # The rest are green, but they're not right.
    assert _classify(facts=facts, in_flight=False).action == _ACT_READY

    summary = _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agents == [], "It’s a certain mechanical move. It’s not supposed to be any of them."
    assert ("mark_ready", {"pr_number": 12}) in rig.gh
    assert "merge_pr" not in rig.gh_names()  # Line before merge: draft state never merge
    assert "Marked ready for review" in summary


def test_act_merge_dispatches_merger_agent_behind_the_gate(rig, tmp_path):
    """Branch 12 (Spec-0017/T2/T3): All Green + applied@head + non-draft **merger union** + issue + doe.

    Merger irreversible: First `gates.assert_merge_allowed` (display this document) secures the red line, then then pass `stages.merge` to meger
    Agent `gh pr merge` - ** no longer definitive `github.merge_pr` Tweet**.
    """
    facts = _facts()  # Default is_draft for False
    assert _classify(facts=facts, in_flight=False).action == _ACT_MERGE

    summary = _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["merger"], (
        "Merger action delegatedr agent (after the gate is released)"
    )
    assert rig.agents[0][1]["pr_number"] == 12
    assert isinstance(rig.backends[0], _TimedBackend)  # Timeout by _TimedBackend
    assert ("close_issue", {"number": 5}) in rig.gh
    assert rig.runs == [(5, "done", "openagents/issue-5", 12)]
    assert summary == "merged"


def test_act_rejects_an_unknown_action(rig, tmp_path):
    """The route is numerous: unknown action must be blown up on the spot** and never silent no-op (quiet = a subject never moves and nobody knows)."""
    with pytest.raises(ValueError, match="Unknown action"):
        vigil_module._act(
            backend=_Backend(),
            state=rig,
            work_dir=tmp_path,
            config=_config(),
            observed=_Observed(facts=_facts(), clock=_Clock(last_progress_at=_NOW)),
            verdict=vigil_module._Verdict(kind=vigil_module._ACTIONABLE, action="teleport"),
            agent_id="bot",
            now=_NOW,
            lock_fd=None,
        )


@pytest.mark.parametrize("budget", ["5400.5", "0"])
def test_act_wraps_the_backend_in_a_timed_backend_on_every_agent_branch(
    rig, tmp_path, monkeypatch, budget
):
    """Every branch of the faction of agent must have been `_TimedBackend` - naked backend hung by no one (flock can’t rule out this way)."""
    monkeypatch.setenv("OPENAGENTS_CLAUDE_MAX_WALL", budget)
    _act(rig=rig, facts=_facts(ci="failure"), work_dir=tmp_path)
    assert rig.backends and all(isinstance(backend, _TimedBackend) for backend in rig.backends)
    assert all(backend._timeout_seconds == float(budget) for backend in rig.backends)


# --------------------------------------------------------------------------------------------------
# 3-state: owner = human `_park_gate` hit needs-human stop-and-go (** zero agent call**).
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage,overrides",
    [
        (agent_config.STAGE_CONFLICT, {"mergeable_state": "dirty"}),
        (agent_config.STAGE_CI, {"ci": "failure"}),
        (agent_config.STAGE_E2E, {"e2e_head_sha": None}),
        (
            agent_config.STAGE_REVIEW,
            {"review_state": None, "review_commit_id": None, "labels": frozenset()},
        ),
        (agent_config.STAGE_MERGE, {}),
    ],
)
def test_act_rejects_retired_stage_owner(rig, tmp_path, stage, overrides):
    with pytest.raises(ValueError, match="Unknown"):
        _act(
            rig=rig,
            facts=_facts(**overrides),
            work_dir=tmp_path,
            config=_config(stages=_stages_policy(**{stage: "hu" + "man"})),
        )
    assert rig.agents == []


# --------------------------------------------------------------------------------------------------
# First-class export contract: `_NEEDS_HUMAN_CONTRACT` must enter the context of ** branch of each **-party agent to agent.
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,agent",
    [
        (
            {"latest_comment_is_ours": False},
            "replier",
        ),  # Branch 2: He may not be able to answer the questions asked.
        ({"pr_number": None}, "drafter"),  # Branch 4: Drafting
        ({"pr_number": None}, "implementer"),  # Branch 4: Achieved
        (
            {"mergeable_state": "dirty"},
            "deliver",
        ),  # Branch 6: The scene of the conflict is the one that should be used to solve the conflict.
        (
            {"ci": "failure"},
            "implementer",
        ),  # Branch 8:CI is the one who should be delivered at the time of the flashy upstream.
        ({"e2e_head_sha": None}, "tester"),  # Branch 9
        (
            {"review_state": None, "review_commit_id": None, "labels": frozenset()},
            "reviewer",
        ),  # Branch 10
        (
            {
                "review_state": "CHANGES_REQUESTED",
                "review_commit_id": _SHA7,
                "labels": frozenset({f"review-changes-requested:{_SHA7}"}),
            },
            "implementer",
        ),  # Branch 10 is back on the job.
    ],
)
def test_autonomous_contract_reaches_every_agent_invoking_branch(rig, tmp_path, overrides, agent):
    """** Precondition for main path closing**: agent does not see the contract and will not return to structured contact request - the bottom of the field becomes the main path.

    The word is ”yes.” `engine.run_agent` This is the only pie. agent Export Up (stage How can you not escape from the inner set of placeholders?`_do_reply`
    `_do_rebase` has missed it — they are the ”failure to answer questions” and ”undefended conflict” — the two most deserving of active communication.
    """
    _act(rig=rig, facts=_facts(**overrides), work_dir=tmp_path)
    assert agent in rig.agent_names()
    assert _AUTONOMOUS_CONTRACT in rig.context_of(agent=agent)


def test_autonomous_contract_reaches_the_replier(rig, tmp_path):
    """Return: `_do_reply` contract is spelled after the **-person’s review body** (for both the respondent and the first-class export)."""
    _act(rig=rig, facts=_facts(latest_comment_is_ours=False), work_dir=tmp_path)
    context = rig.context_of(agent="replier")
    assert context == f"--- human comment ---\nWhy do you write that here?{_AUTONOMOUS_CONTRACT}"


def test_autonomous_contract_reaches_the_conflict_resolver(rig, tmp_path):
    """Returns: `_do_rebase` passed the contract through `stages.conflict(context_text=…)` into the context of the deliver agent."""
    _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)
    assert _AUTONOMOUS_CONTRACT in rig.context_of(agent="deliver")


def test_autonomous_contract_forbids_forge_writes_and_keeps_role_schema():
    assert "JSON schema" in _AUTONOMOUS_CONTRACT
    assert "do not keep retrying" in _AUTONOMOUS_CONTRACT
    assert "change forge labels" in _AUTONOMOUS_CONTRACT
    assert vigil_module._LABEL_AUTOMATION_FAILED == github.AUTOMATION_FAILED_LABEL


# --------------------------------------------------------------------------------------------------
# Worktree belongs: two different standalone PR** must** get two different directories (both degraded to issue-0 = push code on the PR of others).
# --------------------------------------------------------------------------------------------------


def test_bare_prs_get_distinct_worktrees(tmp_path, monkeypatch):
    """standalone PR (no issue) press **PR** instead of ”no issue  → 0”

    `Workspace.ensure` only eats `issue_number` and ** returns directly when the directory exists, without checking which branch is currently in** —
    `pr:12` and `pr:13` will get **** `.worktrees/issue-0`: two agents of worker
    Change the code in the same directory, and later the person who is in the former branch will push the change onto the other person ’s PR**. subsubject level block
    Not here -- they were two sub-projects, shared ** resources**.

    Here is ** True** `git.Workspace`: The three candidate directories are pre-established (including issue-0), so all `ensure` moves ”Existing direct”
    ”Return” short-term, one-time guit; the degradation of the ”issue-0” will be here** and the same path** will be caught.
    """
    monkeypatch.setattr(github, "pr_head_branch", lambda *, pr_number: f"feature/pr-{pr_number}")
    for number in (0, 12, 13):
        (tmp_path / ".openagents" / "worktrees" / f"issue-{number}").mkdir(parents=True)

    first = _pr_worktree(work_dir=tmp_path, facts=_facts(subject="pr:12", pr_number=12))
    second = _pr_worktree(work_dir=tmp_path, facts=_facts(subject="pr:13", pr_number=13))

    assert first != second, "Two naked PRs, one worktree = push the change on someone else’s PR"
    assert first.name == "issue-12"
    assert second.name == "issue-13"


def test_issue_subject_worktree_is_keyed_by_the_issue_number(tmp_path, monkeypatch):
    """The subject of issue still uses the issue + go to `openagents/issue-<n>` branch (old string vigil)."""
    monkeypatch.setattr(git, "Workspace", _FakeWorkspace)
    global _RIG
    _RIG = _Rig()
    path = _pr_worktree(work_dir=tmp_path, facts=_facts(subject="issue:5"))
    assert _RIG.worktrees == [("ensure", 5, "openagents/issue-5")]
    assert path == _issue_worktree(tmp_path, 5)


# --------------------------------------------------------------------------------------------------
# Hard timeout: flock only answers "Is the process in place"; `_TimedBackend` adds "The process is alive but hung on a call that does not return".
# --------------------------------------------------------------------------------------------------


class _HangingBackend:
    """Backend; `Popen` ** Self-reported PID** (under oath, not guess - diff would recognize someone else’s gh/git)."""

    name = "hanging"

    def __init__(self, *, pid: int) -> None:
        self._pid = pid
        self.thread_id = 0

    def run(self, *, work_dir, task, context):
        self.thread_id = threading.get_ident()
        proc.publish(pid=self._pid)
        time.sleep(300)


@pytest.fixture
def killed(monkeypatch) -> list[tuple[int, object]]:
    """Pile `proc.kill_tree`, only `(pid, handle)` - This test file does not really kill any process.

    Even `handle`: The timeout must hand over the `Popen` self-reported by the backend to `kill_tree`.
    ”Not the only basis for the process of the year”; the missing one is only a naked PID that can kill, and the PID will kill another agent when it turns around.
    """
    record: list[tuple[int, object]] = []
    monkeypatch.setattr(proc, "kill_tree", lambda *, pid, handle: record.append((pid, handle)))
    return record


def test_timed_backend_kills_exactly_the_pids_this_call_published(killed):
    """Timeout killing** this call for self-reported** PID,** only killing it**: the dead agent who died while he was killing the wrong process is still alive and push (driving)."""
    proc.track()  # One barrel is also opened (simulate another gh, git subprocess of the worker/ producer)
    proc.publish(pid=999_001)  # It's self-reported PID.
    backend = _HangingBackend(pid=424_242)
    try:
        with pytest.raises(_ActTimeout, match="424242") as exc:
            _TimedBackend(inner=backend, timeout_seconds=1, lock_fd=None).run(
                work_dir=Path("."), task="t", context="c"
            )
        assert killed == [(424_242, None)], "Only this agent calling the self-reported process tree"
        assert "wall-clock limit" in str(exc.value)
        assert "Hang on." not in str(exc.value)
        # Someone else's bucket is in place. {PID: Snack}——Here. gh/git No one's got a handle on it. Remember that. None）。
        assert proc.untrack(thread_id=threading.get_ident()) == {999_001: None}
    finally:
        proc.untrack(thread_id=threading.get_ident())


def test_timed_backend_passes_the_published_handle_to_kill_tree(killed):
    """The timeout to `kill_tree` must be the entry ** of the report ** - it is the only basis for PID to identify the body.

    No handle.`kill_tree` I’m gonna press naked. PID Kill: That. PID If it’s been reap And back and forth. tick Start a few gh/git），
    The victim is another agent of the process that was recycled and re-runed.
    """
    handle = object()  # For Popen; `kill_tree` has been put on a stake, not really go to the Poll

    class _HangingWithHandle:
        name = "hanging"

        def run(self, *, work_dir, task, context):
            proc.publish(pid=424_245, handle=handle)
            time.sleep(300)

    with pytest.raises(_ActTimeout):
        _TimedBackend(inner=_HangingWithHandle(), timeout_seconds=1, lock_fd=None).run(
            work_dir=Path("."), task="t", context="c"
        )
    assert killed == [(424_245, handle)]
    assert killed[0][1] is handle  # It's that one. It's nothing else.


def test_timed_backend_untracks_the_bucket_after_a_timeout(killed):
    """The time-out thread is discarded and its recognized collar cans must be removed (otherwise, `_TRACKED` is available for an unlimited period of time each time)."""
    backend = _HangingBackend(pid=424_243)
    with pytest.raises(_ActTimeout):
        _TimedBackend(inner=backend, timeout_seconds=1, lock_fd=None).run(
            work_dir=Path("."), task="t", context="c"
        )
    assert backend.thread_id not in proc._TRACKED


def test_timed_backend_kills_nothing_on_a_fast_call_and_untracks_cleanly(killed):
    """The result is not killed, the result is passed, the barrel is clean (no tax on normal routes is allowed for the time-out)."""

    class _Fast:
        name = "fast"

        def __init__(self) -> None:
            self.thread_id = 0

        def run(self, *, work_dir, task, context):
            self.thread_id = threading.get_ident()
            proc.publish(pid=424_244)  # Starts the sub-process, but closes on time
            return "ok"

    backend = _Fast()
    result = _TimedBackend(inner=backend, timeout_seconds=30, lock_fd=None).run(
        work_dir=Path("."), task="t", context="c"
    )
    assert result == "ok"
    assert killed == [], "No one can kill a process that returns on time."
    assert backend.thread_id not in proc._TRACKED


@pytest.mark.parametrize("budget", ["0", "-1"])
def test_disabled_budget_waits_for_completion_and_keeps_tracking(monkeypatch, killed, budget):
    """Spec-0046: disabling the shared budget must not become join(timeout=0)."""
    monkeypatch.setenv("OPENAGENTS_CLAUDE_MAX_WALL", budget)
    release = threading.Event()
    timer = threading.Timer(0.05, release.set)

    class Waiting:
        def run(self, *, work_dir, task, context):
            self.thread_id = threading.get_ident()
            proc.publish(pid=424_246)
            assert release.wait(timeout=2)
            return "finished"

    backend = Waiting()
    timer.start()
    try:
        result = _TimedBackend(
            inner=backend, timeout_seconds=vigil_module.effective_max_wall(), lock_fd=None
        ).run(work_dir=Path("."), task="t", context="c")
        assert result == "finished"
        assert not killed
        assert backend.thread_id not in proc._TRACKED
    finally:
        release.set()
        timer.join(timeout=2)


def test_timed_backend_reraises_the_inner_error_without_killing(killed):
    """Back on its own, throw it back, ** no-killing process** (it’s closed) and go back to the top and try again instead of Park."""

    class _Boom:
        name = "boom"

        def run(self, *, work_dir, task, context):
            raise RuntimeError("Back-end wind.")

    with pytest.raises(RuntimeError, match="Back-end wind."):
        _TimedBackend(inner=_Boom(), timeout_seconds=30, lock_fd=None).run(
            work_dir=Path("."), task="t", context="c"
        )
    assert killed == []


# --------------------------------------------------------------------------------------------------
# The survival certificate follows the work process: `_TimedBackend(lock_fd=N)`  →  Run backend** The thread** registers fd N for son succession.
# --------------------------------------------------------------------------------------------------


class _FdProbeBackend:
    """Back on time, write down the succession fd registration (this is where `Popen` started) as you see in your own ** thread."""

    name = "fd-probe"

    def __init__(self) -> None:
        self.thread_id = 0
        self.inherited: tuple[int, ...] = ()

    def run(self, *, work_dir, task, context):
        self.thread_id = threading.get_ident()
        self.inherited = (
            proc.inherited_fds()
        )  # Backend, this is what you used to do with the pass_fds.
        return "ok"


def test_timed_backend_holds_the_lock_fd_on_the_thread_that_runs_the_backend(tmp_path, killed):
    """Spec-0065/T2: `lock_fd=N`  →  on the **back** `proc.hold_fd(fd=N)`, so agent subprocesse inherited
    flock（`backends.claude_code` It’s... `Popen(pass_fds=proc.inherited_fds())` This is the same registration.

    ** Survivors have to follow the process that really works** : When the watch was killed by SIGKILL/OOM/Z`docker stop`, it started ant
    Orphaned rather than killed** (and run once from Yon. `git push`). If the lock is only in the Vigil, the kernel will be locked on the spot. `_reclaim_dead`
    The Quuued  →  Another worker takes the same subject ** double run**. After having given an agent to inherit fd, the Quuued  →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →   →
    The word for the lock becomes ”or its watch** or its agent has one alive” and the entrance is sealed.

    Registration must be on the ** thread** (`_INHERIT` press thread ident): Falling on the main thread equals falling --backend in the sub-routine
    Read `inherited_fds()`, which is empty, and fd will not be passed to `Popen` at all.
    """
    fd = os.open(str(tmp_path / "issue-5.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    backend = _FdProbeBackend()
    try:
        result = _TimedBackend(inner=backend, timeout_seconds=30, lock_fd=fd).run(
            work_dir=Path("."), task="t", context="c"
        )

        assert result == "ok"
        assert backend.inherited == (fd,), "The circuit running backend must see this fd."
        assert backend.thread_id != threading.get_ident()  # It's another line.
        assert os.get_inheritable(fd), (
            "fd must be held as inheritable (PEP 446 default close-on-exec)"
        )
        assert proc.inherited_fds() == (), "The main line should not be registered any fd"
        assert backend.thread_id not in proc._INHERIT, (
            "After work, release_fds must be registered and no leaks must be made."
        )
    finally:
        os.close(fd)


def test_timed_backend_holds_no_fd_when_there_is_no_claim(killed):
    """`lock_fd=None`”Producer’s threads” triager/curator：**No claim, no lock.**）→ One. fd No registration is allowed.

    The new ‘Fd’ program is to use the key that it should not have: it will crucify ** someone else’s ** when it survives.
    `_reclaim_dead` can’t judge death  →  that subject never moves.
    """
    backend = _FdProbeBackend()
    _TimedBackend(inner=backend, timeout_seconds=30, lock_fd=None).run(
        work_dir=Path("."), task="t", context="c"
    )
    assert backend.inherited == (), "There’s no proof of survival without a claim."
    assert backend.thread_id not in proc._INHERIT
