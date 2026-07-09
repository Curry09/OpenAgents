"""Spec-0032/T4：identity.new_human_comments 读侧复活的单元测试。

github.list_comments 注入（monkeypatch 为返回固定 Comment 列表的 fake），不触网。覆盖：
- 带签名的机器评论（任意 agent_id）被滤掉；
- created_at <= since 的历史评论被滤掉；
- 仅 block 之后的无签名人类评论返回、且按时间升序；
- since="" 时返回全部人类评论（仍滤签名）。
"""

import pytest

from openagents.utils import identity as identity_module
from openagents.utils.github import Comment
from openagents.utils.identity import new_human_comments, sign


def _patch_comments(monkeypatch, *, comments):
    monkeypatch.setattr(
        identity_module.github, "list_comments", lambda *, pr_number: list(comments)
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
            _human(created_at="2026-06-29T09:00:00Z", body="历史评论"),
            _human(created_at=wm, body="正好等于水位线"),
            _human(created_at="2026-06-29T11:00:00Z", body="新评论"),
        ],
    )
    result = new_human_comments(pr_number=5, since=wm)
    assert [c.body for c in result] == ["新评论"]


def test_returns_only_post_block_human_comments_sorted(monkeypatch):
    wm = "2026-06-29T10:00:00Z"
    _patch_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-06-29T13:00:00Z", body="第三"),
            _machine(created_at="2026-06-29T12:30:00Z"),  # 机器评论：滤掉
            _human(created_at="2026-06-29T11:00:00Z", body="第一"),
            _human(created_at="2026-06-29T12:00:00Z", body="第二"),
            _human(created_at="2026-06-29T09:00:00Z", body="历史"),  # 水位线之前：滤掉
        ],
    )
    result = new_human_comments(pr_number=5, since=wm)
    assert [c.body for c in result] == ["第一", "第二", "第三"]


def test_empty_since_returns_all_human_comments(monkeypatch):
    _patch_comments(
        monkeypatch,
        comments=[
            _human(created_at="2026-06-29T09:00:00Z", body="历史人类"),
            _machine(created_at="2026-06-29T10:00:00Z"),
            _human(created_at="2026-06-29T11:00:00Z", body="新人类"),
        ],
    )
    result = new_human_comments(pr_number=5, since="")
    assert [c.body for c in result] == ["历史人类", "新人类"]


def test_no_comments_returns_empty(monkeypatch):
    _patch_comments(monkeypatch, comments=[])
    assert new_human_comments(pr_number=5, since="") == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
