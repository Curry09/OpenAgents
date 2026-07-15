"""Spec-0065/T2: recipes.vigil —— level-triggered reconcile 守夜的契约单测。

按 spec §14 的顺序钉死五块：
- **感知**：`_classify` 四值逐分支 + `in_flight` 先于一切；`_fingerprint` 字段集恒等于 `_Facts` 全集、
  不含 clock、**不含 comment id**（盖 attempt 戳前后 fp 必须相等——这条直接钉死护栏一不自毁）；
  `_sense` 在 mergeable UNKNOWN 时**一次 CI 都不读**；`_watchdog` 按 reason 分档。
- **队列**：`_claim_next` exactly-once 不双跑；`INSERT OR IGNORE` 幂等；`_mark_done` 是 DELETE（不是
  `status='done'`——UNIQUE 约束会把 subject 永久锁死）。
- **存活探测（本 spec 的核心断言，零双跑）**：持有者活着 → EWOULDBLOCK → **行原样不动**（哪怕已超
  IN_FLIGHT 告警阈值，也只 `_park`、绝不回收）；持有者被 `kill -9` → 内核放锁 → 行**立刻**回 queued（不
  等任何超时）；同进程两 fd 互斥（**用 `lockf` 这条会失败**——钉死必须 flock）；收工**先删行后 close(fd)**。
- **卡死**：`_act` 硬超时 → 杀子进程 + 抛出 → 持有者自己 `_requeue_or_park`；`attempts` 到顶 → needs-human。
- **收口**：agent 自己打 `needs-human` → 下一圈当场 TERMINAL、**零后续 agent 调用**（主路径，不等阈值）；
  `review-approved:<sha7>` 的 sha 必须等于当前 head 才 merge，陈旧 sha / 裸 label 一律降回 review-or-fix。

全程假 backend + 打桩 github/git/stages，不触真实 LLM/网络/仓库。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
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
    _ACTIONABLE,
    _AWAITING_BLOCKERS,
    _AWAITING_CI,
    _AWAITING_EFFECT,
    _AWAITING_MERGEABILITY,
    _IN_FLIGHT,
    _MAX_ATTEMPTS,
    _QUIET,
    _TERMINAL,
    _ActTimeout,
    _claim_next,
    _classify,
    _Clock,
    _connect,
    _consider,
    _enqueue,
    _Facts,
    _fingerprint,
    _has_cycle,
    _init_db,
    _intake,
    _lock_path,
    _mark_done,
    _Observed,
    _proposed_edges,
    _reclaim_dead,
    _reconcile,
    _requeue_or_park,
    _sense,
    _TimedBackend,
    _try_lock,
    _Verdict,
    _watchdog,
    route,
    run_vigil,
)
from openagents.utils import agent_config, github

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_HEAD = "abc1234def5678901234567890123456789abcde"
_SHA7 = _HEAD[:7]


# --------------------------------------------------------------------------------------------------
# 夹具：facts 造型 + 打桩 github。
# --------------------------------------------------------------------------------------------------


def _facts(**overrides) -> _Facts:
    """一个「万事俱备、只欠合并」的 facts（分支⑪），各测试按需改单个字段往回退。"""
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


def _stages(**owners) -> agent_config.StagePolicy:
    return agent_config.StagePolicy(owners=owners)


def _config(**overrides) -> agent_config.AgentConfig:
    defaults = {
        "version": 1,
        "agents": agent_config.AgentPolicy(backends={}),
        "stages": _stages(),
        "release": agent_config.ReleasePolicy(),
        "interval": 1,
        "base": "main",
        "labels": ["openagents"],
        "repos": [],
    }
    return agent_config.AgentConfig(**(defaults | overrides))


def _db(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    db_path = tmp_path / ".openagents" / "vigil-queue.db"
    _init_db(db_path=db_path)
    return db_path, _connect(db_path=db_path)


# --------------------------------------------------------------------------------------------------
# 感知①：_classify 四值分支表（顺序即正确性）。
# --------------------------------------------------------------------------------------------------


def test_classify_in_flight_precedes_everything_including_needs_human():
    """`in_flight=True` 先于一切分支（含 needs-human）——否则看门狗会误杀正在写代码的 agent。"""
    facts = _facts(labels=frozenset({"needs-human"}))
    assert _classify(facts=facts, in_flight=True).kind == _IN_FLIGHT
    assert _classify(facts=facts, in_flight=False).kind == _TERMINAL


@pytest.mark.parametrize(
    "overrides,kind,reason,action",
    [
        ({"merged": True}, _TERMINAL, None, None),
        ({"closed": True}, _TERMINAL, None, None),
        ({"labels": frozenset({"needs-human"})}, _TERMINAL, None, None),
        ({"latest_comment_is_ours": False}, _ACTIONABLE, None, _ACT_REPLY),
        ({"deps_done": False}, _QUIET, _AWAITING_BLOCKERS, None),
        ({"pr_number": None}, _ACTIONABLE, None, _ACT_SOLVE),
        ({"mergeable_state": "unknown"}, _QUIET, _AWAITING_MERGEABILITY, None),
        ({"mergeable_state": None}, _QUIET, _AWAITING_MERGEABILITY, None),
        ({"mergeable_state": "dirty"}, _ACTIONABLE, None, _ACT_REBASE),
        ({"ci": "pending"}, _QUIET, _AWAITING_CI, None),
        ({"ci": "none"}, _QUIET, _AWAITING_CI, None),  # 零个 check ≠ CI 绿
        ({"ci": "failure"}, _ACTIONABLE, None, _ACT_FIX_CI),
        ({"e2e_head_sha": None}, _ACTIONABLE, None, _ACT_E2E),
        ({"e2e_head_sha": "0" * 40}, _ACTIONABLE, None, _ACT_E2E),  # 证据陈旧（张冠李戴）
        (
            {"is_draft": True},
            _ACTIONABLE,
            None,
            _ACT_READY,
        ),  # Spec-0017: 全绿+approved 但 draft → 转正
        ({}, _ACTIONABLE, None, _ACT_MERGE),  # 非 draft 才落 merge
    ],
)
def test_classify_branch_table(overrides, kind, reason, action):
    verdict = _classify(facts=_facts(**overrides), in_flight=False)
    assert (verdict.kind, verdict.reason, verdict.action) == (kind, reason, action)


def test_classify_draft_self_heal_precedes_merge_and_never_merges():
    """Spec-0017: 全绿+approved@head 但仍 draft → **必落 ready、绝不 merge**（draft PR 合不了、#168 根因）。"""
    draft = _facts(is_draft=True)  # 其余字段全绿、只欠转正
    verdict = _classify(facts=draft, in_flight=False)
    assert verdict.action == _ACT_READY
    assert verdict.action != _ACT_MERGE  # 任何 PR 都不在 draft 态被合
    # 非 draft 同一 facts → merge：证明 draft 自愈支严格排在 merge 分支之前。
    assert _classify(facts=_facts(is_draft=False), in_flight=False).action == _ACT_MERGE


