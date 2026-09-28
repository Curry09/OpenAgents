"""Validate the pressure-test oracle and small concurrent campaign (Spec-0089/T1)."""

import json
import subprocess
import sys
from pathlib import Path

from scripts.stress_delivery_recovery import Campaign


def test_stress_oracle_detects_approval_of_dirty_candidate(tmp_path):
    """Do not let the test double silently forgive the original dirty-review bug."""
    campaign = Campaign(root=tmp_path, scenarios=["clean"], workers=1, seed=59)
    try:
        job = campaign.jobs[1]
        sha = campaign._remote(job=job)
        job.reviewed.append(sha)
        (job.worktree / job.filename).write_text("value = 2\n")
        campaign.add_label(pr_number=10001, name=f"review-approved:{sha[:7]}")
        assert any("dirty worktree" in error for error in campaign.violations)
        report = campaign.report(queue=[], elapsed=0)
        assert not report["passed"]
    finally:
        campaign.logfile.close()


def test_stress_campaign_uses_all_workers_and_distinguishes_negative_controls(tmp_path):
    """Require correct final merges, real concurrency and bounded failure isolation."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "stress_delivery_recovery.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--workers",
            "4",
            "--repeats",
            "1",
            "--baseline",
            "4",
            "--deadline",
            "40",
            "--output-parent",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=80,
    )
    summaries = list(tmp_path.glob("delivery-stress-*/summary.json"))
    assert len(summaries) == 1, result.stdout + result.stderr
    baseline, mixed = json.loads(summaries[0].read_text())
    assert result.returncode == 0, result.stdout + result.stderr
    assert baseline["merged"] == 4 and baseline["peak_active"] == 4
    assert mixed["merged"] == 15 and mixed["expected_failures"] == 2
    assert mixed["peak_active"] == 4
    for campaign in (baseline, mixed):
        assert campaign["passed"]
        assert not campaign["queue_residue"]
        assert not campaign["duplicates"]
        assert not campaign["violations"]
    for row in mixed["rows"]:
        if row["scenario"].startswith("persistent-"):
            assert row["claims"] == [1, 2, 3]
            assert not row["merged"]
        if row["merged"]:
            assert row["merged_sha"] in row["reviewed"]
            assert row["merged_sha"] in row["approved"]
        if row["scenario"] in {"remote-moves", "merge-race"}:
            assert row["calls"]["reviewer"] == 2


def test_three_remote_updates_do_not_exhaust_execution_failure_budget(tmp_path):
    """Spec-0017/0065: invalidate old reviews, then merge the fourth stable candidate."""
    campaign = Campaign(
        root=tmp_path,
        scenarios=["clean", "remote-churn-3", "persistent-fetch-failure", "persistent-review-dirt"],
        workers=4,
        seed=59,
    )
    report = campaign.execute(deadline_seconds=40)
    assert report["passed"], report
    assert report["merged"] == 2 and report["expected_failures"] == 2
    assert not report["duplicates"] and not report["queue_residue"]
    for row in report["rows"]:
        if row["scenario"] == "remote-churn-3":
            assert row["calls"]["reviewer"] == 4
            assert row["claims"] and set(row["claims"]) == {1}
            assert not row["failed"] and row["state"] == "done"
            assert len(set(row["reviewed"])) == 4
            assert row["approved"] == [row["merged_sha"]]
            assert row["merged_sha"] == row["reviewed"][-1]
        elif row["scenario"].startswith("persistent-"):
            assert row["claims"] == [1, 2, 3] and not row["merged"]
