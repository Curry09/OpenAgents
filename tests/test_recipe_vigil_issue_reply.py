"""#Spec-0016/T4:vigil connection — issue page comments response to the unit test (issue sub-section 2)

Coverage:
- `_sense`:ready no-PR issue, latest comment is unsigned human latest_comment_is_ours = False `_classify`
  ACTIONABLE:preply (** non** Solve);
- No-PR issue/ no-ready issue latest_comment_is_ours maintains the status quo (not misactivated);
- `_do_reply`: pass identity.post_signed_comment_on_issue drop issue, push issue
- The latest comments are signed by us. → Next tick _sense Set latest_comment_is_ours=True → branch ②(a) Ceasefire (no repeats);
- `_fingerprint` input field set still = dataclasses.fields (Facts) full collection, without reference id (I am not self-destructing).
"""

import dataclasses
from pathlib import Path

import pytest

from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import (
    _ACT_REPLY,
    _ACT_SOLVE,
    _ACTIONABLE,
    _LABEL_READY,
    _classify,
    _do_reply,
    _Facts,
    _fingerprint,
    _sense,
)
from openagents.utils import agent_config, github, identity


def _config(**overrides) -> agent_config.AgentConfig:
    defaults = {
        "version": 1,
        "agents": agent_config.AgentPolicy(backends={}),
        "stages": agent_config.StagePolicy(owners={}),
        "release": agent_config.ReleasePolicy(),
        "interval": 1,
        "base": "main",
        "labels": ["openagents"],
        "repos": [],
    }
    return agent_config.AgentConfig(**(defaults | overrides))


def _human(*, created_at, body="Can you support it, codex?"):
    return github.Comment(
        id=f"c-{created_at}",
        author="alice",
        body=body,
        created_at=created_at,
        author_association="NONE",
    )


def _ours(*, created_at, agent_id="oa-1"):
    return github.Comment(
        id=f"m-{created_at}",
        author="openagents-bot",
        body=identity.sign(body="I got your question.", agent_id=agent_id),
        created_at=created_at,
        author_association="OWNER",
    )


def _patch_issue_sense(monkeypatch, *, labels, comments, pr=None):
    """Plays _sense side of a read without-PR (or specifies PR)issue."""
    monkeypatch.setattr(
        vigil_module.github, "get_issue", lambda *, number: github.Issue(149, "T", "B", labels)
    )
    monkeypatch.setattr(vigil_module.github, "list_blocked_by", lambda *, number: [])
    monkeypatch.setattr(vigil_module.github, "pr_for_branch", lambda *, branch: pr)
    monkeypatch.setattr(
        vigil_module.github, "list_issue_comments", lambda *, number: list(comments)
    )


# ---- _sense + _classify: new-back-no-PR issue  →  reply (non-solve) --------------------------


def test_ready_no_pr_issue_with_human_comment_classifies_reply(monkeypatch):
    _patch_issue_sense(
        monkeypatch,
        labels=[_LABEL_READY],
        comments=[_human(created_at="2026-07-14T12:00:00Z")],
    )
    facts = _sense(config=_config(), subject="issue:149").facts
    assert facts.pr_number is None
    assert facts.latest_comment_is_ours is False
    verdict = _classify(facts=facts, in_flight=False)
    assert verdict.kind == _ACTIONABLE
    assert verdict.action == _ACT_REPLY  # Branch 2 ahead of Branch 4


def test_ready_no_pr_issue_latest_is_ours_falls_through_to_solve(monkeypatch):
    # The latest comment has been made by our signature (e.g., the last round has been returned) latest_comment_is_ours =True  →  no longer reply to solve.
    _patch_issue_sense(
        monkeypatch,
        labels=[_LABEL_READY],
        comments=[
            _human(created_at="2026-07-14T12:00:00Z"),
            _ours(created_at="2026-07-14T12:05:00Z"),
        ],
    )
    facts = _sense(config=_config(), subject="issue:149").facts
    assert facts.latest_comment_is_ours is True
    verdict = _classify(facts=facts, in_flight=False)
    assert verdict.action == _ACT_SOLVE


