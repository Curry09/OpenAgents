"""Spec-0052/T3：orchestrator 四入口统一走 build_agent_context 的单元测试。

外部副作用注入：capturing backend（记录 task/context）+ monkeypatch github.list_comments
（内存评论账本）+ subprocess（Workspace git 走它）。覆盖：
- refine_rfc / implement 派给 backend 的 task 均含 PR 号（缺口一）；
- refine_rfc / implement / iterate 派给 backend 的 context 含本 PR 历史 + PR 号（缺口二）；
- _review 把历史经 reviewer.review(history=…) 送进 reviewer 的 backend context。
"""

import subprocess

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Comment
from openagents.state import State


class _CaptureBackend:
    """记录每次 run 的 task/context 的伪后端，按序返回预设 summary（默认恒 PASS）。"""

    name = "capture"

    def __init__(self, *, summaries=("VERDICT: PASS",)):
        self._summaries = list(summaries)
        self._index = 0
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        summary = self._summaries[self._index % len(self._summaries)]
        self._index += 1
        return AgentResult(changed=True, summary=summary)


class _GitRecorder:
    """subprocess.run 替身：记录 git 命令，评论查询回空 JSON（Workspace 不触真 git/gh）。"""

    def __init__(self):
        self.commands = []

    def __call__(self, args, **kwargs):
        self.commands.append(list(args))

        class _Proc:
            returncode = 0
            # Spec-0056/T2：交付后 harness 调 assert_delivered（rev-parse origin/<branch> 与 HEAD
            # 对比）；两处 rev-parse 回同一 SHA → head 前移硬闸放行（模拟 agent 已推上）。
            if "comments" in args:
                stdout = '{"comments": []}'
            elif "rev-parse" in args:
                stdout = "deadbeefcafe"
            else:
                stdout = ""
            stderr = ""

        return _Proc()


def _history_comments():
    """PR #128 式历史账本：历轮 reviewer FAIL 裁决 + 人类评论（供 build_agent_context 拉取）。"""
    return [
        Comment(
            id="1",
            author="reviewer-bot",
            body="## 评审闸裁决\n- 裁决：❌ REWORK\n- 反馈摘要：result.md 仍是 skipped\n\n"
            "<!-- openagents:agent=rev -->",
            created_at="2026-07-01T00:00:00Z",
        ),
        Comment(
            id="2",
            author="alice",
            body="人类补充：以文件真实内容为准",
            created_at="2026-07-02T00:00:00Z",
        ),
    ]


def _make(tmp_path, monkeypatch, *, backend):
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = orch_module.Orchestrator(
        backend=backend, state=state, work_dir=tmp_path, agent_id="agent-x"
    )
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    monkeypatch.setattr(
        orch_module.github, "list_comments", lambda *, pr_number: _history_comments()
    )
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    return orch, state


def test_refine_rfc_task_has_pr_number_and_context_has_history(tmp_path, monkeypatch):
    backend = _CaptureBackend()
    orch, _ = _make(tmp_path, monkeypatch, backend=backend)
    monkeypatch.setattr(orch_module.github, "post_comment", lambda *, pr_number, body: None)

    orch.refine_rfc(pr_number=5, detail="本轮评审意见Z", announce=False)

    call = backend.calls[0]
    assert "PR #5" in call["task"]  # 缺口一：PR 号进 task
    assert "本 PR 是 #5" in call["context"]  # 缺口二：context 带 PR 号
    assert "评审闸裁决" in call["context"]  # 历轮裁决进 context
    assert "人类补充：以文件真实内容为准" in call["context"]  # 人类评论进 context
    assert "本轮评审意见Z" in call["context"]  # 本轮反馈进 context


def test_implement_task_has_pr_number_and_context_has_history(tmp_path, monkeypatch):
    backend = _CaptureBackend()
    orch, _ = _make(tmp_path, monkeypatch, backend=backend)
    monkeypatch.setattr(orch_module.github, "mark_ready", lambda *, pr_number: None)

    orch.implement(pr_number=5)

    call = backend.calls[0]
    assert "PR #5" in call["task"]  # 缺口一：implement 模板补 PR 号
    assert "issue #3" in call["task"]  # issue 号线索保留
    assert "本 PR 是 #5" in call["context"]  # 缺口二：context 带 PR 号 + 历史
    assert "评审闸裁决" in call["context"]


def test_iterate_context_has_history_and_detail(tmp_path, monkeypatch):
    backend = _CaptureBackend()
    orch, _ = _make(tmp_path, monkeypatch, backend=backend)

    orch.iterate(pr_number=5, reason="ci", detail="CI 挂了：lint 报错")

    call = backend.calls[0]
    assert "本 PR 是 #5" in call["context"]
    assert "评审闸裁决" in call["context"]  # 历史进 context
    assert "CI 挂了：lint 报错" in call["context"]  # 本轮反馈进 context


def test_review_passes_history_into_reviewer_backend_context(tmp_path, monkeypatch):
    backend = _CaptureBackend(summaries=("VERDICT: PASS",))
    orch, _ = _make(tmp_path, monkeypatch, backend=backend)
    monkeypatch.setattr(
        orch_module.identity, "post_signed_comment", lambda *, pr_number, body, agent_id: None
    )

    decision = orch.review_code(pr_number=5)

    assert decision.passed is True
    # reviewer 经 review(history=…) 把历史送进它的 backend.run context。
    ctx = backend.calls[0]["context"]
    assert "本 PR 是 #5" in ctx
    assert "评审闸裁决" in ctx
    assert "人类补充：以文件真实内容为准" in ctx
