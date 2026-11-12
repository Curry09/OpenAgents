"""Spec-0060/T3: runtime.gates Minimum Hardgate Single Test - Only Objective Facts, Four Gates Positive/Terror.

utils.git.head_sha / utils.github.pr_head_branch staked the stake without touching the real warehouse/network.
Spec-0017 Supplement: 2026-09-09-delivery-review-snapshot-tests-design.md real-time HEAD returns.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from openagents.runtime import gates
from openagents.runtime.gates import GateError
from openagents.utils import github as ugithub


def test_snapshot_head_reads_current_head(monkeypatch):
    # Valid basis for reading: the objective value (for pre-delivery self-collection) of utils.git.head_sha directly.
    monkeypatch.setattr(gates.git, "head_sha", lambda *, work_dir: "cursha00000")
    assert gates.snapshot_head(workspace="/tmp/wt") == "cursha00000"


def test_head_advanced_passes_when_moved(monkeypatch):
    monkeypatch.setattr(gates.git, "head_sha", lambda *, work_dir: "newsha00000")
    # Forward is passed and returns to the actual after (for retroactive retrace of the upper layer of evidence).
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
            seen.append(r)  # Always break and run after three rounds
    assert seen == [1, 2, 3]


def test_round_cap_no_raise_when_break_early():
    seen = []
    for r in gates.round_cap(max_rounds=3):
        seen.append(r)
        if r == 2:
            break  # Early accumulation, pre-disposal of the generator, never raise
    assert seen == [1, 2]


def test_pr_exists_passes(monkeypatch):
    monkeypatch.setattr(gates.github, "pr_head_branch", lambda *, pr_number: "openagents/issue-1")
    gates.assert_pr_exists(pr_number=1)  # Pass or pass.


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

    with pytest.raises(gates.DesignApprovalStale, match="The approved design does not exist"):
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
        with pytest.raises(GateError, match="The approved design does not exist"):
            gates.assert_design_approved(
                workspace=tmp_path, issue_number=8, approved_digest=approved
            )
        return
    gates.assert_design_approved(workspace=tmp_path, issue_number=8, approved_digest=approved)
    group.tasks[0].acceptance = "Allow arbitrary scope escapes"
    model.dump_group(group=group, path=path)
    with pytest.raises(GateError, match="The approved design does not exist"):
        gates.assert_design_approved(workspace=tmp_path, issue_number=8, approved_digest=approved)


def test_duplicate_semantic_design_identity_is_rejected(tmp_path, monkeypatch):
    """Spec-0088/T1: number normalization must not resolve an ambiguous approval by guessing."""
    group = SimpleNamespace(metadata=SimpleNamespace(issue=8))
    monkeypatch.setattr(gates.spec_model, "load_all", lambda *, specs_root: [group, group])
    monkeypatch.setattr(gates.spec_model, "design_digest", lambda *, group: "v2:approved")
    with pytest.raises(GateError, match="multiple Specs matching the approved design digest"):
        gates.assert_design_approved(
            workspace=tmp_path, issue_number=8, approved_digest="v2:approved"
        )


# --------------------------------------------------------------------------- #
# Spec-0017/T3: assert_merge_allowed - Merger of Unreversible Red Line Hardgates (CI Green + review-approved: <head Sha7>@head)
# Read the facts, fake snapshots, and don't touch the net. Four scenarios: green + approved@head; otherwise, each of them throws GateError.
# --------------------------------------------------------------------------- #

_HEAD = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"  # 40 bit head;sha7 = "a1b2c3d"


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
    gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)  # Pass or pass.


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
    # (a) The CI is not fully green and never merges an uncharted CI code.
    _stub_merge_facts(monkeypatch, ci_state="fail", ci_count=3, labels=("review-approved:a1b2c3d",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_pending_is_not_ready_not_a_violation(monkeypatch):
    # Spec-0074: The CI is still running (pending, count > 0) not red, but temporary - throw Megernot Ready instead of GateError, and then move to the next level.
    # For _run_claimed When you're done with the clean work. attempts）Avoid pending→success Unsung inside window needs-human。
    _stub_merge_facts(
        monkeypatch, ci_state="pending", ci_count=3, labels=("review-approved:a1b2c3d",)
    )
    with pytest.raises(gates.MergeNotReady):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)
    assert not issubclass(
        gates.MergeNotReady, GateError
    )  # Strictly distinguish with red line (not swallowed by except GateError)


def test_merge_allowed_raises_when_zero_checks(monkeypatch):
    # No checks at the current head must not authorize a merge.
    # And ** before pending**: count=0 = state even pending is "none CI" and not "CI running"
    _stub_merge_facts(monkeypatch, ci_state="pass", ci_count=0, labels=("review-approved:a1b2c3d",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_zero_checks_with_pending_state_is_hard_block(monkeypatch):
    # Count=0 and state=ping (Gitea empty pattern): still hard red (no CI), not Mergenotready.
    _stub_merge_facts(
        monkeypatch, ci_state="pending", ci_count=0, labels=("review-approved:a1b2c3d",)
    )
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_allowed_raises_when_no_approved_label(monkeypatch):
    # (b) No reported-approved label  →  never merges unheard code.
    _stub_merge_facts(monkeypatch, ci_state="pass", ci_count=3, labels=("openagents",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_merge_allowed_raises_when_label_sha_mismatches_head(monkeypatch):
    # (c) The current head [sense_act] TOCTOU (moved) decision is annulled and no new code is merged without review.
    _stub_merge_facts(monkeypatch, ci_state="pass", ci_count=3, labels=("review-approved:0000000",))
    with pytest.raises(GateError):
        gates.assert_merge_allowed(pr_number=175, head_sha=_HEAD)


def test_delivery_snapshot_merge_rechecks_head_even_when_old_approval_label_remains(monkeypatch):
    """Spec-0017 supplements (2026-09-09 snapshot tests): Push does not automatically delete old approval labels."""
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
    assert rejected, (
        "Far-end re-enactment but old labels are still in place, and the old HeADs cannot be used to merge"
    )
