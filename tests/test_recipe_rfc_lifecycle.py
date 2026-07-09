"""Spec-0062/T1: recipes.rfc_lifecycle 五入口控制流单测——假 backend 喂 drafter canned 裁决。

证明架构契约：draft/backfill/refine/implement/iterate 五 recipe 只做「派 drafter → 按裁决走确定性
兜底动作（认领标签 / 开·转正 PR / 贴公告 / 落 run 状态）」纯控制流，自身零业务判断（spec 正文怎么写、
如何交付是 drafter 的活）；三道确定性硬闸（head 前移 / 证据溯源戳）真能兜底。全程假 backend + 打桩
github/identity/gates/worktree，不触真实 LLM/网络/仓库。
"""

from __future__ import annotations

import json

import pytest

from openagents.backends.base import AgentResult
from openagents.github import PR, Issue
from openagents.recipes import rfc_lifecycle as rl
from openagents.runtime.gates import GateError


class _DrafterBackend:
    """假 backend：回 drafter 的 canned 末行 JSON（delivered/head_sha/summary），记录收到的 task。"""

    name = "drafter-fake"

    def __init__(self, *, delivered=True, head_sha="MOVED", summary="做了X"):
        self._delivered = delivered
        self._head_sha = head_sha
        self._summary = summary
        self.tasks: list[str] = []

    def run(self, *, work_dir, task, context):
        self.tasks.append(task)
        return AgentResult(
            changed=True,
            summary=json.dumps(
                {"delivered": self._delivered, "head_sha": self._head_sha, "summary": self._summary}
            ),
        )


class _FakeState:
    """最简 RuntimeState 替身：按 issue_number 存 run，支持 by-pr 查询（find_run）。"""

    def __init__(self) -> None:
        self.runs: dict[int, dict] = {}

    def set_run(self, *, issue_number, status, branch, pr_number):
        self.runs[issue_number] = {
            "issue_number": issue_number,
            "status": status,
            "branch": branch,
            "pr_number": pr_number,
        }

    def get_run(self, *, issue_number):
        return self.runs.get(issue_number)

    def find_run(self, *, pr_number):
        for record in self.runs.values():
            if record.get("pr_number") == pr_number:
                return record
        return None


class _GithubRecorder:
    """记录 rfc_lifecycle 对 github 写侧（标签 / 评论 / 建 PR / 转正）的调用，供路由断言。"""

    def __init__(self, *, issue=None, pr=None) -> None:
        self._issue = issue or Issue(number=145, title="重构", body="issue 正文")
        self._pr = pr or PR(number=154, url="u")
        self.added_labels: list[tuple[int, str]] = []
        self.removed_labels: list[tuple[int, str]] = []
        self.comments: list[tuple[int, str]] = []
        self.created_prs: list[dict] = []
        self.marked_ready: list[int] = []

    def get_issue(self, *, number):
        return self._issue

    def create_pr(self, *, branch, base, title, body, draft):
        self.created_prs.append(
            {"branch": branch, "base": base, "title": title, "body": body, "draft": draft}
        )
        return self._pr

    def mark_ready(self, *, pr_number):
        self.marked_ready.append(pr_number)

    def issue_add_label(self, *, number, name):
        self.added_labels.append((number, name))

    def issue_remove_label(self, *, number, name):
        self.removed_labels.append((number, name))

    def issue_comment(self, *, number, body):
        self.comments.append((number, body))


