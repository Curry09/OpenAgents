"""Spec-0032/T4: identity.new_human_comments Reader-side Quest Unit Test.

github.list_comments Injecting (monkeypaytch returns the fake of the fixed Comment list), without touching the net. Overwrite:
- Signing machine reviews (arbitrary agent_id) are filtered out;
- created_at < = since history review filtered out;
- Only unsigned humans returning after block and in chronological order;
-Since=”backs all human comments (still filtering).
"""

import pytest

from openagents.utils import identity as identity_module
from openagents.utils.github import Comment
from openagents.utils.identity import new_human_comments, sign


def _patch_comments(monkeypatch, *, comments):
    monkeypatch.setattr(
        identity_module.github, "list_comments", lambda *, pr_number: list(comments)
    )


def _human(*, created_at, body="Human Review"):
    return Comment(id=f"c-{created_at}", author="alice", body=body, created_at=created_at)


def _machine(*, created_at, agent_id="bot-1"):
    return Comment(
        id=f"m-{created_at}",
        author="openagents",
        body=sign(body="Machine Review", agent_id=agent_id),
        created_at=created_at,
    )


def test_filters_out_signed_machine_comments(monkeypatch):
    _patch_comments(
        monkeypatch,
        comments=[
            _machine(created_at="2026-06-29T11:00:00Z"),
            _machine(created_at="2026-06-29T12:00:00Z", agent_id="other-bot"),
        ],
    )
    assert new_human_comments(pr_number=5, since="2026-06-29T10:00:00Z") == []


def test_filters_out_comments_at_or_before_watermark(monkeypatch):
    wm = "2026-06-29T10:00:00Z"
    _patch_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-06-29T09:00:00Z", body="Historical review"),
            _human(created_at=wm, body="It’s exactly the same as the water level."),
            _human(created_at="2026-06-29T11:00:00Z", body="New comments"),
        ],
    )
    result = new_human_comments(pr_number=5, since=wm)
    assert [c.body for c in result] == ["New comments"]


def test_returns_only_post_block_human_comments_sorted(monkeypatch):
    wm = "2026-06-29T10:00:00Z"
    _patch_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-06-29T13:00:00Z", body="Third"),
            _machine(created_at="2026-06-29T12:30:00Z"),  # Machine comment: Filter
            _human(created_at="2026-06-29T11:00:00Z", body="First"),
            _human(created_at="2026-06-29T12:00:00Z", body="Second"),
            _human(
                created_at="2026-06-29T09:00:00Z", body="History"
            ),  # Before the water level: Leach
        ],
    )
    result = new_human_comments(pr_number=5, since=wm)
    assert [c.body for c in result] == ["First", "Second", "Third"]


def test_empty_since_returns_all_human_comments(monkeypatch):
    _patch_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-06-29T09:00:00Z", body="History humans"),
            _machine(created_at="2026-06-29T10:00:00Z"),
            _human(created_at="2026-06-29T11:00:00Z", body="New Humanity"),
        ],
    )
    result = new_human_comments(pr_number=5, since="")
    assert [c.body for c in result] == ["History humans", "New Humanity"]


def test_no_comments_returns_empty(monkeypatch):
    _patch_comments(monkeypatch, comments=[])
    assert new_human_comments(pr_number=5, since="") == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
