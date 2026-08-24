"""RFC-0001 T1: AgentBackend 协议与 AgentResult 的契约测试。"""

from openagents.backends.base import AgentBackend, AgentResult


def test_agent_result_holds_changed_and_summary():
    result = AgentResult(changed=True, summary="改了 foo.py")
    assert result.changed is True
    assert result.summary == "改了 foo.py"
    assert result.protocol_output == "改了 foo.py"


def test_agent_result_separates_protocol_output_from_display_summary():
    result = AgentResult(changed=False, summary="short", raw_output="full structured output")
    assert result.summary == "short"
    assert result.protocol_output == "full structured output"


def test_agent_result_is_frozen():
    result = AgentResult(changed=False, summary="")
    try:
        result.changed = True  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("AgentResult 应为不可变（frozen）")


def test_conforming_object_is_instance_of_backend():
    class DummyBackend:
        name = "dummy"

        def run(self, *, work_dir, task, context):
            return AgentResult(changed=False, summary="")

    assert isinstance(DummyBackend(), AgentBackend)


def test_object_missing_run_is_not_backend():
    class NotABackend:
        name = "nope"

    assert not isinstance(NotABackend(), AgentBackend)