def test_classify_reply_precedes_merge_because_merge_is_irreversible():
    """人的新评论排在 merge 前——「先别合，我有疑问」必须抢得过 merge。**合并不可逆。**"""
    facts = _facts(latest_comment_is_ours=False)  # 其余字段全绿、本该 merge
    assert _classify(facts=facts, in_flight=False).action == _ACT_REPLY


def test_classify_conflict_precedes_ci():
    """冲突排在 CI 前——冲突的 PR 拿不到 merge ref、GitHub 不给它 check，先读 CI 会读成「永远在等」。"""
    facts = _facts(mergeable_state="dirty", ci="failure")
    assert _classify(facts=facts, in_flight=False).action == _ACT_REBASE


# --------------------------------------------------------------------------------------------------
# 感知②：review 裁决绑 commit —— sha 必须进 label 名，否则会合并没人审过的代码。
# --------------------------------------------------------------------------------------------------


def test_review_approved_with_current_head_sha_merges():
    assert _classify(facts=_facts(), in_flight=False).action == _ACT_MERGE


def test_review_approved_with_stale_sha_never_merges():
    """审完后 agent 又 push 了：裁决绑的是旧 commit → 必须降回⑩重审，**绝不 merge**。"""
    stale = _facts(review_commit_id="0000000", labels=frozenset({"review-approved:0000000"}))
    verdict = _classify(facts=stale, in_flight=False)
    assert verdict.action == _ACT_REVIEW_OR_FIX
    assert verdict.action != _ACT_MERGE


def test_bare_review_approved_label_is_not_honored():
    """裸 `review-approved`（无 sha）不被承认——它正是「合并未审代码」的那个 bug。"""
    state, commit = vigil_module._review_from_labels(labels={"review-approved"})
    assert (state, commit) == (None, None)
    bare = _facts(review_state=None, review_commit_id=None, labels=frozenset({"review-approved"}))
    assert _classify(facts=bare, in_flight=False).action == _ACT_REVIEW_OR_FIX


def test_changes_requested_outranks_approved():
    """同时挂两种裁决（审过后又被打回）→ CHANGES_REQUESTED 优先。"""
    state, _ = vigil_module._review_from_labels(
        labels={f"review-approved:{_SHA7}", f"review-changes-requested:{_SHA7}"}
    )
    assert state == "CHANGES_REQUESTED"


# --------------------------------------------------------------------------------------------------
# 感知③：_fingerprint —— 字段集 ≡ _Facts 全集；不含 clock；**不含 comment id**（护栏一的自毁开关）。
# --------------------------------------------------------------------------------------------------


def test_fingerprint_covers_exactly_every_facts_field():
    """fp 的输入集 ≡ `dataclasses.fields(_Facts)` 全集：漏一个字段 = 静默瞎掉一整类活。"""
    baseline = _fingerprint(facts=_facts())
    mutations = {
        "subject": "issue:6",
        "pr_number": 99,
        "head_sha": "f" * 40,
        "merged": True,
        "closed": True,
        "labels": frozenset({"x"}),
        "deps_done": False,
        "mergeable_state": "dirty",
        "ci": "failure",
        "e2e_head_sha": None,
        "review_state": "CHANGES_REQUESTED",
        "review_commit_id": "0000000",
        "latest_comment_is_ours": False,
        "is_draft": True,  # Spec-0017/T2: 转正使 True→False 改 fp、记为真进展 → 护栏一不误触。
    }
    assert set(mutations) == {field.name for field in fields(_Facts)}
    for name, value in mutations.items():
        assert _fingerprint(facts=_facts(**{name: value})) != baseline, f"{name} 未进 fp"


def test_fingerprint_ignores_clock():
    """`_Clock` 不进 fp：check 一开跑就刷 `started_at`，混进去会让 agent 被反复叫起（护栏一失效）。"""
    assert "last_progress_at" not in {field.name for field in fields(_Facts)}
    assert _fingerprint(facts=_facts()) == _fingerprint(facts=_facts())  # clock 根本不是入参


def test_fingerprint_unchanged_by_our_own_comment(monkeypatch):
    """**护栏一不自毁**：盖 attempt 戳（一条新评论）前后 fp 必须相等——否则戳当场作废 → 无限重叫 agent。"""
    posted: list[str] = []
    monkeypatch.setattr(
        vigil_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(body),
    )
    before = _fingerprint(facts=_facts())
    vigil_module._post_attempt_stamp(facts=_facts(), fp=before, conclusion="flaky", agent_id="a")
    # 盖戳只追加一条我方评论：`latest_comment_is_ours` 仍为 True，且 facts 不含 comment id → fp 不变。
    assert _fingerprint(facts=_facts()) == before
    assert posted and f"fp={before}" in posted[0]


# --------------------------------------------------------------------------------------------------
# 感知④：_sense —— mergeable UNKNOWN 时**一次 CI 都不读**；三态 skip 归一成「已过闸」。
# --------------------------------------------------------------------------------------------------


def _snapshot(**overrides) -> github.PRSnapshot:
    base = {
        "number": 12,
        "state": "OPEN",
        "head_sha": _HEAD,
        "labels": (),
        "mergeable": "MERGEABLE",
        "merge_state_status": "CLEAN",
        "head_pushed_at": "2026-07-14T10:00:00Z",
    }
    return github.PRSnapshot(**(base | overrides))


def _patch_sense(monkeypatch, *, snapshot, comments=(), blockers=(), on_checks=None):
    monkeypatch.setattr(
        vigil_module.github, "get_issue", lambda *, number: github.Issue(5, "T", "B", [])
    )
    monkeypatch.setattr(vigil_module.github, "list_blocked_by", lambda *, number: list(blockers))
    monkeypatch.setattr(vigil_module.github, "pr_for_branch", lambda *, branch: github.PR(12, "u"))
    monkeypatch.setattr(vigil_module.github, "pr_snapshot", lambda *, pr_number: snapshot)
    monkeypatch.setattr(vigil_module.github, "list_comments", lambda *, pr_number: list(comments))
    monkeypatch.setattr(
        vigil_module.github,
        "check_snapshot",
        on_checks or (lambda *, pr_number: github.CheckSnapshot("pass", 3, "2026-07-14T11:00:00Z")),
    )


def test_sense_does_not_read_ci_when_mergeability_unknown(monkeypatch):
    """mergeable UNKNOWN ⇒ **一次 CI 请求都不发**（否则「CI 卡住」的症状会盖住「有冲突」的病因）。"""

    def _boom(*, pr_number):
        raise AssertionError("mergeable UNKNOWN 时不得读 CI")

    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(mergeable="UNKNOWN", merge_state_status="UNKNOWN"),
        on_checks=_boom,
    )
    observed = _sense(config=_config(), subject="issue:5")
    assert observed.facts.mergeable_state == "unknown"
    assert _classify(facts=observed.facts, in_flight=False).reason == _AWAITING_MERGEABILITY