def _patch(monkeypatch, *, recorder, head_values=("BASE", "MOVED")):
    """打桩 github 写侧、identity 签名、gates.git.head_sha 序列、worktree 建/拉（不触真 git/网络）。"""
    monkeypatch.setattr(rl.github, "get_issue", recorder.get_issue)
    monkeypatch.setattr(rl.github, "create_pr", recorder.create_pr)
    monkeypatch.setattr(rl.github, "mark_ready", recorder.mark_ready)
    monkeypatch.setattr(rl.github, "issue_add_label", recorder.issue_add_label)
    monkeypatch.setattr(rl.github, "issue_remove_label", recorder.issue_remove_label)
    monkeypatch.setattr(rl.github, "issue_comment", recorder.issue_comment)

    posted: list[dict] = []
    monkeypatch.setattr(rl.identity, "build_claim_note", lambda *, agent_id: f"[claim {agent_id}]")
    monkeypatch.setattr(
        rl.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(
            {"pr_number": pr_number, "body": body, "agent_id": agent_id}
        ),
    )

    # gates.git.head_sha 按调用序返回（snapshot=交付前、assert=交付后），耗尽后钉末值——区分前后 head。
    seq = list(head_values)
    box = {"last": seq[-1] if seq else ""}

    def _head(*, work_dir):
        if seq:
            box["last"] = seq.pop(0)
        return box["last"]

    monkeypatch.setattr(rl.gates.git, "head_sha", _head)
    # worktree 建/拉替免真 git——只返回一个路径给 engine 当 work_dir。
    monkeypatch.setattr(rl, "prepare_worktree", lambda **kw: "/tmp/wt")
    monkeypatch.setattr(rl, "ensure_worktree", lambda **kw: "/tmp/wt")
    return posted


def test_draft_rfc_claims_drafts_and_opens_draft_pr(monkeypatch):
    recorder = _GithubRecorder()
    _patch(monkeypatch, recorder=recorder)
    state = _FakeState()
    backend = _DrafterBackend(summary="草稿完成")

    event = rl.draft_rfc(
        issue_number=145, backend=backend, state=state, work_dir="/tmp", agent_id="agent-A"
    )

    # 认领：打 DISPATCH_LABEL + 贴署名认领便签；开出后摘标签。
    assert (145, rl.github.DISPATCH_LABEL) in recorder.added_labels
    assert recorder.comments == [(145, "[claim agent-A]")]
    assert (145, rl.github.DISPATCH_LABEL) in recorder.removed_labels
    # 开 draft PR（Closes #145、draft=True）。
    assert len(recorder.created_prs) == 1
    assert recorder.created_prs[0]["draft"] is True
    assert "Closes #145" in recorder.created_prs[0]["body"]
    # run 落 rfc-review（含 pr 号）。
    run = state.get_run(issue_number=145)
    assert run["status"] == "rfc-review"
    assert run["pr_number"] == 154
    assert event == {"pr_number": 154, "reason": "drafted", "summary": "草稿完成"}
    # 派给 drafter 的 task 是 draft 模式。
    assert "mode=draft" in backend.tasks[0]


def test_backfill_rfc_opens_pr_when_delivered(monkeypatch):
    recorder = _GithubRecorder(pr=PR(number=200, url="u"))
    _patch(monkeypatch, recorder=recorder)
    state = _FakeState()
    backend = _DrafterBackend(summary="反推完成")

    event = rl.backfill_rfc(
        path="openagents/foo", backend=backend, state=state, work_dir="/tmp", agent_id="agent-A"
    )

    assert event == {"pr_number": 200, "reason": "backfilled", "summary": "反推完成"}
    assert recorder.created_prs[0]["title"] == "docs: backfill spec for openagents/foo"
    assert recorder.created_prs[0]["branch"] == "openagents/backfill-openagents-foo"
    assert "mode=backfill" in backend.tasks[0]


def test_backfill_rfc_not_delivered_raises_and_opens_no_pr(monkeypatch):
    # validate 门控：drafter 自述未交付（未过 spec validate）→ 抛 RfcLifecycleError、不开 PR。
    recorder = _GithubRecorder()
    _patch(monkeypatch, recorder=recorder)
    state = _FakeState()
    backend = _DrafterBackend(delivered=False)

    with pytest.raises(rl.RfcLifecycleError):
        rl.backfill_rfc(
            path="openagents/foo", backend=backend, state=state, work_dir="/tmp", agent_id="agent-A"
        )
    assert recorder.created_prs == []


def test_refine_rfc_posts_announce_and_keeps_rfc_review(monkeypatch):
    recorder = _GithubRecorder()
    posted = _patch(monkeypatch, recorder=recorder)
    state = _FakeState()
    state.set_run(
        issue_number=145, status="rfc-review", branch="openagents/issue-145", pr_number=154
    )
    backend = _DrafterBackend(summary="改了 Motivation")

    event = rl.refine_rfc(
        pr_number=154,
        detail="请补背景",
        backend=backend,
        state=state,
        work_dir="/tmp",
        agent_id="agent-A",
    )

    # announce=True（默认）→ 盖签名回贴公告评论，正文含摘要。
    assert len(posted) == 1
    assert "改了 Motivation" in posted[0]["body"]
    assert posted[0]["agent_id"] == "agent-A"
    assert state.get_run(issue_number=145)["status"] == "rfc-review"
    assert event == {"pr_number": 154, "reason": "refined", "summary": "改了 Motivation"}
    assert "mode=refine" in backend.tasks[0]


