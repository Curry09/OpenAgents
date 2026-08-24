"""Behavioral contract tests for the pre-implementation Architect."""

import json

from openagents.agents import architect
from openagents.backends.base import AgentResult
from openagents.runtime import engine


class _Backend:
    name = "scripted"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=False, summary=json.dumps(self.payload))


def _verdict(value: str) -> dict:
    return {
        "verdict": value,
        "objective_fidelity": "目标保持",
        "intervention_fit": "运行时拥有行为",
        "boundary_integrity": "进程边界闭合",
        "verification_strength": "含正反例",
        "reason": "ok" if value == "PASS" else "应改到进程边界",
        "findings": [] if value == "PASS" else ["prompt 不拥有子进程"],
    }


def test_architect_structured_pass_and_rework() -> None:
    for value in ("PASS", "REWORK"):
        result = engine.run_agent(
            architect,
            backend=_Backend(_verdict(value)),
            work_dir=".",
            context="",
            issue_number=1,
            design_digest="abc",
            spec_text="candidate spec",
        )
        assert result["verdict"] == value
        assert isinstance(result["findings"], list)
