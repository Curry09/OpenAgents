"""Spec-0065/T2: recipes.vigil 的**动作面**（`_act` 与七个 `_do_*` 分支）契约单测。

`tests/test_recipe_vigil.py` 覆盖的是**感知面**（sense/classify/fingerprint/watchdog/队列/存活探测），它
在每处都把 `_act` 打桩掉了——于是「判定说该干 X」与「真的去干了 X」之间那一段（路由 + 七个分支的副作用）
一行都没被执行过。本文件补的正是那一段，钉死四件事：

- **路由是机械的**：`verdict.action` → 唯一的 stage/agent，每支各一个测试（派谁、在哪个 worktree、对哪个
  issue/PR）。三态 `human` 一律落 `_park_gate`（打 needs-human、**零 agent 调用**）。
- **一等出口契约必达**：`_NEEDS_HUMAN_CONTRACT` 必须出现在**每个**派 agent 的分支交给 agent 的上下文里
  （含 `_do_reply` / `_do_rebase`——少了它，「答不了 / 解不动冲突」就只能靠护栏兜，兜底当场变主路径）。
  断言打在 `engine.run_agent` 这个**唯一的派 agent 出口**上，故 stage 内部怎么组占位符都逃不掉。
- **worktree 不共享**：两个**不同的裸 PR**（无 issue 归属）必须拿到**不同的** worktree 目录——都退化成
  `issue-0` 的话，两个 worker 的 agent 会在同一个目录里改代码、把改动推到别人的 PR 上（flock 拦不住：
  它们本就是两个 subject，共享的是**资源**）。
- **硬超时杀对进程**：`_TimedBackend` 超时 → `_ActTimeout` + 只杀**本次调用自报**的 PID（别的线程自报的
  一个都不许碰——杀错进程时真正挂死的 agent 还活着继续 push，双跑就从这个洞漏出来）。

全程假 backend + 打桩 engine/stages 的 IO 边界（github/git/gates/identity/proc），不触真实 LLM/网络/仓库，
也不真杀任何进程。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import (
    _ACT_E2E,
    _ACT_FIX_CI,
    _ACT_MERGE,
    _ACT_READY,
    _ACT_REBASE,
    _ACT_REPLY,
    _ACT_REVIEW_OR_FIX,
    _ACT_SOLVE,
    _NEEDS_HUMAN_CONTRACT,
    _ActTimeout,
    _classify,
    _Clock,
    _Facts,
    _Observed,
    _pr_worktree,
    _TimedBackend,
)
from openagents.runtime import engine, gates
from openagents.utils import agent_config, git, github, identity, proc

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_HEAD = "abc1234def5678901234567890123456789abcde"
_SHA7 = _HEAD[:7]

# Spec-0065/T2: 各 agent 的 OUTPUT_SCHEMA 合规的假裁决（engine 被打桩，故这里就是「agent 说了什么」）。
_AGENT_OUTPUTS: dict[str, dict] = {
    "drafter": {"delivered": True, "head_sha": _HEAD, "summary": "spec 已起草"},
    "implementer": {"summary": "已按反馈修改"},
    "reviewer": {"verdict": "PASS", "reason": "看着没问题"},
    "tester": {"verdict": "PASS", "reason": "e2e 全绿"},
    "replier": {"reply": "已回应你的问题", "resolved": True},
    "deliver": {"delivered": True, "base_sha": "0" * 40, "head_sha": _HEAD, "summary": "已 push"},
    "merger": {"merged": True, "summary": "已合并"},  # Spec-0066/T3: 合并动作下放 merger agent
}


# --------------------------------------------------------------------------------------------------
# 夹具：facts / config 造型（与 test_recipe_vigil.py 同款）+ 一套记录所有对外副作用的探针 `_Rig`。
# --------------------------------------------------------------------------------------------------


def _facts(**overrides) -> _Facts:
    """一个「万事俱备、只欠合并」的 facts（分支⑪），各测试按需改单个字段退回某一支。"""
    base = _Facts(
        subject="issue:5",
        pr_number=12,
        head_sha=_HEAD,
        merged=False,
        closed=False,
        labels=frozenset({f"review-approved:{_SHA7}"}),
        deps_done=True,
        mergeable_state="clean",
        ci="success",
        e2e_head_sha=_HEAD,
        review_state="APPROVED",
        review_commit_id=_SHA7,
        latest_comment_is_ours=True,
    )
    return replace(base, **overrides)


def _stages_policy(**owners) -> agent_config.StagePolicy:
    return agent_config.StagePolicy(owners=owners)


def _config(**overrides) -> agent_config.AgentConfig:
    defaults = {
        "version": 1,
        "agents": agent_config.AgentPolicy(backends={}),
        "stages": _stages_policy(),
        "release": agent_config.ReleasePolicy(),
        "interval": 1,
        "base": "main",
        "labels": ["openagents"],
        "repos": [],
    }
    return agent_config.AgentConfig(**(defaults | overrides))


class _Rig:
    """一次 `_act` 的全部对外副作用探针：兼作 `RuntimeState` 替身（set_run / get_cursor / set_cursor）。"""

    def __init__(self) -> None:
        self.agents: list[tuple[str, dict]] = []  # (agent 模块名, engine 收到的占位符)
        self.backends: list[object] = []  # 每次派 agent 时的 backend（应恒为 _TimedBackend）
        self.gh: list[tuple] = []  # github 调用流水
        self.runs: list[tuple] = []  # state.set_run
        self.cursors: list[tuple] = []  # state.set_cursor
        self.comments: list[tuple] = []  # identity.post_signed_comment
        self.worktrees: list[tuple] = []  # Workspace.prepare / ensure

    # --- RuntimeState 替身（vigil 只用这三个方法） ---
    def set_run(self, *, issue_number: int, status: str, branch: str, pr_number: int) -> None:
        self.runs.append((issue_number, status, branch, pr_number))

    def get_cursor(self, *, pr_number: int) -> str:
        return ""

    def set_cursor(self, *, pr_number: int, comment_id: str) -> None:
        self.cursors.append((pr_number, comment_id))

    # --- 便捷查询 ---
    def agent_names(self) -> list[str]:
        return [name for name, _ in self.agents]

    def context_of(self, *, agent: str) -> str:
        return next(place["context"] for name, place in self.agents if name == agent)

    def gh_names(self) -> list[str]:
        return [call[0] for call in self.gh]


class _FakeWorkspace:
    """`git.Workspace` 替身：不碰 git，按真实实现的命名规则派生 worktree 路径并记录键。"""

    def __init__(self, *, work_dir: Path) -> None:
        self._work_dir = Path(work_dir)

    def prepare(self, *, issue_number: int, branch: str, base: str) -> Path:
        _RIG.worktrees.append(("prepare", issue_number, branch, base))
        return self._path(issue_number=issue_number)

    def ensure(self, *, issue_number: int, branch: str) -> Path:
        _RIG.worktrees.append(("ensure", issue_number, branch))
        return self._path(issue_number=issue_number)

    def _path(self, *, issue_number: int) -> Path:
        return self._work_dir / ".openagents" / "worktrees" / f"issue-{issue_number}"


# `_FakeWorkspace` 由 vigil 内部 `git.Workspace(...)` 构造，拿不到测试的闭包 → 探针挂模块级，由 fixture 重置。
_RIG = _Rig()


class _Backend:
    """假 backend——engine 已被打桩，它不该被真的 run（被调到即测试有洞）。"""

    name = "fake"

    def run(self, *, work_dir, task, context):  # pragma: no cover - 不该被调到
        raise AssertionError("engine.run_agent 已打桩，backend.run 不该被调用")


@pytest.fixture
def rig(monkeypatch) -> _Rig:
    """打桩 `_act` 的全部 IO 边界：engine（唯一的派 agent 出口）/ github / git / gates / identity。"""
    global _RIG
    _RIG = _Rig()
    probe = _RIG

    def _run_agent(agent_module, *, backend, **placeholders):
        name = agent_module.__name__.rsplit(".", 1)[-1]
        probe.agents.append((name, dict(placeholders)))
        probe.backends.append(backend)
        return dict(_AGENT_OUTPUTS[name])

    monkeypatch.setattr(engine, "run_agent", _run_agent)

    # gates：交付类阶段（rfc/deliver/conflict）的三道确定性硬闸——本文件不测它们（T1 已钉），放行即可。
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: "0" * 40)
    monkeypatch.setattr(gates, "assert_head_advanced", lambda *, before, workspace: _HEAD)
    monkeypatch.setattr(gates, "assert_evidence_stamp", lambda *, head_sha, claimed: None)
    # Spec-0066/T3: 合并硬闸——本文件不测它（T3 test_runtime_gates 已钉），放行即可；只验合并动作下放 merger。
    monkeypatch.setattr(gates, "assert_merge_allowed", lambda *, pr_number, head_sha: None)

    monkeypatch.setattr(git, "Workspace", _FakeWorkspace)

    def _gh(name: str, result=None):
        def _call(**kwargs):
            probe.gh.append((name, kwargs))
            return result

        monkeypatch.setattr(github, name, _call)

    _gh("get_issue", github.Issue(5, "标题", "issue 正文", []))
    _gh("create_pr", github.PR(12, "https://example.invalid/pr/12"))
    _gh("mark_ready")
    _gh("merge_pr")
    _gh("close_issue")
    _gh("ensure_label")
    _gh("add_label")
    _gh("remove_label")
    _gh("issue_add_label")
    _gh("issue_comment")
    _gh("post_comment")
    # park 的理由评论幂等：先读回评论流去重（空 → 没说过 → 照贴）。漏了这两个桩，测试会真去调 `gh`。
    _gh("list_issue_comments", [])
    _gh("list_comments", [])
    _gh("update_branch", False)  # 默认「机械 update-branch 不行」→ 下放 agent 解冲突
    _gh("check_logs", ["FAILED tests/test_x.py::test_y"])
    monkeypatch.setattr(github, "pr_head_branch", lambda *, pr_number: f"branch-of-pr-{pr_number}")

    monkeypatch.setattr(
        identity,
        "new_human_comments",
        lambda *, pr_number, since: [
            github.Comment(7, "human", "这里为什么这么写？", "2026-07-14T11:00:00Z")
        ],
    )
    monkeypatch.setattr(
        identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: probe.comments.append((pr_number, body, agent_id)),
    )
    return probe


def _act(
    *, rig: _Rig, facts: _Facts, work_dir: Path, config=None, lock_fd: int | None = None
) -> str:
    """跑一次 `_act`——verdict 由**真** `_classify` 算出，路由与分支表因此不可能各说各话。

    `lock_fd` = 该认领行的 flock fd，透传给 `_TimedBackend` 让 agent 子进程继承（存活证明跟着干活的进程走）。
    这些用例只测路由与副作用，不起真子进程，故默认不传 fd。
    """
    return vigil_module._act(
        backend=_Backend(),
        state=rig,
        work_dir=Path(work_dir),
        config=config or _config(),
        observed=_Observed(facts=facts, clock=_Clock(last_progress_at=_NOW)),
        verdict=_classify(facts=facts, in_flight=False),
        agent_id="bot",
        now=_NOW,
        lock_fd=lock_fd,
    )


def _issue_worktree(work_dir: Path, number: int) -> Path:
    return Path(work_dir) / ".openagents" / "worktrees" / f"issue-{number}"


# --------------------------------------------------------------------------------------------------
# 路由：verdict.action → 唯一的 stage/agent（每支一个测试）。
# --------------------------------------------------------------------------------------------------


def test_act_reply_dispatches_replier_and_posts_signed_comment(rig, tmp_path):
    """分支②：最新评论是人发的 → 派 replier + 回一条签名评论 + 推进游标（**不派任何写码 agent**）。"""
    facts = _facts(latest_comment_is_ours=False)
    assert _classify(facts=facts, in_flight=False).action == _ACT_REPLY

    summary = _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["replier"]
    placeholders = rig.agents[0][1]
    assert placeholders["pr_number"] == 12
    assert placeholders["comment_body"] == "这里为什么这么写？"
    assert rig.comments == [(12, "已回应你的问题", "bot")]
    assert rig.cursors == [(12, "2026-07-14T11:00:00Z")]
    assert summary == "已回应你的问题"


def test_act_solve_cuts_a_vertical_slice_and_never_blocks_on_ci(rig, tmp_path):
    """分支④：还没有 PR → worktree → rfc(drafter) → 开 draft PR → implement → deliver。

    **不在此阻塞等 CI/review**：那两支是 `_classify` 的⑦⑩，回到 `_reconcile` 的循环自然会走到——故这里
    绝不该出现 reviewer/tester。

    Spec-0066/T2：`_do_solve` **不再确定性直调 `github.mark_ready`**——转正归 deliver agent（其完成判据含
    「PR 非 draft」）；脱靶残留 draft 由 `_classify` ⑪ 兜底转正。故 gh 调用流水里不再有 `mark_ready`。
    """
    facts = _facts(pr_number=None)
    assert _classify(facts=facts, in_flight=False).action == _ACT_SOLVE

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["drafter", "implementer", "deliver"]
    assert rig.worktrees == [("prepare", 5, "openagents/issue-5", "main")]
    worktree = _issue_worktree(tmp_path, 5)
    assert rig.agents[1][1]["work_dir"] == worktree  # implementer 在隔离 worktree 里写码
    assert rig.agents[1][1]["issue_number"] == 5
    assert rig.gh_names() == ["get_issue", "create_pr"]  # Spec-0066/T2: 不再直调 mark_ready
    assert "mark_ready" not in rig.gh_names()
    assert rig.runs == [(5, "pr-open", "openagents/issue-5", 12)]


def test_act_solve_skips_rfc_when_that_stage_is_skipped(rig, tmp_path):
    """`rfc: skip` = 不设此闸 → 不派 drafter，但 PR/implement/deliver 照常（`skip` 关的是闸，不是活）。"""
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(stages=_stages_policy(rfc="skip")),
    )
    assert rig.agent_names() == ["implementer", "deliver"]


def test_act_rebase_tries_mechanical_update_branch_before_any_agent(rig, tmp_path, monkeypatch):
    """分支⑥：只是 base 前移（无真冲突）→ 机械 `update_branch` 就够 → **零 LLM 调用**。"""
    monkeypatch.setattr(github, "update_branch", lambda *, pr_number, rebase: True)
    facts = _facts(mergeable_state="dirty")
    assert _classify(facts=facts, in_flight=False).action == _ACT_REBASE

    summary = _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agents == [], "机械 update-branch 成功时不许叫 agent"
    assert "update-branch" in summary


def test_act_rebase_falls_back_to_deliver_agent_when_update_branch_fails(rig, tmp_path):
    """机械 `update_branch` 不行（真冲突）→ 下放 deliver agent 变基（`stages.conflict`）。"""
    _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)

    assert rig.agent_names() == ["deliver"]
    placeholders = rig.agents[0][1]
    assert placeholders["pr_number"] == 12
    assert placeholders["branch"] == "branch-of-pr-12"


def test_act_fix_ci_feeds_failing_check_logs_to_implementer(rig, tmp_path):
    """分支⑧：当前 head 上 CI 红 → 把失败 check 的日志喂给 implementer 去修（在该 PR 的 worktree 里）。"""
    facts = _facts(ci="failure")
    assert _classify(facts=facts, in_flight=False).action == _ACT_FIX_CI

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["implementer"]
    placeholders = rig.agents[0][1]
    assert "FAILED tests/test_x.py::test_y" in placeholders["feedback"]
    assert placeholders["pr_number"] == 12
    assert placeholders["work_dir"] == _issue_worktree(tmp_path, 5)
    assert rig.worktrees == [("ensure", 5, "openagents/issue-5")]


def test_act_e2e_stamps_evidence_with_the_head_it_was_run_against(rig, tmp_path):
    """分支⑨：派 tester；PASS → 贴一条**带 head 溯源戳**的证据评论（戳里的 head 就是这一版代码的 head）。"""
    facts = _facts(e2e_head_sha=None)
    assert _classify(facts=facts, in_flight=False).action == _ACT_E2E

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["tester"]
    assert rig.agents[0][1]["work_dir"] == _issue_worktree(tmp_path, 5)
    assert len(rig.comments) == 1
    pr_number, body, agent_id = rig.comments[0]
    assert (pr_number, agent_id) == (12, "bot")
    assert body.startswith(f"{vigil_module._E2E_MARKER}{_HEAD} -->")


def test_act_e2e_never_stamps_evidence_when_the_run_failed(rig, tmp_path, monkeypatch):
    """tester 判 REWORK → **不盖戳**（盖了就等于用一份失败的证据放行——张冠李戴的另一面）。"""
    monkeypatch.setitem(_AGENT_OUTPUTS, "tester", {"verdict": "REWORK", "reason": "e2e 挂了"})
    _act(rig=rig, facts=_facts(e2e_head_sha=None), work_dir=tmp_path)
    assert rig.agent_names() == ["tester"]
    assert rig.comments == [], "e2e 没过还盖证据戳 = 拿失败的证据放行"


def test_act_review_dispatches_reviewer_and_binds_the_verdict_to_the_head_sha(rig, tmp_path):
    """分支⑩：无裁决 → 派 reviewer；裁决落 label 时**把当前 head 的 sha7 嵌进 label 名**（裁决绑 commit）。"""
    facts = _facts(review_state=None, review_commit_id=None, labels=frozenset())
    assert _classify(facts=facts, in_flight=False).action == _ACT_REVIEW_OR_FIX

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["reviewer"]
    assert rig.agents[0][1]["work_dir"] == _issue_worktree(tmp_path, 5)
    added = [call for call in rig.gh if call[0] == "add_label"]
    assert added == [("add_label", {"pr_number": 12, "name": f"review-approved:{_SHA7}"})]


def test_act_review_clears_stale_verdict_labels_before_landing_the_new_one(
    rig, tmp_path, monkeypatch
):
    """新裁决落下前先摘掉所有旧 `review-*:<sha7>`——留着不伤正确性（sha 对不上就不被承认）但会让人看见一排矛盾裁决。"""
    monkeypatch.setitem(_AGENT_OUTPUTS, "reviewer", {"verdict": "REWORK", "reason": "要改"})
    facts = _facts(
        review_state=None,
        review_commit_id=None,
        labels=frozenset({"review-approved:0000000", "openagents"}),
    )
    _act(rig=rig, facts=facts, work_dir=tmp_path)

    removed = [call[1]["name"] for call in rig.gh if call[0] == "remove_label"]
    assert removed == ["review-approved:0000000"], "只摘 review-* 裁决 label，别的一个不碰"
    added = [call[1]["name"] for call in rig.gh if call[0] == "add_label"]
    assert added == [f"review-changes-requested:{_SHA7}"]  # REWORK 的裁决同样绑当前 head


def test_act_review_or_fix_sends_changes_requested_back_to_implementer(rig, tmp_path):
    """分支⑩另一半：已是 `CHANGES_REQUESTED@当前 head` → 派 implementer 改代码（**不再重审一遍**）。"""
    facts = _facts(
        review_state="CHANGES_REQUESTED",
        review_commit_id=_SHA7,
        labels=frozenset({f"review-changes-requested:{_SHA7}"}),
    )
    assert _classify(facts=facts, in_flight=False).action == _ACT_REVIEW_OR_FIX

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["implementer"]
    assert "[review]" in rig.agents[0][1]["feedback"]


def test_act_ready_promotes_residual_draft_via_mark_ready(rig, tmp_path):
    """分支⑪（Spec-0066/T2）：全绿+approved@head 但仍 draft → 确定性 `github.mark_ready` 转正（level-triggered 安全网）。

    零判断的机械动作，**不派任何 agent**（为何不派新 promoter agent 见 Spec-0066 Rationale）；happy-path
    转正归 deliver agent，本支是那一枪脱靶后的兜底。
    """
    facts = _facts(is_draft=True)  # 其余全绿、只欠转正
    assert _classify(facts=facts, in_flight=False).action == _ACT_READY

    summary = _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agents == [], "转正是确定性机械动作，不该叫任何 agent"
    assert ("mark_ready", {"pr_number": 12}) in rig.gh
    assert "merge_pr" not in rig.gh_names()  # 排在 merge 前：draft 态绝不落合并
    assert "转正" in summary


def test_act_merge_dispatches_merger_agent_behind_the_gate(rig, tmp_path):
    """分支⑫（Spec-0066/T2/T3）：全绿 + approved@head + 非 draft → 经确定性硬闸放行后**下放 merger agent** 合并 + 关 issue + 置 done。

    合并不可逆：先 `gates.assert_merge_allowed`（本文件放行）把守红线，放行后经 `stages.merge` 派 merger
    agent 落 `gh pr merge`——**不再是确定性 `github.merge_pr` 直调**。
    """
    facts = _facts()  # is_draft 默认 False
    assert _classify(facts=facts, in_flight=False).action == _ACT_MERGE

    summary = _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["merger"], "合并动作下放 merger agent（闸放行后）"
    assert rig.agents[0][1]["pr_number"] == 12
    assert isinstance(rig.backends[0], _TimedBackend)  # 经 _TimedBackend 派，超时可杀
    assert ("close_issue", {"number": 5}) in rig.gh
    assert rig.runs == [(5, "done", "openagents/issue-5", 12)]
    assert summary == "merged"


def test_act_rejects_an_unknown_action(rig, tmp_path):
    """路由是穷举的：未知动作必须**当场炸**，绝不静默 no-op（静默 = 一个 subject 永远不动、无人知晓）。"""
    with pytest.raises(ValueError, match="未知动作"):
        vigil_module._act(
            backend=_Backend(),
            state=rig,
            work_dir=tmp_path,
            config=_config(),
            observed=_Observed(facts=_facts(), clock=_Clock(last_progress_at=_NOW)),
            verdict=vigil_module._Verdict(kind=vigil_module._ACTIONABLE, action="teleport"),
            agent_id="bot",
            now=_NOW,
            lock_fd=None,
        )


def test_act_wraps_the_backend_in_a_timed_backend_on_every_agent_branch(rig, tmp_path):
    """每个派 agent 的分支拿到的都必须是 `_TimedBackend`——裸 backend 挂死了没人管（flock 判不出这种死法）。"""
    _act(rig=rig, facts=_facts(ci="failure"), work_dir=tmp_path)
    assert rig.backends and all(isinstance(backend, _TimedBackend) for backend in rig.backends)


# --------------------------------------------------------------------------------------------------
# 三态：可配闸 owner=human → `_park_gate` 打 needs-human 停等人（**零 agent 调用**）。
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage,overrides",
    [
        (agent_config.STAGE_CONFLICT, {"mergeable_state": "dirty"}),
        (agent_config.STAGE_CI, {"ci": "failure"}),
        (agent_config.STAGE_E2E, {"e2e_head_sha": None}),
        (
            agent_config.STAGE_REVIEW,
            {"review_state": None, "review_commit_id": None, "labels": frozenset()},
        ),
        (agent_config.STAGE_MERGE, {}),
    ],
)
def test_act_parks_needs_human_when_the_gate_belongs_to_a_human(rig, tmp_path, stage, overrides):
    """`<stage>: human` → 挂 `needs-human` + 贴理由（下一圈 `_classify` 判 TERMINAL、轮询停止），**不叫 agent**。"""
    summary = _act(
        rig=rig,
        facts=_facts(**overrides),
        work_dir=tmp_path,
        config=_config(stages=_stages_policy(**{stage: "human"})),
    )
    assert rig.agents == [], f"{stage}: human 归人把关，不许派 agent"
    assert summary == f"{stage}: human"
    assert ("issue_add_label", {"number": 5, "name": "needs-human"}) in rig.gh
    assert "issue_comment" in rig.gh_names()


# --------------------------------------------------------------------------------------------------
# 一等出口契约：`_NEEDS_HUMAN_CONTRACT` 必须进到**每个**派 agent 的分支交给 agent 的上下文里。
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,agent",
    [
        ({"latest_comment_is_ours": False}, "replier"),  # 分支②：人问的问题它也可能答不了
        ({"pr_number": None}, "drafter"),  # 分支④：起草
        ({"pr_number": None}, "implementer"),  # 分支④：实现
        ({"mergeable_state": "dirty"}, "deliver"),  # 分支⑥：冲突解不动正是该交人的场景
        ({"ci": "failure"}, "implementer"),  # 分支⑧：CI 是上游 flaky 时该交人
        ({"e2e_head_sha": None}, "tester"),  # 分支⑨
        (
            {"review_state": None, "review_commit_id": None, "labels": frozenset()},
            "reviewer",
        ),  # 分支⑩
        (
            {
                "review_state": "CHANGES_REQUESTED",
                "review_commit_id": _SHA7,
                "labels": frozenset({f"review-changes-requested:{_SHA7}"}),
            },
            "implementer",
        ),  # 分支⑩返工
    ],
)
def test_needs_human_contract_reaches_every_agent_invoking_branch(rig, tmp_path, overrides, agent):
    """**主路径收口的前提**：agent 看不到这条契约，就不会自己打 `needs-human`——兜底当场变成主路径。

    断言打在 `engine.run_agent` 这个唯一的派 agent 出口上（stage 内部怎么组占位符都逃不掉）。`_do_reply`
    与 `_do_rebase` 曾漏掉它——它们分别是「答不了人的提问」和「解不动冲突」，恰恰是最该主动交人的两支。
    """
    _act(rig=rig, facts=_facts(**overrides), work_dir=tmp_path)
    assert agent in rig.agent_names()
    assert _NEEDS_HUMAN_CONTRACT in rig.context_of(agent=agent)


def test_needs_human_contract_reaches_the_replier(rig, tmp_path):
    """回归：`_do_reply` 的契约拼在**人的那条评论正文之后**（既给回应对象、也给一等出口）。"""
    _act(rig=rig, facts=_facts(latest_comment_is_ours=False), work_dir=tmp_path)
    context = rig.context_of(agent="replier")
    assert context == f"这里为什么这么写？{_NEEDS_HUMAN_CONTRACT}"


def test_needs_human_contract_reaches_the_conflict_resolver(rig, tmp_path):
    """回归：`_do_rebase` 经 `stages.conflict(context_text=…)` 把契约透传进 deliver agent 的上下文。"""
    _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)
    assert _NEEDS_HUMAN_CONTRACT in rig.context_of(agent="deliver")


def test_needs_human_contract_names_the_label_and_the_stop_semantics():
    """契约本身必须**指名那个 label**——agent 打错名字（`blocked`/`help-wanted`）等于没打，护栏也就白设了。"""
    assert vigil_module._LABEL_NEEDS_HUMAN in _NEEDS_HUMAN_CONTRACT
    assert vigil_module._LABEL_NEEDS_HUMAN == github.BLOCKED_LABEL


# --------------------------------------------------------------------------------------------------
# worktree 归属：两个不同的裸 PR **必须**拿到两个不同的目录（都退化成 issue-0 = 往别人的 PR 上推代码）。
# --------------------------------------------------------------------------------------------------


def test_bare_prs_get_distinct_worktrees(tmp_path, monkeypatch):
    """裸 PR（无 issue 归属）按 **PR 号**取目录键，而不是「无 issue → 0」。

    `Workspace.ensure` 的目录名只吃 `issue_number`，且**目录已存在就直接返回、不查当前在哪个分支上**——
    两个裸 PR 都传 0 的话，`pr:12` 与 `pr:13` 会拿到**同一个** `.worktrees/issue-0`：两个 worker 的 agent
    在同一个目录里改代码，且后来者其实站在前者的分支上，会把改动推到**别人的 PR** 上。subject 级 flock 拦
    不住这个——它们本就是两个 subject，共享的是**资源**。

    这里用**真** `git.Workspace`：三个候选目录都预先建好（含 issue-0），故 `ensure` 全部走「已存在 → 直接
    返回」的短路、一次 git 都不跑；退化成 issue-0 的实现会在此**返回同一个路径**而被当场抓住。
    """
    monkeypatch.setattr(github, "pr_head_branch", lambda *, pr_number: f"feature/pr-{pr_number}")
    for number in (0, 12, 13):
        (tmp_path / ".openagents" / "worktrees" / f"issue-{number}").mkdir(parents=True)

    first = _pr_worktree(work_dir=tmp_path, facts=_facts(subject="pr:12", pr_number=12))
    second = _pr_worktree(work_dir=tmp_path, facts=_facts(subject="pr:13", pr_number=13))

    assert first != second, "两个裸 PR 共用一个 worktree = 把改动推到别人的 PR 上"
    assert first.name == "issue-12"
    assert second.name == "issue-13"


def test_issue_subject_worktree_is_keyed_by_the_issue_number(tmp_path, monkeypatch):
    """issue 归属的 subject 仍按 issue 号取 worktree + 走 `openagents/issue-<n>` 分支（承旧串行 vigil）。"""
    monkeypatch.setattr(git, "Workspace", _FakeWorkspace)
    global _RIG
    _RIG = _Rig()
    path = _pr_worktree(work_dir=tmp_path, facts=_facts(subject="issue:5"))
    assert _RIG.worktrees == [("ensure", 5, "openagents/issue-5")]
    assert path == _issue_worktree(tmp_path, 5)


# --------------------------------------------------------------------------------------------------
# 硬超时：flock 只回答「进程在不在」；`_TimedBackend` 补的是「进程活着但挂死在一个不返回的调用上」。
# --------------------------------------------------------------------------------------------------


class _HangingBackend:
    """永不返回的 backend；`Popen` 之后**自报 PID**（认领靠自报，不靠猜——diff 会认错别人的 gh/git）。"""

    name = "hanging"

    def __init__(self, *, pid: int) -> None:
        self._pid = pid
        self.thread_id = 0

    def run(self, *, work_dir, task, context):
        self.thread_id = threading.get_ident()
        proc.publish(pid=self._pid)
        time.sleep(300)


@pytest.fixture
def killed(monkeypatch) -> list[tuple[int, object]]:
    """打桩 `proc.kill_tree`，只记录 `(pid, handle)`——本测试文件不真杀任何进程。

    连 `handle` 一起记：超时方必须把 backend 自报的那个 `Popen` 一并递给 `kill_tree`（句柄是「这个 PID 还是
    不是当年那个进程」的唯一依据；丢了它就只剩裸 PID 可杀，PID 回绕时会杀到别的 worker 的 agent）。
    """
    record: list[tuple[int, object]] = []
    monkeypatch.setattr(proc, "kill_tree", lambda *, pid, handle: record.append((pid, handle)))
    return record


def test_timed_backend_kills_exactly_the_pids_this_call_published(killed):
    """超时 → 杀**本次调用自报的** PID，且**只杀它**：杀错进程时真挂死的 agent 还活着继续 push（双跑）。"""
    proc.track()  # 主线程也开一个桶（模拟另一个 worker / 生产者的 gh、git 子进程）
    proc.publish(pid=999_001)  # 它自报的 PID 一个都不许被这次超时杀掉
    backend = _HangingBackend(pid=424_242)
    try:
        with pytest.raises(_ActTimeout, match="424242"):
            _TimedBackend(inner=backend, timeout_seconds=1, lock_fd=None).run(
                work_dir=Path("."), task="t", context="c"
            )
        assert killed == [(424_242, None)], "只许杀本次 agent 调用自报的进程树"
        # 别人的桶原样健在（桶是 {PID: 句柄}——这里的 gh/git 没给句柄，记 None）。
        assert proc.untrack(thread_id=threading.get_ident()) == {999_001: None}
    finally:
        proc.untrack(thread_id=threading.get_ident())


def test_timed_backend_passes_the_published_handle_to_kill_tree(killed):
    """超时时递给 `kill_tree` 的必须是 backend **自报的那个句柄**——它是 PID 验明正身的唯一依据。

    没有句柄，`kill_tree` 只能按裸 PID 杀：那个 PID 若已被 reap 并回绕（长跑守夜每 tick 起若干 gh/git），
    受害者就是本进程另一个 worker 的 agent → 那行被回收重领 → 双跑。
    """
    handle = object()  # 替 Popen；`kill_tree` 已被打桩，不会真去 poll 它

    class _HangingWithHandle:
        name = "hanging"

        def run(self, *, work_dir, task, context):
            proc.publish(pid=424_245, handle=handle)
            time.sleep(300)

    with pytest.raises(_ActTimeout):
        _TimedBackend(inner=_HangingWithHandle(), timeout_seconds=1, lock_fd=None).run(
            work_dir=Path("."), task="t", context="c"
        )
    assert killed == [(424_245, handle)]
    assert killed[0][1] is handle  # 是**那一个**句柄，不是别的


def test_timed_backend_untracks_the_bucket_after_a_timeout(killed):
    """超时线程被丢弃 → 它的认领桶必须一并取走（否则 `_TRACKED` 随每次超时无限长）。"""
    backend = _HangingBackend(pid=424_243)
    with pytest.raises(_ActTimeout):
        _TimedBackend(inner=backend, timeout_seconds=1, lock_fd=None).run(
            work_dir=Path("."), task="t", context="c"
        )
    assert backend.thread_id not in proc._TRACKED


def test_timed_backend_kills_nothing_on_a_fast_call_and_untracks_cleanly(killed):
    """正常返回 → 一个进程都不杀、结果原样透传、桶清干净（超时闸不许对正常路径收任何税）。"""

    class _Fast:
        name = "fast"

        def __init__(self) -> None:
            self.thread_id = 0

        def run(self, *, work_dir, task, context):
            self.thread_id = threading.get_ident()
            proc.publish(pid=424_244)  # 起过子进程，但按时收工
            return "ok"

    backend = _Fast()
    result = _TimedBackend(inner=backend, timeout_seconds=30, lock_fd=None).run(
        work_dir=Path("."), task="t", context="c"
    )
    assert result == "ok"
    assert killed == [], "按时返回的调用一个进程都不许杀"
    assert backend.thread_id not in proc._TRACKED


def test_timed_backend_reraises_the_inner_error_without_killing(killed):
    """backend 自己抛错（gh 抖动等）→ 原样重抛、**不杀进程**（它已经收工了）→ 上层走回队重试而非 park。"""

    class _Boom:
        name = "boom"

        def run(self, *, work_dir, task, context):
            raise RuntimeError("后端抽风")

    with pytest.raises(RuntimeError, match="后端抽风"):
        _TimedBackend(inner=_Boom(), timeout_seconds=30, lock_fd=None).run(
            work_dir=Path("."), task="t", context="c"
        )
    assert killed == []


# --------------------------------------------------------------------------------------------------
# 存活证明跟着干活的进程走：`_TimedBackend(lock_fd=N)` → 跑 backend 的**那条线程**登记 fd N 供子进程继承。
# --------------------------------------------------------------------------------------------------


class _FdProbeBackend:
    """按时返回的 backend，顺手记下**自己这条线程**看到的继承 fd 登记（backend 就是在这里起 `Popen` 的）。"""

    name = "fd-probe"

    def __init__(self) -> None:
        self.thread_id = 0
        self.inherited: tuple[int, ...] = ()

    def run(self, *, work_dir, task, context):
        self.thread_id = threading.get_ident()
        self.inherited = proc.inherited_fds()  # backend 起子进程时正是拿这个当 pass_fds
        return "ok"


def test_timed_backend_holds_the_lock_fd_on_the_thread_that_runs_the_backend(tmp_path, killed):
    """Spec-0065/T2：`lock_fd=N` → 在**跑 backend 的那条线程**上 `proc.hold_fd(fd=N)`，故 agent 子进程继承
    flock（`backends.claude_code` 的 `Popen(pass_fds=proc.inherited_fds())` 读的正是这份登记）。

    **存活证明必须跟着真正在干活的那个进程走**：守夜被 SIGKILL/OOM/`docker stop` 打死时，它起的 agent 是被
    **孤儿化而不是被杀**（还能从容跑完一次 `git push`）。锁若只在守夜手里，内核当场放锁 → `_reclaim_dead`
    抢到 → 判「持有者已死」→ 行回 queued → 另一个 worker 领走同一个 subject → **双跑**。让 agent 继承 fd 后，
    锁的语义变成「守夜**或**它的 agent 还有一个活着」，这个入口就此封死。

    登记必须落在**那条线程**上（`_INHERIT` 按 thread ident 分桶）：落在主线程上等于没落——backend 在子线程
    里读 `inherited_fds()` 会读到空，fd 根本不会被传给 `Popen`。
    """
    fd = os.open(str(tmp_path / "issue-5.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    backend = _FdProbeBackend()
    try:
        result = _TimedBackend(inner=backend, timeout_seconds=30, lock_fd=fd).run(
            work_dir=Path("."), task="t", context="c"
        )

        assert result == "ok"
        assert backend.inherited == (fd,), (
            "跑 backend 的那条线程必须看得见这个 fd（否则子进程继承不到锁）"
        )
        assert (
            backend.thread_id != threading.get_ident()
        )  # 确实是另一条线程（不是主线程侥幸看到的）
        assert os.get_inheritable(fd), "fd 必须被置为可继承（PEP 446 默认 close-on-exec）"
        assert proc.inherited_fds() == (), "主线程不该被登记任何 fd"
        assert backend.thread_id not in proc._INHERIT, "收工后必须 release_fds，登记不许泄漏"
    finally:
        os.close(fd)


def test_timed_backend_holds_no_fd_when_there_is_no_claim(killed):
    """`lock_fd=None`（生产者线程的 triager/curator：**没有认领的行、没有锁**）→ 一个 fd 都不许登记。

    多登记一个 fd = 让那次调用起的子进程白拿一把它不该持有的锁：它苟活时会把**别人的**行钉在 claimed 上，
    `_reclaim_dead` 判不了死 → 那个 subject 永远动不了。
    """
    backend = _FdProbeBackend()
    _TimedBackend(inner=backend, timeout_seconds=30, lock_fd=None).run(
        work_dir=Path("."), task="t", context="c"
    )
    assert backend.inherited == (), "没有认领的行就没有存活证明可传"
    assert backend.thread_id not in proc._INHERIT
