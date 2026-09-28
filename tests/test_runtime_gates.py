"""Spec-0060/T3: runtime.gates 最小硬闸单测——只验客观事实，四闸各正/反例。

utils.git.head_sha / utils.github.pr_head_branch 打桩，不触真实仓库/网络。
Spec-0017 补充：2026-09-09-delivery-review-snapshot-tests-design.md 的实时 HEAD 回归。
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

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


def test_integration_stamp_requires_every_version_to_match():
    approved = gates.IntegrationStamp(
        base_sha="base-a", head_sha="head-a", design_digest="design-a"
    )
    gates.assert_integration_stamp(approved=approved, current=approved)
    for field in ("base_sha", "head_sha", "design_digest"):
        changed = {
            "base_sha": approved.base_sha,
            "head_sha": approved.head_sha,
            "design_digest": approved.design_digest,
        }
        changed[field] += "-changed"
        with pytest.raises(GateError):
            gates.assert_integration_stamp(
                approved=approved, current=gates.IntegrationStamp(**changed)
            )


def test_design_approved_selects_digest_when_issue_number_is_reused(tmp_path, monkeypatch):
    approved = SimpleNamespace(metadata=SimpleNamespace(issue=13))
    historical = SimpleNamespace(metadata=SimpleNamespace(issue=13))
    monkeypatch.setattr(gates.spec_model, "load_all", lambda *, specs_root: [historical, approved])
    monkeypatch.setattr(
        gates.spec_model,
        "design_digest",
        lambda *, group: "approved" if group is approved else "historical",
    )

    gates.assert_design_approved(workspace=tmp_path, issue_number=13, approved_digest="approved")


def test_design_approved_rejects_when_approved_digest_disappeared(tmp_path, monkeypatch):
    changed = SimpleNamespace(metadata=SimpleNamespace(issue=13))
    monkeypatch.setattr(gates.spec_model, "load_all", lambda *, specs_root: [changed])
    monkeypatch.setattr(gates.spec_model, "design_digest", lambda *, group: "changed")

    with pytest.raises(gates.DesignApprovalStale, match="已批准设计不存在"):
        gates.assert_design_approved(
            workspace=tmp_path, issue_number=13, approved_digest="approved"
        )


@pytest.mark.parametrize("legacy", [True, False])
def test_design_approval_renumber_and_real_changes(tmp_path, legacy):
    """Spec-0088/T1: use real persisted Specs through the merge gate, not mock digests."""
    from openagents.spec import model

    group = model.Group(
        number="0002",
        metadata=model.Metadata(title="guard", issue=8, slug="guard", summary="s"),
        tasks=[
            model.Task(
                id="T1",
                title="guard",
                status="in-progress",
                priority="P1",
                scope="Spec-0002/T1: enforce scope",
                acceptance="Spec-0002/T1: reject escape",
            )
        ],
        overview=model.Overview(summary="Keep the user scope"),
    )
    path = tmp_path / "docs/specs/0002-guard.md"
    digest = model.legacy_design_digest if legacy else model.design_digest
    approved = digest(group=group)
    model.dump_group(group=group, path=path)
    gates.assert_design_approved(workspace=tmp_path, issue_number=8, approved_digest=approved)
    group = replace(group, number="0005")
    group.tasks[0].scope = group.tasks[0].scope.replace("0002", "0005")
    group.tasks[0].acceptance = group.tasks[0].acceptance.replace("0002", "0005")
    path = path.rename(path.with_name("0005-guard.md"))
    model.dump_group(group=group, path=path)
    if legacy:
        # No original snapshot migration: an old approval never blesses changed raw content.
        with pytest.raises(GateError, match="已批准设计不存在"):
            gates.assert_design_approved(
                workspace=tmp_path, issue_number=8, approved_digest=approved
            )
        return
    gates.assert_design_approved(workspace=tmp_path, issue_number=8, approved_digest=approved)
    group.tasks[0].acceptance = "Allow arbitrary scope escapes"
    model.dump_group(group=group, path=path)
    with pytest.raises(GateError, match="已批准设计不存在"):
        gates.assert_design_approved(workspace=tmp_path, issue_number=8, approved_digest=approved)


def test_duplicate_semantic_design_identity_is_rejected(tmp_path, monkeypatch):
    """Spec-0088/T1: number normalization must not resolve an ambiguous approval by guessing."""
    group = SimpleNamespace(metadata=SimpleNamespace(issue=8))
    monkeypatch.setattr(gates.spec_model, "load_all", lambda *, specs_root: [group, group])
    monkeypatch.setattr(gates.spec_model, "design_digest", lambda *, group: "v2:approved")
    with pytest.raises(GateError, match="多个内容相同"):
        gates.assert_design_approved(
            workspace=tmp_path, issue_number=8, approved_digest="v2:approved"
        )


# --------------------------------------------------------------------------- #
# Spec-0017/T3: assert_merge_allowed —— 合并不可逆红线硬闸（CI 全绿 + review-approved:<head sha7>@head）。
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


def test_merge_allowed_skips_ci_but_still_requires_approved_head(monkeypatch):
    _stub_merge_facts(
        monkeypatch,
        ci_state="pending",
        ci_count=1,
        labels=("review-approved:a1b2c3d",),
    )
    monkeypatch.setattr(
        gates.github,
        "check_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("ci:skip must not read checks")),
    )
    gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD, require_ci=False)

    monkeypatch.setattr(
        gates.github,
        "pr_snapshot",
        lambda *, pr_number: ugithub.PRSnapshot(
            number=pr_number,
            state="OPEN",
            head_sha=_HEAD,
            labels=("openagents",),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            head_pushed_at="",
        ),
    )
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD, require_ci=False)


def test_merge_allowed_raises_when_ci_failing(monkeypatch):
    # (a) CI 非全绿 → 决不合并未过 CI 的代码。
    _stub_merge_facts(monkeypatch, ci_state="fail", ci_count=3, labels=("review-approved:a1b2c3d",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_pending_is_not_ready_not_a_violation(monkeypatch):
    # Spec-0074 实证：CI 仍在跑（pending，count>0）不是红线、是暂态——抛 MergeNotReady 而非 GateError，
    # 供 _run_claimed 当干净收工（不烧 attempts），避免 pending→success 窗口内误挂 needs-human。
    _stub_merge_facts(
        monkeypatch, ci_state="pending", ci_count=3, labels=("review-approved:a1b2c3d",)
    )
    with pytest.raises(gates.MergeNotReady):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)
    assert not issubclass(
        gates.MergeNotReady, GateError
    )  # 与红线严格区分（不被 except GateError 吞）


def test_merge_allowed_raises_when_zero_checks(monkeypatch):
    # 零个 check「不算绿」（比照 vigil _ci_state）——防合并一份没跑过 CI 的代码。硬红线 GateError，
    # 且**先于 pending 判**：count==0 时 state 即便是 pending 也是「根本没 CI」不是「CI 在跑」。
    _stub_merge_facts(monkeypatch, ci_state="pass", ci_count=0, labels=("review-approved:a1b2c3d",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_zero_checks_with_pending_state_is_hard_block(monkeypatch):
    # count==0 且 state=pending（Gitea 空 combined 的形态）：仍是硬红线（没 CI），不是 MergeNotReady。
    _stub_merge_facts(
        monkeypatch, ci_state="pending", ci_count=0, labels=("review-approved:a1b2c3d",)
    )
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


def test_delivery_snapshot_merge_rechecks_head_even_when_old_approval_label_remains(monkeypatch):
    """Spec-0017 补充（2026-09-09 snapshot tests）：push 不会自动删除旧审批标签。"""
    old_label = f"review-approved:{_HEAD[:7]}"
    _stub_merge_facts(monkeypatch, ci_state="pass", ci_count=3, labels=(old_label,))
    monkeypatch.setattr(
        gates.github,
        "pr_snapshot",
        lambda *, pr_number: ugithub.PRSnapshot(
            number=pr_number,
            state="OPEN",
            head_sha="b" * 40,
            labels=(old_label,),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            head_pushed_at="",
        ),
    )
    rejected = False
    try:
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)
    except (GateError, gates.MergeNotReady):
        rejected = True
    assert rejected, "远端已换版但旧标签还在，不能用感知时的旧 HEAD 放行合并"
