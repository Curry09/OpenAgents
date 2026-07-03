"""Spec-0049/T3：vigil 发现段认领闸的归属感知分流单元测试。

只测 `_dispatch_kind` / `_claim_reclaimable` 的认领闸；github.list_issue_comments 与远端分支探测
（git ls-remote 子进程）一律 mock，不真实联网。既有两道闸（本地 State / 远端分支）与 resume
语义的回归由 test_vigil.py 覆盖，这里聚焦「读署名认领便签判归属 + 过期回收」的新行为。
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openagents import github, identity, vigil
from openagents.github import DISPATCH_LABEL, Comment, GithubError, Issue
from openagents.state import STATUS_SOLVING, RunRecord
from openagents.vigil import CLAIM_EXPIRY_SECONDS, Vigil

SELF_ID = "agent-self"


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


def _vigil(*, state=None, agent_id=SELF_ID):
    return Vigil(
        orchestrator=object(),
        messages=object(),
        state=state or _StubState(),
        work_dir=Path("/repo"),
        agent_id=agent_id,
    )


def _iso(*, ago_seconds):
    return (datetime.now(UTC) - timedelta(seconds=ago_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _claim_comment(*, owner, ago_seconds):
    """一条 owner 在 ago_seconds 秒前贴的署名认领便签评论。"""
    return Comment(
        id="IC",
        author=owner,
        body=identity.build_claim_note(agent_id=owner),
        created_at=_iso(ago_seconds=ago_seconds),
    )


def _patch_no_remote_branch(monkeypatch):
    monkeypatch.setattr(Vigil, "_remote_branch_exists", lambda self, *, branch: False)


def _patch_comments(monkeypatch, comments):
    monkeypatch.setattr(github, "list_issue_comments", lambda *, number: list(comments))


# --------------------------------------------------------------------------- #
# 归属闸：他人未过期 → 跳过；他人过期 / 无便签 / 自己残留 → fresh
# --------------------------------------------------------------------------- #


def test_other_backend_fresh_claim_is_skipped(monkeypatch):
    _patch_no_remote_branch(monkeypatch)
    _patch_comments(monkeypatch, [_claim_comment(owner="agent-other", ago_seconds=5)])
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) is None


def test_other_backend_expired_claim_is_recovered_as_fresh(monkeypatch):
    _patch_no_remote_branch(monkeypatch)
    _patch_comments(
        monkeypatch, [_claim_comment(owner="agent-other", ago_seconds=CLAIM_EXPIRY_SECONDS + 60)]
    )
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) == "fresh"


def test_no_valid_claim_note_is_fresh(monkeypatch):
    # 带认领标签但 issue 上没有有效认领便签（只有粗标签、无归属凭证）→ 可认领。
    _patch_no_remote_branch(monkeypatch)
    _patch_comments(
        monkeypatch, [Comment(id="IC", author="human", body="+1", created_at=_iso(ago_seconds=1))]
    )
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) == "fresh"


def test_own_fresh_residue_is_reclaimed_as_fresh(monkeypatch):
    # 最近便签是**自己**的（record 却为 None，如上轮退让/begin_run 失败的残留）→ 重认领，不跳过。
    _patch_no_remote_branch(monkeypatch)
    _patch_comments(monkeypatch, [_claim_comment(owner=SELF_ID, ago_seconds=5)])
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) == "fresh"


def test_latest_note_wins_other_newer_over_own_older(monkeypatch):
    # 自己贴过一条旧便签、他人贴了更晚一条 → 最近便签是他人且未过期 → 跳过（末位 created_at 定胜负）。
    _patch_no_remote_branch(monkeypatch)
    _patch_comments(
        monkeypatch,
        [
            _claim_comment(owner=SELF_ID, ago_seconds=100),
            _claim_comment(owner="agent-other", ago_seconds=5),
        ],
    )
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) is None


# --------------------------------------------------------------------------- #
# 读评论失败：保守跳过、不上抛（决策 8：不拖垮整轮）
# --------------------------------------------------------------------------- #


def test_comments_query_error_is_conservative_skip_and_no_raise(monkeypatch):
    _patch_no_remote_branch(monkeypatch)

    def _boom(*, number):
        raise GithubError("gh issue view failed")

    monkeypatch.setattr(github, "list_issue_comments", _boom)
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    # 不上抛、保守判「他人活认领」→ 跳过。
    assert _vigil()._dispatch_kind(issue=issue) is None


# --------------------------------------------------------------------------- #
# 无认领标签：既有 fresh 语义不变；且**不读评论**（认领闸罕见路径不拖慢常态）
# --------------------------------------------------------------------------- #


def test_unclaimed_no_record_no_branch_is_fresh_without_reading_comments(monkeypatch):
    _patch_no_remote_branch(monkeypatch)

    def _boom(*, number):
        raise AssertionError("无认领标签时不应读评论")

    monkeypatch.setattr(github, "list_issue_comments", _boom)
    issue = Issue(number=9, title="t", body="b", labels=("openagents",))

    assert _vigil()._dispatch_kind(issue=issue) == "fresh"


# --------------------------------------------------------------------------- #
# resume / 远端分支：认领闸不干扰既有语义
# --------------------------------------------------------------------------- #


def test_resume_orphan_run_unaffected_by_claim_gate(monkeypatch):
    _patch_no_remote_branch(monkeypatch)

    def _boom(*, number):
        raise AssertionError("resume 路径不应触及认领闸")

    monkeypatch.setattr(github, "list_issue_comments", _boom)
    state = _StubState(records={9: _run_record(issue_number=9, status=STATUS_SOLVING, pr_number=0)})
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil(state=state)._dispatch_kind(issue=issue) == "resume"


def test_existing_remote_branch_skips_before_claim_gate(monkeypatch):
    monkeypatch.setattr(Vigil, "_remote_branch_exists", lambda self, *, branch: True)

    def _boom(*, number):
        raise AssertionError("闸 2 命中后不应进认领闸")

    monkeypatch.setattr(github, "list_issue_comments", _boom)
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) is None


# --------------------------------------------------------------------------- #
# 阈值可配
# --------------------------------------------------------------------------- #


def test_expiry_threshold_is_configurable(monkeypatch):
    # 把 T 调大后，原本超时的他人认领龄变为未超时 → 从 fresh 回收翻转为跳过（阈值参与判定）。
    _patch_no_remote_branch(monkeypatch)
    _patch_comments(
        monkeypatch, [_claim_comment(owner="agent-other", ago_seconds=CLAIM_EXPIRY_SECONDS + 100)]
    )
    monkeypatch.setattr(vigil, "CLAIM_EXPIRY_SECONDS", CLAIM_EXPIRY_SECONDS + 1000)
    issue = Issue(number=9, title="t", body="b", labels=(DISPATCH_LABEL,))

    assert _vigil()._dispatch_kind(issue=issue) is None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
