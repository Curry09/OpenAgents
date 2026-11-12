"""Behavioral contract tests for the pre-implementation Architect."""

import json

from openagents.agents import architect
from openagents.backends.base import AgentResult
from openagents.runtime import engine


class _Backend:
    name = "scripted"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.task = ""
        self.context = ""

    def run(self, *, work_dir, task, context):
        self.task = task
        self.context = context
        return AgentResult(changed=False, summary=json.dumps(self.payload))


def _verdict(value: str) -> dict:
    return {
        "verdict": value,
        "objective_fidelity": "Targets maintained.",
        "intervention_fit": "Behavior on Runtime",
        "boundary_integrity": "Process border closure",
        "verification_strength": "With positive and negative examples",
        "reason": "ok" if value == "PASS" else "Should be moved to the process boundary",
        "findings": [] if value == "PASS" else ["Prompt does not own subprocesses"],
    }


def test_architect_structured_pass_and_rework() -> None:
    for value in ("PASS", "REWORK"):
        backend = _Backend(_verdict(value))
        result = engine.run_agent(
            architect,
            backend=backend,
            work_dir=".",
            context="candidate spec sentinel",
            issue_number=1,
            design_digest="abc",
        )
        assert result["verdict"] == value
        assert isinstance(result["findings"], list)
        assert backend.context == "candidate spec sentinel"
        assert "candidate spec sentinel" not in backend.task
