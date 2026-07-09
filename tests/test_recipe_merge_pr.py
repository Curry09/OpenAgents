"""Spec-0062/T2: recipes.merge_pr 合并流水线控制流单测——假 backend 喂 reviewer/deliver 裁决。

证明架构契约：merge_pr 只做「读 gates 客观判读 → 路由」纯控制流，自身零业务判断（能不能合是
reviewer 的活、冲突怎么解是 deliver 的活）；覆盖旧 messages.poll 的 reason 词表（merged/closed/
reopened/resolved/unmergeable/blocked/ci/e2e/review/synced/behind-conflict/hold-merge/skip-*/error），
hold/skip 对称短路；单 PR 失败错误隔离不拖垮整轮。全程假 backend + 打桩 github，不触真实 LLM/网络/仓库。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from openagents.backends.base import AgentResult
from openagents.github import PR, CheckStatus, GithubError, Issue, Mergeability
from openagents.recipes import merge_pr as mp
from openagents.recipes.merge_pr import Run, merge_pr
from openagents.runtime.state import RuntimeState
from openagents.utils.hold import Hold
from openagents.utils.skip import Skip

_CLEAN = Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN")
_DIRTY = Mergeability(mergeable="CONFLICTING", merge_state_status="DIRTY")
_BEHIND = Mergeability(mergeable="MERGEABLE", merge_state_status="BEHIND")
_UNKNOWN = Mergeability(mergeable="UNKNOWN", merge_state_status="UNKNOWN")
_CI_PASS = CheckStatus(state="pass", failed_logs=[])
_CI_FAIL = CheckStatus(state="fail", failed_logs=["build failed"])
_CI_PENDING = CheckStatus(state="pending", failed_logs=[])


class _Backend:
    """假 backend：按 task 里的 agent 抬头回 canned 末行 JSON（reviewer 判 verdict、deliver 判 delivered）。"""

    name = "merge-fake"

    def __init__(self, *, verdict="PASS", reason="需补测试", delivered=True) -> None:
        self._verdict = verdict
        self._reason = reason
        self._delivered = delivered
        self.tasks: list[str] = []

    def run(self, *, work_dir, task, context):
        self.tasks.append(task)
        if "交付 agent" in task:
            payload = {
                "delivered": self._delivered,
                "base_sha": "b0",
                "head_sha": "h1",
                "summary": "解冲突",
            }
        else:
            payload = {"verdict": self._verdict, "reason": self._reason}
        return AgentResult(changed=False, summary=json.dumps(payload, ensure_ascii=False))


class _Recorder:
    """记录 merge_pr / close_issue / update_branch 副作用调用，供断言。"""

    def __init__(self) -> None:
        self.merged: list[int] = []
        self.closed_issues: list[int] = []
        self.updated: list[int] = []


def _patch(monkeypatch, **over):
    """在 mp.github 上装默认桩（clean/绿/open/非 draft），按 over 覆盖；返回副作用 Recorder。"""
    g = mp.github
    rec = _Recorder()
    monkeypatch.setattr(g, "is_merged", over.get("is_merged", lambda *, pr_number: False))
    monkeypatch.setattr(g, "is_closed", over.get("is_closed", lambda *, pr_number: False))
    monkeypatch.setattr(g, "is_open", over.get("is_open", lambda *, pr_number: True))
    monkeypatch.setattr(g, "is_draft", over.get("is_draft", lambda *, pr_number: False))
    monkeypatch.setattr(g, "mergeability", over.get("mergeability", lambda *, pr_number: _CLEAN))
    monkeypatch.setattr(g, "check_status", over.get("check_status", lambda *, pr_number: _CI_PASS))
    monkeypatch.setattr(g, "pr_head_branch", lambda *, pr_number: "openagents/issue-1")
    monkeypatch.setattr(
        g, "get_issue", lambda *, number: Issue(number=number, title="t", body="issue 正文")
    )
    monkeypatch.setattr(g, "merge_pr", lambda *, pr_number: rec.merged.append(pr_number))
    monkeypatch.setattr(g, "close_issue", lambda *, number: rec.closed_issues.append(number))

    def _update(*, pr_number):
        rec.updated.append(pr_number)
        if over.get("update_conflict"):
            raise GithubError("update-branch 撞冲突")
        return True

    monkeypatch.setattr(g, "update_branch", _update)
    monkeypatch.setattr(g, "list_open_prs", over.get("list_open_prs", lambda: []))
    return rec


def _state(tmp_path):
    return RuntimeState(path=tmp_path / "runtime-state.json")


# ---------------------------------------------------------------------------------------------
# 终态 reconcile：merged / closed
# ---------------------------------------------------------------------------------------------


def test_merged_reconcile_marks_done_and_closes_issue(monkeypatch, tmp_path):
    rec = _patch(monkeypatch, is_merged=lambda *, pr_number: True)
    state = _state(tmp_path)
    run = Run(pr_number=42, issue_number=7, branch="openagents/issue-7")

    events = merge_pr(backend=_Backend(), state=state, agent_id="A", work_dir=tmp_path, runs=[run])

    assert events == [{"pr_number": 42, "reason": "merged"}]
    assert rec.closed_issues == [7]
    assert state.get_run(issue_number=7)["status"] == "done"


def test_closed_reconcile(monkeypatch, tmp_path):
    _patch(monkeypatch, is_closed=lambda *, pr_number: True)
    run = Run(pr_number=42, issue_number=7)

    events = merge_pr(
        backend=_Backend(), state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == [{"pr_number": 42, "reason": "closed"}]


# ---------------------------------------------------------------------------------------------
# 合并流水线：clean → CI → e2e → review → merge
# ---------------------------------------------------------------------------------------------


def test_clean_reviewer_pass_merges(monkeypatch, tmp_path):
    rec = _patch(monkeypatch)
    run = Run(pr_number=9)  # 无 issue 归属：reviewer issue_body 空、_mark_done 优雅降级。

    events = merge_pr(
        backend=_Backend(verdict="PASS"),
        state=_state(tmp_path),
        agent_id="A",
        work_dir=tmp_path,
        runs=[run],
    )

    assert events == [{"pr_number": 9, "reason": "merged"}]
    assert rec.merged == [9]


def test_reviewer_rework_returns_review(monkeypatch, tmp_path):
    rec = _patch(monkeypatch)
    run = Run(pr_number=9)

    events = merge_pr(
        backend=_Backend(verdict="REWORK", reason="补测试"),
        state=_state(tmp_path),
        agent_id="A",
        work_dir=tmp_path,
        runs=[run],
    )

    assert events == [{"pr_number": 9, "reason": "review", "feedback": "补测试"}]
    assert rec.merged == []  # 未通过评审绝不合并。


def test_ci_fail_returns_ci_before_review(monkeypatch, tmp_path):
    _patch(monkeypatch, check_status=lambda *, pr_number: _CI_FAIL)
    backend = _Backend()
    run = Run(pr_number=9)

    events = merge_pr(
        backend=backend, state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == [{"pr_number": 9, "reason": "ci"}]
    assert backend.tasks == []  # CI 红即短路，不白跑 reviewer。


def test_ci_pending_is_noop(monkeypatch, tmp_path):
    _patch(monkeypatch, check_status=lambda *, pr_number: _CI_PENDING)
    run = Run(pr_number=9)

    events = merge_pr(
        backend=_Backend(), state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == []


def test_e2e_evidence_stamp_mismatch_returns_e2e(monkeypatch, tmp_path):
    _patch(monkeypatch)
    # 证据自述 head 与实际 head 不匹配 → e2e 闸 FAIL → 本轮回去补 e2e。
    monkeypatch.setattr(mp, "_pr_evidence_stamp", lambda *, pr_number: ("head_now", "head_stale"))
    backend = _Backend()
    run = Run(pr_number=9)

    events = merge_pr(
        backend=backend, state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == [{"pr_number": 9, "reason": "e2e"}]
    assert backend.tasks == []  # 证据未就绪即短路，不进 review。


def test_e2e_evidence_stamp_match_proceeds(monkeypatch, tmp_path):
    rec = _patch(monkeypatch)
    monkeypatch.setattr(mp, "_pr_evidence_stamp", lambda *, pr_number: ("head_now", "head_now"))
    run = Run(pr_number=9)

    events = merge_pr(
        backend=_Backend(verdict="PASS"),
        state=_state(tmp_path),
        agent_id="A",
        work_dir=tmp_path,
        runs=[run],
    )

    assert events == [{"pr_number": 9, "reason": "merged"}]
    assert rec.merged == [9]


# ---------------------------------------------------------------------------------------------
# 可合并性：conflict（deliver 解）/ unknown / behind
# ---------------------------------------------------------------------------------------------


def test_conflict_resolved_by_deliver_agent(monkeypatch, tmp_path):
    _patch(monkeypatch, mergeability=lambda *, pr_number: _DIRTY)
    backend = _Backend(delivered=True)
    run = Run(pr_number=9, branch="openagents/issue-9")

    events = merge_pr(
        backend=backend, state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == [{"pr_number": 9, "reason": "resolved"}]
    assert any("交付 agent" in t for t in backend.tasks)  # 派了 deliver agent 去解冲突。


def test_conflict_deliver_fails_blocks(monkeypatch, tmp_path):
    _patch(monkeypatch, mergeability=lambda *, pr_number: _DIRTY)
    state = _state(tmp_path)
    run = Run(pr_number=9, issue_number=9, branch="openagents/issue-9")

    events = merge_pr(
        backend=_Backend(delivered=False), state=state, agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == [{"pr_number": 9, "reason": "blocked", "gate": "merge"}]
    assert state.get_run(issue_number=9)["status"] == "blocked"


def test_conflict_no_backend_unmergeable(monkeypatch, tmp_path):
    _patch(monkeypatch, mergeability=lambda *, pr_number: _DIRTY)
    state = _state(tmp_path)
    run = Run(pr_number=9, issue_number=9)

    events = merge_pr(backend=None, state=state, agent_id="A", work_dir=tmp_path, runs=[run])

    assert events == [{"pr_number": 9, "reason": "unmergeable"}]
    assert state.get_run(issue_number=9)["status"] == "blocked"


def test_mergeable_unknown_is_noop(monkeypatch, tmp_path):
    _patch(monkeypatch, mergeability=lambda *, pr_number: _UNKNOWN)
    run = Run(pr_number=9)

    events = merge_pr(
        backend=_Backend(), state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == []


def test_behind_synced(monkeypatch, tmp_path):
    rec = _patch(monkeypatch, mergeability=lambda *, pr_number: _BEHIND)
    run = Run(pr_number=9)

    events = merge_pr(
        backend=_Backend(), state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == [{"pr_number": 9, "reason": "synced"}]
    assert rec.updated == [9]


def test_behind_conflict(monkeypatch, tmp_path):
    _patch(monkeypatch, mergeability=lambda *, pr_number: _BEHIND, update_conflict=True)
    run = Run(pr_number=9)

    events = merge_pr(
        backend=_Backend(), state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == [{"pr_number": 9, "reason": "behind-conflict"}]


# ---------------------------------------------------------------------------------------------
# closed-run 复活窗口 / reopened
# ---------------------------------------------------------------------------------------------


def test_reopened_revives_open_pr(monkeypatch, tmp_path):
    _patch(monkeypatch, is_open=lambda *, pr_number: True, is_draft=lambda *, pr_number: False)
    state = _state(tmp_path)
    recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    run = Run(
        pr_number=9, issue_number=9, branch="openagents/issue-9", status="closed", closed_at=recent
    )

    events = merge_pr(backend=_Backend(), state=state, agent_id="A", work_dir=tmp_path, runs=[run])

    assert events == [{"pr_number": 9, "reason": "reopened", "stage": "pr-open"}]
    assert state.get_run(issue_number=9)["status"] == "open"


def test_revive_window_expired_is_noop(monkeypatch, tmp_path):
    _patch(monkeypatch)
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    run = Run(pr_number=9, issue_number=9, status="closed", closed_at=old)

    events = merge_pr(
        backend=_Backend(), state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == []  # 超复活窗口：硬化真终态、不发 gh。


def test_revive_candidate_still_closed_is_noop(monkeypatch, tmp_path):
    _patch(monkeypatch, is_open=lambda *, pr_number: False)
    recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    run = Run(pr_number=9, issue_number=9, status="closed", closed_at=recent)

    events = merge_pr(
        backend=_Backend(), state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == []  # 窗口内但 PR 仍非 OPEN：保持跳过、不重打戳。


# ---------------------------------------------------------------------------------------------
# blocked 短路
# ---------------------------------------------------------------------------------------------


def test_blocked_run_short_circuits(monkeypatch, tmp_path):
    _patch(monkeypatch)
    backend = _Backend()
    run = Run(pr_number=9, issue_number=9, status="blocked")

    events = merge_pr(
        backend=backend, state=_state(tmp_path), agent_id="A", work_dir=tmp_path, runs=[run]
    )

    assert events == []  # blocked 软挂起：merge_pr 不重跑闸（解挂是 replier 的活）。
    assert backend.tasks == []


# ---------------------------------------------------------------------------------------------
# hold / skip 对称短路
# ---------------------------------------------------------------------------------------------


def test_hold_merge_freezes_instead_of_merging(monkeypatch, tmp_path):
    rec = _patch(monkeypatch)
    run = Run(pr_number=9)

    events = merge_pr(
        backend=_Backend(verdict="PASS"),
        state=_state(tmp_path),
        agent_id="A",
        work_dir=tmp_path,
        runs=[run],
        hold=Hold(at_merge=True),
    )

    assert events == [{"pr_number": 9, "reason": "hold-merge"}]
    assert rec.merged == []  # hold-merge：过评审仍不自动合并、夯住等人。


def test_skip_ci_bypasses_red_ci(monkeypatch, tmp_path):
    rec = _patch(monkeypatch)

    def _boom(*, pr_number):
        raise AssertionError("skip.at_ci 命中不应再读 CI")

    monkeypatch.setattr(mp.github, "check_status", _boom)
    run = Run(pr_number=9)

    events = merge_pr(
        backend=_Backend(verdict="PASS"),
        state=_state(tmp_path),
        agent_id="A",
        work_dir=tmp_path,
        runs=[run],
        skip=Skip(at_ci=True),
    )

    assert events == [{"pr_number": 9, "reason": "merged"}]
    assert rec.merged == [9]


def test_skip_code_bypasses_reviewer(monkeypatch, tmp_path):
    rec = _patch(monkeypatch)
    backend = _Backend()
    run = Run(pr_number=9)

    events = merge_pr(
        backend=backend,
        state=_state(tmp_path),
        agent_id="A",
        work_dir=tmp_path,
        runs=[run],
        skip=Skip(at_code=True),
    )

    assert events == [{"pr_number": 9, "reason": "merged"}]
    assert rec.merged == [9]
    assert backend.tasks == []  # skip.at_code：不派 reviewer，直接放行合并。


def test_skip_code_with_hold_merge_freezes(monkeypatch, tmp_path):
    rec = _patch(monkeypatch)
    run = Run(pr_number=9)

    events = merge_pr(
        backend=_Backend(),
        state=_state(tmp_path),
        agent_id="A",
        work_dir=tmp_path,
        runs=[run],
        skip=Skip(at_code=True),
        hold=Hold(at_merge=True),
    )

    assert events == [{"pr_number": 9, "reason": "skip-code"}]
    assert rec.merged == []


# ---------------------------------------------------------------------------------------------
# 错误隔离 + 默认迭代源
# ---------------------------------------------------------------------------------------------


def test_single_pr_failure_isolated(monkeypatch, tmp_path):
    def _boom(*, pr_number):
        if pr_number == 1:
            raise RuntimeError("gh 炸了")
        return False

    rec = _patch(monkeypatch, is_merged=_boom)
    runs = [Run(pr_number=1), Run(pr_number=2)]

    events = merge_pr(
        backend=_Backend(verdict="PASS"),
        state=_state(tmp_path),
        agent_id="A",
        work_dir=tmp_path,
        runs=runs,
    )

    assert {"pr_number": 1, "reason": "error", "error": "gh 炸了"} in events
    assert {"pr_number": 2, "reason": "merged"} in events
    assert rec.merged == [2]  # PR1 抛异常隔离、PR2 照常推进。


def test_default_runs_from_list_open_prs(monkeypatch, tmp_path):
    rec = _patch(monkeypatch, list_open_prs=lambda: [PR(number=5, url="u")])

    events = merge_pr(
        backend=_Backend(verdict="PASS"), state=_state(tmp_path), agent_id="A", work_dir=tmp_path
    )

    assert events == [{"pr_number": 5, "reason": "merged"}]
    assert rec.merged == [5]  # runs=None → 默认从 github.list_open_prs 派生迭代源。