def test_sense_zero_checks_is_awaiting_ci_not_green(monkeypatch):
    """当前 head 上零个 check → `none` → QUIET(awaiting-ci)，**绝不是「CI 绿了」**。"""
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(),
        on_checks=lambda *, pr_number: github.CheckSnapshot("pass", 0, ""),
    )
    facts = _sense(config=_config(), subject="issue:5").facts
    assert facts.ci == "none"
    assert _classify(facts=facts, in_flight=False).reason == _AWAITING_CI


def test_sense_reads_is_draft_from_snapshot(monkeypatch):
    """Spec-0017/T2: `_sense` 从 pr_snapshot.is_draft 读入 → `_classify` 全绿+approved 时判 ready（非 merge）。"""
    # e2e:skip 把证据戳归一成 head（本测只关心 draft 支）；review 留 agent，用真 review-approved label。
    config = _config(stages=_stages(e2e="skip"))
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(labels=(f"review-approved:{_SHA7}",), is_draft=True),
    )
    facts = _sense(config=config, subject="issue:5").facts
    assert facts.is_draft is True
    assert _classify(facts=facts, in_flight=False).action == _ACT_READY
    # 非 draft 同源 → merge（证明 is_draft 是每 tick 复检的一等事实）。
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(labels=(f"review-approved:{_SHA7}",), is_draft=False),
    )
    facts = _sense(config=config, subject="issue:5").facts
    assert facts.is_draft is False
    assert _classify(facts=facts, in_flight=False).action == _ACT_MERGE


def test_sense_normalizes_skip_gates_as_already_passed(monkeypatch):
    """三态 `skip` 在 `_sense` 归一成「事实上已过闸」，`_classify` 因而保持纯机械、不吃 config。"""
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(),
        on_checks=lambda *, pr_number: github.CheckSnapshot("fail", 2, "2026-07-14T11:00:00Z"),
    )
    config = _config(stages=_stages(ci="skip", e2e="skip", review="skip", merge="human"))
    facts = _sense(config=config, subject="issue:5").facts
    assert facts.ci == "success"
    assert facts.e2e_head_sha == _HEAD
    assert (facts.review_state, facts.review_commit_id) == ("APPROVED", _SHA7)
    assert _classify(facts=facts, in_flight=False).action == _ACT_MERGE


def test_sense_still_sees_the_pr_after_it_is_merged(monkeypatch):
    """PR 一合并就从 open 列表消失——`_sense` 若用 open-only 的查法，会把已完成的 issue 读成「还没有 PR」。

    后果不是漏一个字段，是**把同一个 issue 整个重做一遍**（分支④ solve → 再开一个 PR）。故这里钉死：
    `_sense` 查 PR 走 `pr_for_branch`（不限状态），merged 读得出来 → `_classify` 判 TERMINAL。
    """
    monkeypatch.setattr(
        vigil_module.github, "find_pr_by_branch", lambda *, branch: None
    )  # open 为空
    _patch_sense(monkeypatch, snapshot=_snapshot(state="MERGED"))
    facts = _sense(config=_config(), subject="issue:5").facts
    assert (facts.pr_number, facts.merged) == (12, True)
    assert _classify(facts=facts, in_flight=False).kind == _TERMINAL


def test_sense_reads_deps_from_native_blocked_by(monkeypatch):
    """依赖边读 GitHub 原生 `blocked_by`；响应自带 state ⇒ 一次调用同时拿到「边」和「关没关」。"""
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(),
        blockers=[github.Blocker(4, "OPEN"), github.Blocker(3, "CLOSED")],
    )
    facts = _sense(config=_config(), subject="issue:5").facts
    assert facts.deps_done is False
    assert _classify(facts=facts, in_flight=False).reason == _AWAITING_BLOCKERS


def test_sense_clock_uses_head_push_time_when_no_checks_no_comments(monkeypatch):
    """刚推上去、零 check、零评论的 PR：`last_progress_at` 必须来自 head 推送时间——否则看门狗永不响。"""
    _patch_sense(
        monkeypatch,
        snapshot=_snapshot(),
        on_checks=lambda *, pr_number: github.CheckSnapshot("pass", 0, ""),
    )
    observed = _sense(config=_config(), subject="issue:5")
    assert observed.clock.last_progress_at == datetime(2026, 7, 14, 10, 0, tzinfo=UTC)


def test_sense_clock_reads_the_issue_comments_when_there_is_no_pr_yet(monkeypatch):
    """还没 PR 的 issue，进度时钟必须从 **issue 自己的评论流** 走——否则 `last_progress_at` 恒 `None`，
    护栏二（QUIET 看门狗）对整个 `solve` 阶段**永久失效**：一个空转的 solve（agent 跑完没推 PR → fp 没变
    → 盖同-fp attempt 戳 → 降级 QUIET(awaiting-effect)）会静默永久卡死、`_watchdog` 因 None 直接返回
    False、needs-human 永不触发。attempt 戳落在 issue 上，读它，看门狗才算得出 age。"""
    monkeypatch.setattr(
        vigil_module.github, "get_issue", lambda *, number: github.Issue(7, "T", "B", [])
    )
    monkeypatch.setattr(vigil_module.github, "list_blocked_by", lambda *, number: [])
    monkeypatch.setattr(vigil_module.github, "pr_for_branch", lambda *, branch: None)  # 还没 PR
    stamp = github.Comment(
        id="IC_1",
        author="openagents-bot",
        body="<!-- openagents:attempt fp=abc -->",
        created_at="2026-07-14T12:00:00Z",
        author_association="OWNER",
    )
    monkeypatch.setattr(vigil_module.github, "list_issue_comments", lambda *, number: [stamp])

    observed = _sense(config=_config(), subject="issue:7")

    assert observed.facts.pr_number is None
    assert observed.clock.last_progress_at == datetime(2026, 7, 14, 12, 0, tzinfo=UTC), (
        "无-PR issue 的时钟没读 issue 评论 → last_progress_at 恒 None → 看门狗永不响 → 静默永久卡死"
    )


def test_sense_reads_e2e_evidence_stamp(monkeypatch):
    """e2e 证据是一条带 head 溯源戳的评论；head 一前移，证据自动作废 → 分支⑨重跑。"""
    body = vigil_module.identity.sign(
        body=f"<!-- openagents:e2e head={_HEAD} -->\n✅ e2e 通过", agent_id="bot"
    )
    stamp = github.Comment(1, "bot", body, "2026-07-14T11:00:00Z")
    _patch_sense(monkeypatch, snapshot=_snapshot(), comments=[stamp])
    assert _sense(config=_config(), subject="issue:5").facts.e2e_head_sha == _HEAD

    _patch_sense(monkeypatch, snapshot=_snapshot(head_sha="f" * 40), comments=[stamp])
    facts = _sense(config=_config(), subject="issue:5").facts
    assert facts.e2e_head_sha != facts.head_sha  # 陈旧证据不被承认
    assert _classify(facts=facts, in_flight=False).action == _ACT_E2E


