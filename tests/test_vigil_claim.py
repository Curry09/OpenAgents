"""Spec-0039/T2：vigil 发现段第 3 道认领闸 + 过期回收的单元测试。

只测 `_dispatch_kind` 的认领闸分流；github.issue_label_age_seconds 与远端分支探测
（git ls-remote 子进程）一律 mock，不真实联网。既有两道闸（本地 State / 远端分支）与
resume 语义的回归由 test_vigil.py 覆盖，这里聚焦第 3 道闸引入后的新行为。
"""

from pathlib import Path

import pytest

from openagents import github, vigil
from openagents.github import DISPATCH_LABEL, GithubError, Issue
from openagents.state import STATUS_SOLVING, RunRecord
from openagents.vigil import CLAIM_EXPIRY_SECONDS, Vigil


class _StubState:
    def __init__(self, *, records=None):
        self._records = dict(records or {})

    def find_by_issue(self, *, issue_number):
        return self._records.get(issue_number)


def _run_record(*, issue_number, status, pr_number):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url="u" if pr_number else "",
        status=status,
        summary="",
    )


def _vigil(*, state=None):
    return Vigil(
        orchestrator=object(),
        messages=object(),
        state=state or _StubState(),
        work_dir=Path("/repo"),
    )


def _patch_no_remote_branch(monkeypatch):
    """远端无该 issue 分支（闸 2 不命中）。"""
    monkeypatch.setattr(Vigil, "_remote_branch_exists", lambda self, *, branch: False)


def _patch_age(monkeypatch, *, age):
    """认领标签秒龄固定为 age（None 表示取不到时戳）。"""
    monkeypatch.setattr(github, "issue_label_age_seconds", lambda *, number, name: age)


# --------------------------------------------------------------------------- #
# 闸 3：带认领标签且未过期 → 跳过
# --------------------------------------------------------------------------- #


def test_claimed_and_not_expired_is_skipped(monkeypatch):
    _patch_no_remote_branch(monkeypatch)
    _patch_age(monkeypatch, age=CLAIM_EXPIRY_SECONDS - 1)  # 未过期
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) is None


def test_claimed_but_expired_is_recovered_as_fresh(monkeypatch):
    # 带认领标签、无分支、标签龄 > T → 僵尸认领，回收（视同 fresh 重新认领）。
    _patch_no_remote_branch(monkeypatch)
    _patch_age(monkeypatch, age=CLAIM_EXPIRY_SECONDS + 1)
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) == "fresh"


def test_claim_age_none_is_treated_as_not_expired(monkeypatch):
    # 取不到时戳（None）→ 保守判未过期 → 跳过，不误回收活后端的认领。
    _patch_no_remote_branch(monkeypatch)
    _patch_age(monkeypatch, age=None)
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) is None


def test_timeline_error_does_not_raise_and_is_treated_as_not_expired(monkeypatch):
    # 时间线 API 抛 GithubError（gh < 2.42/限流/权限）→ _dispatch_kind 不上抛（否则掀翻整轮
    # 发现、饿死其后所有 issue 与本轮 PR 轮询，破坏决策 8）→ 保守判未过期 → 跳过。
    _patch_no_remote_branch(monkeypatch)

    def _boom(*, number, name):
        raise GithubError("gh timeline failed")

    monkeypatch.setattr(github, "issue_label_age_seconds", _boom)
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) is None


# --------------------------------------------------------------------------- #
# 无认领标签：既有 fresh 语义不变；且不查时间线（认领闸罕见路径不拖慢常态）
# --------------------------------------------------------------------------- #


def test_unclaimed_no_record_no_branch_is_fresh(monkeypatch):
    _patch_no_remote_branch(monkeypatch)

    def _boom(*, number, name):
        raise AssertionError("无认领标签时不应查时间线")

    monkeypatch.setattr(github, "issue_label_age_seconds", _boom)
    issue = Issue(number=9, title="t", body="b", labels=("openagents",))

    assert _vigil()._dispatch_kind(issue=issue) == "fresh"


# --------------------------------------------------------------------------- #
# resume / 远端分支：认领闸不干扰既有语义
# --------------------------------------------------------------------------- #


def test_resume_orphan_run_unaffected_by_claim_label(monkeypatch):
    # solving/pr=0 的孤儿 run 即使 issue 带认领标签，仍判 resume（record 分支先于认领闸）。
    _patch_no_remote_branch(monkeypatch)

    def _boom(*, number, name):
        raise AssertionError("resume 路径不应触及认领闸")

    monkeypatch.setattr(github, "issue_label_age_seconds", _boom)
    state = _StubState(records={9: _run_record(issue_number=9, status=STATUS_SOLVING, pr_number=0)})
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil(state=state)._dispatch_kind(issue=issue) == "resume"


def test_existing_remote_branch_skips_before_claim_gate(monkeypatch):
    # 远端已有分支（闸 2 命中）→ None，且不进认领闸（不查时间线）。
    monkeypatch.setattr(Vigil, "_remote_branch_exists", lambda self, *, branch: True)

    def _boom(*, number, name):
        raise AssertionError("闸 2 命中后不应进认领闸")

    monkeypatch.setattr(github, "issue_label_age_seconds", _boom)
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) is None


# --------------------------------------------------------------------------- #
# 阈值可配
# --------------------------------------------------------------------------- #


def test_expiry_threshold_is_configurable(monkeypatch):
    # 把 T 调大后，原本超时的龄变为未超时 → 从 fresh 回收翻转为跳过（证明阈值可配、参与判定）。
    _patch_no_remote_branch(monkeypatch)
    _patch_age(monkeypatch, age=CLAIM_EXPIRY_SECONDS + 100)
    monkeypatch.setattr(vigil, "CLAIM_EXPIRY_SECONDS", CLAIM_EXPIRY_SECONDS + 1000)
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) is None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
