"""Spec-0049/T2:identity recognition tag + attribution/age resolution (latest_claim/build_claim_note) is a single measure.

Pure function (the only ”now” from datetime.now, for age calculation): netless, gh. Overwrite:
- build_claim_note → latest_claim To-to-to-to-Pass (to-Pass)owner Revert;
- latest_claim only recognises comments with ”claim tag + signed” and filters out precheck signed comments / unsigned human comments;
- Multiple identification sign to press created_at for the current article ’s owner and age;
- Sign  →  None without valid identification; created_at is empty/ undecomment  →  Conservative age= 0.0 (unexpired).
"""

from datetime import UTC, datetime, timedelta

import pytest

from openagents.utils.github import Comment
from openagents.utils.identity import build_claim_note, latest_claim, parse_agent_id, sign


def _comment(*, body, created_at, author="bot", cid="IC"):
    return Comment(id=cid, author=author, body=body, created_at=created_at)


def _iso(*, ago_seconds):
    """Construct an ISO 8601 UTC time stamp (with Z suffix) ”Six of ago_seconds seconds”"""
    stamp = datetime.now(UTC) - timedelta(seconds=ago_seconds)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# To and from:build_claim_note → latest_claim
# --------------------------------------------------------------------------- #


def test_build_claim_note_round_trips_owner():
    note = build_claim_note(agent_id="agent-A")
    # Sign with a claim tag and agent (parse_agent_id can remove an owner).
    assert "<!-- openagents:claim -->" in note
    assert parse_agent_id(body=note) == "agent-A"

    claim = latest_claim(comments=[_comment(body=note, created_at=_iso(ago_seconds=5))])
    assert claim is not None
    owner, age = claim
    assert owner == "agent-A"
    assert 0 <= age < 60  # The first one is very young and has not expired.


# --------------------------------------------------------------------------- #
# Recognition and then signing: filtering precheck signed comments / unsigned human comments
# --------------------------------------------------------------------------- #


def test_latest_claim_ignores_signed_non_claim_and_unsigned_comments():
    # A precheck/reviewer type signed comment (agent signed but** not marked** claim) - should not be accepted as a sign.
    precheck = sign(
        body="The law is being applied in a different direction.", agent_id="agent-precheck"
    )
    # A human comment without a signature.
    human = _comment(body="I think this is a good plan.", created_at=_iso(ago_seconds=1))
    # The only real claim is signed.
    claim_note = build_claim_note(agent_id="agent-owner")

    comments = [
        _comment(body=precheck, created_at=_iso(ago_seconds=2)),
        human,
        _comment(body=claim_note, created_at=_iso(ago_seconds=3)),
    ]
    claim = latest_claim(comments=comments)
    assert claim is not None
    assert claim[0] == "agent-owner"


def test_latest_claim_none_when_no_claim_note():
    precheck = sign(body="Alignment Comments", agent_id="agent-x")
    human = _comment(body="Pure human comment", created_at=_iso(ago_seconds=1))
    assert (
        latest_claim(comments=[_comment(body=precheck, created_at=_iso(ago_seconds=2)), human])
        is None
    )


def test_latest_claim_none_on_empty():
    assert latest_claim(comments=[]) is None


def test_latest_claim_ignores_claim_marker_without_signature():
    # Not valid as a sign.
    bogus = _comment(body="<!-- openagents:claim --> No signature", created_at=_iso(ago_seconds=1))
    assert latest_claim(comments=[bogus]) is None


# --------------------------------------------------------------------------- #
# Take the latest one + age
# --------------------------------------------------------------------------- #


def test_latest_claim_picks_latest_by_created_at():
    older = build_claim_note(agent_id="agent-old")
    newer = build_claim_note(agent_id="agent-new")
    comments = [
        _comment(body=older, created_at="2020-01-01T00:00:00Z"),
        _comment(body=newer, created_at="2026-07-03T00:00:00Z"),
    ]
    claim = latest_claim(comments=comments)
    assert claim is not None
    assert claim[0] == "agent-new"


def test_latest_claim_age_reflects_created_at():
    note = build_claim_note(agent_id="agent-A")
    claim = latest_claim(comments=[_comment(body=note, created_at=_iso(ago_seconds=3600))])
    assert claim is not None
    # About an hour ago, the age of the child was close to 3600, allowing a little bit of the drift.
    assert 3590 <= claim[1] <= 3610


def test_latest_claim_unparseable_created_at_is_conservative_not_expired():
    # created_at empty/scrap > 0.0 (conservative sentence not expired, recovery backend).
    note = build_claim_note(agent_id="agent-A")
    assert latest_claim(comments=[_comment(body=note, created_at="")])[1] == 0.0
    assert latest_claim(comments=[_comment(body=note, created_at="not-a-date")])[1] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