# --------------------------------------------------------------------------------------------------
# 感知⑤：看门狗按 reason 分档（护栏二）。
# --------------------------------------------------------------------------------------------------


def test_watchdog_fires_per_reason_threshold():
    clock = _Clock(last_progress_at=_NOW - timedelta(seconds=600))
    thresholds = {_AWAITING_CI: 3600, _AWAITING_EFFECT: 300, _AWAITING_BLOCKERS: None}
    assert not _watchdog(  # 10 分钟 < 1 小时：CI 还在正常跑
        verdict=_Verdict(kind=_QUIET, reason=_AWAITING_CI),
        clock=clock,
        thresholds=thresholds,
        now=_NOW,
    )
    assert _watchdog(  # 10 分钟 > 5 分钟：agent 出手了但状态没动 → 叫人
        verdict=_Verdict(kind=_QUIET, reason=_AWAITING_EFFECT),
        clock=clock,
        thresholds=thresholds,
        now=_NOW,
    )
    assert not _watchdog(  # 阈值 None = 不看门（上游 blocker 有自己的看门狗）
        verdict=_Verdict(kind=_QUIET, reason=_AWAITING_BLOCKERS),
        clock=clock,
        thresholds=thresholds,
        now=_NOW,
    )
    assert not _watchdog(  # 非 QUIET 一律不看门
        verdict=_Verdict(kind=_ACTIONABLE, action=_ACT_MERGE),
        clock=clock,
        thresholds=thresholds,
        now=_NOW,
    )


# --------------------------------------------------------------------------------------------------
# 队列：幂等入队 / exactly-once 领取 / _mark_done 是 DELETE。
# --------------------------------------------------------------------------------------------------


def test_enqueue_is_idempotent_via_subject_unique(tmp_path):
    """`subject` UNIQUE + `INSERT OR IGNORE`：每 tick 无脑入队，重复是 no-op（level-triggered 的落地）。"""
    _, conn = _db(tmp_path)
    assert _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW) is True
    assert _enqueue(conn=conn, subject="issue:5", priority=9, now=_NOW) is False
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 1


def test_claim_next_is_exactly_once(tmp_path):
    """两次领取同一行 → 第二次领空。这正是 GitHub label 做不到的（不安全方法无条件请求 ⇒ 无 CAS）。"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    first = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w1", now=_NOW)
    assert first is not None
    row, fd = first
    assert (row["subject"], row["status"], row["attempts"]) == ("issue:5", "claimed", 1)
    assert _claim_next(conn=conn, work_dir=tmp_path, worker_id="w2", now=_NOW) is None
    os.close(fd)


def test_claim_next_orders_by_priority_then_fifo(tmp_path):
    """`ORDER BY priority DESC, enqueued_at ASC` 在**领取时**求值（久候行的优先级不冻结在入队时刻）。"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:1", priority=1, now=_NOW)
    _enqueue(conn=conn, subject="pr:2", priority=6, now=_NOW + timedelta(seconds=10))
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    assert row["subject"] == "pr:2"  # 后入队但优先级高
    os.close(fd)


def test_mark_done_deletes_the_row(tmp_path):
    """**必须是 DELETE**：留个 `status='done'` 行会因 UNIQUE 约束把该 subject 永久锁死（再也入不了队）。"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    _mark_done(conn=conn, task_id=row["id"], fd=fd)
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0
    assert _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW) is True  # 能再入队


def test_mark_done_deletes_row_before_closing_fd(tmp_path, monkeypatch):
    """**先删行、后 close(fd)**：反过来会开一个窗口让 `_reclaim_dead` 抢到锁、把行打回 queued → 双跑。"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    seen: list[int] = []
    real_close = os.close

    def _spy_close(target_fd):
        seen.append(conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0])
        real_close(target_fd)

    monkeypatch.setattr(vigil_module.os, "close", _spy_close)
    _mark_done(conn=conn, task_id=row["id"], fd=fd)
    assert seen == [0], "close(fd) 的那一刻，队列行必须已经删掉"


# --------------------------------------------------------------------------------------------------
# 存活探测（**本 spec 的核心断言：零双跑**）：凭 flock 判死，不凭租约猜死。
# --------------------------------------------------------------------------------------------------


def test_two_fds_in_same_process_are_mutually_exclusive(tmp_path):
    """**必须 flock、不能 lockf**：lockf 的锁是 per-process 的，同进程两 fd 不互斥 → K 线程互斥静默失效。

    本模块是「一个进程 K 条 worker 线程」——这条断言是那个选择的护城河。改用 `fcntl.lockf` 后它会失败。
    """
    path = tmp_path / "claims" / "issue-5.lock"
    first = _try_lock(path=path)
    assert first is not None
    assert _try_lock(path=path) is None, "同进程第二个 fd 必须抢不到锁（lockf 会误判为抢到）"
    os.close(first)
    second = _try_lock(path=path)
    assert second is not None  # 释放后可再抢
    os.close(second)


def test_reclaim_leaves_row_alone_while_holder_is_alive(tmp_path):
    """持有者**活着** → EWOULDBLOCK → **行原样不动**。回收一个活着的持有者的行，定义上就是双跑。"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w1", now=_NOW)
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 0
    after = conn.execute(
        "SELECT status, worker FROM work_queue WHERE id=?", (row["id"],)
    ).fetchone()
    assert (after["status"], after["worker"]) == ("claimed", "w1")
    assert _claim_next(conn=conn, work_dir=tmp_path, worker_id="w2", now=_NOW) is None  # 领不走
    os.close(fd)


def test_reclaim_leaves_row_alone_even_past_inflight_alarm_age(tmp_path):
    """哪怕 `claimed_at` 已超 IN_FLIGHT 告警阈值：持有者还活着 → **只 `_park` 告警，绝不回收行**。"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    ancient = _NOW - timedelta(seconds=vigil_module._INFLIGHT_ALARM_SECONDS * 3)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w1", now=ancient)
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 0
    after = conn.execute(
        "SELECT status, worker FROM work_queue WHERE id=?", (row["id"],)
    ).fetchone()
    assert (after["status"], after["worker"]) == ("claimed", "w1")
    os.close(fd)


