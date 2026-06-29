"""RFC-0009 T2: rebase_open_prs 扇出模块的单元测试。

所有 GitHub 交互通过 monkeypatch github.list_open_prs / update_branch / post_comment
桩掉，保持 hermetic（不触达真实 gh）。

覆盖：正常更新、排除已合并 PR、up-to-date 归类、冲突→留言且不中断后续、空 open 列表。
"""

import pytest

from openagents import rebase as rebase_module
from openagents.github import PR, GithubError
from openagents.identity import parse_agent_id
from openagents.rebase import (
    CONFLICT_COMMENT,
    RESULT_CONFLICT,
    RESULT_HEALED,
    RESULT_UP_TO_DATE,
    RESULT_UPDATED,
    rebase_open_prs,
)

# RFC-0011 T5：所有 rebase_open_prs 调用都需传 agent_id（冲突留言据此盖章）。
_AGENT_ID = "agent-x"


def _patch(monkeypatch, *, open_prs, update):
    """monkeypatch github.*：open_prs 为 list_open_prs 返回值；update 为 update_branch 行为。

    update 是 dict[pr_number] -> 行为：True/False（返回值）或 GithubError 实例（抛出）。
    返回记录 update_branch 与 post_comment 调用的列表。
    """
    updates: list[dict] = []
    comments: list[dict] = []

    monkeypatch.setattr(rebase_module.github, "list_open_prs", lambda: list(open_prs))

    def _update_branch(*, pr_number, rebase):
        updates.append({"pr_number": pr_number, "rebase": rebase})
        outcome = update[pr_number]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _post_comment(*, pr_number, body):
        comments.append({"pr_number": pr_number, "body": body})

    monkeypatch.setattr(rebase_module.github, "update_branch", _update_branch)
    monkeypatch.setattr(rebase_module.github, "post_comment", _post_comment)
    # Spec-0033/T2：冲突回落分支新增 has_label（重发收敛）门控——默认 False（未 needs-human），
    # 逐字节保持既有冲突→留言行为；带诊断/抑制的专属断言放在 tests/test_rebase_conflict_diag.py。
    monkeypatch.setattr(rebase_module.github, "has_label", lambda *, pr_number, name: False)
    return updates, comments


def _pr(number):
    return PR(number=number, url=f"https://github.com/acme/widget/pull/{number}")


def test_updates_each_open_pr(monkeypatch):
    updates, comments = _patch(monkeypatch, open_prs=[_pr(5), _pr(8)], update={5: True, 8: True})

    events = rebase_open_prs(agent_id=_AGENT_ID)

    assert events == [
        {"pr_number": 5, "result": RESULT_UPDATED},
        {"pr_number": 8, "result": RESULT_UPDATED},
    ]
    assert [u["pr_number"] for u in updates] == [5, 8]
    # 默认 merge：rebase=False 透传给 update_branch。
    assert all(u["rebase"] is False for u in updates)
    assert comments == []


def test_excludes_merged_pr(monkeypatch):
    updates, _ = _patch(monkeypatch, open_prs=[_pr(5), _pr(8)], update={8: True})

    events = rebase_open_prs(merged_pr_number=5, agent_id=_AGENT_ID)

    # 刚合并的 PR #5 被排除，只同步 #8。
    assert [u["pr_number"] for u in updates] == [8]
    assert events == [{"pr_number": 8, "result": RESULT_UPDATED}]


def test_up_to_date_classified(monkeypatch):
    _patch(monkeypatch, open_prs=[_pr(5)], update={5: False})

    events = rebase_open_prs(agent_id=_AGENT_ID)

    assert events == [{"pr_number": 5, "result": RESULT_UP_TO_DATE}]


def test_conflict_posts_comment_and_continues(monkeypatch):
    # PR #5 冲突 → 留言并继续；PR #8 仍正常更新（错误隔离，决策 4）。
    updates, comments = _patch(
        monkeypatch,
        open_prs=[_pr(5), _pr(8)],
        update={5: GithubError("merge conflict"), 8: True},
    )

    events = rebase_open_prs(agent_id=_AGENT_ID)

    assert events == [
        {"pr_number": 5, "result": RESULT_CONFLICT},
        {"pr_number": 8, "result": RESULT_UPDATED},
    ]
    # 冲突 PR 收到提示评论；正常 PR 不留言。
    assert [c["pr_number"] for c in comments] == [5]
    # RFC-0011 T5：留言含原文案且盖本实例签名（下一轮 poll 据签名剔除自评论）。
    assert CONFLICT_COMMENT in comments[0]["body"]
    assert parse_agent_id(body=comments[0]["body"]) == _AGENT_ID
    assert [u["pr_number"] for u in updates] == [5, 8]


def test_rebase_flag_passed_through(monkeypatch):
    updates, _ = _patch(monkeypatch, open_prs=[_pr(5)], update={5: True})

    rebase_open_prs(rebase=True, agent_id=_AGENT_ID)

    assert updates == [{"pr_number": 5, "rebase": True}]


def test_conflict_healed_skips_comment(monkeypatch):
    # issue #48：服务端冲突先试索引自愈，成功 → RESULT_HEALED 且不留言。
    _, comments = _patch(monkeypatch, open_prs=[_pr(5)], update={5: GithubError("merge conflict")})
    healed = []

    def _heal(*, pr_number):
        healed.append(pr_number)
        return True

    events = rebase_open_prs(agent_id=_AGENT_ID, heal=_heal)

    assert events == [{"pr_number": 5, "result": RESULT_HEALED}]
    assert healed == [5]
    assert comments == []


def test_conflict_heal_fails_falls_back_to_comment(monkeypatch):
    # issue #48：自愈不了（含真实冲突）→ 回落到既有人工留言路径。
    _, comments = _patch(monkeypatch, open_prs=[_pr(5)], update={5: GithubError("merge conflict")})

    events = rebase_open_prs(agent_id=_AGENT_ID, heal=lambda *, pr_number: False)

    assert events == [{"pr_number": 5, "result": RESULT_CONFLICT}]
    assert [c["pr_number"] for c in comments] == [5]


def test_empty_open_list_is_noop(monkeypatch):
    updates, comments = _patch(monkeypatch, open_prs=[], update={})

    events = rebase_open_prs(merged_pr_number=5, agent_id=_AGENT_ID)

    assert events == []
    assert updates == []
    assert comments == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
