"""Spec-0065/T2: Four types of original-readable contract test for Vigil level-triggered `_sense`.

Overwrite 8 new functions for this spec: pr_for_branch/ pr_snapshot/ _head_committed_at/
check_snapshot / check_logs / issue_rest_id / list_blocked_by / add_blocked_by。

All gh subprocesses are mock (monkeypact subprocess.run), not real call gh - follow existing github
Tested house rules (see tests/test_github_claim_label.py / test_github_is_open_draft.py).

The assertion is that** the non-variable**: the Vigil sheet (`_classify`) is based on the semantics of these fields, any of which is the interpretation
The drifting will allow the dispatcher to make the wrong decision (e.g. redo the merged issue or read ”Zero Check” as ”CI Green.”
Combining a code that has not run past CI directly.
"""

import json
import subprocess
from dataclasses import dataclass

import pytest

from openagents.utils.github import (
    Blocker,
    CheckSnapshot,
    GithubError,
    PRSnapshot,
    _head_committed_at,
    add_blocked_by,
    check_logs,
    check_snapshot,
    issue_rest_id,
    list_blocked_by,
    pr_for_branch,
    pr_snapshot,
)


@dataclass
class _FakeProc:
    """Hypothetical subprocess.CompletedProcess."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    """Single-response subprocess.run double; `runner.calls` records argv (for assertion of gh parameters) at each time."""
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    runner.calls = calls
    return runner


def _fake_run_seq(*, responses):
    """subprocess.run (for a multi-girth call for business) is a callback.

    `add_blocked_by` First `issue_rest_id` (GET) second and second gh
    . The _fake_run cannot be expressed in a single response.
    """
    calls: list[list[str]] = []
    queue = list(responses)

    def runner(args, **kwargs):
        calls.append(list(args))
        return queue.pop(0) if queue else _FakeProc()

    runner.calls = calls
    return runner


# --------------------------------------------------------------------------- #
# pr_for_branch (Spec-0065/T2:** state not relevant** - merged/closed PR must also be visible)
# --------------------------------------------------------------------------- #


def test_pr_for_branch_uses_state_all(monkeypatch):
    # Core regression gate: The search must be `--state all`. If returned, PR disappears from the list as soon as it is returned, and the night is up and down.
    # The issue will be read as "P" before "P" and "P" will be taken to branch four and then a PR will be redo the same issue again.
    payload = json.dumps([{"number": 164, "url": "https://github.com/o/r/pull/164"}])
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    pr_for_branch(branch="openagents/issue-150")

    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "pr", "list"]
    assert cmd[cmd.index("--state") + 1] == "all"
    assert cmd[cmd.index("--head") + 1] == "openagents/issue-150"


def test_pr_for_branch_returns_merged_pr(monkeypatch):
    # The termination of the `_classify` -- the termination condition can only be read out from "that PR is what it is now."
    # So the merged PR must be returned (and not Noone).
    payload = json.dumps([{"number": 164, "url": "https://github.com/o/r/pull/164"}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    pr = pr_for_branch(branch="openagents/issue-150")

    assert pr is not None
    assert pr.number == 164
    assert pr.url == "https://github.com/o/r/pull/164"


def test_pr_for_branch_returns_closed_pr(monkeypatch):
    # The PR that people turn off voluntarily also needs to be seen (or the vigil will be reopened).
    payload = json.dumps([{"number": 99, "url": "https://github.com/o/r/pull/99"}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    pr = pr_for_branch(branch="openagents/issue-9")

    assert pr is not None and pr.number == 99


def test_pr_for_branch_none_when_never_opened(monkeypatch):
    # The only legitimate signal to "should go 4-by-P" is the "P" page.
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))

    assert pr_for_branch(branch="openagents/issue-1") is None


def test_pr_for_branch_none_when_number_missing(monkeypatch):
    # The absence of a number of units is a flawed structure that is conservatively considered "no PR" and not to be thrown.
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps([{"url": "u"}])))

    assert pr_for_branch(branch="b") is None


def test_pr_for_branch_none_when_payload_not_list(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"oops": 1})))

    assert pr_for_branch(branch="b") is None


def test_pr_for_branch_takes_most_recent_only(monkeypatch):
    # `--limit 1`: gh Press the old row, only the latest.
    runner = _fake_run(stdout=json.dumps([{"number": 3, "url": "u3"}]))
    monkeypatch.setattr(subprocess, "run", runner)

    assert pr_for_branch(branch="b").number == 3
    cmd = runner.calls[-1]
    assert cmd[cmd.index("--limit") + 1] == "1"


def test_pr_for_branch_raises_on_gh_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401"))

    with pytest.raises(GithubError):
        pr_for_branch(branch="b")


# --------------------------------------------------------------------------- #
# pr_snapshot（Spec-0065/T2: Same source PR (a) Current status;head_pushed_at The only time a guard dog can get away with it.
# --------------------------------------------------------------------------- #


def _pr_view_payload(**overrides):
    """A real `gh pr view --json …` response; overwrites individual fields as needed."""
    payload = {
        "number": 164,
        "state": "OPEN",
        "headRefOid": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "labels": [{"name": "openagents"}, {"name": "review-approved:a1b2c3d"}],
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "commits": [
            {"oid": "old", "committedDate": "2026-07-14T09:00:00Z"},
            {"oid": "head", "committedDate": "2026-07-14T10:30:00Z"},
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_pr_snapshot_parses_every_field(monkeypatch):
    runner = _fake_run(stdout=_pr_view_payload())
    monkeypatch.setattr(subprocess, "run", runner)

    snap = pr_snapshot(pr_number=164)

    assert isinstance(snap, PRSnapshot)
    assert snap.number == 164
    assert snap.state == "OPEN"
    assert snap.head_sha == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    assert snap.labels == ("openagents", "review-approved:a1b2c3d")
    assert snap.mergeable == "MERGEABLE"
    assert snap.merge_state_status == "CLEAN"
    # head_pushed_at takes committees** last article**(=head) referredDate, not the first article.
    assert snap.head_pushed_at == "2026-07-14T10:30:00Z"
    # Spec-0017/T1: is Draft default is_draft default False (the existing construction point/payload zero changes are still available for example).
    assert snap.is_draft is False
    # All fields must be retrieved from the same `gh pr view` (same-source snapshot, without reading contradictory middle).
    cmd = runner.calls[-1]
    assert cmd[:4] == ["gh", "pr", "view", "164"]
    fields = cmd[cmd.index("--json") + 1].split(",")
    assert set(fields) == {
        "number",
        "state",
        "headRefOid",
        "labels",
        "mergeable",
        "mergeStateStatus",
        "commits",
        "isDraft",  # Spec-0017/T1: draft and the rest of the current same source read-and-read
    }
    assert len(runner.calls) == 1


def test_pr_snapshot_is_draft_true(monkeypatch):
    # Spec-0017/T1: isDraft=true is_draft True (draft to First Class Sniper Fact).
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(isDraft=True)))
    assert pr_snapshot(pr_number=164).is_draft is True


def test_pr_snapshot_is_draft_false(monkeypatch):
    # Spec-0017/T1: isDraft=false → is_draft False(Reformed) PR）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(isDraft=False)))
    assert pr_snapshot(pr_number=164).is_draft is False


def test_pr_snapshot_is_draft_non_bool_defaults_false(monkeypatch):
    # Spec-0017/T1: is Draft Non-Breble (Agnormal Structure) Default Error Perception False (cf. is_draft).
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(isDraft="yes")))
    assert pr_snapshot(pr_number=164).is_draft is False


def test_pr_snapshot_state_and_mergeable_upcased(monkeypatch):
    # Original capital, not integrated into Boolean - the "what combination is conflict" is the caller (recipes.vigil).
    payload = _pr_view_payload(state="merged", mergeable="conflicting", mergeStateStatus="dirty")
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = pr_snapshot(pr_number=164)

    assert snap.state == "MERGED"
    assert snap.mergeable == "CONFLICTING"
    assert snap.merge_state_status == "DIRTY"


def test_pr_snapshot_mergeable_unknown_is_legal(monkeypatch):
    # UNKNOWN (GitHub walk is not yet complete, just push is common) is a valid value, as it is sent back and not thrown.
    payload = _pr_view_payload(mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = pr_snapshot(pr_number=164)

    assert snap.mergeable == "UNKNOWN"
    assert snap.merge_state_status == "UNKNOWN"


def test_pr_snapshot_missing_mergeable_defaults_to_unknown(monkeypatch):
    # Unlike mergeability(), fields are missing/is nullit and fall into the snapshot of UNKNOWN (the Vigil is "not finished" and the rest of the day is not finished).
    # Next lap, you can look at it.
    payload = _pr_view_payload(mergeable=None, mergeStateStatus=None)
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = pr_snapshot(pr_number=164)

    assert snap.mergeable == "UNKNOWN"
    assert snap.merge_state_status == "UNKNOWN"


def test_pr_snapshot_empty_labels(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(labels=[])))

    assert pr_snapshot(pr_number=164).labels == ()


def test_pr_snapshot_head_pushed_at_empty_when_no_commits(monkeypatch):
    # No committees (anomaly/disable structure) Empty string: the watchdogs "no doorkeeper" on this basis, rather than taking the Noone to calculate the time difference.
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_pr_view_payload(commits=[])))

    assert pr_snapshot(pr_number=164).head_pushed_at == ""


def test_pr_snapshot_fresh_pr_has_timestamp_from_head_commit(monkeypatch):
    # PR: Except for head committee, there's no time stamp.
    # Even a new head with no checks or comments needs a progress timestamp.
    payload = _pr_view_payload(
        commits=[{"oid": "head", "committedDate": "2026-07-14T11:00:00Z"}],
        labels=[],
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert pr_snapshot(pr_number=164).head_pushed_at == "2026-07-14T11:00:00Z"


def test_pr_snapshot_raises_on_non_dict(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps(["oops"])))

    with pytest.raises(GithubError):
        pr_snapshot(pr_number=164)


def test_pr_snapshot_raises_when_number_missing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "OPEN"})))

    with pytest.raises(GithubError):
        pr_snapshot(pr_number=164)


# --------------------------------------------------------------------------- #
# _head_committed_at (Spec-0065/T2:head timetamp parsing function - direct single id, free of gh)
# --------------------------------------------------------------------------- #


def test_head_committed_at_takes_last_commit():
    commits = [
        {"committedDate": "2026-07-14T09:00:00Z"},
        {"committedDate": "2026-07-14T10:00:00Z"},
    ]
    assert _head_committed_at(commits=commits) == "2026-07-14T10:00:00Z"


def test_head_committed_at_empty_for_empty_or_bad_shapes():
    # Empty list / None / Nonlist / Last non-dict/ missing committeeDate - empty string (fail-soft).
    assert _head_committed_at(commits=[]) == ""
    assert _head_committed_at(commits=None) == ""
    assert _head_committed_at(commits={"committedDate": "x"}) == ""
    assert _head_committed_at(commits=["not-a-dict"]) == ""
    assert _head_committed_at(commits=[{"oid": "abc"}]) == ""


# --------------------------------------------------------------------------- #
# check_snapshot (Spec-0065/T2:**count cannot save** - zero check  →  green)
# --------------------------------------------------------------------------- #


def test_check_snapshot_zero_checks_is_not_green_by_count(monkeypatch):
    # The key one: gh, state remains "pass" when returning to the empty list (using _classify_checks's old calibre), but
    # ** count = 0** so the caller can read it as "waiting CI" instead of "CI Green" -- otherwise the watch will be a single one.
    # A check code that never ran.
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))

    snap = check_snapshot(pr_number=164)

    assert isinstance(snap, CheckSnapshot)
    assert snap.count == 0
    assert snap.latest_started_at == ""
    # The only evidence to distinguish between "zero check" and "full green" is the count, which is the fact that the state itself cannot separate.
    assert snap.state == "pass"


def test_check_snapshot_no_checks_reported_is_swallowed_with_zero_count(monkeypatch):
    # The warehouse was uncircle-free and reported "no checks reported" - swallowed, but counted as zero.
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="no checks reported on the 'x' branch")
    )

    snap = check_snapshot(pr_number=164)

    assert snap == CheckSnapshot(state="pass", count=0, latest_started_at="")


def test_check_snapshot_all_green_has_nonzero_count(monkeypatch):
    # "All Green" is the same as the state of "Zero Check" by count: Here count = 2.
    payload = json.dumps(
        [
            {
                "name": "test",
                "state": "SUCCESS",
                "link": "https://x/1",
                "startedAt": "2026-07-14T10:00:00Z",
            },
            {
                "name": "lint",
                "state": "SKIPPED",
                "link": "https://x/2",
                "startedAt": "2026-07-14T10:05:00Z",
            },
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = check_snapshot(pr_number=164)

    assert snap.state == "pass"
    assert snap.count == 2
    # latest_started_at takes the last start time (ISO dictionary order, time order).
    assert snap.latest_started_at == "2026-07-14T10:05:00Z"


def test_check_snapshot_pending_rollup(monkeypatch):
    # Any check is still running (non-fail pass, IN_PROGRESS/ QUEUD / PENDING etc.) pending.
    payload = json.dumps(
        [
            {
                "name": "test",
                "state": "SUCCESS",
                "link": "",
                "startedAt": "2026-07-14T10:00:00Z",
            },
            {
                "name": "e2e",
                "state": "IN_PROGRESS",
                "link": "",
                "startedAt": "2026-07-14T10:02:00Z",
            },
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = check_snapshot(pr_number=164)

    assert snap.state == "pending"
    assert snap.count == 2
    assert snap.latest_started_at == "2026-07-14T10:02:00Z"


def test_check_snapshot_failure_beats_pending(monkeypatch):
    # Failure takes precedence over ongoing (same as _classify_checks): one-off run #fail.
    payload = json.dumps(
        [
            {
                "name": "e2e",
                "state": "IN_PROGRESS",
                "link": "",
                "startedAt": "2026-07-14T10:02:00Z",
            },
            {"name": "test", "state": "FAILURE", "link": "https://x/9", "startedAt": ""},
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    snap = check_snapshot(pr_number=164)

    assert snap.state == "fail"
    assert snap.count == 2


def test_check_snapshot_pending_returncode_8_is_allowed(monkeypatch):
    # gh Returns with exit code 8 when check is still in progress, stdout remains legal JSON - cannot be thrown when wrong.
    payload = json.dumps(
        [{"name": "test", "state": "QUEUED", "link": "", "startedAt": "2026-07-14T10:00:00Z"}]
    )
    runner = _fake_run(returncode=8, stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    snap = check_snapshot(pr_number=164)

    assert snap.state == "pending"
    assert snap.count == 1
    cmd = runner.calls[-1]
    assert cmd[:4] == ["gh", "pr", "checks", "164"]
    # StartedAt must be in --json request, otherwise latest_started_at is permanently empty, _Clock is blind.
    assert "startedAt" in cmd[cmd.index("--json") + 1].split(",")


def test_check_snapshot_missing_started_at_tolerated(monkeypatch):
    payload = json.dumps([{"name": "test", "state": "SUCCESS", "link": ""}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert check_snapshot(pr_number=164).latest_started_at == ""


def test_check_snapshot_reraises_other_gh_errors(monkeypatch):
    # The only thing that swallows is "no checks reported", "scrutinizing" and "scrutinizing" the true wrongs.
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401 must authenticate")
    )

    with pytest.raises(GithubError):
        check_snapshot(pr_number=164)


# --------------------------------------------------------------------------- #
# check_logs (Spec-0065/T2: failed check digest, feed back the fix-ci agent)
# --------------------------------------------------------------------------- #


def test_check_logs_returns_failed_summaries(monkeypatch):
    payload = json.dumps(
        [
            {"name": "test", "state": "FAILURE", "link": "https://x/run/1"},
            {"name": "lint", "state": "SUCCESS", "link": "https://x/run/2"},
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    logs = check_logs(pr_number=164)

    assert logs == ["test [FAILURE] https://x/run/1"]


def test_check_logs_empty_when_all_green(monkeypatch):
    payload = json.dumps([{"name": "test", "state": "SUCCESS", "link": "https://x/1"}])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert check_logs(pr_number=164) == []


def test_check_logs_empty_when_no_checks(monkeypatch):
    # Empty payload/ no CI repository  →  No summary failed (not dropped).
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))
    assert check_logs(pr_number=164) == []

    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="no checks reported on the 'x' branch")
    )
    assert check_logs(pr_number=164) == []


# --------------------------------------------------------------------------- #
# issue_rest_id (Spec-0065/T2: RET id issue number)
# --------------------------------------------------------------------------- #


def test_issue_rest_id_happy_path(monkeypatch):
    # RET id (3372285600) and issue number (150) are two numbers - the one that depends on API for requests.
    runner = _fake_run(stdout=json.dumps({"id": 3372285600}))
    monkeypatch.setattr(subprocess, "run", runner)

    assert issue_rest_id(number=150) == 3372285600

    cmd = runner.calls[-1]
    assert cmd[:2] == ["gh", "api"]
    assert cmd[2] == "repos/{owner}/{repo}/issues/150"


def test_issue_rest_id_raises_when_id_missing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"number": 150})))

    with pytest.raises(GithubError):
        issue_rest_id(number=150)


def test_issue_rest_id_raises_on_empty_payload(monkeypatch):
    # gh Output is empty _gh_json and None Zidc Z GithubError (no silent return 0).
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=""))

    with pytest.raises(GithubError):
        issue_rest_id(number=150)


def test_issue_rest_id_raises_on_gh_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="HTTP 404 Not Found"))

    with pytest.raises(GithubError):
        issue_rest_id(number=150)


# --------------------------------------------------------------------------- #
# list_blocked_by (Spec-0065/T2: GitHub Native Dependency Side - Call at once to give "side"+ "blocker off")
# --------------------------------------------------------------------------- #


def test_list_blocked_by_parses_edges_and_states(monkeypatch):
    # Answers to the state deps_done directly, without a second round of queries.
    payload = json.dumps(
        [
            {"number": 151, "state": "closed", "title": "T1 Bottom"},
            {"number": 152, "state": "open", "title": "T2 github"},
        ]
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    blockers = list_blocked_by(number=150)

    assert blockers == [Blocker(number=151, state="CLOSED"), Blocker(number=152, state="OPEN")]
    cmd = runner.calls[-1]
    assert cmd[:2] == ["gh", "api"]
    assert cmd[2] == "repos/{owner}/{repo}/issues/150/dependencies/blocked_by"


def test_list_blocked_by_empty_list(monkeypatch):
    # No dependent tiding [] (the issue can be immediately moved).
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))

    assert list_blocked_by(number=150) == []


def test_list_blocked_by_404_becomes_empty(monkeypatch):
    # The repository does not open the dependency feature  →  404 is classified as "no dependence " and does not throw it (dependent is optional).
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="gh: Not Found (HTTP 404)")
    )

    assert list_blocked_by(number=150) == []


def test_list_blocked_by_skips_rows_without_number(monkeypatch):
    payload = json.dumps([{"state": "open"}, {"number": 152, "state": "open"}, "junk"])
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert list_blocked_by(number=150) == [Blocker(number=152, state="OPEN")]


def test_list_blocked_by_missing_state_becomes_empty_string(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps([{"number": 152}])))

    assert list_blocked_by(number=150) == [Blocker(number=152, state="")]


def test_list_blocked_by_non_list_payload_becomes_empty(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"message": "x"})))

    assert list_blocked_by(number=150) == []


def test_list_blocked_by_reraises_other_gh_errors(monkeypatch):
    # Just 404, and the real wrongs like genetics.
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401 must authenticate")
    )

    with pytest.raises(GithubError):
        list_blocked_by(number=150)


# --------------------------------------------------------------------------- #
# add_blocked_by (Spec-0065/T2: POST Dependence Edge; Request for brooker's id, not number)
# --------------------------------------------------------------------------- #


def test_add_blocked_by_posts_rest_id_not_number(monkeypatch):
    # Two gh: REST id 2 POST of GHt brooker to blocked_by endpoint** of blocked issue**.
    runner = _fake_run_seq(
        responses=[
            _FakeProc(stdout=json.dumps({"id": 3372285600})),  # issue_rest_id(151)
            _FakeProc(stdout="{}"),  # POST
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    assert add_blocked_by(number=150, blocker_number=151) is None
    assert len(runner.calls) == 2

    # 1 id was read by blocker(151), not blocked issue(150).
    lookup = runner.calls[0]
    assert lookup[2] == "repos/{owner}/{repo}/issues/151"

    # 2 POST landed on the end of the block issue (150) and requested to be accompanied by REST id (3372285600) of blocker,
    #    Instead of its issue number (151) -- the reverse GitHub would have sidelined to another issue.
    post = runner.calls[1]
    assert post[:2] == ["gh", "api"]
    assert post[post.index("--method") + 1] == "POST"
    assert "repos/{owner}/{repo}/issues/150/dependencies/blocked_by" in post
    assert "issue_id=3372285600" in post
    assert "issue_id=151" not in post


def test_add_blocked_by_swallows_already_exists(monkeypatch):
    # GitHub returns 4x  →  & Zi (and ensure_label swallows "already exists") when the border already exists.
    runner = _fake_run_seq(
        responses=[
            _FakeProc(stdout=json.dumps({"id": 1})),
            _FakeProc(returncode=1, stderr="HTTP 422: Issue dependency already exists"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    assert add_blocked_by(number=150, blocker_number=151) is None


def test_add_blocked_by_swallows_duplicate(monkeypatch):
    runner = _fake_run_seq(
        responses=[
            _FakeProc(stdout=json.dumps({"id": 1})),
            _FakeProc(returncode=1, stderr="HTTP 422: duplicate dependency"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    assert add_blocked_by(number=150, blocker_number=151) is None


def test_add_blocked_by_reraises_other_gh_errors(monkeypatch):
    runner = _fake_run_seq(
        responses=[
            _FakeProc(stdout=json.dumps({"id": 1})),
            _FakeProc(returncode=1, stderr="HTTP 403 Resource not accessible"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", runner)

    with pytest.raises(GithubError):
        add_blocked_by(number=150, blocker_number=151)


def test_add_blocked_by_propagates_rest_id_lookup_failure(monkeypatch):
    # id id id id cannot be guessed, no number tops, throw (and no POST).
    runner = _fake_run_seq(responses=[_FakeProc(returncode=1, stderr="HTTP 404 Not Found")])
    monkeypatch.setattr(subprocess, "run", runner)

    with pytest.raises(GithubError):
        add_blocked_by(number=150, blocker_number=151)
    assert len(runner.calls) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
