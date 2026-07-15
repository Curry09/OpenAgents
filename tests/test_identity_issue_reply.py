"""# Spec-0016/T1：identity 的 issue 版签名读/写原语单元测试。

覆盖（monkeypatch github.list_issue_comments / issue_comment，不触网）：
- new_human_comments_on_issue 只返回 since 之后的无签名人类评论、滤掉带签名机器评论、按 created_at 升序；
- post_signed_comment_on_issue 盖签名后经 issue_comment 落 issue；回读最新已含本签名 → 不补签；
- 回读最新漏签 → 主动补一条签名评论（约束③闭环）；
- 既有 PR 版 new_human_comments / post_signed_comment 行为不变（零回归）。
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


def _human(*, created_at, body="人类评论"):
    return Comment(id=f"c-{created_at}", author="alice", body=body, created_at=created_at)


def _machine(*, created_at, agent_id="bot-1"):
    return Comment(
        id=f"m-{created_at}",
        author="openagents",
        body=sign(body="机器评论", agent_id=agent_id),
        created_at=created_at,
    )


def _patch_issue_comments(monkeypatch, *, comments):
    monkeypatch.setattr(
        identity_module.github, "list_issue_comments", lambda *, number: list(comments)
    )


# ---- new_human_comments_on_issue：读侧 issue 版，与 PR 版对称 ---------------------------------------


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
            _human(created_at="2026-07-14T09:00:00Z", body="历史"),
            _human(created_at=cursor, body="正好等于游标"),
            _human(created_at="2026-07-14T11:00:00Z", body="新评论"),
        ],
    )
    result = new_human_comments_on_issue(number=149, since=cursor)
    assert [c.body for c in result] == ["新评论"]


def test_issue_reader_returns_human_comments_sorted(monkeypatch):
    cursor = "2026-07-14T10:00:00Z"
    _patch_issue_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-07-14T13:00:00Z", body="第三"),
            _machine(created_at="2026-07-14T12:30:00Z"),
            _human(created_at="2026-07-14T11:00:00Z", body="第一"),
            _human(created_at="2026-07-14T12:00:00Z", body="第二"),
            _human(created_at="2026-07-14T09:00:00Z", body="历史"),
        ],
    )
    result = new_human_comments_on_issue(number=149, since=cursor)
    assert [c.body for c in result] == ["第一", "第二", "第三"]


def test_issue_reader_empty_since_returns_all_human(monkeypatch):
    _patch_issue_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-07-14T09:00:00Z", body="历史人类"),
            _machine(created_at="2026-07-14T10:00:00Z"),
            _human(created_at="2026-07-14T11:00:00Z", body="新人类"),
        ],
    )
    result = new_human_comments_on_issue(number=149, since="")
    assert [c.body for c in result] == ["历史人类", "新人类"]


# ---- post_signed_comment_on_issue：写侧 issue 版 + 回读补签闭环 -------------------------------------


def test_issue_writer_signs_and_posts(monkeypatch):
    posted = []
    monkeypatch.setattr(
        identity_module.github,
        "issue_comment",
        lambda *, number, body: posted.append((number, body)),
    )
    # 回读校验：最新一条恰是我方刚发的签名评论 → 不补签。
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
    post_signed_comment_on_issue(number=149, body="收到你的追问", agent_id="oa-1")
    assert len(posted) == 1
    number, body = posted[0]
    assert number == 149
    assert parse_agent_id(body=body) == "oa-1"
    assert "收到你的追问" in body


def test_issue_writer_backfills_when_signature_missing(monkeypatch):
    posted = []
    monkeypatch.setattr(
        identity_module.github,
        "issue_comment",
        lambda *, number, body: posted.append((number, body)),
    )
    # 回读时最新一条**没有**我方签名（被外部改写/截断）→ 触发补签。
    monkeypatch.setattr(
        identity_module.github,
        "list_issue_comments",
        lambda *, number: [
            Comment(id="c1", author="alice", body="人类的话", created_at="2026-07-14T13:00:00Z")
        ],
    )
    post_signed_comment_on_issue(number=149, body="首答", agent_id="oa-1")
    # 一条首答 + 一条补签，两条都经 issue_comment 落 issue 149，且都带本实例签名。
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
    post_signed_comment_on_issue(number=149, body="首答", agent_id="oa-1")
    assert len(posted) == 1  # 回读为空 → best-effort no-op（不补签）


# ---- 零回归：PR 版原语行为不变 ---------------------------------------------------------------------


def test_pr_reader_unchanged(monkeypatch):
    monkeypatch.setattr(
        identity_module.github,
        "list_comments",
        lambda *, pr_number: [
            _human(created_at="2026-07-14T11:00:00Z", body="PR 人类评论"),
            _machine(created_at="2026-07-14T12:00:00Z"),
        ],
    )
    result = new_human_comments(pr_number=7, since="")
    assert [c.body for c in result] == ["PR 人类评论"]


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
    post_signed_comment(pr_number=7, body="PR 回复", agent_id="oa-1")
    assert len(posted) == 1
    assert posted[0][0] == 7
    assert parse_agent_id(body=posted[0][1]) == "oa-1"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
