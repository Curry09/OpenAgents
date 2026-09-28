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

Spec-0056 / Spec-0017 补充：2026-09-09-delivery-review-snapshot-tests-design.md
同时覆盖错误审批与正常交付的可推进性；修复后所有回归均作为普通测试执行。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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
    _AUTONOMOUS_CONTRACT,
    _ActTimeout,
    _classify,
    _Clock,
    _conflict_fingerprint,
    _Facts,
    _Observed,
    _pr_worktree,
    _TimedBackend,
)
from openagents.runtime import engine, gates
from openagents.runtime.gates import assert_merge_allowed
from openagents.utils import agent_config, git, github, identity, proc
from openagents.utils.workspace import Workspace, WorkspaceError

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_HEAD = "abc1234def5678901234567890123456789abcde"
_SHA7 = _HEAD[:7]

# Spec-0065/T2: 各 agent 的 OUTPUT_SCHEMA 合规的假裁决（engine 被打桩，故这里就是「agent 说了什么」）。
_AGENT_OUTPUTS: dict[str, dict] = {
    "spec_writer": {
        "status": "READY",
        "head_sha": _HEAD,
        "summary": "compact spec",
        "blocker": "",
        "objective_coverage": [{"scope_coverage": "FULL", "evidence_level": "STRUCTURAL"}],
        "candidate_assessments": [
            {
                "candidate": "one",
                "ownership": "runtime",
                "delivery": "wired",
                "control_effect": "guard",
                "evidence": "source",
                "assumptions": "none",
                "failure_modes": "bypass",
                "verdict": "selected",
            }
        ],
        "selected_intervention": {},
        "evidence_pack": [],
        "falsifiers": [],
    },
    "drafter": {
        "delivered": True,
        "head_sha": _HEAD,
        "summary": "spec 已起草",
        "evidence_pack": [],
    },
    "implementer": {"summary": "已按反馈修改"},
    "executor": {
        "summary": "已按 compact spec 实现",
        "head_sha": _HEAD,
        "lookup_exception_reason": "",
    },
    "acceptance": {
        "verdict": "PASS",
        "reason": "原 issue 已满足",
        "evidence": [
            {
                "case_id": "original",
                "source": "original_replay",
                "kind": "behavior",
                "observed": "original failure no longer reproduces",
                "expected": "original objective is satisfied",
                "path": "artifacts/original.log",
                "passed": True,
            },
            {
                "case_id": "variant",
                "source": "independent_variant",
                "kind": "behavior",
                "observed": "independent semantic variant passes",
                "expected": "implementation is not sample-specific",
                "path": "artifacts/variant.log",
                "passed": True,
            },
        ],
    },
    "reviewer": {"verdict": "PASS", "reason": "看着没问题"},
    "tester": {
        "verdict": "PASS",
        "reason": "e2e 全绿",
        "evidence": [
            {"case_id": "p", "kind": "behavior", "observed": "ok", "expected": "ok", "path": "log"}
        ],
    },
    "replier": {"reply": "已回应你的问题", "resolved": True},
    "deliver": {"delivered": True, "base_sha": "0" * 40, "head_sha": _HEAD, "summary": "已 push"},
    "merger": {"merged": True, "summary": "已合并"},  # Spec-0017/T3: 合并动作下放 merger agent
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
        self.run_records: dict[int, dict] = {}
        self.review_feedback: dict[int, dict[str, str]] = {}
        self.delivered = True  # Default fixture models an already-pushed candidate.

    # --- RuntimeState 替身（vigil 只用这三个方法） ---
    def set_run(
        self,
        *,
        issue_number: int,
        status: str,
        branch: str,
        pr_number: int,
        design_digest: str = "",
        design_raw_digest: str = "",
        evidence_pack: list | None = None,
    ) -> None:
        self.runs.append((issue_number, status, branch, pr_number))
        previous = self.run_records.get(issue_number, {})
        self.run_records[issue_number] = {
            "status": status,
            "branch": branch,
            "pr_number": pr_number,
            "design_digest": design_digest or previous.get("design_digest", ""),
            "design_raw_digest": design_raw_digest or previous.get("design_raw_digest", ""),
            "evidence_pack": (
                evidence_pack if evidence_pack is not None else previous.get("evidence_pack", [])
            ),
        }

    def get_run(self, *, issue_number: int) -> dict | None:
        return self.run_records.get(issue_number)

    def get_review_feedback(self, *, issue_number: int, head_sha: str) -> str | None:
        record = self.review_feedback.get(issue_number, {})
        return record.get("reason") if record.get("head_sha") == head_sha else None

    def set_review_feedback(self, *, issue_number: int, head_sha: str, reason: str) -> None:
        self.review_feedback[issue_number] = {"head_sha": head_sha, "reason": reason}

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

    def assert_delivered(self, *, worktree: Path, branch: str) -> None:
        _RIG.worktrees.append(("assert-delivered", Path(worktree), branch))

    def delivery_heads(self, *, worktree: Path, branch: str) -> tuple[str, str]:
        _RIG.worktrees.append(("delivery-heads", Path(worktree), branch))
        return _HEAD, _HEAD

    def sync_delivered(self, *, worktree: Path, branch: str) -> bool:
        _RIG.worktrees.append(("sync-delivered", Path(worktree), branch))
        return _RIG.delivered

    def remote_branch_exists(self, *, branch: str) -> bool:
        return False

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
    monkeypatch.setattr(gates, "assert_repository_integrity", lambda *, workspace: None)
    monkeypatch.setattr(gates, "assert_design_approved", lambda **kwargs: None)
    monkeypatch.setattr(git, "head_sha", lambda *, work_dir: _HEAD)
    monkeypatch.setattr(
        github,
        "pr_snapshot",
        lambda *, pr_number: github.PRSnapshot(
            number=pr_number,
            state="OPEN",
            head_sha=_HEAD,
            labels=(),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            head_pushed_at="",
        ),
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "architecture",
        lambda **kwargs: {
            "verdict": "PASS",
            "reason": "ok",
            "design_digest": "d",
            "spec_path": "docs/specs/0001-x.md",
        },
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "design_snapshot",
        lambda **kwargs: {"design_digest": "minimal-digest", "spec_path": "docs/specs/0001-x.md"},
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "minimal_design_snapshot",
        lambda **kwargs: {
            "design_digest": "minimal-digest",
            "spec_path": "docs/objectives/issue-5.md",
        },
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "assert_minimal_design_approved",
        lambda **kwargs: None,
    )
    # Spec-0017/T3: 合并硬闸——本文件不测它（T3 test_runtime_gates 已钉），放行即可；只验合并动作下放 merger。
    monkeypatch.setattr(
        gates,
        "assert_merge_allowed",
        lambda *, pr_number, head_sha, require_ci=True: None,
    )

    monkeypatch.setattr(git, "Workspace", _FakeWorkspace)
    # ``recipes.stages`` imports Workspace directly, so patch that bound name too.
    # This keeps the recipe tests hermetic now that minimal_spec verifies remote
    # delivery before stamping the host-observed HEAD.
    monkeypatch.setattr(vigil_module.stages, "Workspace", _FakeWorkspace)
    # Spec-0074: rfc:skip 态的确定性 seed 分支（空 commit+push）——打桩记录，不真碰 git。
    monkeypatch.setattr(
        git,
        "seed_branch",
        lambda *, work_dir, branch, message: probe.worktrees.append(("seed", branch)),
    )

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


@pytest.mark.parametrize("votes", [["PASS"], ["REWORK", "PASS"], ["REWORK", "REWORK"]])
def test_design_recovery_requires_an_actual_pass(rig, tmp_path, monkeypatch, votes):
    """Spec-0090/T1: a validated/refined Spec does not approve itself."""
    rig.set_run(
        issue_number=5,
        status="pr-open",
        branch="openagents/issue-5",
        pr_number=12,
        design_digest="old",
        design_raw_digest="old-raw",
    )
    calls = []
    remaining = iter(votes)

    def review(**kwargs):
        calls.append(kwargs)
        return {
            "verdict": next(remaining),
            "reason": "retain original acceptance",
            "design_digest": "new",
            "design_raw_digest": "new-raw",
            "spec_path": "docs/specs/0001-x.md",
        }

    monkeypatch.setattr(vigil_module.stages, "architecture", review)
    monkeypatch.setattr(gates, "snapshot_head", lambda **kw: _HEAD)
    timed = _TimedBackend(inner=_Backend(), timeout_seconds=10, lock_fd=None)
    kwargs = dict(backend=timed, state=rig, work_dir=tmp_path, facts=_facts())
    if votes[-1] == "REWORK":
        with pytest.raises(gates.GateError, match="仍未获批准"):
            vigil_module._refresh_design_approval(**kwargs)
        assert rig.get_run(issue_number=5)["design_digest"] == "old"
    else:
        vigil_module._refresh_design_approval(**kwargs)
        assert rig.get_run(issue_number=5)["design_digest"] == "new"
    assert len(calls) == len(votes)
    assert all(call["backend"] is timed for call in calls)
    assert all("old-raw" in call["context_text"] for call in calls)
    assert rig.agent_names() == (["drafter"] if len(votes) == 2 else [])
    assert "merger" not in rig.agent_names()


def test_design_recovery_does_not_approve_changed_candidate(rig, tmp_path, monkeypatch):
    """Spec-0090/T1: even a PASS is invalid after the published head changes."""
    rig.set_run(
        issue_number=5,
        status="pr-open",
        branch="openagents/issue-5",
        pr_number=12,
        design_digest="old",
    )

    def changed(**kwargs):
        raise gates.MergeNotReady("candidate changed during architecture")

    monkeypatch.setattr(vigil_module, "_verify_candidate", changed)
    with pytest.raises(gates.MergeNotReady):
        vigil_module._refresh_design_approval(
            backend=_Backend(), state=rig, work_dir=tmp_path, facts=_facts()
        )
    assert rig.get_run(issue_number=5)["design_digest"] == "old"


@pytest.mark.parametrize("fixed", [True, False])
def test_integrity_repair_rechecks_the_delivered_tree(rig, tmp_path, monkeypatch, fixed):
    """Spec-0090/T1: send precise gate evidence to the writer, then verify its result."""
    checks = []

    def verify(**kwargs):
        checks.append(kwargs)
        if not fixed:
            raise gates.RepositoryIntegrityStale("still inconsistent")

    monkeypatch.setattr(gates, "assert_repository_integrity", verify)
    kwargs = dict(
        backend=_Backend(),
        state=rig,
        work_dir=tmp_path,
        config=_config(),
        facts=_facts(),
        reason="0099/T1 has an invalid dependency",
    )
    if fixed:
        vigil_module._repair_repository_integrity(**kwargs)
    else:
        with pytest.raises(gates.RepositoryIntegrityStale, match="still inconsistent"):
            vigil_module._repair_repository_integrity(**kwargs)
    assert len(checks) == 1
    assert rig.agent_names() == ["implementer"]
    placeholders = rig.agents[0][1]
    assert "invalid dependency" in (str(placeholders.get("feedback", "")) + placeholders["context"])


@pytest.fixture
def delivery_snapshot(rig, tmp_path, monkeypatch):
    """Spec-0056/0017 补充：恢复真实 assert_delivered/merge_allowed，其余沿用 rig。"""
    snapshot = {"head": _HEAD, "remote": _HEAD, "status": "", "effects": {}, "git": []}
    _issue_worktree(tmp_path, 5).mkdir(parents=True)
    compact = _issue_worktree(tmp_path, 5) / "docs" / "objectives" / "issue-5.md"
    compact.parent.mkdir(parents=True)
    compact.write_text("compact objective: finish original issue\n", encoding="utf-8")
    monkeypatch.setattr(
        vigil_module.stages,
        "minimal_design_snapshot",
        lambda **kwargs: {"design_digest": "minimal-digest", "spec_path": str(compact)},
    )

    def workspace_git(self, *, args, cwd, check):
        snapshot["git"].append(list(args))
        command = args[0]
        if command == "rev-parse":
            output = snapshot["head"] if args[1] == "HEAD" else snapshot["remote"]
        elif command == "status":
            output = snapshot["status"]
        elif command == "merge-base":
            behind = snapshot["head"] == _HEAD and snapshot["remote"] != _HEAD
            return SimpleNamespace(returncode=0 if behind else 1, stdout="", stderr="")
        elif command == "merge":
            snapshot["head"] = snapshot["remote"]
            output = ""
        elif command in {"fetch", "ls-remote", "worktree", "branch"}:
            output = ""
        else:
            # 新 IO 需显式建模，不允许靠静默放行换绿。
            raise RuntimeError(f"snapshot test has no Git stub for {args!r}")
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(Workspace, "_git", workspace_git)
    monkeypatch.setattr(git, "Workspace", Workspace)
    monkeypatch.setattr(vigil_module.stages, "Workspace", Workspace)
    monkeypatch.setattr(git, "head_sha", lambda *, work_dir: snapshot["head"])
    monkeypatch.setattr(git, "porcelain", lambda *, work_dir: snapshot["status"])
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: snapshot["head"])
    monkeypatch.setattr(gates, "assert_merge_allowed", assert_merge_allowed)
    monkeypatch.setattr(
        github,
        "pr_snapshot",
        lambda *, pr_number: github.PRSnapshot(
            number=pr_number,
            state="OPEN",
            head_sha=snapshot["remote"],
            labels=tuple(_delivery_snapshot_labels(rig=rig)),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            head_pushed_at="",
        ),
    )
    monkeypatch.setattr(
        github,
        "check_snapshot",
        lambda *, pr_number: github.CheckSnapshot(state="pass", count=1, latest_started_at=""),
    )
    run_agent = engine.run_agent

    def run_with_effect(agent_module, *, backend, **placeholders):
        report = run_agent(agent_module, backend=backend, **placeholders)
        effect = snapshot["effects"].get(agent_module.__name__.rsplit(".", 1)[-1])
        if effect is not None:
            effect()
        return report

    monkeypatch.setattr(engine, "run_agent", run_with_effect)
    return snapshot