def test_refine_rfc_announce_false_suppresses_comment(monkeypatch):
    recorder = _GithubRecorder()
    posted = _patch(monkeypatch, recorder=recorder)
    state = _FakeState()
    state.set_run(
        issue_number=145, status="rfc-review", branch="openagents/issue-145", pr_number=154
    )

    rl.refine_rfc(
        pr_number=154,
        detail="d",
        backend=_DrafterBackend(),
        state=state,
        work_dir="/tmp",
        agent_id="agent-A",
        announce=False,
    )

    assert posted == []


def test_implement_marks_ready_and_sets_pr_open(monkeypatch):
    recorder = _GithubRecorder()
    _patch(monkeypatch, recorder=recorder)
    state = _FakeState()
    state.set_run(
        issue_number=145, status="rfc-review", branch="openagents/issue-145", pr_number=154
    )
    backend = _DrafterBackend(summary="实现了 T1")

    event = rl.implement(
        pr_number=154, backend=backend, state=state, work_dir="/tmp", agent_id="agent-A"
    )

    assert recorder.marked_ready == [154]
    assert state.get_run(issue_number=145)["status"] == "pr-open"
    assert event == {"pr_number": 154, "reason": "implemented", "summary": "实现了 T1"}
    assert "mode=implement" in backend.tasks[0]


def test_iterate_sets_iterating_and_threads_reason(monkeypatch):
    recorder = _GithubRecorder()
    _patch(monkeypatch, recorder=recorder)
    state = _FakeState()
    state.set_run(issue_number=145, status="pr-open", branch="openagents/issue-145", pr_number=154)
    backend = _DrafterBackend(summary="修了 CI")

    event = rl.iterate(
        pr_number=154,
        reason="ci",
        detail="pytest 红了",
        backend=backend,
        state=state,
        work_dir="/tmp",
        agent_id="agent-A",
    )

    assert state.get_run(issue_number=145)["status"] == "iterating"
    assert event == {"pr_number": 154, "reason": "iterated", "summary": "修了 CI"}
    # reason 拼进派给 drafter 的 detail（iterate 模式）。
    assert "mode=iterate" in backend.tasks[0]
    assert "ci反馈" in backend.tasks[0]


def test_require_run_missing_pr_raises(monkeypatch):
    recorder = _GithubRecorder()
    _patch(monkeypatch, recorder=recorder)
    state = _FakeState()  # 无任何 run 记录

    with pytest.raises(rl.RfcLifecycleError):
        rl.implement(
            pr_number=999,
            backend=_DrafterBackend(),
            state=state,
            work_dir="/tmp",
            agent_id="agent-A",
        )


def test_head_not_advanced_raises_gate_error(monkeypatch):
    # 交付前后 head 恒为 "BASE"（未前移）→ head 前移硬闸 raise（哪怕 drafter 自述 delivered=True）。
    recorder = _GithubRecorder()
    _patch(monkeypatch, recorder=recorder, head_values=("BASE",))
    state = _FakeState()
    backend = _DrafterBackend(head_sha="BASE")

    with pytest.raises(GateError):
        rl.draft_rfc(
            issue_number=145, backend=backend, state=state, work_dir="/tmp", agent_id="agent-A"
        )
    assert recorder.created_prs == []  # 硬闸拦下，不开 PR


def test_evidence_stamp_mismatch_raises_gate_error(monkeypatch):
    # head 确实前移（BASE→MOVED），但 drafter 自报 head_sha 报了别处 → 证据溯源戳硬闸 raise。
    recorder = _GithubRecorder()
    _patch(monkeypatch, recorder=recorder, head_values=("BASE", "MOVED"))
    state = _FakeState()
    backend = _DrafterBackend(head_sha="ELSEWHERE")

    with pytest.raises(GateError):
        rl.draft_rfc(
            issue_number=145, backend=backend, state=state, work_dir="/tmp", agent_id="agent-A"
        )
