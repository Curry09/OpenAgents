"""Spec-0064/T3: recipes.vigil run_vigil 策略路由 + 合并流水线打回回环单测。

证明架构契约：
- 策略路由（route 原语 + triage/review/ci/e2e/merge 三态）真按注入 config 的 owner 分 agent/human/skip 三支；
- 合并流水线定稿序 conflict→CI→e2e→review→merge，conflict 在读 CI 前先判 mergeable；
- CI/e2e/review 失败经统一回环派 implementer 迭代（返阶段事件，下轮从 conflict 重进）；
- 确定性硬闸（round_cap）不受 stages 关。
全程假 backend + 打桩 github/git，不触真实 LLM/网络/仓库。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from openagents.backends.base import AgentResult
from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import CLAIM_EXPIRY_SECONDS, _Run, discover_and_dispatch, route
from openagents.runtime.state import RuntimeState
from openagents.utils import agent_config
from openagents.utils.github import Comment, Issue
from openagents.utils.identity import build_claim_note

_NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)
SELF_ID = "agent-self"


def _stages(**owners):
    return agent_config.StagePolicy(owners=owners)


class _TriagerBackend:
    name = "triager-fake"

    def __init__(self):
        self.tasks: list[str] = []

    def run(self, *, work_dir, task, context):
        self.tasks.append(task)
        actionable = "PARK" not in task
        return AgentResult(
            changed=False, summary=json.dumps({"actionable": actionable, "reason": "R"})
        )


def _patch(monkeypatch, *, issues, remote_exists=False):
    monkeypatch.setattr(vigil_module.github, "list_issues", lambda *, labels: list(issues))
    monkeypatch.setattr(
        vigil_module.git, "remote_branch_exists", lambda *, work_dir, branch: remote_exists
    )
    recorder = {"labels": [], "comments": []}
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: recorder["labels"].append((number, name)),
    )
    monkeypatch.setattr(
        vigil_module.github,
        "issue_comment",
        lambda *, number, body: recorder["comments"].append((number, body)),
    )
    return recorder


def _discover(state, tmp_path, *, backend, stages, calls, agent_id=SELF_ID):
    def _dispatch(*, issue_number, base, backend, state, work_dir):
        calls.append({"issue_number": issue_number, "base": base})

    return discover_and_dispatch(
        backend=backend,
        state=state,
        work_dir=tmp_path,
        stages_policy=stages,
        labels=["openagents"],
        base="main",
        agent_id=agent_id,
        dispatch=_dispatch,
        now=_NOW,
        claim_expiry_seconds=CLAIM_EXPIRY_SECONDS,
    )


# ---- route 原语 ----


def test_route_three_states():
    assert (
        route(owner="agent", on_agent=lambda: "a", on_human=lambda: "h", on_skip=lambda: "s") == "a"
    )
    assert (
        route(owner="human", on_agent=lambda: "a", on_human=lambda: "h", on_skip=lambda: "s") == "h"
    )
    assert (
        route(owner="skip", on_agent=lambda: "a", on_human=lambda: "h", on_skip=lambda: "s") == "s"
    )


# ---- triage 三态路由 ----


def test_triage_agent_actionable_dispatches(monkeypatch, tmp_path):
    _patch(monkeypatch, issues=[Issue(number=1, title="t", body="ok")])
    state = RuntimeState(path=tmp_path / "s.json")
    calls = []
    dispatched = _discover(
        state, tmp_path, backend=_TriagerBackend(), stages=_stages(triage="agent"), calls=calls
    )
    assert dispatched == [1]
    assert calls == [{"issue_number": 1, "base": "main"}]


def test_triage_agent_non_actionable_parks(monkeypatch, tmp_path):
    rec = _patch(monkeypatch, issues=[Issue(number=1, title="t", body="矛盾 PARK")])
    state = RuntimeState(path=tmp_path / "s.json")
    calls = []
    dispatched = _discover(
        state, tmp_path, backend=_TriagerBackend(), stages=_stages(triage="agent"), calls=calls
    )
    assert dispatched == []
    assert calls == []
    assert rec["labels"] == [(1, vigil_module.github.BLOCKED_LABEL)]
    assert state.get_run(issue_number=1)["status"] == "blocked"


def test_triage_human_parks_without_calling_triager(monkeypatch, tmp_path):
    rec = _patch(monkeypatch, issues=[Issue(number=1, title="t", body="ok")])
    state = RuntimeState(path=tmp_path / "s.json")
    backend = _TriagerBackend()
    calls = []
    dispatched = _discover(
        state, tmp_path, backend=backend, stages=_stages(triage="human"), calls=calls
    )
    assert dispatched == []
    assert backend.tasks == []  # human：不派 triager，直接停等人
    assert rec["labels"] == [(1, vigil_module.github.BLOCKED_LABEL)]


def test_triage_skip_dispatches_without_calling_triager(monkeypatch, tmp_path):
    _patch(monkeypatch, issues=[Issue(number=1, title="t", body="ok")])
    state = RuntimeState(path=tmp_path / "s.json")
    backend = _TriagerBackend()
    calls = []
    dispatched = _discover(
        state, tmp_path, backend=backend, stages=_stages(triage="skip"), calls=calls
    )
    assert dispatched == [1]
    assert backend.tasks == []  # skip：跳过分诊直接派单


# ---- 去重四闸 ----


def test_dedup_local_run(monkeypatch, tmp_path):
    _patch(monkeypatch, issues=[Issue(number=1, title="t", body="b")])
    state = RuntimeState(path=tmp_path / "s.json")
    state.set_run(issue_number=1, status="solving", branch="openagents/issue-1", pr_number=None)
    backend = _TriagerBackend()
    calls = []
    assert (
        _discover(state, tmp_path, backend=backend, stages=_stages(triage="agent"), calls=calls)
        == []
    )
    assert backend.tasks == []


def test_dedup_remote_branch(monkeypatch, tmp_path):
    _patch(monkeypatch, issues=[Issue(number=1, title="t", body="b")], remote_exists=True)
    state = RuntimeState(path=tmp_path / "s.json")
    assert (
        _discover(
            state, tmp_path, backend=_TriagerBackend(), stages=_stages(triage="agent"), calls=[]
        )
        == []
    )


def test_dedup_blocked_label(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        issues=[Issue(number=1, title="t", body="b", labels=(vigil_module.github.BLOCKED_LABEL,))],
    )
    state = RuntimeState(path=tmp_path / "s.json")
    assert (
        _discover(
            state, tmp_path, backend=_TriagerBackend(), stages=_stages(triage="agent"), calls=[]
        )
        == []
    )


# ---- 认领归属闸 ----


def _iso(ago):
    return (_NOW - timedelta(seconds=ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _claim(owner, ago):
    return Comment(
        id="IC", author=owner, body=build_claim_note(agent_id=owner), created_at=_iso(ago)
    )


def test_claim_other_fresh_skipped(monkeypatch, tmp_path):
    issue = Issue(number=9, title="t", body="ok", labels=(vigil_module.github.DISPATCH_LABEL,))
    _patch(monkeypatch, issues=[issue])
    monkeypatch.setattr(
        vigil_module.github, "list_issue_comments", lambda *, number: [_claim("other", 5)]
    )
    state = RuntimeState(path=tmp_path / "s.json")
    assert (
        _discover(
            state, tmp_path, backend=_TriagerBackend(), stages=_stages(triage="agent"), calls=[]
        )
        == []
    )


def test_claim_other_expired_reclaimed(monkeypatch, tmp_path):
    issue = Issue(number=9, title="t", body="ok", labels=(vigil_module.github.DISPATCH_LABEL,))
    _patch(monkeypatch, issues=[issue])
    monkeypatch.setattr(
        vigil_module.github,
        "list_issue_comments",
        lambda *, number: [_claim("other", CLAIM_EXPIRY_SECONDS + 60)],
    )
    state = RuntimeState(path=tmp_path / "s.json")
    assert _discover(
        state, tmp_path, backend=_TriagerBackend(), stages=_stages(triage="agent"), calls=[]
    ) == [9]


def test_claim_query_error_conservative_skip(monkeypatch, tmp_path):
    issue = Issue(number=9, title="t", body="ok", labels=(vigil_module.github.DISPATCH_LABEL,))
    _patch(monkeypatch, issues=[issue])

    def _boom(*, number):
        raise vigil_module.github.GithubError("boom")

    monkeypatch.setattr(vigil_module.github, "list_issue_comments", _boom)
    state = RuntimeState(path=tmp_path / "s.json")
    assert (
        _discover(
            state, tmp_path, backend=_TriagerBackend(), stages=_stages(triage="agent"), calls=[]
        )
        == []
    )


# ---- 合并流水线：顺序 + 打回回环 ----


class _MergeBackend:
    """按 agent 自称回 canned；记录被派 agent 序，供断言打回回环真派 implementer。"""

    name = "merge-fake"

    def __init__(self, *, review="PASS"):
        self.calls: list[str] = []
        self._review = review

    def run(self, *, work_dir, task, context):
        if "实现 agent" in task:
            self.calls.append("implementer")
            return AgentResult(changed=True, summary=json.dumps({"summary": "iterated"}))
        if "评审 agent" in task:
            self.calls.append("reviewer")
            return AgentResult(
                changed=True, summary=json.dumps({"verdict": self._review, "reason": "r"})
            )
        raise AssertionError(task[:30])


def _clean_mergeability(monkeypatch):
    class _M:
        mergeable = "MERGEABLE"
        merge_state_status = "CLEAN"

    monkeypatch.setattr(vigil_module.github, "mergeability", lambda *, pr_number: _M())
    monkeypatch.setattr(vigil_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(vigil_module.github, "is_closed", lambda *, pr_number: False)


def _run():
    return _Run(pr_number=10, issue_number=5, branch="openagents/issue-5", status="open")


def test_conflict_checked_before_ci(monkeypatch, tmp_path):
    # mergeable=CONFLICTING → 走 conflict 分支，绝不读 CI（check_status 不应被调）。
    class _M:
        mergeable = "CONFLICTING"
        merge_state_status = "DIRTY"

    monkeypatch.setattr(vigil_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(vigil_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(vigil_module.github, "mergeability", lambda *, pr_number: _M())

    def _no_ci(*, pr_number):
        raise AssertionError("冲突未解不应读 CI")

    monkeypatch.setattr(vigil_module.stages, "ci", _no_ci)
    # conflict owner=human → 直接挂起（不派 deliver），验证走了 conflict 分支。
    state = RuntimeState(path=tmp_path / "s.json")
    event = vigil_module.advance_merge(
        backend=None,
        state=state,
        work_dir=tmp_path,
        stages_policy=_stages(conflict="human"),
        run=_run(),
        now=_NOW,
    )
    assert event["reason"] == "blocked"
    assert event["gate"] == "conflict"


def test_ci_fail_agent_retries_implementer(monkeypatch, tmp_path):
    _clean_mergeability(monkeypatch)
    monkeypatch.setattr(vigil_module.stages, "ci", lambda *, pr_number: vigil_module.stages.CI_FAIL)
    monkeypatch.setattr(vigil_module, "_ensure_pr_worktree", lambda *, work_dir, run: tmp_path)
    backend = _MergeBackend()
    state = RuntimeState(path=tmp_path / "s.json")
    event = vigil_module.advance_merge(
        backend=backend,
        state=state,
        work_dir=tmp_path,
        stages_policy=_stages(ci="agent"),
        run=_run(),
        now=_NOW,
    )
    # 打回回环：真派 implementer，返 ci 事件（下轮从 conflict 重进）。
    assert event["reason"] == "ci"
    assert backend.calls == ["implementer"]


def test_ci_fail_human_parks(monkeypatch, tmp_path):
    _clean_mergeability(monkeypatch)
    monkeypatch.setattr(vigil_module.stages, "ci", lambda *, pr_number: vigil_module.stages.CI_FAIL)
    state = RuntimeState(path=tmp_path / "s.json")
    event = vigil_module.advance_merge(
        backend=_MergeBackend(),
        state=state,
        work_dir=tmp_path,
        stages_policy=_stages(ci="human"),
        run=_run(),
        now=_NOW,
    )
    assert event["reason"] == "blocked"
    assert event["gate"] == "ci"
    assert state.get_run(issue_number=5)["status"] == "blocked"


def test_ci_skip_proceeds_to_review(monkeypatch, tmp_path):
    _clean_mergeability(monkeypatch)

    def _no_ci(*, pr_number):
        raise AssertionError("skip ci 不应读 check")

    monkeypatch.setattr(vigil_module.stages, "ci", _no_ci)
    monkeypatch.setattr(vigil_module.stages, "e2e", lambda *, pr_number: vigil_module.stages.E2E_OK)
    monkeypatch.setattr(
        vigil_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="t", body="b"),
    )
    merged = {}
    monkeypatch.setattr(
        vigil_module.stages, "merge", lambda *, pr_number: merged.setdefault("pr", pr_number)
    )
    monkeypatch.setattr(vigil_module.github, "close_issue", lambda *, number: None)
    backend = _MergeBackend(review="PASS")
    state = RuntimeState(path=tmp_path / "s.json")
    event = vigil_module.advance_merge(
        backend=backend,
        state=state,
        work_dir=tmp_path,
        stages_policy=_stages(ci="skip", e2e="agent", review="agent", merge="agent"),
        run=_run(),
        now=_NOW,
    )
    assert event["reason"] == "merged"
    assert merged["pr"] == 10
    assert backend.calls == ["reviewer"]  # 跳过 CI，直达 review


def test_review_rework_agent_retries(monkeypatch, tmp_path):
    _clean_mergeability(monkeypatch)
    monkeypatch.setattr(vigil_module.stages, "ci", lambda *, pr_number: vigil_module.stages.CI_PASS)
    monkeypatch.setattr(vigil_module.stages, "e2e", lambda *, pr_number: vigil_module.stages.E2E_OK)
    monkeypatch.setattr(
        vigil_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="t", body="b"),
    )
    monkeypatch.setattr(vigil_module, "_ensure_pr_worktree", lambda *, work_dir, run: tmp_path)
    backend = _MergeBackend(review="REWORK")
    state = RuntimeState(path=tmp_path / "s.json")
    event = vigil_module.advance_merge(
        backend=backend,
        state=state,
        work_dir=tmp_path,
        stages_policy=_stages(ci="agent", e2e="agent", review="agent"),
        run=_run(),
        now=_NOW,
    )
    assert event["reason"] == "review"
    assert backend.calls == ["reviewer", "implementer"]  # REWORK → 打回 implementer


def test_merge_human_holds(monkeypatch, tmp_path):
    _clean_mergeability(monkeypatch)
    monkeypatch.setattr(vigil_module.stages, "ci", lambda *, pr_number: vigil_module.stages.CI_PASS)
    monkeypatch.setattr(vigil_module.stages, "e2e", lambda *, pr_number: vigil_module.stages.E2E_OK)
    monkeypatch.setattr(
        vigil_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="t", body="b"),
    )

    def _no_merge(*, pr_number):
        raise AssertionError("merge:human 不应自动合")

    monkeypatch.setattr(vigil_module.stages, "merge", _no_merge)
    state = RuntimeState(path=tmp_path / "s.json")
    event = vigil_module.advance_merge(
        backend=_MergeBackend(review="PASS"),
        state=state,
        work_dir=tmp_path,
        stages_policy=_stages(review="agent", merge="human"),
        run=_run(),
        now=_NOW,
    )
    assert event["reason"] == "hold-merge"


def test_merged_terminal_short_circuits(monkeypatch, tmp_path):
    monkeypatch.setattr(vigil_module.github, "is_merged", lambda *, pr_number: True)
    monkeypatch.setattr(vigil_module.github, "close_issue", lambda *, number: None)
    state = RuntimeState(path=tmp_path / "s.json")
    event = vigil_module.advance_merge(
        backend=None, state=state, work_dir=tmp_path, stages_policy=_stages(), run=_run(), now=_NOW
    )
    assert event["reason"] == "merged"
    assert state.get_run(issue_number=5)["status"] == "done"


def test_merge_runs_projection(tmp_path):
    state = RuntimeState(path=tmp_path / "s.json")
    state.set_run(issue_number=5, status="done", branch="openagents/issue-5", pr_number=10)
    state.set_run(issue_number=6, status="solving", branch="openagents/issue-6", pr_number=None)
    state.set_run(issue_number=7, status="blocked", branch="openagents/issue-7", pr_number=20)
    runs = vigil_module._merge_runs(state=state)
    by_pr = {r.pr_number: r for r in runs}
    assert set(by_pr) == {10, 20}  # 无 pr_number 的跳过
    assert by_pr[10].status == "open"
    assert by_pr[20].status == "blocked"