def _delivery_snapshot_labels(*, rig):
    """Spec-0017 补充：从实际 forge 写入投影标签，不凭测试假定已经批准。"""
    labels = set()
    for name, call in rig.gh:
        if name == "add_label":
            labels.add(call["name"])
        elif name == "remove_label":
            labels.discard(call["name"])
    return labels


def _delivery_snapshot_finish(*, rig, snapshot, work_dir, config):
    """Spec-0017 补充：只用真实产生的审批驱动下一次合并，不伪造 PASS。"""
    labels = _delivery_snapshot_labels(rig=rig)
    head = snapshot["remote"]
    assert f"review-approved:{head[:7]}" in labels
    _act(
        rig=rig,
        facts=_facts(
            head_sha=head, e2e_head_sha=head, review_commit_id=head[:7], labels=frozenset(labels)
        ),
        work_dir=work_dir,
        config=config,
    )
    assert ("close_issue", {"number": 5}) in rig.gh
    assert rig.run_records[5]["status"] == "done"


@pytest.mark.parametrize(
    "flow", [agent_config.FLOW_STANDARD, agent_config.FLOW_MINIMAL, agent_config.FLOW_GENERATE_ONLY]
)
@pytest.mark.parametrize(
    "ignored_artifacts", [False, True], ids=["clean", "ignored-test-artifacts"]
)
def test_delivery_snapshot_normal_review_reaches_merge_without_extra_delivery(
    rig, delivery_snapshot, tmp_path, flow, ignored_artifacts
):
    """Spec-0017 补充：正常候选可完成；Git 已忽略的缓存不造成额外模型调用。"""
    if ignored_artifacts:
        # 此处模拟 Git 已应用 ignore 后返回空 status，不自行按文件名豁免源码。
        cache = _issue_worktree(tmp_path, 5) / ".pytest_cache"
        cache.mkdir()
        (cache / "lastfailed").write_text("{}\n")
    config = _config(flow=flow)
    _act(
        rig=rig,
        facts=_facts(review_state=None, review_commit_id=None, labels=frozenset()),
        work_dir=tmp_path,
        config=config,
    )
    _delivery_snapshot_finish(rig=rig, snapshot=delivery_snapshot, work_dir=tmp_path, config=config)

    expected = {
        agent_config.FLOW_STANDARD: ["reviewer", "merger"],
        agent_config.FLOW_MINIMAL: ["acceptance"],
        agent_config.FLOW_GENERATE_ONLY: [],
    }
    assert rig.agent_names() == expected[flow]
    assert delivery_snapshot["status"] == ""


