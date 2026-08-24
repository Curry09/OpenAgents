"""Structured tool-usage telemetry tests."""

from __future__ import annotations

import json

from openagents.runtime import tool_usage


def test_summarize_counts_lookup_before_first_edit() -> None:
    summary = tool_usage.summarize(tool_names=("Read", "Bash", "Grep", "Edit", "Read", "Write"))
    assert summary == {
        "tool_count": 6,
        "tool_names": ["Read", "Bash", "Grep", "Edit", "Read", "Write"],
        "first_edit_index": 3,
        "lookup_before_first_edit": 3,
        "lookup_budget": 6,
        "lookup_budget_exceeded": False,
    }


def test_record_writes_names_not_tool_inputs(tmp_path) -> None:
    tool_usage.record(work_dir=tmp_path, role="implementer", tool_names=("Read", "Edit"))
    path = tmp_path / ".openagents" / tool_usage.TOOL_USAGE_FILENAME
    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["role"] == "implementer"
    assert event["tool_names"] == ["Read", "Edit"]
    assert "command" not in event


def test_record_failure_does_not_affect_the_workflow(tmp_path) -> None:
    (tmp_path / ".openagents").write_text("not a directory", encoding="utf-8")

    tool_usage.record(work_dir=tmp_path, role="implementer", tool_names=("Read", "Edit"))

    assert (tmp_path / ".openagents").is_file()


def test_record_from_linked_worktree_writes_to_main_worktree(tmp_path) -> None:
    main = tmp_path / "repo"
    linked = main / ".openagents" / "worktrees" / "issue-17"
    git_dir = main / ".git" / "worktrees" / "issue-17"
    git_dir.mkdir(parents=True)
    linked.mkdir(parents=True)
    (linked / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")

    tool_usage.record(work_dir=linked, role="implementer", tool_names=("Read", "Edit"))

    assert (main / ".openagents" / tool_usage.TOOL_USAGE_FILENAME).exists()
    assert not (linked / ".openagents" / tool_usage.TOOL_USAGE_FILENAME).exists()


def test_record_keeps_bounded_reason_only_when_budget_is_exceeded(tmp_path) -> None:
    tool_usage.record(
        work_dir=tmp_path,
        role="implementer",
        tool_names=("Read",) * 7 + ("Edit",),
        lookup_exception_reason="缺少运行时接口定义" * 100,
    )
    event = json.loads(
        (tmp_path / ".openagents" / tool_usage.TOOL_USAGE_FILENAME).read_text(encoding="utf-8")
    )
    assert event["lookup_exception_reason"].startswith("缺少运行时接口定义")
    assert len(event["lookup_exception_reason"]) == 400

    other = tmp_path / "other"
    tool_usage.record(
        work_dir=other,
        role="implementer",
        tool_names=("Read", "Edit"),
        lookup_exception_reason="不应保存",
    )
    below_budget = json.loads(
        (other / ".openagents" / tool_usage.TOOL_USAGE_FILENAME).read_text(encoding="utf-8")
    )
    assert "lookup_exception_reason" not in below_budget


def test_load_and_aggregate_by_role(tmp_path) -> None:
    path = tmp_path / "usage.jsonl"
    path.write_text(
        '{"role":"implementer","tool_count":3,"lookup_before_first_edit":2,"lookup_budget_exceeded":false}\n'
        "not-json\n"
        '{"role":"implementer","tool_count":9,"lookup_before_first_edit":8,"lookup_budget_exceeded":true}\n',
        encoding="utf-8",
    )
    rows = tool_usage.aggregate(events=tool_usage.load_events(path=path))
    assert rows == [
        {
            "role": "implementer",
            "invocations": 2,
            "average_lookup_before_edit": 5.0,
            "max_lookup_before_edit": 8,
            "budget_exceeded": 1,
            "exceeded_without_reason": 1,
        }
    ]