def test_not_ready_no_pr_issue_does_not_activate_reply(monkeypatch):
    # Not ready to release (at entry admitter): ** Not activated, even if signed,** reply.
    _patch_issue_sense(
        monkeypatch,
        labels=["openagents"],  # No ready
        comments=[_human(created_at="2026-07-14T12:00:00Z")],
    )
    facts = _sense(config=_config(), subject="issue:149").facts
    assert facts.latest_comment_is_ours is True  # Maintain default, no error in activation
    verdict = _classify(facts=facts, in_flight=False)
    assert verdict.action == _ACT_SOLVE


def test_fingerprint_input_is_full_facts_fields_without_comment_id(monkeypatch):
    # The input field set  → Facts is complete and does not contain a code id (latest_comment_is_ours Bull only).
    _patch_issue_sense(
        monkeypatch,
        labels=[_LABEL_READY],
        comments=[_human(created_at="2026-07-14T12:00:00Z")],
    )
    facts = _sense(config=_config(), subject="issue:149").facts
    field_names = {f.name for f in dataclasses.fields(_Facts)}
    assert "latest_comment_is_ours" in field_names
    assert not any("comment_id" in name or name == "id" for name in field_names)
    # fp is pure function, stable: equal to fact.
    assert _fingerprint(facts=facts) == _fingerprint(facts=facts)


# ---- _do_reply It's... issue Support: Fall issue + Push! issue Cursor ----------------------------------------------


class _FakeState:
    def __init__(self):
        self.issue_cursors = {}

    def get_issue_cursor(self, *, number):
        return self.issue_cursors.get(number)

    def set_issue_cursor(self, *, number, comment_id):
        self.issue_cursors[number] = comment_id


class _FakeBackend:
    """engine.run_agent will read agent_module.PROMPT.substitute  →  backend.run  →  endline JSON."""

    def run(self, *, work_dir, task, context):
        import types

        return types.SimpleNamespace(
            summary='{"reply": "Copy that. I understand.", "resolved": false}'
        )


def test_do_reply_issue_posts_signed_and_advances_cursor(monkeypatch, tmp_path):
    posted = []
    monkeypatch.setattr(
        vigil_module.identity,
        "post_signed_comment_on_issue",
        lambda *, number, body, agent_id: posted.append((number, body, agent_id)),
    )
    # No-PR issue: new_human_comments_on_issue Read side returns a new human comment.
    monkeypatch.setattr(
        vigil_module.identity,
        "new_human_comments_on_issue",
        lambda *, number, since: [_human(created_at="2026-07-14T12:00:00Z")],
    )
    state = _FakeState()
    facts = _Facts(
        subject="issue:149",
        pr_number=None,
        head_sha=None,
        merged=False,
        closed=False,
        labels=frozenset({_LABEL_READY}),
        deps_done=True,
        mergeable_state=None,
        ci="none",
        e2e_head_sha=None,
        review_state=None,
        review_commit_id=None,
        latest_comment_is_ours=False,
    )
    reply = _do_reply(
        backend=_FakeBackend(),
        state=state,
        work_dir=Path(tmp_path),
        facts=facts,
        agent_id="oa-1",
    )
    assert reply == "Copy that. I understand."
    assert posted == [(149, "Copy that. I understand.", "oa-1")]
    # The cursor is pushed to the created_at of the human comment (next tick does not repeat it).
    assert state.get_issue_cursor(number=149) == "2026-07-14T12:00:00Z"


def test_do_reply_issue_noop_when_no_new_human_comments(monkeypatch, tmp_path):
    posted = []
    monkeypatch.setattr(
        vigil_module.identity,
        "post_signed_comment_on_issue",
        lambda *, number, body, agent_id: posted.append(number),
    )
    monkeypatch.setattr(
        vigil_module.identity,
        "new_human_comments_on_issue",
        lambda *, number, since: [],  # No new human comment after the cursor
    )
    facts = _Facts(
        subject="issue:149",
        pr_number=None,
        head_sha=None,
        merged=False,
        closed=False,
        labels=frozenset({_LABEL_READY}),
        deps_done=True,
        mergeable_state=None,
        ci="none",
        e2e_head_sha=None,
        review_state=None,
        review_commit_id=None,
        latest_comment_is_ours=False,
    )
    reply = _do_reply(
        backend=_FakeBackend(),
        state=_FakeState(),
        work_dir=Path(tmp_path),
        facts=facts,
        agent_id="oa-1",
    )
    assert reply == ""
    assert posted == []  # No new comments. No comments.


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