def test_reclaim_requeues_immediately_when_holder_was_killed(tmp_path):
    """持有者被 `kill -9` → 内核放锁 → 行**立刻**回 queued（**不等任何超时**：根本没有租约可等）。"""
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    lock_file = _lock_path(work_dir=tmp_path, subject="issue:5")
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    # 真起一个子进程持锁再 kill -9——只有内核能证明「flock 随进程死亡自动释放」这条性质。
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(f"""
                import fcntl, os, sys, time
                fd = os.open({str(lock_file)!r}, os.O_CREAT | os.O_RDWR, 0o644)
                fcntl.flock(fd, fcntl.LOCK_EX)
                sys.stdout.write("locked\\n"); sys.stdout.flush()
                time.sleep(300)
            """),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout.readline().strip() == "locked"
    conn.execute(
        "UPDATE work_queue SET status='claimed', worker='dead', worker_pid=?, claimed_at=?",
        (holder.pid, _NOW.isoformat()),
    )
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 0, "持有者活着时不许回收"

    holder.kill()
    holder.wait(timeout=5)
    assert _reclaim_dead(conn=conn, work_dir=tmp_path) == 1, "持有者已死 → 立刻回收"
    row = conn.execute("SELECT status, worker, claimed_at FROM work_queue").fetchone()
    assert (row["status"], row["worker"], row["claimed_at"]) == ("queued", None, None)
    reclaimed = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w2", now=_NOW)
    assert reclaimed is not None  # 可被重领
    os.close(reclaimed[1])


# --------------------------------------------------------------------------------------------------
# 卡死：_act 硬超时 + attempts 上限（唯一必须计数的护栏）。
# --------------------------------------------------------------------------------------------------


def test_requeue_returns_row_to_queue_below_max_attempts(tmp_path):
    _, conn = _db(tmp_path)
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
    _requeue_or_park(conn=conn, task_id=row["id"], subject="issue:5", fd=fd, agent_id="vigil-1")
    after = conn.execute("SELECT status, attempts FROM work_queue").fetchone()
    assert (after["status"], after["attempts"]) == ("queued", 1)
    freed = _try_lock(path=_lock_path(work_dir=tmp_path, subject="issue:5"))
    assert freed is not None, "回队时必须把锁一起释放"
    os.close(freed)


def test_requeue_parks_needs_human_at_max_attempts(tmp_path, monkeypatch):
    """反复领取不收工（agent 崩 / 被 kill：GitHub 上零痕迹，fp 与 age 都判不出）→ 计数到顶 → 交人。"""
    _, conn = _db(tmp_path)
    parked: list[tuple[int, str]] = []
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: parked.append((number, name)),
    )
    monkeypatch.setattr(vigil_module.github, "issue_comment", lambda *, number, body: None)
    monkeypatch.setattr(vigil_module.github, "list_issue_comments", lambda *, number: [])
    _enqueue(conn=conn, subject="issue:5", priority=1, now=_NOW)
    for _ in range(_MAX_ATTEMPTS):
        row, fd = _claim_next(conn=conn, work_dir=tmp_path, worker_id="w", now=_NOW)
        _requeue_or_park(conn=conn, task_id=row["id"], subject="issue:5", fd=fd, agent_id="vigil-1")
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0  # 行已删，不霸占槽
    assert parked == [(5, "needs-human")]


class _HangingBackend:
    """永不返回的 backend——模拟「进程活着但挂死在一个不返回的调用上」（flock 判不出这种死法）。"""

    name = "hanging"

    def run(self, *, work_dir, task, context):
        time.sleep(300)


def test_timed_backend_raises_on_agent_hang():
    """`_act` 硬超时 → 抛 `_ActTimeout` → `_worker_loop` 捕获 → 持有者自己 `_requeue_or_park`（行不成孤儿）。"""
    with pytest.raises(_ActTimeout):
        _TimedBackend(inner=_HangingBackend(), timeout_seconds=1, lock_fd=None).run(
            work_dir=Path("."), task="t", context="c"
        )


def test_timed_backend_passes_through_normal_result():
    class _Fast:
        name = "fast"

        def run(self, *, work_dir, task, context):
            return "ok"

    result = _TimedBackend(inner=_Fast(), timeout_seconds=30, lock_fd=None).run(
        work_dir=Path("."), task="t", context="c"
    )
    assert result == "ok"


def test_intake_runs_its_producer_thread_agent_calls_through_a_timed_backend(monkeypatch, tmp_path):
    """# Spec-0065/T2: 准入面的两次 agent 调用（triager / curator）**必须**是 `_TimedBackend`，不是裸 backend。

    它们跑在**生产者线程**上——那是整条守夜的主循环。任何一个挂死（模型不返回 / 网络半开），停摆的就不是
    某一个 subject 而是**全系统**：不再有 tick、不再有 `_reclaim_dead`（真死掉的持有者永远不被回收）、
    `--once` 连排空都进不去，而 K 个 worker 全都在等生产者补给。且这种死法**没有任何护栏看得见**：
    看门狗与 IN_FLIGHT 告警本身就住在那条停掉的循环里。硬超时是这里唯一的活口。

    这条路上没有认领的行（准入还没入队），故 `lock_fd=None`——不传 fd，不参与存活证明。
    """
    raw = object()  # 裸 backend：它绝不能原样漏到任何一个 stage 手上
    seen: list[object] = []
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)
    monkeypatch.setattr(
        vigil_module.github,
        "list_issues",
        lambda *, labels: [github.Issue(number=5, title="标题", body="正文", labels=())],
    )
    monkeypatch.setattr(vigil_module.github, "issue_add_label", lambda *, number, name: None)
    monkeypatch.setattr(
        vigil_module.stages,
        "triage",
        lambda *, backend, work_dir, issue: (
            seen.append(backend) or {"actionable": True, "reason": ""}
        ),
    )
    monkeypatch.setattr(
        vigil_module, "_order_edges", lambda *, backend, work_dir, agent_id: seen.append(backend)
    )

    _intake(
        backend=raw,
        work_dir=tmp_path,
        config=_config(stages=_stages(triage="agent")),
        agent_id="vigil-1",
        now=_NOW,
    )

    assert len(seen) == 2, "triage 与 curator 两处都要经过硬超时（漏一处，主循环就还是能被挂死）"
    for backend in seen:
        assert isinstance(backend, _TimedBackend), "裸 backend 挂死 = 整条守夜停摆，且无人看得见"
        assert backend._inner is raw  # 只是包了一层，没换掉真正干活的那个
        assert backend._lock_fd is None, "准入面没有认领的行 → 不传存活证明的 fd"


# --------------------------------------------------------------------------------------------------
# reconcile：worker 恒以 in_flight=False 调 _classify（否则每个 worker 领到活就空转）；零进展 → 盖戳收工。
# --------------------------------------------------------------------------------------------------


