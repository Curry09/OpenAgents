"""# Spec-0063/T1: runtime.RuntimeState 扩容单测——agent_id/ui_capable 顶层存取 + 权威 STATUS_*。

用 tmp_path 真实读写临时 runtime-state.json（hermetic，不触网）；覆盖 agent_id/ui_capable 的
读写与缺键/损坏容错、与 runs 平级不互相覆盖的隔离性，以及 STATUS_* 权威常量字面量。
"""

from openagents.runtime.state import (
    STATUS_BLOCKED,
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    STATUS_SOLVING,
    RuntimeState,
)


def _new_state(tmp_path):
    """构造一个指向临时 runtime-state.json 的 RuntimeState。"""
    return RuntimeState(path=tmp_path / ".openagents" / "runtime-state.json")


def test_get_agent_id_none_when_unset(tmp_path):
    state = _new_state(tmp_path)
    assert state.get_agent_id() is None


def test_set_then_get_agent_id(tmp_path):
    state = _new_state(tmp_path)
    state.set_agent_id(agent_id="agent-abc")
    assert state.get_agent_id() == "agent-abc"


def test_agent_id_persists_across_instances(tmp_path):
    path = tmp_path / ".openagents" / "runtime-state.json"
    RuntimeState(path=path).set_agent_id(agent_id="agent-xyz")
    assert RuntimeState(path=path).get_agent_id() == "agent-xyz"


def test_get_agent_id_none_when_file_corrupt(tmp_path):
    path = tmp_path / ".openagents" / "runtime-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json", encoding="utf-8")
    assert RuntimeState(path=path).get_agent_id() is None


def test_get_ui_capable_false_when_unset(tmp_path):
    state = _new_state(tmp_path)
    assert state.get_ui_capable() is False


def test_set_ui_capable_true_then_get(tmp_path):
    state = _new_state(tmp_path)
    state.set_ui_capable(value=True)
    assert state.get_ui_capable() is True


def test_set_ui_capable_false_then_get(tmp_path):
    state = _new_state(tmp_path)
    state.set_ui_capable(value=True)
    state.set_ui_capable(value=False)
    assert state.get_ui_capable() is False


def test_ui_capable_false_when_file_corrupt(tmp_path):
    path = tmp_path / ".openagents" / "runtime-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<<<broken", encoding="utf-8")
    assert RuntimeState(path=path).get_ui_capable() is False


def test_top_level_keys_isolated_from_runs(tmp_path):
    """先 set_run 再 set agent_id/ui_capable：三者互不干扰（顶层键与 runs 平级）。"""
    state = _new_state(tmp_path)
    state.set_run(issue_number=5, status=STATUS_SOLVING, branch="openagents/issue-5", pr_number=0)
    state.set_agent_id(agent_id="agent-iso")
    state.set_ui_capable(value=True)

    run = state.get_run(issue_number=5)
    assert run == {"status": STATUS_SOLVING, "branch": "openagents/issue-5", "pr_number": 0}
    assert state.get_agent_id() == "agent-iso"
    assert state.get_ui_capable() is True


def test_runs_isolated_from_top_level_keys(tmp_path):
    """反向：先 set agent_id/ui_capable 再 set_run，run 落盘后 agent_id/ui_capable 仍在。"""
    state = _new_state(tmp_path)
    state.set_agent_id(agent_id="agent-rev")
    state.set_ui_capable(value=True)
    state.set_run(issue_number=9, status=STATUS_PR_OPEN, branch="openagents/issue-9", pr_number=42)

    assert state.get_agent_id() == "agent-rev"
    assert state.get_ui_capable() is True
    run = state.get_run(issue_number=9)
    assert run == {"status": STATUS_PR_OPEN, "branch": "openagents/issue-9", "pr_number": 42}


def test_status_constants_literals():
    assert STATUS_SOLVING == "solving"
    assert STATUS_RFC_REVIEW == "rfc-review"
    assert STATUS_PR_OPEN == "pr-open"
    assert STATUS_ITERATING == "iterating"
    assert STATUS_DONE == "done"
    assert STATUS_CLOSED == "closed"
    assert STATUS_BLOCKED == "blocked"
