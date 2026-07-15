"""# Spec-0016/T2：RuntimeState 的 issue 评论游标（get/set_issue_cursor，独立命名空间）单元测试。

覆盖：
- set 后 get 读回同值；
- 缺省 get 返回 None；
- issue N 与 PR N 游标互不干扰（独立命名空间键 issue_cursors vs cursors）；
- 写路径落 runtime-state.json（其余顶层键不被覆盖）。
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
    # issue N 与 PR N 撞号也互不干扰：独立命名空间键。
    state.set_cursor(pr_number=149, comment_id="pr-cursor")
    state.set_issue_cursor(number=149, comment_id="issue-cursor")
    assert state.get_cursor(pr_number=149) == "pr-cursor"
    assert state.get_issue_cursor(number=149) == "issue-cursor"
    # 反向：写 issue 游标不影响 PR 游标读回。
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
