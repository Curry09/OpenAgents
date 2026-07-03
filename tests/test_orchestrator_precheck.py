"""Spec-0043/T3：orchestrator.precheck_issue 的单元测试。

github.* 一律 mock、backend 注入桩；聚焦「命中冲突 → 冻结（署名对齐评论 + needs-human）+
返回 True、全程不建 worktree/begin_run」与「自洽 → 返回 False、无评论无标签」。
"""

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import Issue
from openagents.state import State

_CONFLICT_SUMMARY = (
    "冲突：是\n"
    "冲突点：标题主张按 commit sha 缓存；正文主张 hold-merge 冻结。\n"
    "候选修法：按 commit sha 缓存评审结论\n"
    "候选修法：hold-merge 冻结 PR\n"
)


class _StubBackend:
    name = "stub"

    def __init__(self, *, summary):
        self.calls = 0
        self._summary = summary

    def run(self, *, work_dir, task, context):
        self.calls += 1
        return AgentResult(changed=False, summary=self._summary)


def _make(tmp_path, *, summary):
    backend = _StubBackend(summary=summary)
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = orch_module.Orchestrator(
        backend=backend, state=state, work_dir=tmp_path, agent_id="agent-x"
    )
    return orch, state, backend


def _patch_github(monkeypatch, *, title, body):
    calls = {"comment": [], "add_label": []}
    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title=title, body=body),
    )
    monkeypatch.setattr(
        orch_module.github,
        "issue_comment",
        lambda *, number, body: calls["comment"].append((number, body)),
    )
    monkeypatch.setattr(
        orch_module.github,
        "issue_add_label",
        lambda *, number, name: calls["add_label"].append((number, name)),
    )
    return calls


def test_precheck_freezes_conflicting_issue(tmp_path, monkeypatch):
    orch, state, backend = _make(tmp_path, summary=_CONFLICT_SUMMARY)
    calls = _patch_github(monkeypatch, title="标题主张 A", body="正文主张互斥的 B")

    result = orch.precheck_issue(issue_number=106)

    assert result is True
    # 恰贴一条署名对齐评论。
    assert len(calls["comment"]) == 1
    number, comment_body = calls["comment"][0]
    assert number == 106
    assert "候选修法" in comment_body
    # 署名（identity.sign 追加的隐藏签名）在场，可溯源。
    assert "openagents:agent=agent-x" in comment_body
    # 不含 PR 级失败文案。
    assert "卡住了" not in comment_body
    # 打上 needs-human（= BLOCKED_LABEL）恰一次。
    assert calls["add_label"] == [(106, orch_module.github.BLOCKED_LABEL)]
    # 判读只调 backend 一次；全程未建 worktree / begin_run（无 run 记录落地）。
    assert backend.calls == 1
    assert state.find_by_issue(issue_number=106) is None


def test_precheck_passes_self_consistent_issue(tmp_path, monkeypatch):
    orch, state, backend = _make(tmp_path, summary="冲突：否")
    calls = _patch_github(monkeypatch, title="清晰的标题", body="与标题一致的正文")

    result = orch.precheck_issue(issue_number=200)

    assert result is False
    # 自洽 issue：零评论、零标签、零 run 记录（零打扰、零回归）。
    assert calls["comment"] == []
    assert calls["add_label"] == []
    assert state.find_by_issue(issue_number=200) is None


def test_precheck_fail_open_passes_on_garbled_verdict(tmp_path, monkeypatch):
    # backend 输出格式跑偏 → fail-open 放行（不误拦健康 issue）。
    orch, state, backend = _make(tmp_path, summary="嗯我觉得还行")
    calls = _patch_github(monkeypatch, title="t", body="b")

    assert orch.precheck_issue(issue_number=7) is False
    assert calls["comment"] == [] and calls["add_label"] == []