def _stub_reconcile(monkeypatch, *, facts_seq: list[_Facts]) -> list[str]:
    """把 `_sense` 打成一串预置 facts（每调一次吐一个，用尽后重复最后一个），并记录 `_act` 的动作序列。"""
    seen: list[str] = []
    box = {"index": 0}

    def _fake_sense(*, config, subject):
        index = min(box["index"], len(facts_seq) - 1)
        box["index"] += 1
        return _Observed(facts=facts_seq[index], clock=_Clock(last_progress_at=_NOW))

    def _fake_act(*, backend, state, work_dir, config, observed, verdict, agent_id, now, lock_fd):
        seen.append(verdict.action)
        return "结论"

    monkeypatch.setattr(vigil_module, "_sense", _fake_sense)
    monkeypatch.setattr(vigil_module, "_act", _fake_act)
    return seen


def _reconcile_once(tmp_path):
    # Spec-0065/T2: `lock_fd` = 认领行的 flock fd（透传给 agent 子进程继承）；本组只测感知/路由，无认领行。
    _reconcile(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        subject="issue:5",
        agent_id="a",
        now_fn=lambda: _NOW,
        lock_fd=None,
    )


def test_reconcile_never_idles_on_its_own_claim(monkeypatch, tmp_path):
    """worker **就是**那个 in-flight 的持有者 → 必须以 `in_flight=False` 调 `_classify`，否则它立刻空转收工。"""
    seen = _stub_reconcile(monkeypatch, facts_seq=[_facts(), _facts(merged=True)])
    _reconcile_once(tmp_path)
    assert seen == [_ACT_MERGE], "worker 领到活必须真出手（传 in_flight=True 会让它空转）"


def test_reconcile_drives_to_a_stop_not_one_step(monkeypatch, tmp_path):
    """一次认领里**推进到卡住为止**：e2e → review → merge 应在一趟走完，而不是烧三个 tick（每 tick 一支）。"""
    seen = _stub_reconcile(
        monkeypatch,
        facts_seq=[
            _facts(e2e_head_sha=None, review_state=None, review_commit_id=None, labels=frozenset()),
            _facts(review_state=None, review_commit_id=None, labels=frozenset()),
            _facts(),
            _facts(merged=True),
        ],
    )
    _reconcile_once(tmp_path)
    assert seen == [_ACT_E2E, _ACT_REVIEW_OR_FIX, _ACT_MERGE]


def test_reconcile_returns_the_slot_when_stuck_on_something_external(monkeypatch, tmp_path):
    """卡在外部（QUIET：等 CI）→ 立刻交还 slot，不占着 worker 空等。"""
    seen = _stub_reconcile(monkeypatch, facts_seq=[_facts(ci="pending")])
    _reconcile_once(tmp_path)
    assert seen == []


def test_reconcile_stamps_and_stops_when_agent_made_zero_progress(monkeypatch, tmp_path):
    """护栏一：agent 出手后 fp **一个字节没变** → 盖 attempt 戳收工（它自己意识不到，不会去打 needs-human）。"""
    stuck = _facts(ci="failure")
    seen = _stub_reconcile(monkeypatch, facts_seq=[stuck, stuck, stuck])
    stamps: list[tuple[str, str]] = []
    monkeypatch.setattr(
        vigil_module,
        "_post_attempt_stamp",
        lambda *, facts, fp, conclusion, agent_id: stamps.append((fp, conclusion)),
    )
    _reconcile_once(tmp_path)
    assert seen == [_ACT_FIX_CI], "同一个 fp 上只许出手一次"
    assert stamps == [(_fingerprint(facts=stuck), "结论")]


def test_reconcile_stops_immediately_when_agent_self_labels_needs_human(monkeypatch, tmp_path):
    """**主路径收口**：agent 在 `_act` 里自己打 `needs-human` → 下一圈当场 TERMINAL、**零后续 agent 调用**。

    不烧多余 LLM 调用、不等任何阈值——护栏一/二只兜「它没意识到自己在空转」那类它自己看不见的死法。
    """
    seen = _stub_reconcile(
        monkeypatch,
        facts_seq=[_facts(ci="failure"), _facts(ci="failure", labels=frozenset({"needs-human"}))],
    )
    stamps: list[str] = []
    monkeypatch.setattr(
        vigil_module,
        "_post_attempt_stamp",
        lambda *, facts, fp, conclusion, agent_id: stamps.append(fp),
    )
    _reconcile_once(tmp_path)
    assert seen == [_ACT_FIX_CI]  # 出手一次，然后 agent 自己叫了人
    assert stamps == [], "TERMINAL 收口不该再盖 attempt 戳，更不该再叫 agent"


# --------------------------------------------------------------------------------------------------
# 生产者：护栏一读侧（同 fp 戳 → 不入队）；四值分流；单 subject 错误隔离。
# --------------------------------------------------------------------------------------------------


def _consider_once(conn, *, in_flight=None, quiet_counts=None) -> int:
    return _consider(
        conn=conn,
        subject="issue:5",
        config=_config(),
        in_flight=in_flight or {},
        priority_fn=vigil_module._priority_default,
        thresholds=dict(vigil_module._WATCHDOG_DEFAULTS),
        quiet_counts=quiet_counts if quiet_counts is not None else {},
        now=_NOW,
        agent_id="vigil-1",
    )


def _stub_consider(monkeypatch, *, facts: _Facts, comments=()):
    monkeypatch.setattr(
        vigil_module,
        "_sense",
        lambda *, config, subject: _Observed(facts=facts, clock=_Clock(last_progress_at=_NOW)),
    )
    monkeypatch.setattr(vigil_module.github, "list_comments", lambda *, pr_number: list(comments))


def test_producer_skips_enqueue_when_same_fp_attempt_stamp_exists(tmp_path, monkeypatch):
    """护栏一读侧：GitHub 上已有**同 fp** 的 attempt 戳 → 降级 QUIET(awaiting-effect)、**不入队**（零 LLM）。"""
    _, conn = _db(tmp_path)
    stuck = _facts(ci="failure")
    fp = _fingerprint(facts=stuck)
    stamp = github.Comment(
        1, "bot", f"<!-- openagents:attempt fp={fp} -->\n撞墙了", "2026-07-14T11:00:00Z"
    )
    _stub_consider(monkeypatch, facts=stuck, comments=[stamp])
    quiet: dict[str, int] = {}
    assert _consider_once(conn, quiet_counts=quiet) == 0
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0
    assert quiet == {_AWAITING_EFFECT: 1}


def test_producer_enqueues_again_once_fingerprint_changes(tmp_path, monkeypatch):
    """fp 一变（真有进展 / 新情况）→ 旧戳自动失配 → 正常重新入队（护栏一不会把 subject 永久钉死）。"""
    _, conn = _db(tmp_path)
    old_fp = _fingerprint(facts=_facts(ci="failure"))
    stale = github.Comment(
        1, "bot", f"<!-- openagents:attempt fp={old_fp} -->\n撞墙了", "2026-07-14T11:00:00Z"
    )
    _stub_consider(monkeypatch, facts=_facts(ci="failure", head_sha="f" * 40), comments=[stale])
    assert _consider_once(conn) == 1


