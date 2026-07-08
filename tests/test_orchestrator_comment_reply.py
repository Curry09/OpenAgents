"""Spec-0036/T4：orchestrator 原子操作回传 summary + 人类解挂 prompt + announce 开关单测。

外部副作用全部注入/monkeypatch（backend / github / git subprocess），hermetic（不触网、不调真实
LLM/gh）。覆盖：
- refine_rfc / iterate 回传 agent 本轮动作的 summary 字符串；
- iterate(reason="human") 走人类解挂专属 task（含「正面回应」框定，且不同于 ci/review）；
- refine_rfc(announce=False) 不广播 _REFINE_COMMENT；announce=True（默认）仍广播（零回归）；
- ci/review 闸既有调用方（忽略返回值）行为不变。
"""

import subprocess

import pytest

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR
from openagents.orchestrator import Orchestrator
from openagents.state import State


class _FakeBackend:
    """记录 run 调用参数的伪后端，返回可定制 summary。"""

    name = "fake"

    def __init__(self, *, summary="本轮动作摘要"):
        self.calls = []
        self._result = AgentResult(changed=True, summary=summary)

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        return self._result


class _GitRecorder:
    def __init__(self):
        self.commands = []

    def __call__(self, args, **kwargs):
        self.commands.append(list(args))

        class _Proc:
            returncode = 0
            # Spec-0056/T2：交付后 harness 调 assert_delivered（rev-parse origin/<branch> 与 HEAD
            # 对比）；两处 rev-parse 回同一 SHA → head 前移硬闸放行（模拟 agent 已推上）。
            stdout = "deadbeefcafe" if "rev-parse" in args else ""
            stderr = ""

        return _Proc()


def _make(tmp_path, *, backend=None, agent_id="agent-x"):
    backend = backend or _FakeBackend()
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = Orchestrator(backend=backend, state=state, work_dir=tmp_path, agent_id=agent_id)
    return orch, backend, state


def _record(state, *, pr_number=5):
    state.record_run(
        issue_number=3, branch="openagents/issue-3", pr=PR(number=pr_number, url="u/pull/5")
    )


# --------------------------------------------------------------------------- #
# refine_rfc：回传 summary + announce 开关
# --------------------------------------------------------------------------- #


def test_refine_rfc_returns_summary(tmp_path, monkeypatch):
    backend = _FakeBackend(summary="已据评审补全权衡章节")
    orch, _, state = _make(tmp_path, backend=backend)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _record(state)
    monkeypatch.setattr(orch_module.github, "post_comment", lambda *, pr_number, body: None)

    summary = orch.refine_rfc(pr_number=5, detail="请补充权衡章节")

    assert summary == "已据评审补全权衡章节"


def test_refine_rfc_announce_true_posts_broadcast(tmp_path, monkeypatch):
    # 默认 announce=True：仍回贴泛化 _REFINE_COMMENT 广播（reviewer 驱动路径零回归）。
    orch, _, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _record(state)
    posted = []
    monkeypatch.setattr(
        orch_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(body),
    )

    orch.refine_rfc(pr_number=5, detail="x")

    assert len(posted) == 1
    assert "已根据评审意见更新 spec" in posted[0]


def test_refine_rfc_announce_false_suppresses_broadcast(tmp_path, monkeypatch):
    # announce=False（人类解挂路径）：不调 post_signed_comment 广播——回应由 messages 统一贴。
    orch, _, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _record(state)
    posted = []
    monkeypatch.setattr(
        orch_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(body),
    )

    summary = orch.refine_rfc(pr_number=5, detail="x", announce=False)

    assert posted == []  # 零广播
    assert summary == "本轮动作摘要"  # 仍回传 summary
    # 状态仍维持 rfc-review（announce 只控广播，不动状态流转）。
    assert state.all_runs()[0].status == "rfc-review"


# --------------------------------------------------------------------------- #
# iterate：回传 summary + reason="human" 专属 prompt
# --------------------------------------------------------------------------- #


def test_iterate_returns_summary(tmp_path, monkeypatch):
    backend = _FakeBackend(summary="已修复 typo")
    orch, _, state = _make(tmp_path, backend=backend)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _record(state)

    summary = orch.iterate(pr_number=5, reason="comment", detail="fix typo")

    assert summary == "已修复 typo"


def test_iterate_human_prompt_frames_reply(tmp_path, monkeypatch):
    # reason="human" 的 task 含「正面回应这条评论」框定 + detail。
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _record(state)

    orch.iterate(pr_number=5, reason="human", detail="别动 messages，先补测试")

    task = backend.calls[0]["task"]
    assert "正面回应这条评论" in task
    assert "挂起评论" in task
    assert "别动 messages，先补测试" in task


def test_iterate_human_prompt_differs_from_ci_and_review(tmp_path, monkeypatch):
    # 人类解挂专属 prompt 不同于 ci / review 的泛化反馈模板。
    orch, backend, state = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    _record(state)

    orch.iterate(pr_number=5, reason="human", detail="D")
    orch.iterate(pr_number=5, reason="ci", detail="D")
    orch.iterate(pr_number=5, reason="review", detail="D")

    human_task = backend.calls[0]["task"]
    ci_task = backend.calls[1]["task"]
    review_task = backend.calls[2]["task"]
    assert human_task != ci_task
    assert human_task != review_task
    # ci / review 仍走泛化反馈模板（含 reason 字样），逐字节同今天。
    assert "针对 PR #5 的ci反馈" in ci_task
    assert "针对 PR #5 的review反馈" in review_task
    # 人类解挂 prompt 不含泛化「反馈，请继续修改」开头（区分两类）。
    assert "正面回应这条评论" in human_task


def test_iterate_ci_caller_ignoring_return_unaffected(tmp_path, monkeypatch):
    # ci 闸既有调用方忽略返回值，行为不变：置 iterating + 交付走 head 前移硬闸。
    # Spec-0056/T2：交付下放 agent——harness 不再自著 commit/push，改调 assert_delivered（rev-parse 对比）。
    orch, _, state = _make(tmp_path)
    recorder = _GitRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    _record(state)

    orch.iterate(pr_number=5, reason="ci", detail="CI failed")

    assert state.all_runs()[0].status == "iterating"
    joined = [" ".join(c) for c in recorder.commands]
    assert any("rev-parse origin/openagents/issue-3" in c for c in joined)
    assert any("rev-parse HEAD" in c for c in joined)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
