"""# Spec-0066/T2: vigil 旁路埋点针对性单测（假 backend/github seam，不触真实 LLM/网络/仓库）。

覆盖：`_phase_of` 对四值 verdict × facts 逐态归一（TERMINAL 细分 merged/closed/needs-human；QUIET 取
reason；ACTIONABLE 取 action；IN_FLIGHT→in-flight）；`_consider` 跑一 tick 后 timing.jsonl 生成、含
dispatch(solve)/等待(awaiting-*)/合并各段；record 抛异常时 `_consider` 照常返回（容错端到端）；`_fingerprint`
埋点前后相等（旁路不进 fp、不触护栏一自毁）；合并段 awaiting-ci（CI-wait）与 review-or-fix（review-wait）可区分。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import (
    _ACT_FIX_CI,
    _ACT_MERGE,
    _ACT_SOLVE,
    _ACTIONABLE,
    _AWAITING_CI,
    _AWAITING_EFFECT,
    _IN_FLIGHT,
    _QUIET,
    _TERMINAL,
    _Clock,
    _connect,
    _consider,
    _Facts,
    _fingerprint,
    _init_db,
    _Observed,
    _phase_of,
    _Verdict,
)
from openagents.runtime import timing
from openagents.utils import agent_config, github

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_HEAD = "abc1234def5678901234567890123456789abcde"
_SHA7 = _HEAD[:7]


def _facts(**overrides) -> _Facts:
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


def _config(**overrides) -> agent_config.AgentConfig:
    defaults = {
        "version": 1,
        "agents": agent_config.AgentPolicy(backends={}),
        "stages": agent_config.StagePolicy(owners={}),
        "release": agent_config.ReleasePolicy(),
        "interval": 60,
        "base": "main",
        "labels": ["openagents"],
        "repos": [],
    }
    return agent_config.AgentConfig(**(defaults | overrides))


def _db(tmp_path: Path):
    db_path = tmp_path / ".openagents" / "vigil-queue.db"
    _init_db(db_path=db_path)
    return _connect(db_path=db_path)


def _stub_sense(monkeypatch, *, facts: _Facts, comments=()):
    monkeypatch.setattr(
        vigil_module,
        "_sense",
        lambda *, config, subject: _Observed(facts=facts, clock=_Clock(last_progress_at=_NOW)),
    )
    monkeypatch.setattr(vigil_module.github, "list_comments", lambda *, pr_number: list(comments))
    # solve 段（pr_number=None）的护栏一读侧走 issue 评论——同样打桩，杜绝真触网。
    monkeypatch.setattr(
        vigil_module.github, "list_issue_comments", lambda *, number: list(comments)
    )


def _consider_once(conn, *, subject, work_dir, in_flight=None) -> int:
    return _consider(
        conn=conn,
        subject=subject,
        config=_config(),
        work_dir=work_dir,
        in_flight=in_flight or {},
        priority_fn=vigil_module._priority_default,
        thresholds=dict(vigil_module._WATCHDOG_DEFAULTS),
        quiet_counts={},
        now=_NOW,
        agent_id="vigil-1",
    )


def _timing_events(work_dir: Path):
    return timing.load_events(path=work_dir / ".openagents" / timing.TIMING_FILENAME)


# --------------------------------------------------------------------------------------------------
# _phase_of：四值 verdict × facts 逐态归一。
# --------------------------------------------------------------------------------------------------


def test_phase_of_in_flight():
    assert _phase_of(verdict=_Verdict(kind=_IN_FLIGHT), facts=_facts()) == "in-flight"


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"merged": True}, "merged"),
        ({"closed": True}, "closed"),
        ({"labels": frozenset({"automation-failed"})}, "automation-failed"),
    ],
)
def test_phase_of_terminal_subdivides_by_facts(overrides, expected):
    """TERMINAL 据 facts 细分 merged/closed/automation-failed。"""
    assert _phase_of(verdict=_Verdict(kind=_TERMINAL), facts=_facts(**overrides)) == expected


def test_phase_of_quiet_takes_reason():
    verdict = _Verdict(kind=_QUIET, reason=_AWAITING_CI)
    assert _phase_of(verdict=verdict, facts=_facts()) == "awaiting-ci"


def test_phase_of_actionable_takes_action():
    verdict = _Verdict(kind=_ACTIONABLE, action=_ACT_FIX_CI)
    assert _phase_of(verdict=verdict, facts=_facts()) == "fix-ci"


# --------------------------------------------------------------------------------------------------
# _consider 旁路：timing.jsonl 生成、含 dispatch(solve)/等待/合并各段；issue/pr 归属。
# --------------------------------------------------------------------------------------------------


def test_consider_stamps_dispatch_solve_phase(tmp_path, monkeypatch):
    """还没有 PR → ACTIONABLE:solve → timing.jsonl 落一条 solve 事件（dispatch 段），带 issue 归属。"""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts(pr_number=None))
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    events = _timing_events(tmp_path)
    assert len(events) == 1
    assert events[0]["phase"] == _ACT_SOLVE
    assert events[0]["subject"] == "issue:5"
    assert events[0]["issue"] == 5


def test_consider_stamps_merge_phase_with_pr_attribution(tmp_path, monkeypatch):
    """全绿 + APPROVED → ACTIONABLE:merge；issue subject 的 pr 归属取 facts.pr_number。"""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts())
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    (event,) = _timing_events(tmp_path)
    assert event["phase"] == _ACT_MERGE
    assert (event["issue"], event["pr"]) == (5, 12)


def test_consider_bare_pr_subject_has_null_issue(tmp_path, monkeypatch):
    """裸 PR subject（pr:12）→ issue 归属为 null，pr 取 subject 号。"""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts(subject="pr:12"))
    _consider_once(conn, subject="pr:12", work_dir=tmp_path)
    (event,) = _timing_events(tmp_path)
    assert event["issue"] is None
    assert event["pr"] == 12


def test_consider_merge_segment_distinguishes_ci_wait_from_review_wait(tmp_path, monkeypatch):
    """合并段咽喉：CI pending → awaiting-ci（CI-wait）；review 陈旧 → review-or-fix（review-wait）。
    两者是不同 phase，不再糊成旧栈的一段 `open`——这是本 issue 价值的核心。"""
    conn = _db(tmp_path)
    # ① CI 排队。
    _stub_sense(monkeypatch, facts=_facts(ci="pending"))
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    # ② review 陈旧（裁决绑旧 sha）→ review-or-fix。
    stale = _facts(review_commit_id="0000000", labels=frozenset({"review-approved:0000000"}))
    _stub_sense(monkeypatch, facts=stale)
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    phases = [ev["phase"] for ev in _timing_events(tmp_path)]
    assert phases == [_AWAITING_CI, "review-or-fix"]
    assert _AWAITING_CI != "review-or-fix"  # CI-wait ≠ review-wait


def test_consider_guardrail_one_downgrade_records_awaiting_effect(tmp_path, monkeypatch):
    """护栏一降级：同 fp attempt 戳 → ACTIONABLE 降 QUIET(awaiting-effect)，记的是**降级后**的等待相。"""
    conn = _db(tmp_path)
    stuck = _facts(ci="failure")
    fp = _fingerprint(facts=stuck)
    stamp = github.Comment(
        1, "bot", f"<!-- openagents:attempt fp={fp} -->\n撞墙了", "2026-07-14T11:00:00Z"
    )
    _stub_sense(monkeypatch, facts=stuck, comments=[stamp])
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    (event,) = _timing_events(tmp_path)
    assert event["phase"] == _AWAITING_EFFECT


# --------------------------------------------------------------------------------------------------
# 容错端到端 + fp 不变（旁路不回归）。
# --------------------------------------------------------------------------------------------------


def test_consider_survives_timing_record_raising(tmp_path, monkeypatch):
    """record 抛异常（注入）→ `_consider` 照常返回入队数、不受影响（容错端到端）。"""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts(pr_number=None))  # solve → 会入队

    def _boom(**kwargs):
        raise RuntimeError("timing backend down")

    monkeypatch.setattr(vigil_module.timing, "record", _boom)
    assert _consider_once(conn, subject="issue:5", work_dir=tmp_path) == 1  # 照常入队


def test_fingerprint_unchanged_by_timing_stamp(tmp_path, monkeypatch):
    """旁路写 timing.jsonl 不进 fp——埋点前后 `_fingerprint` 相等（护栏一不自毁）。"""
    conn = _db(tmp_path)
    facts = _facts(ci="failure")
    fp_before = _fingerprint(facts=facts)
    _stub_sense(monkeypatch, facts=facts)
    _consider_once(conn, subject="issue:5", work_dir=tmp_path)
    fp_after = _fingerprint(facts=facts)
    assert fp_before == fp_after
    # 且确实盖了戳（旁路真发生，不是空转）。
    assert len(_timing_events(tmp_path)) == 1


def test_consider_timing_write_failure_does_not_block_enqueue(tmp_path, monkeypatch):
    """即便 timing 目录被占成文件导致写崩，主流程仍入队（容错断言，另一条注入路径）。"""
    conn = _db(tmp_path)
    _stub_sense(monkeypatch, facts=_facts(pr_number=None))
    # 让 record 内部 open 抛错，验证是 timing.record 自身的 try 兜住、`_consider` 无感。
    monkeypatch.setattr(Path, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert _consider_once(conn, subject="issue:5", work_dir=tmp_path) == 1