def test_producer_parks_on_watchdog_timeout(tmp_path, monkeypatch):
    """护栏二：QUIET 超该 reason 的阈值 → `_park` 打 needs-human + 贴**机械**诊断（不叫 LLM）。"""
    _, conn = _db(tmp_path)
    monkeypatch.setattr(
        vigil_module,
        "_sense",
        lambda *, config, subject: _Observed(
            facts=_facts(ci="none"),
            clock=_Clock(last_progress_at=_NOW - timedelta(seconds=7200)),
        ),
    )
    parked: list[tuple[str, str]] = []
    monkeypatch.setattr(
        vigil_module,
        "_park_needs_human",
        lambda *, subject, body, agent_id: parked.append((subject, body)),
    )
    _consider_once(conn)
    assert parked and parked[0][0] == "issue:5"
    assert _AWAITING_CI in parked[0][1]


def test_producer_does_not_park_a_live_in_flight_holder(tmp_path, monkeypatch):
    """IN_FLIGHT 未超龄 → 什么都不做（**绝不**把正在写代码的 agent 当成「状态没动」而误挂 needs-human）。"""
    _, conn = _db(tmp_path)
    _stub_consider(monkeypatch, facts=_facts(ci="failure"))
    parked: list[str] = []
    monkeypatch.setattr(
        vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: parked.append(subject)
    )
    assert _consider_once(conn, in_flight={"issue:5": _NOW.isoformat()}) == 0
    assert parked == []
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0


def test_producer_alarms_on_overdue_in_flight_without_touching_the_row(tmp_path, monkeypatch):
    """IN_FLIGHT 超龄（持有者活着但挂死）→ **只打 needs-human 告警**，队列行一个字节都不动。"""
    _, conn = _db(tmp_path)
    _stub_consider(monkeypatch, facts=_facts(ci="failure"))
    parked: list[str] = []
    monkeypatch.setattr(
        vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: parked.append(subject)
    )
    ancient = (_NOW - timedelta(seconds=vigil_module._INFLIGHT_ALARM_SECONDS * 2)).isoformat()
    assert _consider_once(conn, in_flight={"issue:5": ancient}) == 0
    assert parked == ["issue:5"]


def test_producer_isolates_a_failing_subject(tmp_path, monkeypatch):
    """单 subject 感知失败 → 记日志跳过，**不拖垮整轮生产**（守夜第一要务是活着进下一轮）。"""
    db_path, conn = _db(tmp_path)

    def _flaky_sense(*, config, subject):
        if subject == "issue:5":
            raise RuntimeError("gh 抽风")
        return _Observed(facts=_facts(subject=subject), clock=_Clock(last_progress_at=_NOW))

    monkeypatch.setattr(vigil_module, "_sense", _flaky_sense)
    monkeypatch.setattr(vigil_module, "_intake", lambda **kw: None)
    monkeypatch.setattr(vigil_module, "_has_attempt_stamp", lambda *, facts, fp: False)
    monkeypatch.setattr(vigil_module, "_subjects", lambda *, config: ["issue:5", "issue:6"])
    enqueued = vigil_module._producer_tick(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        agent_id="a",
        db_path=db_path,
        priority_fn=vigil_module._priority_default,
        thresholds=dict(vigil_module._WATCHDOG_DEFAULTS),
        seen_locked={},
        now=_NOW,
    )
    assert enqueued == 1
    assert [row["subject"] for row in conn.execute("SELECT subject FROM work_queue")] == ["issue:6"]


def test_producer_tick_survives_a_park_that_never_lands(tmp_path, monkeypatch):
    """# Spec-0065/T2: `_sweep_stalled` 里一行 park 不成（`gh` 429）→ **整轮生产照跑**。

    park 的 `gh` 抛出若上抛出 `_producer_tick`，这一 tick 的 `_intake` 与**全部**感知/入队一起停摆——
    一个泄漏的行把整条流水线拖死，比它自己卡住坏得多（而它本来只是「下一轮重试 park」而已）。
    """
    db_path, conn = _db(tmp_path)
    intake_calls: list[int] = []
    monkeypatch.setattr(vigil_module, "_intake", lambda **kw: intake_calls.append(1))
    monkeypatch.setattr(vigil_module, "_has_attempt_stamp", lambda *, facts, fp: False)
    monkeypatch.setattr(vigil_module, "_subjects", lambda *, config: ["issue:6"])
    monkeypatch.setattr(
        vigil_module,
        "_sense",
        lambda *, config, subject: _Observed(
            facts=_facts(subject=subject, ci="failure"), clock=_Clock(last_progress_at=_NOW)
        ),
    )
    monkeypatch.setattr(
        vigil_module,
        "_park_needs_human",
        lambda *, subject, body, agent_id: (_ for _ in ()).throw(RuntimeError("gh 限流 429")),
    )
    # 一个「存活证明泄漏」的 queued 行：锁被持着，且**上一 tick 就已经**见过它锁着（跨 tick 记忆已超龄）
    # → 本 tick 的 `_sweep_stalled` 会去 park 它，而 park 的 `gh` 必抛。
    vigil_module._enqueue(conn=conn, subject="issue:9", priority=1, now=_NOW)
    leaked = vigil_module._try_lock(
        path=vigil_module._lock_path(work_dir=tmp_path, subject="issue:9")
    )
    assert leaked is not None
    seen_locked = {"issue:9": _NOW - timedelta(seconds=vigil_module._STALE_LOCK_SECONDS + 60)}

    enqueued = vigil_module._producer_tick(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        agent_id="a",
        db_path=db_path,
        priority_fn=vigil_module._priority_default,
        thresholds=dict(vigil_module._WATCHDOG_DEFAULTS),
        seen_locked=seen_locked,
        now=_NOW,
    )

    assert intake_calls == [1], "park 抛出不许吃掉 `_intake`（准入面停摆 = 新 issue 永远进不来）"
    assert enqueued == 1, "park 抛出不许吃掉本轮感知/入队"
    assert vigil_module._is_claimed(conn=conn, subject="issue:9") is False
    # 行是**开口之前**用 DELETE 抢下来的（`_park_stalled`：删行即预约），故 `gh` 抛了它也不回来。
    # 恢复靠下一 tick 的 `_intake` 从 GitHub 现态重新推导（锁还占着 → 重新计时 → 重新 park：有节流、零 LLM）。
    assert conn.execute("SELECT 1 FROM work_queue WHERE subject='issue:9'").fetchone() is None
    assert vigil_module._enqueue(conn=conn, subject="issue:9", priority=1, now=_NOW) is True, (
        "subject 必须仍可恢复（UNIQUE 的坑没被这次失败的 park 占死）"
    )
    os.close(leaked)


