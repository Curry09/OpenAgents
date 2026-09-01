"""Spec-0079 token usage ledger behavior tests."""

from __future__ import annotations

import json

from openagents.backends.base import TokenUsage
from openagents.runtime import token_usage


def _usage(total: int = 35) -> TokenUsage:
    return TokenUsage(
        input_tokens=10,
        output_tokens=2,
        cache_read_input_tokens=20,
        cache_creation_input_tokens=3,
        total_tokens=total,
        total_source="derived-components",
    )


def test_record_and_aggregate_preserves_unavailable_coverage(tmp_path):
    token_usage.record(
        work_dir=tmp_path,
        role="implementer",
        backend="api-backend",
        status="success",
        usage=_usage(),
    )
    token_usage.record(
        work_dir=tmp_path,
        role="implementer",
        backend="legacy",
        status="backend_error",
        usage=None,
    )
    path = tmp_path / ".openagents" / token_usage.TOKEN_USAGE_FILENAME
    events = token_usage.load_events(path=path)
    rows = token_usage.aggregate(events=events)
    assert rows == [
        {
            "role": "implementer",
            "invocations": 2,
            "reported": 1,
            "unavailable": 1,
            "reported_total_count": 0,
            "derived_total_count": 1,
            "input_tokens": 10,
            "output_tokens": 2,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 3,
            "reasoning_tokens": 0,
            "total_tokens": 35,
        }
    ]


def test_record_uses_privacy_field_allowlist(tmp_path):
    token_usage.record(
        work_dir=tmp_path,
        role="reviewer",
        backend="api-backend",
        status="success",
        usage=_usage(),
    )
    event = json.loads((tmp_path / ".openagents" / token_usage.TOKEN_USAGE_FILENAME).read_text())
    assert set(event) == {
        "invocation_id",
        "at",
        "role",
        "backend",
        "status",
        "usage_source",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "reasoning_tokens",
        "total_tokens",
        "total_source",
    }


def test_record_failure_is_fail_open(tmp_path):
    (tmp_path / ".openagents").write_text("not a directory", encoding="utf-8")
    token_usage.record(
        work_dir=tmp_path,
        role="implementer",
        backend="api-backend",
        status="success",
        usage=_usage(),
    )
    assert (tmp_path / ".openagents").is_file()


def test_linked_worktree_writes_to_main_and_loader_skips_damage(tmp_path):
    main = tmp_path / "repo"
    linked = main / ".openagents" / "worktrees" / "issue-17"
    git_dir = main / ".git" / "worktrees" / "issue-17"
    git_dir.mkdir(parents=True)
    linked.mkdir(parents=True)
    (linked / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
    token_usage.record(
        work_dir=linked,
        role="implementer",
        backend="api-backend",
        status="success",
        usage=_usage(),
    )
    path = main / ".openagents" / token_usage.TOKEN_USAGE_FILENAME
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
        handle.write('{"role":"x","usage_source":"reported"}\n')
    assert len(token_usage.load_events(path=path)) == 1
