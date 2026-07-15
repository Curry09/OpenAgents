"""# Spec-0016/T4：vigil 接线——issue 页评论回复分支（reply 分支②的 issue 支）单元测试。

覆盖：
- `_sense`：ready 无-PR issue、最新评论是无签名人类 → latest_comment_is_ours=False → `_classify` 判
  ACTIONABLE:reply（**非** solve）；
- 未 ready 的无-PR issue / 有 PR 的 issue → latest_comment_is_ours 维持现状（不误激活）；
- `_do_reply` 的 issue 支：经 identity.post_signed_comment_on_issue 落 issue、推 issue 游标；
- 回帖后最新评论是我方签名 → 下一 tick _sense 置 latest_comment_is_ours=True → 分支②停火（不重复回帖）；
- `_fingerprint` 输入字段集仍 == dataclasses.fields(_Facts) 全集、不含 comment id（护栏一不自毁）。
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


def _human(*, created_at, body="能不能也支持 codex？"):
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
        body=identity.sign(body="收到你的追问", agent_id=agent_id),
        created_at=created_at,
        author_association="OWNER",
    )


def _patch_issue_sense(monkeypatch, *, labels, comments, pr=None):
    """打桩无-PR（或指定 PR）issue 的 _sense 读侧。"""
    monkeypatch.setattr(
        vigil_module.github, "get_issue", lambda *, number: github.Issue(149, "T", "B", labels)
    )
    monkeypatch.setattr(vigil_module.github, "list_blocked_by", lambda *, number: [])
    monkeypatch.setattr(vigil_module.github, "pr_for_branch", lambda *, branch: pr)
    monkeypatch.setattr(
        vigil_module.github, "list_issue_comments", lambda *, number: list(comments)
    )


# ---- _sense + _classify：ready 无-PR issue 的新人类评论 → reply（非 solve）--------------------------


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
    assert verdict.action == _ACT_REPLY  # 分支②抢在分支④ solve 前面


def test_ready_no_pr_issue_latest_is_ours_falls_through_to_solve(monkeypatch):
    # 最新评论已是我方签名（比如上一轮已回过）→ latest_comment_is_ours=True → 不再 reply、落到 solve。
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
    # 未 ready 的 issue（归准入面 admitter）：即便有无签名人类评论，也**不**激活 reply。
    _patch_issue_sense(
        monkeypatch,
        labels=["openagents"],  # 无 ready
        comments=[_human(created_at="2026-07-14T12:00:00Z")],
    )
    facts = _sense(config=_config(), subject="issue:149").facts
    assert facts.latest_comment_is_ours is True  # 维持默认，不误激活
    verdict = _classify(facts=facts, in_flight=False)
    assert verdict.action == _ACT_SOLVE


def test_fingerprint_input_is_full_facts_fields_without_comment_id(monkeypatch):
    # 护栏一：fp 的输入字段集 ≡ _Facts 全集，且绝不含 comment id（只留 latest_comment_is_ours 布尔）。
    _patch_issue_sense(
        monkeypatch,
        labels=[_LABEL_READY],
        comments=[_human(created_at="2026-07-14T12:00:00Z")],
    )
    facts = _sense(config=_config(), subject="issue:149").facts
    field_names = {f.name for f in dataclasses.fields(_Facts)}
    assert "latest_comment_is_ours" in field_names
    assert not any("comment_id" in name or name == "id" for name in field_names)
    # fp 是纯函数、稳定：同 facts 两次算得同值。
    assert _fingerprint(facts=facts) == _fingerprint(facts=facts)


# ---- _do_reply 的 issue 支：落 issue + 推 issue 游标 ----------------------------------------------


class _FakeState:
    def __init__(self):
        self.issue_cursors = {}

    def get_issue_cursor(self, *, number):
        return self.issue_cursors.get(number)

    def set_issue_cursor(self, *, number, comment_id):
        self.issue_cursors[number] = comment_id


class _FakeBackend:
    """engine.run_agent 会读 agent_module.PROMPT.substitute → backend.run → 末行 JSON。"""

    def run(self, *, work_dir, task, context):
        import types

        return types.SimpleNamespace(
            summary='{"reply": "收到，我理解成要兼容 codex，对吗？", "resolved": false}'
        )


def test_do_reply_issue_posts_signed_and_advances_cursor(monkeypatch, tmp_path):
    posted = []
    monkeypatch.setattr(
        vigil_module.identity,
        "post_signed_comment_on_issue",
        lambda *, number, body, agent_id: posted.append((number, body, agent_id)),
    )
    # 无-PR issue：new_human_comments_on_issue 读侧返回一条新人类评论。
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
    assert reply == "收到，我理解成要兼容 codex，对吗？"
    assert posted == [(149, "收到，我理解成要兼容 codex，对吗？", "oa-1")]
    # 游标推到那条人类评论的 created_at（下一 tick 起不再重复读它）。
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
        lambda *, number, since: [],  # 游标之后无新人类评论
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
    assert posted == []  # 没有新评论 → 不回帖


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
