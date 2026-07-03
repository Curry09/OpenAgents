"""Spec-0048/T2：identity 认领便签标记 + 归属/年龄解析（latest_claim / build_claim_note）单测。

纯函数（唯一的「现在」来自 datetime.now，用于算年龄）：不触网、不调 gh。覆盖：
- build_claim_note → latest_claim 往返保真（owner 还原）；
- latest_claim 只认「含 claim 标记 + 有签名」的评论，滤掉 precheck 署名评论 / 无签名人类评论；
- 多条认领便签按 created_at 取最新一条的 owner 与年龄；
- 无有效认领便签 → None；created_at 空/不可解析 → 保守 age=0.0（未过期）。
"""

from datetime import UTC, datetime, timedelta

import pytest

from openagents.github import Comment
from openagents.identity import build_claim_note, latest_claim, parse_agent_id, sign


def _comment(*, body, created_at, author="bot", cid="IC"):
    return Comment(id=cid, author=author, body=body, created_at=created_at)


def _iso(*, ago_seconds):
    """构造一个「距今 ago_seconds 秒」的 ISO 8601 UTC 时戳（带 Z 后缀）。"""
    stamp = datetime.now(UTC) - timedelta(seconds=ago_seconds)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# 往返：build_claim_note → latest_claim
# --------------------------------------------------------------------------- #


def test_build_claim_note_round_trips_owner():
    note = build_claim_note(agent_id="agent-A")
    # 便签同时带 claim 标记与 agent 签名（parse_agent_id 能取出 owner）。
    assert "<!-- openagents:claim -->" in note
    assert parse_agent_id(body=note) == "agent-A"

    claim = latest_claim(comments=[_comment(body=note, created_at=_iso(ago_seconds=5))])
    assert claim is not None
    owner, age = claim
    assert owner == "agent-A"
    assert 0 <= age < 60  # 刚贴的便签年龄很小、未过期


# --------------------------------------------------------------------------- #
# 只认认领便签：滤掉 precheck 署名评论 / 无签名人类评论
# --------------------------------------------------------------------------- #


def test_latest_claim_ignores_signed_non_claim_and_unsigned_comments():
    # 一条 precheck/reviewer 类署名评论（有 agent 签名但**无** claim 标记）——不应被当认领便签。
    precheck = sign(body="🤖 修法方向对齐请人取舍", agent_id="agent-precheck")
    # 一条无签名的人类评论。
    human = _comment(body="我觉得这个方案不错 +1", created_at=_iso(ago_seconds=1))
    # 唯一真正的认领便签。
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
    precheck = sign(body="对齐评论", agent_id="agent-x")
    human = _comment(body="纯人类评论", created_at=_iso(ago_seconds=1))
    assert (
        latest_claim(comments=[_comment(body=precheck, created_at=_iso(ago_seconds=2)), human])
        is None
    )


def test_latest_claim_none_on_empty():
    assert latest_claim(comments=[]) is None


def test_latest_claim_ignores_claim_marker_without_signature():
    # 有 claim 标记但没有 agent 签名（无归属）→ 不算有效认领便签。
    bogus = _comment(body="<!-- openagents:claim --> 无签名", created_at=_iso(ago_seconds=1))
    assert latest_claim(comments=[bogus]) is None


# --------------------------------------------------------------------------- #
# 取最新一条 + 年龄
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
    # 约 1 小时前 → 年龄接近 3600，允许一点执行漂移。
    assert 3590 <= claim[1] <= 3610


def test_latest_claim_unparseable_created_at_is_conservative_not_expired():
    # created_at 空/垃圾 → age=0.0（保守判未过期，不误回收活后端）。
    note = build_claim_note(agent_id="agent-A")
    assert latest_claim(comments=[_comment(body=note, created_at="")])[1] == 0.0
    assert latest_claim(comments=[_comment(body=note, created_at="not-a-date")])[1] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