def test_priority_finishes_work_in_progress_before_starting_new():
    """先收尾在制品、再开新工；人在等的 reply 最高。"""
    order = [_ACT_REPLY, _ACT_MERGE, _ACT_REVIEW_OR_FIX, _ACT_E2E, _ACT_FIX_CI, _ACT_SOLVE]
    priorities = [
        vigil_module._priority_default(verdict=_Verdict(kind=_ACTIONABLE, action=action))
        for action in order
    ]
    assert priorities == sorted(priorities, reverse=True)


# --------------------------------------------------------------------------------------------------
# 准入面：三态 route / 依赖图 validate（无环 + 真实 issue；半张错图比没有图更糟）。
# --------------------------------------------------------------------------------------------------


def test_route_dispatches_three_ways():
    calls: dict[str, int] = {"agent": 0, "human": 0, "skip": 0}

    def _bump(key):
        def _run():
            calls[key] += 1
            return key

        return _run

    for owner in ("agent", "human", "skip"):
        assert (
            route(
                owner=owner,
                on_agent=_bump("agent"),
                on_human=_bump("human"),
                on_skip=_bump("skip"),
            )
            == owner
        )
    assert calls == {"agent": 1, "human": 1, "skip": 1}


def test_has_cycle_detects_cycles():
    assert _has_cycle(graph={5: {6}, 6: {5}}) is True
    assert _has_cycle(graph={5: {6}, 6: set()}) is False


def test_proposed_edges_returns_only_new_edges_and_keeps_anchors():
    """已有边是锚点（人可能在 UI 手设）——只 POST 新边，绝不重排、不删。"""
    fresh = _proposed_edges(
        edges=[{"issue": 6, "blocked_by": [5]}, {"issue": 7, "blocked_by": [5]}],
        known={5, 6, 7},
        existing={5: [], 6: [5], 7: []},
        agent_id="vigil-1",
    )
    assert fresh == [(7, 5)]  # 6←5 已存在（锚点），只补 7←5


def test_proposed_edges_rejects_the_whole_batch_on_cycle(monkeypatch):
    """成环 → **不落任何边** + park 交人（错边会持久冻住本可并行的流转，半张错图比没有图更糟）。"""
    monkeypatch.setattr(vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: None)
    assert (
        _proposed_edges(
            edges=[{"issue": 5, "blocked_by": [6]}, {"issue": 6, "blocked_by": [5]}],
            known={5, 6},
            existing={5: [], 6: []},
            agent_id="vigil-1",
        )
        is None
    )


def test_proposed_edges_rejects_hallucinated_issue_numbers(monkeypatch):
    monkeypatch.setattr(vigil_module, "_park_needs_human", lambda *, subject, body, agent_id: None)
    assert (
        _proposed_edges(
            edges=[{"issue": 5, "blocked_by": [999]}],
            known={5, 6},
            existing={5: [], 6: []},
            agent_id="vigil-1",
        )
        is None
    )


# --------------------------------------------------------------------------------------------------
# 生命周期：once 走 _drain_queue 排空；K=1 与 K=2 同末态；KeyboardInterrupt 经 stop_event 收池。
# --------------------------------------------------------------------------------------------------


def _run_once(tmp_path, *, concurrency, subjects) -> list[str]:
    """跑一趟 `run_vigil(once=True)`：打桩 `_sense`/`_act`，返回被真正推进过的 subject 序列。"""
    acted: list[str] = []
    lock = threading.Lock()
    done: set[str] = set()

    def _fake_sense(*, config, subject):
        with lock:
            finished = subject in done
        return _Observed(
            facts=_facts(subject=subject, merged=finished), clock=_Clock(last_progress_at=_NOW)
        )

    def _fake_act(*, backend, state, work_dir, config, observed, verdict, agent_id, now, lock_fd):
        with lock:
            acted.append(observed.facts.subject)
            done.add(observed.facts.subject)
        return "done"

    import openagents.recipes.vigil as mod

    saved = (mod._sense, mod._act, mod._intake, mod._subjects, mod._has_attempt_stamp)
    mod._sense, mod._act = _fake_sense, _fake_act
    mod._intake = lambda **kw: None
    mod._subjects = lambda *, config: list(subjects)
    mod._has_attempt_stamp = lambda *, facts, fp: False
    try:
        run_vigil(
            backend=None,
            state=None,
            work_dir=tmp_path,
            config=_config(),
            once=True,
            concurrency=concurrency,
            agent_id="a",
        )
    finally:
        (mod._sense, mod._act, mod._intake, mod._subjects, mod._has_attempt_stamp) = saved
    return acted


def test_run_vigil_once_drains_the_queue(tmp_path):
    """`once=True`：一个生产者 tick + `_drain_queue` 排空（队列必须见底才返回，给测试确定性同步语义）。"""
    acted = _run_once(tmp_path, concurrency=1, subjects=["issue:5", "issue:6"])
    assert sorted(acted) == ["issue:5", "issue:6"]
    conn = _connect(db_path=tmp_path / ".openagents" / "vigil-queue.db")
    assert conn.execute("SELECT COUNT(*) FROM work_queue").fetchone()[0] == 0


def test_k1_serial_and_k2_parallel_reach_the_same_end_state(tmp_path):
    """**K=1 不是另一种模式，只是并发上限为 1** —— 两者末态必须一致。"""
    subjects = ["issue:5", "issue:6", "issue:7"]
    serial = _run_once(tmp_path / "a", concurrency=1, subjects=subjects)
    parallel = _run_once(tmp_path / "b", concurrency=2, subjects=subjects)
    assert sorted(serial) == sorted(parallel) == subjects


def test_run_vigil_survives_keyboard_interrupt(tmp_path, monkeypatch):
    """Ctrl-C → `stop_event` 置位 → worker 收池退出；queued 行留 DB（幂等 + 持久，重启续跑）。"""

    def _boom(**kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(vigil_module, "_producer_tick", _boom)
    run_vigil(  # 不得把 KeyboardInterrupt 漏出去
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        once=False,
        concurrency=2,
        agent_id="a",
    )
    assert not [
        t for t in threading.enumerate() if t.name.startswith("vigil-worker") and t.is_alive()
    ]


def test_producer_error_does_not_kill_the_daemon(tmp_path, monkeypatch):
    """`once=False` 时单轮生产者异常 → 记日志、继续（**不杀生产者**）；第二轮确认还活着后收工。"""
    ticks = {"n": 0}

    def _flaky(**kwargs):
        ticks["n"] += 1
        if ticks["n"] == 1:
            raise RuntimeError("gh 抽风")
        raise KeyboardInterrupt

    monkeypatch.setattr(vigil_module, "_producer_tick", _flaky)
    monkeypatch.setattr(vigil_module.time, "sleep", lambda _: None)
    run_vigil(
        backend=None,
        state=None,
        work_dir=tmp_path,
        config=_config(),
        once=False,
        concurrency=1,
        agent_id="a",
    )
    assert ticks["n"] == 2, "第一轮抛异常后生产者必须活着进第二轮"
