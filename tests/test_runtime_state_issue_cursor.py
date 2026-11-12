"""# Spec-0016/T2:issue comment for Runtestate (get/set_issue_cursor, independent naming space) unit test.

Coverage:
- Set after get read back the same value;
- Not get back
- Assue N and PR N do not interfere (separate namespace key issue_cursors vs Cursors);
- Write path down runtime-state.json (the remaining top key is not overwritten).
"""

import json

import pytest

from openagents.runtime.state import RuntimeState


@pytest.fixture
def state(tmp_path):
    return RuntimeState(path=tmp_path / "runtime-state.json")


def test_set_then_get_roundtrip(state):
    state.set_issue_cursor(number=149, comment_id="2026-07-14T12:00:00Z")
    assert state.get_issue_cursor(number=149) == "2026-07-14T12:00:00Z"


def test_default_get_is_none(state):
    assert state.get_issue_cursor(number=149) is None


def test_issue_and_pr_cursors_are_independent(state):
    # The issue N and PR N collisions are also non-interference: an independent namespace key.
    state.set_cursor(pr_number=149, comment_id="pr-cursor")
    state.set_issue_cursor(number=149, comment_id="issue-cursor")
    assert state.get_cursor(pr_number=149) == "pr-cursor"
    assert state.get_issue_cursor(number=149) == "issue-cursor"
    # Reverse: Write the issue cursor does not affect PR cursor reading back.
    state.set_issue_cursor(number=149, comment_id="issue-cursor-2")
    assert state.get_cursor(pr_number=149) == "pr-cursor"


def test_persists_to_dedicated_namespace_key(state, tmp_path):
    state.set_issue_cursor(number=149, comment_id="c-1")
    data = json.loads((tmp_path / "runtime-state.json").read_text(encoding="utf-8"))
    assert data["issue_cursors"] == {"149": "c-1"}


def test_write_preserves_other_top_level_keys(state):
    state.set_agent_id(agent_id="oa-1")
    state.set_cursor(pr_number=7, comment_id="pr-7")
    state.set_issue_cursor(number=149, comment_id="issue-149")
    assert state.get_agent_id() == "oa-1"
    assert state.get_cursor(pr_number=7) == "pr-7"
    assert state.get_issue_cursor(number=149) == "issue-149"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
