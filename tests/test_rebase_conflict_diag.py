"""Spec-0033/T2：rebase_open_prs 冲突回落的「带诊断首发」+「已 needs-human 抑制重发」单元测试。

github.list_open_prs / update_branch / has_label / post_comment 全部 monkeypatch，保持 hermetic
（不触达真实 gh）。诊断器 diagnose 以注入桩提供。专属新测试文件——不改既有 tests/test_rebase.py
（把跨并行 PR 的共享测试文件冲突面降到最小，理念：本组谈的正是冲突通知，不该自己制造共享冲突）。

覆盖：未打标签 + 注入诊断器 → 留一条带诊断的签名评论；diagnose=None → 退回静态 CONFLICT_COMMENT；
已 needs-human → 跳过留言记 RESULT_CONFLICT_SUPPRESSED；抑制后仍续跑后续 PR（错误隔离/收敛不中断）。
"""

from openagents import rebase as rebase_module
from openagents.github import PR, GithubError
from openagents.identity import parse_agent_id
from openagents.rebase import (
    CONFLICT_COMMENT,
    RESULT_CONFLICT,
    RESULT_CONFLICT_SUPPRESSED,
    RESULT_UPDATED,
    rebase_open_prs,
)

_AGENT_ID = "agent-x"

_DIAG_BODY = "自动合并目标分支 origin/main 时以下文件存在无法自动解决的冲突，需人工裁断——\n冲突文件清单（1）\n- docs/specs/OVERVIEW.md"


def _pr(number):
    return PR(number=number, url=f"https://github.com/acme/widget/pull/{number}")


def _patch(monkeypatch, *, open_prs, update, labeled=None):
    """monkeypatch github.*：update 同 test_rebase；labeled 为已 needs-human 的 pr_number 集合。"""
    comments: list[dict] = []
    labeled_set = set(labeled or set())

    monkeypatch.setattr(rebase_module.github, "list_open_prs", lambda: list(open_prs))

    def _update_branch(*, pr_number, rebase):
        outcome = update[pr_number]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _has_label(*, pr_number, name):
        return pr_number in labeled_set

    def _post_comment(*, pr_number, body):
        comments.append({"pr_number": pr_number, "body": body})

    monkeypatch.setattr(rebase_module.github, "update_branch", _update_branch)
    monkeypatch.setattr(rebase_module.github, "has_label", _has_label)
    monkeypatch.setattr(rebase_module.github, "post_comment", _post_comment)
    return comments


def test_first_conflict_posts_diagnostic_signed_comment(monkeypatch):
    comments = _patch(monkeypatch, open_prs=[_pr(5)], update={5: GithubError("merge conflict")})

    events = rebase_open_prs(agent_id=_AGENT_ID, diagnose=lambda *, pr_number: _DIAG_BODY)

    assert events == [{"pr_number": 5, "result": RESULT_CONFLICT}]
    # 正文带诊断（冲突文件清单），且盖了本实例签名（#89 读侧据签名滤掉它）。
    assert len(comments) == 1
    assert "冲突文件清单" in comments[0]["body"]
    assert parse_agent_id(body=comments[0]["body"]) == _AGENT_ID


def test_conflict_without_diagnoser_falls_back_to_static(monkeypatch):
    comments = _patch(monkeypatch, open_prs=[_pr(5)], update={5: GithubError("merge conflict")})

    events = rebase_open_prs(agent_id=_AGENT_ID)  # diagnose 缺省 None

    assert events == [{"pr_number": 5, "result": RESULT_CONFLICT}]
    assert CONFLICT_COMMENT in comments[0]["body"]


def test_already_needs_human_suppresses_resend(monkeypatch):
    comments = _patch(
        monkeypatch,
        open_prs=[_pr(5)],
        update={5: GithubError("merge conflict")},
        labeled={5},
    )

    events = rebase_open_prs(agent_id=_AGENT_ID, diagnose=lambda *, pr_number: _DIAG_BODY)

    # 已 needs-human → 跳过留言、记抑制分类；diagnose 即便注入也不被调用。
    assert events == [{"pr_number": 5, "result": RESULT_CONFLICT_SUPPRESSED}]
    assert comments == []


def test_suppression_does_not_halt_fanout(monkeypatch):
    # PR5 已 needs-human（抑制），PR8 干净更新——抑制不中断整轮扇出。
    comments = _patch(
        monkeypatch,
        open_prs=[_pr(5), _pr(8)],
        update={5: GithubError("merge conflict"), 8: True},
        labeled={5},
    )

    events = rebase_open_prs(agent_id=_AGENT_ID, diagnose=lambda *, pr_number: _DIAG_BODY)

    assert events == [
        {"pr_number": 5, "result": RESULT_CONFLICT_SUPPRESSED},
        {"pr_number": 8, "result": RESULT_UPDATED},
    ]
    assert comments == []
