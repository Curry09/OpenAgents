"""Spec-0060/T3: runtime.gates 最小硬闸单测——只验客观事实，四闸各正/反例。

utils.git.head_sha / utils.github.pr_head_branch 打桩，不触真实仓库/网络。
"""

from __future__ import annotations

import pytest

from openagents.runtime import gates
from openagents.runtime.gates import GateError
from openagents.utils import github as ugithub


def test_snapshot_head_reads_current_head(monkeypatch):
    # 确定性基点读取：直接透传 utils.git.head_sha 的客观值（供 recipe 交付前自记 before）。
    monkeypatch.setattr(gates.git, "head_sha", lambda *, work_dir: "cursha00000")
    assert gates.snapshot_head(workspace="/tmp/wt") == "cursha00000"


def test_head_advanced_passes_when_moved(monkeypatch):
    monkeypatch.setattr(gates.git, "head_sha", lambda *, work_dir: "newsha00000")
    # 前移即通过，并返回实际 after（供上层接证据溯源戳复用）。
    assert gates.assert_head_advanced(before="oldsha00000", workspace="/tmp/wt") == "newsha00000"


def test_head_advanced_raises_when_unmoved(monkeypatch):
    monkeypatch.setattr(gates.git, "head_sha", lambda *, work_dir: "samesha0000")
    with pytest.raises(GateError):
        gates.assert_head_advanced(before="samesha0000", workspace="/tmp/wt")


def test_head_advanced_raises_when_no_head(monkeypatch):
    monkeypatch.setattr(gates.git, "head_sha", lambda *, work_dir: "")
    with pytest.raises(GateError):
        gates.assert_head_advanced(before="oldsha00000", workspace="/tmp/wt")


def test_round_cap_yields_then_raises_on_overflow():
    seen = []
    with pytest.raises(GateError):
        for r in gates.round_cap(max_rounds=3):
            seen.append(r)  # 恒不 break → 跑满 3 轮后 raise
    assert seen == [1, 2, 3]


def test_round_cap_no_raise_when_break_early():
    seen = []
    for r in gates.round_cap(max_rounds=3):
        seen.append(r)
        if r == 2:
            break  # 提前收敛 → 生成器丢弃、永不 raise
    assert seen == [1, 2]


def test_pr_exists_passes(monkeypatch):
    monkeypatch.setattr(gates.github, "pr_head_branch", lambda *, pr_number: "openagents/issue-1")
    gates.assert_pr_exists(pr_number=1)  # 不抛即通过


def test_pr_exists_raises_when_absent(monkeypatch):
    def _boom(*, pr_number):
        raise ugithub.GithubError("not found")

    monkeypatch.setattr(gates.github, "pr_head_branch", _boom)
    with pytest.raises(GateError):
        gates.assert_pr_exists(pr_number=999)


def test_evidence_stamp_passes_on_match():
    gates.assert_evidence_stamp(head_sha="abc123", claimed="abc123")


def test_evidence_stamp_raises_on_mismatch():
    with pytest.raises(GateError):
        gates.assert_evidence_stamp(head_sha="abc123", claimed="def456")


# --------------------------------------------------------------------------- #
# Spec-0066/T3: assert_merge_allowed —— 合并不可逆红线硬闸（CI 全绿 + review-approved:<head sha7>@head）。
# 纯读客观事实、假快照注入、不触网。四情形：全绿+approved@head 放行；否则各抛 GateError。
# --------------------------------------------------------------------------- #

_HEAD = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"  # 40 位 head；sha7 = "a1b2c3d"


def _stub_merge_facts(monkeypatch, *, ci_state, ci_count, labels):
    monkeypatch.setattr(
        gates.github,
        "check_snapshot",
        lambda *, pr_number: ugithub.CheckSnapshot(
            state=ci_state, count=ci_count, latest_started_at=""
        ),
    )
    monkeypatch.setattr(
        gates.github,
        "pr_snapshot",
        lambda *, pr_number: ugithub.PRSnapshot(
            number=pr_number,
            state="OPEN",
            head_sha=_HEAD,
            labels=tuple(labels),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            head_pushed_at="",
        ),
    )


def test_merge_allowed_passes_when_green_and_approved_at_head(monkeypatch):
    _stub_merge_facts(monkeypatch, ci_state="pass", ci_count=3, labels=("review-approved:a1b2c3d",))
    gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)  # 不抛即通过


def test_merge_allowed_raises_when_ci_failing(monkeypatch):
    # (a) CI 非全绿 → 决不合并未过 CI 的代码。
    _stub_merge_facts(monkeypatch, ci_state="fail", ci_count=3, labels=("review-approved:a1b2c3d",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_allowed_raises_when_ci_pending(monkeypatch):
    _stub_merge_facts(
        monkeypatch, ci_state="pending", ci_count=3, labels=("review-approved:a1b2c3d",)
    )
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_allowed_raises_when_zero_checks(monkeypatch):
    # 零个 check「不算绿」（比照 vigil _ci_state）——防合并一份没跑过 CI 的代码。
    _stub_merge_facts(monkeypatch, ci_state="pass", ci_count=0, labels=("review-approved:a1b2c3d",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_allowed_raises_when_no_approved_label(monkeypatch):
    # (b) 无 review-approved label → 决不合并未审代码。
    _stub_merge_facts(monkeypatch, ci_state="pass", ci_count=3, labels=("openagents",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_allowed_raises_when_label_sha_mismatches_head(monkeypatch):
    # (c) label sha ≠ 当前 head（_sense→_act 间 head 前移的 TOCTOU）→ 裁决作废，决不合并未审的新代码。
    _stub_merge_facts(monkeypatch, ci_state="pass", ci_count=3, labels=("review-approved:0000000",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)
