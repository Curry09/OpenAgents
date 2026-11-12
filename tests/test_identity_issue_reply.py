"""# Spec-0016/T1:issue signature for original language unit testing.

Overwrite (monkeypaytch github.list_issue_comments/ issue_comment, netless):
- new_human_comments_on_issue returns only unsigned human comments after since, filters signed machine reviews, and press created_at ascending order;
- post_signed_comment_on_issue seal signed by issue_comment to issue; read the latest signed in this format without signing;
- Read back the latest missing signature and take the initiative to add a signature comment (closure of 3 bound);
- There is no change in behaviour (no behavior change) with the PR version new_human_comments/post_signed_comment.
"""

import pytest

from openagents.utils import identity as identity_module
from openagents.utils.github import Comment
from openagents.utils.identity import (
    new_human_comments,
    new_human_comments_on_issue,
    parse_agent_id,
    post_signed_comment,
    post_signed_comment_on_issue,
    sign,
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


def _patch_issue_comments(monkeypatch, *, comments):
    monkeypatch.setattr(
        identity_module.github, "list_issue_comments", lambda *, number: list(comments)
    )


# ----new_human_comments_on_issue: Read side issue with PR symmetric ---------------------------------------


def test_issue_reader_filters_signed_machine_comments(monkeypatch):
    _patch_issue_comments(
        monkeypatch,
        comments=[
            _machine(created_at="2026-07-14T11:00:00Z"),
            _machine(created_at="2026-07-14T12:00:00Z", agent_id="other-bot"),
        ],
    )
    assert new_human_comments_on_issue(number=149, since="2026-07-14T10:00:00Z") == []


def test_issue_reader_filters_at_or_before_cursor(monkeypatch):
    cursor = "2026-07-14T10:00:00Z"
    _patch_issue_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-07-14T09:00:00Z", body="History"),
            _human(created_at=cursor, body="It’s exactly the same as the cruise."),
            _human(created_at="2026-07-14T11:00:00Z", body="New comments"),
        ],
    )
    result = new_human_comments_on_issue(number=149, since=cursor)
    assert [c.body for c in result] == ["New comments"]


def test_issue_reader_returns_human_comments_sorted(monkeypatch):
    cursor = "2026-07-14T10:00:00Z"
    _patch_issue_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-07-14T13:00:00Z", body="Third"),
            _machine(created_at="2026-07-14T12:30:00Z"),
            _human(created_at="2026-07-14T11:00:00Z", body="First"),
            _human(created_at="2026-07-14T12:00:00Z", body="Second"),
            _human(created_at="2026-07-14T09:00:00Z", body="History"),
        ],
    )
    result = new_human_comments_on_issue(number=149, since=cursor)
    assert [c.body for c in result] == ["First", "Second", "Third"]


def test_issue_reader_empty_since_returns_all_human(monkeypatch):
    _patch_issue_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-07-14T09:00:00Z", body="History humans"),
            _machine(created_at="2026-07-14T10:00:00Z"),
            _human(created_at="2026-07-14T11:00:00Z", body="New Humanity"),
        ],
    )
    result = new_human_comments_on_issue(number=149, since="")
    assert [c.body for c in result] == ["History humans", "New Humanity"]


# ---- post_signed_comment_on_issue: Write side issue + Read Back to Back-Sclosure -------------------------------------


def test_issue_writer_signs_and_posts(monkeypatch):
    posted = []
    monkeypatch.setattr(
        identity_module.github,
        "issue_comment",
        lambda *, number, body: posted.append((number, body)),
    )
    # Read back: The latest one just came from us and signed without a signature.
    monkeypatch.setattr(
        identity_module.github,
        "list_issue_comments",
        lambda *, number: [
            Comment(
                id="c1",
                author="openagents",
                body=posted[-1][1] if posted else "",
                created_at="2026-07-14T12:00:00Z",
            )
        ],
    )
    post_signed_comment_on_issue(number=149, body="I got your question.", agent_id="oa-1")
    assert len(posted) == 1
    number, body = posted[0]
    assert number == 149
    assert parse_agent_id(body=body) == "oa-1"
    assert "I got your question." in body


def test_issue_writer_backfills_when_signature_missing(monkeypatch):
    posted = []
    monkeypatch.setattr(
        identity_module.github,
        "issue_comment",
        lambda *, number, body: posted.append((number, body)),
    )
    # The latest article at the time of reading back** did not have our signature (rewritten/cut off from the outside) triggers the additional signature.
    monkeypatch.setattr(
        identity_module.github,
        "list_issue_comments",
        lambda *, number: [
            Comment(id="c1", author="alice", body="Human words.", created_at="2026-07-14T13:00:00Z")
        ],
    )
    post_signed_comment_on_issue(number=149, body="First Answer", agent_id="oa-1")
    # One reply + one additional signature, both of which are signed with this instance, by issue_comment assue 149.
    assert len(posted) == 2
    assert all(number == 149 for number, _ in posted)
    assert parse_agent_id(body=posted[-1][1]) == "oa-1"


def test_issue_writer_no_backfill_on_empty_readback(monkeypatch):
    posted = []
    monkeypatch.setattr(
        identity_module.github,
        "issue_comment",
        lambda *, number, body: posted.append((number, body)),
    )
    monkeypatch.setattr(identity_module.github, "list_issue_comments", lambda *, number: [])
    post_signed_comment_on_issue(number=149, body="First Answer", agent_id="oa-1")
    assert len(posted) == 1  # Read back as empty


# ---- zero returns: PR version original language behaviour remains unchanged ---------------------------------------------------------------------


def test_pr_reader_unchanged(monkeypatch):
    monkeypatch.setattr(
        identity_module.github,
        "list_comments",
        lambda *, pr_number: [
            _human(created_at="2026-07-14T11:00:00Z", body="PR Human Review"),
            _machine(created_at="2026-07-14T12:00:00Z"),
        ],
    )
    result = new_human_comments(pr_number=7, since="")
    assert [c.body for c in result] == ["PR Human Review"]


def test_pr_writer_unchanged(monkeypatch):
    posted = []
    monkeypatch.setattr(
        identity_module.github,
        "post_comment",
        lambda *, pr_number, body: posted.append((pr_number, body)),
    )
    monkeypatch.setattr(
        identity_module.github,
        "list_comments",
        lambda *, pr_number: [
            Comment(
                id="c1",
                author="openagents",
                body=posted[-1][1] if posted else "",
                created_at="2026-07-14T12:00:00Z",
            )
        ],
    )
    post_signed_comment(pr_number=7, body="PR Response", agent_id="oa-1")
    assert len(posted) == 1
    assert posted[0][0] == 7
    assert parse_agent_id(body=posted[0][1]) == "oa-1"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
