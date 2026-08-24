"""Architecture approval persistence tests for RuntimeState."""

from openagents.runtime.state import RuntimeState


def test_run_round_trip_preserves_design_digest(tmp_path) -> None:
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    state.set_run(
        issue_number=7,
        status="pr-open",
        branch="openagents/issue-7",
        pr_number=9,
        design_digest="abc123",
    )
    assert state.get_run(issue_number=7)["design_digest"] == "abc123"

    state.set_run(
        issue_number=7,
        status="iterating",
        branch="openagents/issue-7",
        pr_number=9,
    )
    assert state.get_run(issue_number=7)["design_digest"] == "abc123"


def test_run_round_trip_normalizes_and_preserves_evidence_pack(tmp_path) -> None:
    state = RuntimeState(path=tmp_path / "runtime-state.json")
    state.set_run(
        issue_number=8,
        status="pr-open",
        branch="openagents/issue-8",
        pr_number=10,
        evidence_pack=[
            {
                "fact": "timeout is polled",
                "path": "entry.py",
                "symbol": "_run_supervised",
                "subjective": "discard me",
            }
        ],
    )
    assert state.get_run(issue_number=8)["evidence_pack"] == [
        {
            "fact": "timeout is polled",
            "path": "entry.py",
            "symbol": "_run_supervised",
            "verification": "",
        }
    ]

    state.set_run(
        issue_number=8,
        status="iterating",
        branch="openagents/issue-8",
        pr_number=10,
    )
    assert state.get_run(issue_number=8)["evidence_pack"][0]["path"] == "entry.py"
