"""Spec-0081: every production role carries dynamic material through context exactly once."""

from __future__ import annotations

import json

import pytest

from openagents.agents import (
    architect,
    curator,
    deliver,
    drafter,
    implementer,
    merger,
    replier,
    reviewer,
    tester,
    triager,
)
from openagents.backends.base import AgentResult
from openagents.backends.claude_code import _build_prompt
from openagents.runtime import engine

_SENTINEL = "SPEC0081_DYNAMIC_SENTINEL_" + "z" * 96
_ROLES = (
    triager,
    drafter,
    architect,
    implementer,
    replier,
    tester,
    reviewer,
    merger,
    curator,
    deliver,
)


class _RecordingBackend:
    name = "recording"

    def __init__(self, *, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def run(self, *, work_dir, task, context):
        self.calls.append((task, context))
        return AgentResult(changed=False, summary=json.dumps(self.payload))


def _output(module) -> dict:
    values = {bool: True, str: "ok", list: []}
    output = {key: values[kind] for key, kind in module.OUTPUT_SCHEMA.items()}
    # Reviewer has a stricter machine contract than the legacy type-only map.
    if module is reviewer:
        output["verdict"] = "PASS"
    return output


def _placeholders(module, tmp_path) -> dict:
    values = {name: "route-scalar" for name in module.PROMPT.get_identifiers()}
    values.update(
        work_dir=tmp_path,
        context=f"dynamic material\n\n{_SENTINEL}\n\nend material",
    )
    return values


@pytest.mark.parametrize("module", _ROLES, ids=lambda module: module.__name__.rsplit(".", 1)[-1])
def test_all_production_roles_have_one_dynamic_payload_copy(module, tmp_path):
    backend = _RecordingBackend(payload=_output(module))

    engine.run_agent(module, backend=backend, **_placeholders(module, tmp_path))

    assert len(backend.calls) == 1
    task, context = backend.calls[0]
    assert _SENTINEL not in task
    assert context.count(_SENTINEL) == 1
    assert _build_prompt(task=task, context=context).count(_SENTINEL) == 1
