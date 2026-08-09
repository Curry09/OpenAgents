"""Spec-0060/T2: runtime.engine.run_agent 单测——填占位符 / 派 backend / 校验末行 JSON。

假 backend 回可控字符串（模拟 agent 输出末行 JSON），聚焦：
- Template 占位符被正确填进 task、work_dir/context 保留字被取出交给 backend；
- 末行 JSON 解析成 dict 且键/类型符合 OUTPUT_SCHEMA；
- 坏 JSON / 缺键 / 类型不符 / 缺 work_dir → 明确 raise AgentOutputError。
"""

from __future__ import annotations

from string import Template

import pytest

from openagents.backends.base import AgentResult
from openagents.runtime import engine
from openagents.runtime.engine import AgentOutputError, NeedsHumanRequest


class _FakeAgent:
    PROMPT = Template("审 PR #$pr_number；issue：$issue_body")
    OUTPUT_SCHEMA = {"verdict": str, "reason": str}


class _CaptureBackend:
    name = "capture"

    def __init__(self, *, summary):
        self._summary = summary
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        return AgentResult(changed=True, summary=self._summary)


def test_fills_placeholders_and_passes_reserved_to_backend():
    backend = _CaptureBackend(summary='{"verdict": "PASS", "reason": "ok"}')
    out = engine.run_agent(
        _FakeAgent,
        backend=backend,
        work_dir="/tmp/wt",
        context="历史评论",
        pr_number=154,
        issue_body="修 bug",
    )
    assert out == {"verdict": "PASS", "reason": "ok"}
    call = backend.calls[0]
    assert call["work_dir"] == "/tmp/wt"
    assert call["context"] == "历史评论"
    # 占位符填进 task；保留字 work_dir/context 不泄漏进 prompt。
    assert "审 PR #154" in call["task"]
    assert "修 bug" in call["task"]


def test_last_line_json_parsed_even_with_trailing_prose():
    backend = _CaptureBackend(summary='这是我的评审。\n{"verdict": "REWORK", "reason": "缺测试"}\n')
    out = engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")
    assert out["verdict"] == "REWORK"


def test_context_defaults_empty_when_omitted():
    backend = _CaptureBackend(summary='{"verdict": "PASS", "reason": "ok"}')
    engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")
    assert backend.calls[0]["context"] == ""


def test_bad_json_raises():
    backend = _CaptureBackend(summary="完全没有 JSON 的一段话")
    with pytest.raises(AgentOutputError):
        engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")


def test_missing_schema_key_raises():
    backend = _CaptureBackend(summary='{"verdict": "PASS"}')  # 缺 reason
    with pytest.raises(AgentOutputError):
        engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")


def test_wrong_type_raises():
    backend = _CaptureBackend(summary='{"verdict": 1, "reason": "x"}')  # verdict 应为 str
    with pytest.raises(AgentOutputError):
        engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")


def test_missing_work_dir_raises():
    backend = _CaptureBackend(summary='{"verdict": "PASS", "reason": "ok"}')
    with pytest.raises(AgentOutputError):
        engine.run_agent(_FakeAgent, backend=backend, pr_number=1, issue_body="x")


def test_int_schema_rejects_bool():
    class _NumAgent:
        PROMPT = Template("$x")
        OUTPUT_SCHEMA = {"n": int}

    backend = _CaptureBackend(summary='{"n": true}')
    with pytest.raises(AgentOutputError):
        engine.run_agent(_NumAgent, backend=backend, work_dir=".", x="1")


def test_needs_human_envelope_precedes_role_schema_validation():
    backend = _CaptureBackend(summary='{"needs_human": true, "reason": "  上游服务持续 503  "}')

    with pytest.raises(NeedsHumanRequest, match="上游服务持续 503") as raised:
        engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")

    assert raised.value.reason == "上游服务持续 503"


@pytest.mark.parametrize(
    "payload",
    [
        '{"needs_human": false, "reason": "x"}',
        '{"needs_human": true}',
        '{"needs_human": true, "reason": "   "}',
        '{"needs_human": true, "reason": 123}',
        '{"needs_human": true, "reason": "x", "subject": 7}',
    ],
)
def test_invalid_needs_human_envelope_is_protocol_error(payload):
    backend = _CaptureBackend(summary=payload)

    with pytest.raises(AgentOutputError, match="needs-human"):
        engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")