@pytest.mark.parametrize("flow", [agent_config.FLOW_STANDARD, agent_config.FLOW_MINIMAL])
@pytest.mark.parametrize(
    "change",
    ["dirty-before", "unpushed-before", "dirty-during", "push-during", "remote-rebased-before"],
)
def test_delivery_snapshot_never_approves_a_different_candidate(
    rig, delivery_snapshot, tmp_path, flow, change
):
    """Spec-0017 补充：相同 HEAD 的脏代码、未推送提交、评审中换版都不能冒领 PASS。"""
    snapshot = delivery_snapshot
    newer = "b" * 40
    if change == "dirty-before":
        snapshot["status"] = " M entry.py\n"
    elif change == "unpushed-before":
        snapshot["head"] = newer
    elif change == "remote-rebased-before":
        snapshot["remote"] = newer

    reviewed = []

    def observe_review():
        reviewed.append((snapshot["head"], snapshot["status"]))
        if change == "dirty-during":
            snapshot["status"] = " M entry.py\n"
        elif change == "push-during":
            snapshot["head"] = snapshot["remote"] = newer

    reviewer = "reviewer" if flow == agent_config.FLOW_STANDARD else "acceptance"
    snapshot["effects"][reviewer] = observe_review
    try:
        _act(
            rig=rig,
            facts=_facts(
                head_sha=snapshot["remote"],
                e2e_head_sha=snapshot["remote"],
                review_state=None,
                review_commit_id=None,
                labels=frozenset(),
            ),
            work_dir=tmp_path,
            config=_config(flow=flow),
        )
    except (WorkspaceError, gates.GateError, gates.MergeNotReady):
        # 本用例只钉安全性：明确拒绝可以。恢复用例不吞异常，另行要求能继续完成。
        pass
    approved = [
        label
        for label in _delivery_snapshot_labels(rig=rig)
        if label.startswith("review-approved:")
    ]
    # 允许实现通过同步/续交付后重新评审恢复，但必须真正审过最后的干净候选。
    if approved:
        assert snapshot["head"] == snapshot["remote"] and not snapshot["status"]
        assert reviewed and reviewed[-1] == (snapshot["remote"], "")
        assert approved == [f"review-approved:{snapshot['remote'][:7]}"]
    assert "close_issue" not in rig.gh_names(), "评审动作不得自行结束交付"


@pytest.mark.parametrize("action", ["fix-ci", "review-rework", "draft-ready"])
def test_delivery_snapshot_dirty_work_does_not_block_development_actions(
    rig, delivery_snapshot, tmp_path, action
):
    """Spec-0017 补充：未交付是可恢复状态，不能在所有动作入口统一拒绝。"""
    delivery_snapshot["status"] = " M entry.py\n"

    def complete_existing_work():
        delivery_snapshot["status"] = ""

    delivery_snapshot["effects"]["implementer"] = complete_existing_work
    cases = {
        "fix-ci": (_facts(ci="failure"), ["implementer"]),
        "review-rework": (
            _facts(review_state="CHANGES_REQUESTED", review_commit_id=_SHA7),
            ["implementer"],
        ),
        # Gitea draft 即使报 DIRTY 也必须能先转正，不回到旧死锁。
        "draft-ready": (_facts(is_draft=True, mergeable_state="dirty"), []),
    }
    facts, agents = cases[action]
    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == agents
    assert not _delivery_snapshot_labels(rig=rig)
    assert "close_issue" not in rig.gh_names()
    assert delivery_snapshot["status"] == (" M entry.py\n" if action == "draft-ready" else "")
    assert not any(
        command[0] in {"worktree", "reset", "clean"} for command in delivery_snapshot["git"]
    ), "继续开发不能先强制重建/清理工作区"
    if action == "draft-ready":
        assert "mark_ready" in rig.gh_names()


