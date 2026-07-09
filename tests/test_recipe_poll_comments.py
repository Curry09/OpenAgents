"""Spec-0061/T3: recipes.poll_comments 守候段控制流单测——假 backend 喂 replier 回复裁决。

证明架构契约：poll_comments 只做「拉游标后的新人类评论 → 派 replier → 盖签名回帖 → 推进游标」
纯控制流，自身零业务判断（该怎么回是 replier 的活）；单 PR 失败错误隔离不拖垮整轮。全程假 backend
+ 打桩 github/identity，不触真实 LLM/网络/仓库。
"""

from __future__ import annotations

import json

from openagents.backends.base import AgentResult
from openagents.github import PR, Comment
from openagents.recipes import poll_comments as pc_module
from openagents.recipes.poll_comments import poll_comments
from openagents.runtime.state import RuntimeState


class _ReplierBackend:
    """假 backend：按 replier 的 task 文本回 canned 末行 JSON。

    task 含被回应评论正文；正文里带 "RESOLVED" → resolved=true，否则 false。据此驱动两条 reason 路由。
    """

    name = "replier-fake"

    def __init__(self) -> None:
        self.tasks: list[str] = []

    def run(self, *, work_dir, task, context):
        self.tasks.append(task)
        resolved = "RESOLVED" in task
        return AgentResult(
            changed=False,
            summary=json.dumps({"reply": "已回应R", "resolved": resolved}),
        )


class _IdentityRecorder:
    """打桩 identity.new_human_comments / post_signed_comment，记录回帖以断言签名回复。"""

    def __init__(self, *, comments_by_pr) -> None:
        self._comments_by_pr = comments_by_pr
        self.posted: list[dict] = []

    def new_human_comments(self, *, pr_number, since):
        # 仅返回严于 since 游标的评论（模拟水位线语义）。
        return [c for c in self._comments_by_pr.get(pr_number, []) if c.created_at > since]

    def post_signed_comment(self, *, pr_number, body, agent_id):
        self.posted.append({"pr_number": pr_number, "body": body, "agent_id": agent_id})


def _patch(monkeypatch, *, prs, comments_by_pr, branch="openagents/issue-1"):
    monkeypatch.setattr(pc_module.github, "list_open_prs", lambda: list(prs))
    monkeypatch.setattr(pc_module.github, "pr_head_branch", lambda *, pr_number: branch)
    recorder = _IdentityRecorder(comments_by_pr=comments_by_pr)
    monkeypatch.setattr(pc_module.identity, "new_human_comments", recorder.new_human_comments)
    monkeypatch.setattr(pc_module.identity, "post_signed_comment", recorder.post_signed_comment)
    return recorder


def _comment(*, created_at, body):
    return Comment(id=created_at, author="curry", body=body, created_at=created_at)


def test_new_human_comment_replied_and_cursor_advances(monkeypatch, tmp_path):
    pr = PR(number=154, url="u")
    comment = _comment(created_at="2026-07-09T10:00", body="请补测试")
    recorder = _patch(monkeypatch, prs=[pr], comments_by_pr={154: [comment]})
    state = RuntimeState(path=tmp_path / "runtime-state.json")

    events = poll_comments(
        backend=_ReplierBackend(), state=state, agent_id="agent-A", work_dir=tmp_path
    )

    assert events == [{"pr_number": 154, "reason": "replied"}]
    # 盖签名回帖（body=replier 的 reply、带本实例 agent_id）。
    assert recorder.posted == [{"pr_number": 154, "body": "已回应R", "agent_id": "agent-A"}]
    # 游标推进到刚回应评论的 created_at（下轮不重复回）。
    assert state.get_cursor(pr_number=154) == "2026-07-09T10:00"


def test_resolved_verdict_reported(monkeypatch, tmp_path):
    pr = PR(number=154, url="u")
    comment = _comment(created_at="2026-07-09T11:00", body="搞定了吗 RESOLVED")
    _patch(monkeypatch, prs=[pr], comments_by_pr={154: [comment]})
    state = RuntimeState(path=tmp_path / "runtime-state.json")

    events = poll_comments(
        backend=_ReplierBackend(), state=state, agent_id="agent-A", work_dir=tmp_path
    )

    assert events == [{"pr_number": 154, "reason": "resolved"}]


def test_no_new_comments_is_noop(monkeypatch, tmp_path):
    pr = PR(number=154, url="u")
    recorder = _patch(monkeypatch, prs=[pr], comments_by_pr={154: []})
    state = RuntimeState(path=tmp_path / "runtime-state.json")

    events = poll_comments(
        backend=_ReplierBackend(), state=state, agent_id="agent-A", work_dir=tmp_path
    )

    assert events == []
    assert recorder.posted == []
    assert state.get_cursor(pr_number=154) is None


def test_cursor_filters_already_processed(monkeypatch, tmp_path):
    # 游标已到 latest → new_human_comments 过滤掉不新的评论 → 本轮 no-op。
    pr = PR(number=154, url="u")
    comment = _comment(created_at="2026-07-09T09:00", body="旧评论")
    _patch(monkeypatch, prs=[pr], comments_by_pr={154: [comment]})
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    state.set_cursor(pr_number=154, comment_id="2026-07-09T09:00")

    events = poll_comments(
        backend=_ReplierBackend(), state=state, agent_id="agent-A", work_dir=tmp_path
    )

    assert events == []


def test_only_latest_comment_replied(monkeypatch, tmp_path):
    # 多条积压：只回应最新一条，游标一次推进到它。
    pr = PR(number=154, url="u")
    comments = [
        _comment(created_at="2026-07-09T08:00", body="第一条"),
        _comment(created_at="2026-07-09T09:00", body="最新一条"),
    ]
    recorder = _patch(monkeypatch, prs=[pr], comments_by_pr={154: comments})
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    backend = _ReplierBackend()

    events = poll_comments(backend=backend, state=state, agent_id="agent-A", work_dir=tmp_path)

    assert events == [{"pr_number": 154, "reason": "replied"}]
    assert len(recorder.posted) == 1
    assert "最新一条" in backend.tasks[0]  # 派给 replier 的是最新一条评论正文
    assert state.get_cursor(pr_number=154) == "2026-07-09T09:00"


def test_single_pr_failure_isolated(monkeypatch, tmp_path):
    # 一个 PR 处理抛异常（pr_head_branch 炸）→ 记 error 事件 + continue，另一个 PR 照常回应。
    prs = [PR(number=1, url="u1"), PR(number=2, url="u2")]
    comments_by_pr = {
        1: [_comment(created_at="2026-07-09T10:00", body="PR1 评论")],
        2: [_comment(created_at="2026-07-09T10:00", body="PR2 评论")],
    }
    recorder = _patch(monkeypatch, prs=prs, comments_by_pr=comments_by_pr)

    def _boom(*, pr_number):
        if pr_number == 1:
            raise RuntimeError("gh 炸了")
        return "openagents/issue-2"

    monkeypatch.setattr(pc_module.github, "pr_head_branch", _boom)
    state = RuntimeState(path=tmp_path / "runtime-state.json")

    events = poll_comments(
        backend=_ReplierBackend(), state=state, agent_id="agent-A", work_dir=tmp_path
    )

    # PR1 记 error 事件、PR2 正常回应——异常隔离，不掀翻整轮。
    assert {"pr_number": 1, "reason": "error", "error": "gh 炸了"} in events
    assert {"pr_number": 2, "reason": "replied"} in events
    assert [p["pr_number"] for p in recorder.posted] == [2]
