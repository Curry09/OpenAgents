"""Spec-0060/T2: runtime.engine.run_agent 单测——填占位符 / 派 backend / 校验末行 JSON。

假 backend 回可控字符串（模拟 agent 输出末行 JSON），聚焦：
- Template 占位符被正确填进 task、work_dir/context 保留字被取出交给 backend；
- 末行 JSON 解析成 dict 且键/类型符合 OUTPUT_SCHEMA；
- 坏 JSON / 缺键 / 类型不符 / 缺 work_dir → 明确 raise AgentOutputError。
"""

from __future__ import annotations

from string import Template

import pytest

from openagents.backends.base import AgentResult, TokenUsage
from openagents.runtime import engine
from openagents.runtime.engine import AgentOutputError


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


class _SplitOutputBackend:
    name = "split-output"

    def __init__(self, *, summary, raw_output):
        self.summary = summary
        self.raw_output = raw_output

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=False, summary=self.summary, raw_output=self.raw_output)


class _ToolEventBackend:
    name = "tool-events"

    def run(self, *, work_dir, task, context):
        return AgentResult(
            changed=True,
            summary='{"verdict":"PASS","reason":"ok"}',
            tool_events=("Read", "Edit"),
        )


class _LookupExceptionBackend:
    name = "lookup-exception"

    def run(self, *, work_dir, task, context):
        return AgentResult(
            changed=True,
            summary=(
                '{"verdict":"PASS","reason":"ok","lookup_exception_reason":"现场版本与证据不一致"}'
            ),
            tool_events=("Read",) * 7 + ("Edit",),
        )


class _TokenUsageBackend:
    name = "usage-backend"

    def run(self, *, work_dir, task, context):
        return AgentResult(
            changed=False,
            summary='{"verdict":"PASS","reason":"ok"}',
            usage=TokenUsage(
                input_tokens=11,
                output_tokens=2,
                total_tokens=13,
                total_source="reported",
                model="m",
            ),
        )


class _FailingBackend:
    name = "failing"

    def run(self, *, work_dir, task, context):
        raise RuntimeError("backend broke")


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


def test_parses_full_protocol_output_when_display_summary_was_truncated():
    raw = "analysis " * 400 + '\n{"verdict":"REWORK","reason":"架构边界未闭合"}'
    backend = _SplitOutputBackend(summary=raw[:2000], raw_output=raw)

    out = engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")

    assert out == {"verdict": "REWORK", "reason": "架构边界未闭合"}


def test_context_defaults_empty_when_omitted():
    backend = _CaptureBackend(summary='{"verdict": "PASS", "reason": "ok"}')
    engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")
    assert backend.calls[0]["context"] == ""


def test_records_structured_tool_usage_for_backend_events(tmp_path):
    out = engine.run_agent(
        _FakeAgent,
        backend=_ToolEventBackend(),
        work_dir=tmp_path,
        pr_number=1,
        issue_body="x",
    )
    assert out["verdict"] == "PASS"
    metric = tmp_path / ".openagents" / "tool-usage.jsonl"
    assert '"lookup_before_first_edit": 1' in metric.read_text(encoding="utf-8")


def test_records_structured_lookup_exception_reason(tmp_path):
    engine.run_agent(
        _FakeAgent,
        backend=_LookupExceptionBackend(),
        work_dir=tmp_path,
        pr_number=1,
        issue_body="x",
    )
    metric = tmp_path / ".openagents" / "tool-usage.jsonl"
    assert '"lookup_exception_reason": "现场版本与证据不一致"' in metric.read_text(encoding="utf-8")


def _token_rows(tmp_path):
    path = tmp_path / ".openagents" / "token-usage.jsonl"
    return [__import__("json").loads(line) for line in path.read_text().splitlines()]


def test_records_one_reported_token_row_per_successful_call(tmp_path):
    engine.run_agent(
        _FakeAgent,
        backend=_TokenUsageBackend(),
        work_dir=tmp_path,
        pr_number=1,
        issue_body="x",
    )
    rows = _token_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["total_tokens"] == 13
    assert rows[0]["usage_source"] == "reported"


def test_records_unavailable_without_changing_backend_exception(tmp_path):
    with pytest.raises(RuntimeError, match="backend broke"):
        engine.run_agent(
            _FakeAgent,
            backend=_FailingBackend(),
            work_dir=tmp_path,
            pr_number=1,
            issue_body="x",
        )
    rows = _token_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "backend_error"
    assert rows[0]["usage_source"] == "unavailable"


def test_protocol_failures_have_one_token_row_each(tmp_path):
    with pytest.raises(AgentOutputError):
        engine.run_agent(
            _FakeAgent,
            backend=_CaptureBackend(summary="bad-json"),
            work_dir=tmp_path,
            pr_number=1,
            issue_body="x",
        )
    with pytest.raises(AgentOutputError):
        engine.run_agent(
            _FakeAgent,
            backend=_CaptureBackend(summary='{"needs_human":true,"reason":"external decision"}'),
            work_dir=tmp_path,
            pr_number=2,
            issue_body="x",
        )
    rows = _token_rows(tmp_path)
    assert [row["status"] for row in rows] == ["protocol_error", "protocol_error"]


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


def test_retired_control_envelope_fails_normal_role_schema_validation():
    backend = _CaptureBackend(summary='{"needs_human": true, "reason": "  上游服务持续 503  "}')

    with pytest.raises(AgentOutputError, match="schema 键 'verdict'"):
        engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")


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
def test_any_retired_control_envelope_is_protocol_error(payload):
    backend = _CaptureBackend(summary=payload)

    with pytest.raises(AgentOutputError, match="schema 键 'verdict'"):
        engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")