@pytest.mark.parametrize("residue", ["uncommitted", "unpushed", "already-pushed"])
def test_delivery_snapshot_timeout_recovery_must_finish_not_just_block(
    rig, delivery_snapshot, tmp_path, residue
):
    """Spec-0056/0017 补充：超时后复用同一 PR 和工作区，最终审批最新交付并合并。"""
    snapshot = delivery_snapshot
    newer = "b" * 40

    def timeout_after_writing():
        if residue == "uncommitted":
            snapshot["status"] = " M entry.py\n"
        else:
            snapshot["head"] = newer
            if residue == "already-pushed":
                snapshot["remote"] = newer
        raise _ActTimeout("implementation invocation exceeded 1800s before returning")

    snapshot["effects"]["implementer"] = timeout_after_writing
    with pytest.raises(_ActTimeout):
        _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert rig.run_records[5]["pr_number"] == 12
    snapshot["git"].clear()
    rig.agents.clear()

    def finish_delivery():
        snapshot["head"] = snapshot["remote"] = newer
        snapshot["status"] = ""

    # 模型替身会成功续交付；只有框架真正调了已有角色才会发生，不由测试手动纠正状态。
    snapshot["effects"].update(implementer=finish_delivery, deliver=finish_delivery)
    facts = _facts(
        head_sha=snapshot["remote"],
        e2e_head_sha=snapshot["remote"],
        review_state=None,
        review_commit_id=None,
        labels=frozenset(),
        is_draft=True,
        mergeable_state="dirty",
    )
    _act(rig=rig, facts=facts, work_dir=tmp_path)
    assert "mark_ready" in rig.gh_names()

    for _ in range(4):
        _act(
            rig=rig,
            facts=_facts(
                head_sha=snapshot["remote"],
                e2e_head_sha=snapshot["remote"],
                review_state=None,
                review_commit_id=None,
                labels=frozenset(_delivery_snapshot_labels(rig=rig)),
            ),
            work_dir=tmp_path,
        )
        if any(
            label.startswith("review-approved:") for label in _delivery_snapshot_labels(rig=rig)
        ):
            break

    assert snapshot["remote"] == newer and snapshot["status"] == "", (
        "被挡住后必须续交付，而非永久停住或审批 Spec-only 提交"
    )
    assert sum(name == "create_pr" for name in rig.gh_names()) == 1
    assert not any(command[0] in {"worktree", "reset", "clean"} for command in snapshot["git"])
    if residue == "already-pushed":
        # A timeout lost the completion result. Verify once through the original developer;
        # the same commit is accepted and no extra delivery/empty commit is requested.
        assert rig.agent_names() == ["implementer", "reviewer"]
    else:
        assert any(name in {"implementer", "deliver"} for name in rig.agent_names())
    _delivery_snapshot_finish(rig=rig, snapshot=snapshot, work_dir=tmp_path, config=_config())


@pytest.mark.parametrize("implementation_result", ["uncommitted", "already-pushed", "commit-only"])
def test_delivery_snapshot_first_implementation_handoff_reaches_merge(
    rig, delivery_snapshot, tmp_path, monkeypatch, implementation_result
):
    """Spec-0056 补充：正常开发交接不仅要接住未提交，还要接住已提交但未推送。"""
    snapshot = delivery_snapshot
    newer = "b" * 40

    def implement():
        if implementation_result == "uncommitted":
            snapshot["status"] = " M entry.py\n"
        else:
            snapshot["head"] = newer
            if implementation_result == "already-pushed":
                snapshot["remote"] = newer

    def deliver():
        snapshot["head"] = snapshot["remote"] = newer
        snapshot["status"] = ""

    snapshot["effects"].update(implementer=implement, deliver=deliver)
    monkeypatch.setitem(_AGENT_OUTPUTS, "deliver", _AGENT_OUTPUTS["deliver"] | {"head_sha": newer})
    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert snapshot["head"] == snapshot["remote"] == newer and not snapshot["status"]
    expected = ["drafter", "implementer"]
    if implementation_result != "already-pushed":
        expected.append("deliver")
    assert rig.agent_names() == expected
    _act(rig=rig, facts=_facts(is_draft=True), work_dir=tmp_path)
    _act(
        rig=rig,
        facts=_facts(
            head_sha=newer,
            e2e_head_sha=newer,
            review_state=None,
            review_commit_id=None,
            labels=frozenset(),
        ),
        work_dir=tmp_path,
    )
    _delivery_snapshot_finish(rig=rig, snapshot=snapshot, work_dir=tmp_path, config=_config())


@pytest.mark.parametrize(
    "change,in_flight,expected",
    [
        ({"ci": "pending"}, False, _ACT_SOLVE),
        ({"ci": "failure"}, False, _ACT_SOLVE),
        ({"mergeable_state": "unknown"}, False, _ACT_SOLVE),
        ({"merged": True}, False, None),
        ({"closed": True}, False, None),
        ({"labels": frozenset({"automation-failed"})}, False, None),
        ({"deps_done": False}, False, None),
        ({}, True, None),
        ({"latest_comment_is_ours": False}, False, _ACT_REPLY),
        ({"is_draft": True}, False, _ACT_READY),
    ],
)
def test_pending_delivery_priority_preserves_existing_stop_conditions(
    rig, change, in_flight, expected
):
    """Spec-0056: unfinished development precedes CI, not stop/reply/dependency rules."""
    rig.run_records[5] = {"status": "iterating", "pr_number": 12}
    facts = _facts(**change)
    verdict = _classify(facts=facts, in_flight=in_flight)
    resumed = vigil_module._resume_verdict(state=rig, facts=facts, verdict=verdict)
    assert resumed.action == expected
    if expected != _ACT_SOLVE:
        assert resumed == verdict


def test_merger_reports_failure_does_not_close_issue_or_mark_done(rig, tmp_path, monkeypatch):
    """Spec-0017: a rejected native merge must remain retryable, not become a false done."""
    monkeypatch.setitem(
        _AGENT_OUTPUTS, "merger", {"merged": False, "summary": "head changed before write"}
    )
    with pytest.raises(gates.MergeNotReady):
        _act(rig=rig, facts=_facts(), work_dir=tmp_path, config=_config())
    assert "close_issue" not in rig.gh_names()
    assert not any(record.get("status") == "done" for record in rig.run_records.values())


