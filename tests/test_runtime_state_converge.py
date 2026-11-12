"""#Spec-0063/T1: runtime.RuntimeState amplification single — agent_id/ui_capable top layer access + authoritative STATUS_*

Use tmp_path Real reading and writing temporary runtime-state.json（hermetic, no net; overwhelm agent_id/ui_capable It’s...
Read-write and write-deficit/damage error, isolation from the runs level, and STATUS_* authoritative constant.
"""

from openagents.runtime.state import (
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    STATUS_SOLVING,
    RuntimeState,
)


def _new_state(tmp_path):
    """Construct a Runtestate that points to temporary runtime-state.json."""
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
    """set_run and set agent_id/ui_capable: Three are non-interference (top and runs level)."""
    state = _new_state(tmp_path)
    state.set_run(issue_number=5, status=STATUS_SOLVING, branch="openagents/issue-5", pr_number=0)
    state.set_agent_id(agent_id="agent-iso")
    state.set_ui_capable(value=True)

    run = state.get_run(issue_number=5)
    assert run == {"status": STATUS_SOLVING, "branch": "openagents/issue-5", "pr_number": 0}
    assert state.get_agent_id() == "agent-iso"
    assert state.get_ui_capable() is True


def test_runs_isolated_from_top_level_keys(tmp_path):
    """Reverse: Set agent_id/ui_capable first, set_run, run-off agent_id/ui_capable is still in place."""
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
    assert STATUS_FAILED == "failed"
