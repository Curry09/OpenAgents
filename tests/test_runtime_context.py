"""Spec-0060/T5: runtime.context + runtime.state 单测。

context：各阶段占位符 dict 键齐全、issue 正文/PR 历史经 utils.github 注入（打桩、不触网）。
state：读写走独立命名空间文件 runtime-state.json，与旧 state.json 文件级零冲突。
"""

from __future__ import annotations

from pathlib import Path

from openagents.github import Comment, Issue
from openagents.runtime import context as context_module
from openagents.runtime.context import Context
from openagents.runtime.state import RUNTIME_STATE_FILENAME, RuntimeState


def _stub_github(monkeypatch, *, issue, comments):
    monkeypatch.setattr(context_module.github, "get_issue", lambda *, number: issue)
    monkeypatch.setattr(context_module.github, "list_comments", lambda *, pr_number: comments)


def _ctx(*, pr_number):
    return Context(
        work_dir=Path("/tmp/wt"),
        issue_number=145,
        branch="openagents/issue-145",
        pr_number=pr_number,
    )


def test_for_plan_keys(monkeypatch):
    _stub_github(monkeypatch, issue=Issue(number=145, title="重构", body="正文X"), comments=[])
    payload = _ctx(pr_number=154).for_plan(issue_number=145)
    assert payload["work_dir"] == Path("/tmp/wt")
    assert payload["issue_number"] == 145
    assert payload["issue_body"] == "正文X"
    assert "正文X" in payload["context"]


def test_for_implement_and_iterate_feedback(monkeypatch):
    _stub_github(monkeypatch, issue=Issue(number=145, title="t", body="b"), comments=[])
    ctx = _ctx(pr_number=154)
    impl = ctx.for_implement(issue_number=145)
    assert impl["feedback"] == ""
    assert impl["pr_number"] == 154
    itr = ctx.for_iterate(issue_number=145, feedback="补测试")
    assert itr["feedback"] == "补测试"


def test_for_review_injects_pr_history(monkeypatch):
    comments = [Comment(id="1", author="curry", body="改这里", created_at="2026-07-09")]
    _stub_github(monkeypatch, issue=Issue(number=145, title="t", body="b"), comments=comments)
    payload = _ctx(pr_number=154).for_review(issue_number=145)
    assert payload["pr_number"] == 154
    assert "改这里" in payload["context"]
    assert "@curry" in payload["context"]


def test_for_deliver_keys():
    payload = _ctx(pr_number=154).for_deliver(issue_number=145)
    assert payload["branch"] == "openagents/issue-145"
    assert payload["pr_number"] == 154


def test_workspace_property():
    assert _ctx(pr_number=None).workspace == Path("/tmp/wt")


def test_review_context_without_pr(monkeypatch):
    # 无 PR 号：只给 issue 上下文，不调 list_comments。
    _stub_github(monkeypatch, issue=Issue(number=145, title="t", body="b"), comments=[])
    payload = _ctx(pr_number=None).for_review(issue_number=145)
    assert "PR #" not in payload["context"]


def test_runtime_state_roundtrip_independent_namespace(tmp_path):
    path = tmp_path / ".openagents" / RUNTIME_STATE_FILENAME
    state = RuntimeState(path=path)
    assert state.get_run(issue_number=145) is None
    state.set_run(issue_number=145, status="solving", branch="openagents/issue-145", pr_number=154)
    got = state.get_run(issue_number=145)
    assert got == {"status": "solving", "branch": "openagents/issue-145", "pr_number": 154}
    state.set_cursor(pr_number=154, comment_id="c-9")
    assert state.get_cursor(pr_number=154) == "c-9"
    # 独立命名空间：文件名是 runtime-state.json，不是旧 state.json。
    assert path.name == "runtime-state.json"
    assert path.exists()


def test_runtime_state_tolerates_corrupt_file(tmp_path):
    path = tmp_path / RUNTIME_STATE_FILENAME
    path.write_text("{not json", encoding="utf-8")
    state = RuntimeState(path=path)
    assert state.get_run(issue_number=1) is None  # 损坏视为空状态、不抛
