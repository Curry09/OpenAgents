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