def test_producer_enqueues_pending_delivery_even_while_ci_waits(rig, tmp_path, monkeypatch):
    """Spec-0056: recovery must be reachable through the real producer, not just direct _act."""
    rig.run_records[5] = {"status": "iterating", "pr_number": 12}
    observed = _Observed(facts=_facts(ci="pending"), clock=_Clock(last_progress_at=_NOW))
    monkeypatch.setattr(vigil_module, "_sense", lambda **kw: observed)
    # A pre-existing no-progress stamp on this Git head must not suppress local phase recovery.
    monkeypatch.setattr(vigil_module, "_has_attempt_stamp", lambda **kw: True)
    conn = sqlite3.connect(":memory:")
    conn.executescript(vigil_module._SCHEMA)
    try:
        enqueued = vigil_module._consider(
            conn=conn,
            state=rig,
            subject="issue:5",
            config=_config(),
            work_dir=tmp_path,
            in_flight={},
            priority_fn=lambda **kw: 0,
            thresholds={},
            quiet_counts={},
            now=_NOW,
            agent_id="test",
        )
        assert enqueued == 1
        assert conn.execute("SELECT subject, status FROM work_queue").fetchall() == [
            ("issue:5", "queued")
        ]
    finally:
        conn.close()


@pytest.mark.parametrize("stage", ["review", "e2e", "merge"])
def test_skipped_reader_does_not_trigger_delivery_recovery(rig, tmp_path, stage):
    """Spec-0056: checking a candidate must not bypass an explicit skipped stage."""
    rig.delivered = False
    changes = {}
    if stage == "review":
        changes = {"review_state": None, "review_commit_id": None}
    elif stage == "e2e":
        changes = {"e2e_head_sha": None}
    _act(
        rig=rig,
        facts=_facts(**changes),
        work_dir=tmp_path,
        config=_config(stages=_stages_policy(**{stage: "skip"})),
    )
    assert not rig.agents
    assert not rig.worktrees


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
    assert "comment_body" not in placeholders
    assert placeholders["context"].count("这里为什么这么写？") == 1
    assert rig.comments == [(12, "已回应你的问题", "bot")]
    assert rig.cursors == [(12, "2026-07-14T11:00:00Z")]
    assert summary == "已回应你的问题"


def test_act_solve_cuts_a_vertical_slice_and_never_blocks_on_ci(rig, tmp_path):
    """分支④：还没有 PR → worktree → rfc(drafter) → 开 draft PR → implement → deliver。

    **不在此阻塞等 CI/review**：那两支是 `_classify` 的⑦⑩，回到 `_reconcile` 的循环自然会走到——故这里
    绝不该出现 reviewer/tester。

    Spec-0017/T2：`_do_solve` **不再确定性直调 `github.mark_ready`**——转正归 deliver agent（其完成判据含
    「PR 非 draft」）；脱靶残留 draft 由 `_classify` ⑪ 兜底转正。故 gh 调用流水里不再有 `mark_ready`。
    """
    rig.delivered = False  # Developer leaves changes for the existing delivery role.
    facts = _facts(pr_number=None)
    assert _classify(facts=facts, in_flight=False).action == _ACT_SOLVE

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["drafter", "implementer", "deliver"]
    assert [call for call in rig.worktrees if call[0] == "prepare"] == [
        ("prepare", 5, "openagents/issue-5", "main")
    ]
    worktree = _issue_worktree(tmp_path, 5)
    assert rig.agents[1][1]["work_dir"] == worktree  # implementer 在隔离 worktree 里写码
    assert rig.agents[1][1]["issue_number"] == 5
    assert rig.gh_names() == ["get_issue", "create_pr"]  # Spec-0017/T2: 不再直调 mark_ready
    assert "mark_ready" not in rig.gh_names()
    assert rig.runs[-1] == (5, "pr-open", "openagents/issue-5", 12)
    assert all(call[1] == "iterating" for call in rig.runs[:-1])


def test_soft_advice_reaches_developer_alongside_unchanged_original_issue(rig, tmp_path):
    from openagents.runtime import preflight

    issue = github.Issue(5, "标题", "issue 正文", [])
    preflight.write(
        work_dir=tmp_path,
        data={
            "version": 1,
            "fingerprints": {"5": preflight.fingerprint(issue=issue)},
            "plan": {"notes": [{"issues": [5], "advice": "inspect shared loop before reuse"}]},
        },
    )
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(coordination="soft"),
    )
    draft = rig.context_of(agent="drafter")
    implementation = rig.context_of(agent="implementer")
    assert "issue 正文" in draft
    assert "inspect shared loop before reuse" in draft
    assert "inspect shared loop before reuse" in implementation
    assert implementation.count("issue 正文") == 1
    assert "NOT requirements or blockers" in implementation


@pytest.mark.parametrize("body_repeats_title", [False, True])
def test_solve_keeps_long_issue_title_out_of_task(rig, tmp_path, monkeypatch, body_repeats_title):
    """Keep long issue text in context, including when the body repeats its title."""
    title = "diagnose workspace topology and recover historical evidence " * 2
    body = (
        f"Question:\n\n{title}\n\nEvidence required."
        if body_repeats_title
        else "Evidence required."
    )
    issue = github.Issue(5, title, body, [])
    monkeypatch.setattr(vigil_module.github, "get_issue", lambda *, number: issue)
    recording_run = engine.run_agent

    def validate_and_record(agent_module, *, backend, **placeholders):
        if agent_module.__name__.rsplit(".", 1)[-1] == "drafter":
            task = agent_module.PROMPT.substitute(**placeholders)
            assert placeholders["target"] == "issue #5"
            assert title not in task
            assert title in placeholders["context"]
            assert body in placeholders["context"]
            engine._assert_single_copy(
                task=task, context=placeholders["context"], values=placeholders, role="drafter"
            )
        return recording_run(agent_module, backend=backend, **placeholders)

    monkeypatch.setattr(engine, "run_agent", validate_and_record)
    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert "drafter" in rig.agent_names()


def test_act_solve_skips_delivery_agent_when_implementer_already_pushed(rig, tmp_path, monkeypatch):
    heads = iter(["draft-before", "draft-after", "impl-before", "impl-after"])
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: next(heads))

    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)

    assert rig.agent_names() == ["drafter", "implementer"]
    assert (
        "assert-delivered",
        _issue_worktree(tmp_path, 5),
        "openagents/issue-5",
    ) in rig.worktrees


