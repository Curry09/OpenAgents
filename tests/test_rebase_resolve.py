"""Spec-0028/T3：rebase_open_prs 的分层降级 heal → resolve → 人工 单元测试。

所有 GitHub 交互通过 monkeypatch github.* 桩掉，heal/resolve 注入假回调，保持 hermetic。
覆盖：heal 命中 → HEALED（不调 resolve）；heal 未命中、resolve 命中 → RESOLVED；
两层都未命中 → CONFLICT + 留言；resolve=None → 回落现状 CONFLICT；无冲突 → UPDATED（不调 resolve）。
"""

import pytest

from openagents import rebase as rebase_module
from openagents.github import PR, GithubError
from openagents.rebase import (
    CONFLICT_COMMENT,
    RESULT_CONFLICT,
    RESULT_HEALED,
    RESULT_RESOLVED,
    RESULT_UPDATED,
    rebase_open_prs,
)

_AGENT_ID = "agent-x"


def _patch(monkeypatch, *, open_prs, update):
    """monkeypatch github.*：open_prs 为 list_open_prs 返回值；update 为 update_branch 行为。

    update[pr_number] → True/False（返回值）或 GithubError 实例（抛出，触发冲突分层降级）。
    返回记录 post_comment 调用的列表。
    """
    comments: list[dict] = []

    monkeypatch.setattr(rebase_module.github, "list_open_prs", lambda: list(open_prs))

    def _update_branch(*, pr_number, rebase):
        outcome = update[pr_number]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(rebase_module.github, "update_branch", _update_branch)
    monkeypatch.setattr(
        rebase_module.github,
        "post_comment",
        lambda *, pr_number, body: comments.append({"pr_number": pr_number, "body": body}),
    )
    return comments


def _pr(number):
    return PR(number=number, url=f"https://github.com/acme/widget/pull/{number}")


def test_heal_hit_short_circuits_resolve(monkeypatch):
    _patch(monkeypatch, open_prs=[_pr(5)], update={5: GithubError("冲突")})
    resolve_calls = []

    events = rebase_open_prs(
        agent_id=_AGENT_ID,
        heal=lambda *, pr_number: True,
        resolve=lambda *, pr_number: resolve_calls.append(pr_number) or True,
    )

    assert events == [{"pr_number": 5, "result": RESULT_HEALED}]
    assert resolve_calls == []  # heal 命中即短路，不调 resolve


def test_resolve_hit_when_heal_misses(monkeypatch):
    comments = _patch(monkeypatch, open_prs=[_pr(8)], update={8: GithubError("冲突")})

    events = rebase_open_prs(
        agent_id=_AGENT_ID,
        heal=lambda *, pr_number: False,
        resolve=lambda *, pr_number: True,
    )

    assert events == [{"pr_number": 8, "result": RESULT_RESOLVED}]
    assert comments == []  # resolve 命中即不留言


def test_both_miss_falls_back_to_conflict_comment(monkeypatch):
    comments = _patch(monkeypatch, open_prs=[_pr(9)], update={9: GithubError("冲突")})

    events = rebase_open_prs(
        agent_id=_AGENT_ID,
        heal=lambda *, pr_number: False,
        resolve=lambda *, pr_number: False,
    )

    assert events == [{"pr_number": 9, "result": RESULT_CONFLICT}]
    assert len(comments) == 1
    assert comments[0]["pr_number"] == 9
    assert CONFLICT_COMMENT in comments[0]["body"]


def test_resolve_none_keeps_legacy_conflict_behavior(monkeypatch):
    # resolve 未注入（如手动 sync-prs）：逐字节回落现状——冲突即留言 + CONFLICT。
    comments = _patch(monkeypatch, open_prs=[_pr(3)], update={3: GithubError("冲突")})

    events = rebase_open_prs(agent_id=_AGENT_ID)

    assert events == [{"pr_number": 3, "result": RESULT_CONFLICT}]
    assert len(comments) == 1
    assert comments[0]["pr_number"] == 3
    assert CONFLICT_COMMENT in comments[0]["body"]


def test_no_conflict_does_not_call_resolve(monkeypatch):
    _patch(monkeypatch, open_prs=[_pr(7)], update={7: True})
    resolve_calls = []

    events = rebase_open_prs(
        agent_id=_AGENT_ID, resolve=lambda *, pr_number: resolve_calls.append(pr_number) or True
    )

    assert events == [{"pr_number": 7, "result": RESULT_UPDATED}]
    assert resolve_calls == []  # 干净 update 不触发任何冲突降级


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
