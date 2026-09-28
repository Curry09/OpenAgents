import json

import pytest

from openagents.backends.base import AgentResult
from openagents.recipes import stages
from openagents.runtime.engine import AgentOutputError


class RecordedReviewer:
    name = "recorded-reviewer"

    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        output = json.dumps({"verdict": self.verdict, "reason": "All acceptance checks passed."})
        return AgentResult(changed=False, summary=output, raw_output=output)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("pass", "PASS"),
        ("PASS", "PASS"),
        (" Pass ", "PASS"),
        ("rework", "REWORK"),
        ("REWORK", "REWORK"),
    ],
)
def test_recorded_verdict_preserves_its_meaning(tmp_path, raw, expected):
    backend = RecordedReviewer(raw)
    result = stages.review(
        backend=backend,
        work_dir=tmp_path,
        pr_number=262,
        issue_body="Review this candidate.",
        context_text="",
    )
    assert result["verdict"] == expected
    assert backend.calls == 1


@pytest.mark.parametrize("raw", ["APPROVED", "", "maybe", "FAIL"])
def test_unknown_verdict_is_protocol_failure_not_rework(tmp_path, raw):
    with pytest.raises(AgentOutputError):
        stages.review(
            backend=RecordedReviewer(raw),
            work_dir=tmp_path,
            pr_number=262,
            issue_body="Review this candidate.",
            context_text="",
        )