def test_minimal_flow_role_sequence_is_exactly_three_subjective_calls(rig, tmp_path, monkeypatch):
    heads = iter(["spec-before", _HEAD, "impl-before", _HEAD])
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: next(heads))
    config = _config(flow=agent_config.FLOW_MINIMAL)

    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path, config=config)
    assert rig.agent_names() == ["spec_writer", "implementer"]
    assert "issue 正文" in rig.context_of(agent="implementer")
    assert "objective contract" in rig.context_of(agent="implementer")
    assert "严禁 cd /work/harness" in rig.context_of(agent="implementer")

    _act(
        rig=rig,
        facts=_facts(review_state=None, review_commit_id=None, labels=frozenset()),
        work_dir=tmp_path,
        config=config,
    )
    assert rig.agent_names() == ["spec_writer", "implementer", "acceptance"]

    _act(rig=rig, facts=_facts(), work_dir=tmp_path, config=config)
    assert rig.agent_names() == ["spec_writer", "implementer", "acceptance"]
    assert "merger" not in rig.agent_names()
    assert ("merge_pr", {"pr_number": 12, "head_sha": _HEAD}) in rig.gh


def test_generate_only_flow_specs_executes_and_merges_without_validation(
    rig, tmp_path, monkeypatch
):
    heads = iter(["spec-before", _HEAD, "exec-before", _HEAD])
    monkeypatch.setattr(gates, "snapshot_head", lambda *, workspace: next(heads))
    monkeypatch.setattr(
        gates,
        "assert_repository_integrity",
        lambda *, workspace: (_ for _ in ()).throw(
            AssertionError("generate-only must not run the repository-wide Spec gate")
        ),
    )
    config = _config(flow=agent_config.FLOW_GENERATE_ONLY)

    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path, config=config)
    assert rig.agent_names() == ["spec_writer", "executor"]
    assert "compact objective spec" in rig.context_of(agent="executor")
    assert "original issue" in rig.context_of(agent="executor")

    _act(
        rig=rig,
        facts=_facts(review_state=None, review_commit_id=None, labels=frozenset()),
        work_dir=tmp_path,
        config=config,
    )
    assert rig.agent_names() == ["spec_writer", "executor"]

    _act(rig=rig, facts=_facts(), work_dir=tmp_path, config=config)
    assert rig.agent_names() == ["spec_writer", "executor"]
    assert ("merge_pr", {"pr_number": 12, "head_sha": _HEAD}) in rig.gh


def test_minimal_spec_blocked_stops_before_pr_and_implementation(rig, tmp_path, monkeypatch):
    monkeypatch.setitem(
        _AGENT_OUTPUTS,
        "spec_writer",
        {
            "status": "BLOCKED",
            "head_sha": "",
            "summary": "cannot preserve objective",
            "blocker": "read-only boundary",
            "objective_coverage": [],
            "candidate_assessments": [],
            "selected_intervention": {},
            "evidence_pack": [],
            "falsifiers": [],
        },
    )
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(flow=agent_config.FLOW_MINIMAL),
    )
    assert rig.agent_names() == ["spec_writer"]
    assert "create_pr" not in rig.gh_names()
    assert ("issue_add_label", {"number": 5, "name": github.AUTOMATION_FAILED_LABEL}) in rig.gh


def test_minimal_spec_partial_stops_before_pr_and_implementation(rig, tmp_path, monkeypatch):
    monkeypatch.setitem(
        _AGENT_OUTPUTS,
        "spec_writer",
        {
            "status": "PARTIAL",
            "head_sha": _HEAD,
            "summary": "useful but incomplete",
            "blocker": "one objective is unclosed",
            "objective_coverage": [{"scope_coverage": "PARTIAL", "evidence_level": "HYPOTHESIS"}],
            "candidate_assessments": [
                {
                    "candidate": "one",
                    "ownership": "model",
                    "delivery": "unknown",
                    "control_effect": "unknown",
                    "evidence": "none",
                    "assumptions": "compliance",
                    "failure_modes": "ignored",
                    "verdict": "selected",
                }
            ],
            "selected_intervention": {},
            "evidence_pack": [],
            "falsifiers": [],
        },
    )
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(flow=agent_config.FLOW_MINIMAL),
    )
    assert rig.agent_names() == ["spec_writer"]
    assert "create_pr" not in rig.gh_names()
    assert ("issue_add_label", {"number": 5, "name": github.AUTOMATION_FAILED_LABEL}) in rig.gh


def test_minimal_partial_acceptance_never_reworks_or_merges(rig, tmp_path, monkeypatch):
    monkeypatch.setitem(
        _AGENT_OUTPUTS,
        "acceptance",
        {"verdict": "PARTIAL", "reason": "hard half missing", "evidence": ["replay"]},
    )
    _act(
        rig=rig,
        facts=_facts(review_state=None, review_commit_id=None, labels=frozenset()),
        work_dir=tmp_path,
        config=_config(flow=agent_config.FLOW_MINIMAL),
    )
    assert rig.agent_names() == ["acceptance"]
    assert "implementer" not in rig.agent_names()
    assert "merge_pr" not in rig.gh_names()
    assert ("issue_add_label", {"number": 5, "name": github.AUTOMATION_FAILED_LABEL}) in rig.gh


def test_minimal_ci_failure_stops_without_second_implementation(rig, tmp_path):
    _act(
        rig=rig,
        facts=_facts(ci="failure"),
        work_dir=tmp_path,
        config=_config(flow=agent_config.FLOW_MINIMAL),
    )
    assert rig.agent_names() == []
    assert ("issue_add_label", {"number": 5, "name": github.AUTOMATION_FAILED_LABEL}) in rig.gh


def test_act_solve_skips_rfc_when_that_stage_is_skipped(rig, tmp_path):
    """`rfc: skip` = 不设此闸 → 不派 drafter，但 PR/implement/deliver 照常（`skip` 关的是闸，不是活）。

    Spec-0074 实证修复：skip 态没有 drafter 落「首个 commit + push」，远端无 head 分支 → create_pr
    404。确定性 seed 分支（git.seed_branch 空 commit + push）必须在 create_pr 之前补位。
    """
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(stages=_stages_policy(rfc="skip")),
    )
    assert rig.agent_names() == ["implementer"]  # Fixture already pushed; no redundant deliver.
    assert ("seed", "openagents/issue-5") in rig.worktrees  # 无它 create_pr 404


def test_act_solve_agent_rfc_does_not_seed_branch(rig, tmp_path):
    """rfc=agent 态首个 commit+push 归 drafter 交付协议——seed 分支不该多此一举。"""
    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert all(record[0] != "seed" for record in rig.worktrees)


def test_retired_architecture_owner_is_rejected_before_implementer(rig, tmp_path) -> None:
    with pytest.raises(ValueError, match="未知 stage owner"):
        _act(
            rig=rig,
            facts=_facts(pr_number=None),
            work_dir=tmp_path,
            config=_config(stages=_stages_policy(architecture="human")),
        )
    assert rig.agent_names() == ["drafter"]


def test_architecture_rework_refines_before_implementer(rig, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        vigil_module.stages,
        "architecture",
        lambda **kwargs: {
            "verdict": "REWORK",
            "reason": "wrong layer",
            "design_digest": "a",
            "spec_path": "docs/specs/0001-x.md",
        },
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "design_snapshot",
        lambda **kwargs: {
            "design_digest": "b",
            "design_raw_digest": "raw-b",
            "spec_path": "docs/specs/0001-x.md",
        },
    )
    _act(rig=rig, facts=_facts(pr_number=None), work_dir=tmp_path)
    assert rig.agent_names()[:3] == ["drafter", "drafter", "implementer"]
    assert rig.run_records[5]["design_raw_digest"] == "raw-b"


def test_solve_reuses_drafter_evidence_for_architect_and_implementer(
    rig, tmp_path, monkeypatch
) -> None:
    evidence_pack = [
        {
            "fact": "timeout is polled",
            "path": "entry.py",
            "symbol": "_run_supervised",
            "verification": "read body",
        }
    ]
    monkeypatch.setitem(_AGENT_OUTPUTS["drafter"], "evidence_pack", evidence_pack)
    captured = {}

    def _architecture(**kwargs):
        captured.update(kwargs)
        return {
            "verdict": "PASS",
            "reason": "ok",
            "design_digest": "approved",
            "design_raw_digest": "raw-approved",
            "spec_path": "docs/specs/0001-x.md",
        }

    monkeypatch.setattr(vigil_module.stages, "architecture", _architecture)
    _act(
        rig=rig,
        facts=_facts(pr_number=None),
        work_dir=tmp_path,
        config=_config(stages=_stages_policy(architecture="agent")),
    )

    assert captured["evidence_pack"] == evidence_pack
    implement_call = next(payload for name, payload in rig.agents if name == "implementer")
    assert "timeout is polled" in implement_call["context"]
    assert rig.run_records[5]["evidence_pack"] == evidence_pack
    assert rig.run_records[5]["design_raw_digest"] == "raw-approved"


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
    assert placeholders["rebase_onto"] == "main"
    assert placeholders["work_dir"] == _issue_worktree(tmp_path, 5)
    assert [call for call in rig.worktrees if call[0] == "prepare"] == [
        ("prepare", 5, "branch-of-pr-12", "main")
    ]


def test_act_rebase_preserves_unpublished_worktree(rig, tmp_path):
    """Dirty/diverged local work is never destroyed by conflict preparation."""
    rig.delivered = False
    _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)

    assert [call for call in rig.worktrees if call[0] == "prepare"] == []
    assert [call for call in rig.worktrees if call[0] == "sync-delivered"]


def test_act_rebase_turns_unresolved_delivery_into_bounded_failure(rig, tmp_path, monkeypatch):
    """A resolver that did not publish must requeue/park; it cannot look like success."""
    monkeypatch.setattr(
        vigil_module.stages,
        "conflict",
        lambda **kwargs: {"delivered": False, "reason": "仍有语义资源冲突"},
    )
    with pytest.raises(WorkspaceError, match="conflict_fp="):
        _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)


def test_conflict_context_contains_snapshot_and_deterministic_protocol(rig, tmp_path):
    """The resolver receives enough bounded evidence to inspect only this conflict."""
    _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)
    prompt = rig.context_of(agent="deliver")
    assert "conflict snapshot" in prompt
    assert "conflict_fingerprint" in prompt
    assert "重复 spec 编号" in prompt
    assert (
        _conflict_fingerprint(
            # Resolver attempts refresh the forge snapshot first, so this fixture's
            # dirty input is replaced by the mocked clean remote state.
            facts=_facts(mergeable_state="clean"),
            base="main",
            branch="branch-of-pr-12",
        )
        in prompt
    )


def test_act_fix_ci_feeds_failing_check_logs_to_implementer(rig, tmp_path):
    """分支⑧：当前 head 上 CI 红 → 把失败 check 的日志喂给 implementer 去修（在该 PR 的 worktree 里）。"""
    facts = _facts(ci="failure")
    assert _classify(facts=facts, in_flight=False).action == _ACT_FIX_CI

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["implementer"]
    placeholders = rig.agents[0][1]
    assert "feedback" not in placeholders
    assert placeholders["context"].count("FAILED tests/test_x.py::test_y") == 1
    assert placeholders["pr_number"] == 12
    assert placeholders["work_dir"] == _issue_worktree(tmp_path, 5)
    assert [call for call in rig.worktrees if call[0] == "ensure"] == [
        ("ensure", 5, "openagents/issue-5")
    ]
    assert rig.run_records[5]["status"] == "pr-open"


def test_act_e2e_stamps_evidence_with_the_head_it_was_run_against(rig, tmp_path):
    """分支⑨：派 tester；PASS → 贴一条**带 head 溯源戳**的证据评论（戳里的 head 就是这一版代码的 head）。"""
    facts = _facts(e2e_head_sha=None)
    rig.run_records[5] = {"evidence_pack": [{"fact": "timeout is polled", "path": "entry.py"}]}
    assert _classify(facts=facts, in_flight=False).action == _ACT_E2E

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["tester"]
    assert rig.agents[0][1]["work_dir"] == _issue_worktree(tmp_path, 5)
    assert "timeout is polled" in rig.agents[0][1]["context"]
    assert len(rig.comments) == 1
    pr_number, body, agent_id = rig.comments[0]
    assert (pr_number, agent_id) == (12, "bot")
    assert body.startswith(f"{vigil_module._E2E_MARKER}{_HEAD} -->")


def test_act_e2e_never_stamps_evidence_when_the_run_failed(rig, tmp_path, monkeypatch):
    """tester 判 REWORK → **不盖戳**（盖了就等于用一份失败的证据放行——张冠李戴的另一面）。"""
    monkeypatch.setitem(
        _AGENT_OUTPUTS, "tester", {"verdict": "REWORK", "reason": "e2e 挂了", "evidence": []}
    )
    _act(rig=rig, facts=_facts(e2e_head_sha=None), work_dir=tmp_path)
    assert rig.agent_names() == ["tester"]
    assert rig.comments == [], "e2e 没过还盖证据戳 = 拿失败的证据放行"


def test_act_review_dispatches_reviewer_and_binds_the_verdict_to_the_head_sha(rig, tmp_path):
    """分支⑩：无裁决 → 派 reviewer；裁决落 label 时**把当前 head 的 sha7 嵌进 label 名**（裁决绑 commit）。"""
    facts = _facts(review_state=None, review_commit_id=None, labels=frozenset())
    rig.run_records[5] = {"evidence_pack": [{"fact": "timeout is polled", "path": "entry.py"}]}
    assert _classify(facts=facts, in_flight=False).action == _ACT_REVIEW_OR_FIX

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["reviewer"]
    assert rig.agents[0][1]["work_dir"] == _issue_worktree(tmp_path, 5)
    assert "timeout is polled" in rig.agents[0][1]["context"]
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
    assert rig.review_feedback[5] == {"head_sha": _HEAD, "reason": "要改"}


def test_act_review_or_fix_sends_changes_requested_back_to_implementer(rig, tmp_path):
    """分支⑩另一半：已是 `CHANGES_REQUESTED@当前 head` → 派 implementer 改代码（**不再重审一遍**）。"""
    facts = _facts(
        review_state="CHANGES_REQUESTED",
        review_commit_id=_SHA7,
        labels=frozenset({f"review-changes-requested:{_SHA7}"}),
    )
    rig.run_records[5] = {"evidence_pack": [{"fact": "timeout is polled", "path": "entry.py"}]}
    rig.review_feedback[5] = {"head_sha": _HEAD, "reason": "必须运行 live GLM 验证 BC1-BC3"}
    assert _classify(facts=facts, in_flight=False).action == _ACT_REVIEW_OR_FIX

    _act(rig=rig, facts=facts, work_dir=tmp_path)

    assert rig.agent_names() == ["implementer"]
    assert "feedback" not in rig.agents[0][1]
    assert "[review]" in rig.agents[0][1]["context"]
    assert "live GLM 验证 BC1-BC3" in rig.agents[0][1]["context"]
    assert "timeout is polled" in rig.agents[0][1]["context"]


def test_act_ready_promotes_residual_draft_via_mark_ready(rig, tmp_path):
    """分支⑪（Spec-0017/T2）：全绿+approved@head 但仍 draft → 确定性 `github.mark_ready` 转正（level-triggered 安全网）。

    零判断的机械动作，**不派任何 agent**（为何不派新 promoter agent 见 Spec-0017 Rationale）；happy-path
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
    """分支⑫（Spec-0017/T2/T3）：全绿 + approved@head + 非 draft → 经确定性硬闸放行后**下放 merger agent** 合并 + 关 issue + 置 done。

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


@pytest.mark.parametrize("budget", ["5400.5", "0"])
def test_act_wraps_the_backend_in_a_timed_backend_on_every_agent_branch(
    rig, tmp_path, monkeypatch, budget
):
    """每个派 agent 的分支拿到的都必须是 `_TimedBackend`——裸 backend 挂死了没人管（flock 判不出这种死法）。"""
    monkeypatch.setenv("OPENAGENTS_CLAUDE_MAX_WALL", budget)
    _act(rig=rig, facts=_facts(ci="failure"), work_dir=tmp_path)
    assert rig.backends and all(isinstance(backend, _TimedBackend) for backend in rig.backends)
    assert all(backend._timeout_seconds == float(budget) for backend in rig.backends)


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
def test_act_rejects_retired_stage_owner(rig, tmp_path, stage, overrides):
    with pytest.raises(ValueError, match="未知 stage owner"):
        _act(
            rig=rig,
            facts=_facts(**overrides),
            work_dir=tmp_path,
            config=_config(stages=_stages_policy(**{stage: "hu" + "man"})),
        )
    assert rig.agents == []


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
def test_autonomous_contract_reaches_every_agent_invoking_branch(rig, tmp_path, overrides, agent):
    """**主路径收口的前提**：agent 看不到这条契约，就不会返回结构化交人请求——兜底当场变成主路径。

    断言打在 `engine.run_agent` 这个唯一的派 agent 出口上（stage 内部怎么组占位符都逃不掉）。`_do_reply`
    与 `_do_rebase` 曾漏掉它——它们分别是「答不了人的提问」和「解不动冲突」，恰恰是最该主动交人的两支。
    """
    _act(rig=rig, facts=_facts(**overrides), work_dir=tmp_path)
    assert agent in rig.agent_names()
    assert _AUTONOMOUS_CONTRACT in rig.context_of(agent=agent)


def test_autonomous_contract_reaches_the_replier(rig, tmp_path):
    """回归：`_do_reply` 的契约拼在**人的那条评论正文之后**（既给回应对象、也给一等出口）。"""
    _act(rig=rig, facts=_facts(latest_comment_is_ours=False), work_dir=tmp_path)
    context = rig.context_of(agent="replier")
    assert context == f"--- human comment ---\n这里为什么这么写？{_AUTONOMOUS_CONTRACT}"


def test_autonomous_contract_reaches_the_conflict_resolver(rig, tmp_path):
    """回归：`_do_rebase` 经 `stages.conflict(context_text=…)` 把契约透传进 deliver agent 的上下文。"""
    _act(rig=rig, facts=_facts(mergeable_state="dirty"), work_dir=tmp_path)
    assert _AUTONOMOUS_CONTRACT in rig.context_of(agent="deliver")


def test_autonomous_contract_forbids_forge_writes_and_keeps_role_schema():
    assert "本角色既有 JSON schema" in _AUTONOMOUS_CONTRACT
    assert "不要空转" in _AUTONOMOUS_CONTRACT
    assert "自行修改 forge 标签" in _AUTONOMOUS_CONTRACT
    assert vigil_module._LABEL_AUTOMATION_FAILED == github.AUTOMATION_FAILED_LABEL


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
        with pytest.raises(_ActTimeout, match="424242") as exc:
            _TimedBackend(inner=backend, timeout_seconds=1, lock_fd=None).run(
                work_dir=Path("."), task="t", context="c"
            )
        assert killed == [(424_242, None)], "只许杀本次 agent 调用自报的进程树"
        assert "时间预算耗尽" in str(exc.value)
        assert "挂死" not in str(exc.value)
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


@pytest.mark.parametrize("budget", ["0", "-1"])
def test_disabled_budget_waits_for_completion_and_keeps_tracking(monkeypatch, killed, budget):
    """Spec-0046: disabling the shared budget must not become join(timeout=0)."""
    monkeypatch.setenv("OPENAGENTS_CLAUDE_MAX_WALL", budget)
    release = threading.Event()
    timer = threading.Timer(0.05, release.set)

    class Waiting:
        def run(self, *, work_dir, task, context):
            self.thread_id = threading.get_ident()
            proc.publish(pid=424_246)
            assert release.wait(timeout=2)
            return "finished"

    backend = Waiting()
    timer.start()
    try:
        result = _TimedBackend(
            inner=backend, timeout_seconds=vigil_module.effective_max_wall(), lock_fd=None
        ).run(work_dir=Path("."), task="t", context="c")
        assert result == "finished"
        assert not killed
        assert backend.thread_id not in proc._TRACKED
    finally:
        release.set()
        timer.join(timeout=2)


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
