"""Spec-0060/T2: runtime.engine.run_agent 单测——填占位符 / 派 backend / 校验末行 JSON。

假 backend 回可控字符串（模拟 agent 输出末行 JSON），聚焦：
- Template 占位符被正确填进 task、work_dir/context 保留字被取出交给 backend；
- 末行 JSON 解析成 dict 且键/类型符合 OUTPUT_SCHEMA；
- 坏 JSON / 缺键 / 类型不符 / 缺 work_dir → 明确 raise AgentOutputError。
"""

from __future__ import annotations

import json
from string import Template

import pytest

from openagents.agents import spec_writer
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


class _SequenceBackend:
    name = "sequence"

    def __init__(self, *outputs):
        self._outputs = iter(outputs)
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        return AgentResult(changed=False, summary=next(self._outputs))


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


def test_multiline_fenced_json_selects_outer_schema_object_not_nested_item():
    backend = _CaptureBackend(
        summary="""```json
{
  "verdict": "PASS",
  "reason": "ok",
  "items": [
    {"reason": "nested"}
  ]
}
```"""
    )

    out = engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")

    assert out["verdict"] == "PASS"
    assert len(backend.calls) == 1


def test_protocol_error_gets_one_serialization_only_retry(tmp_path):
    backend = _SequenceBackend(
        "Result: verdict PASS because checks passed.",
        '{"verdict":"PASS","reason":"checks passed"}',
    )

    out = engine.run_agent(
        _FakeAgent,
        backend=backend,
        work_dir=tmp_path,
        pr_number=1,
        issue_body="x",
    )

    assert out == {"verdict": "PASS", "reason": "checks passed"}
    assert len(backend.calls) == 2
    assert backend.calls[1]["work_dir"] != tmp_path
    assert "机器协议格式修复器" in backend.calls[1]["task"]
    assert "不得新增事实或证据" in backend.calls[1]["task"]


def test_explicit_nested_schema_repairs_spec_coverage_field_names(tmp_path):
    base = {
        "status": "PARTIAL",
        "head_sha": "abc",
        "summary": "summary",
        "blocker": "behavioral evidence pending",
        "candidate_assessments": [
            {
                "candidate": "A",
                "ownership": "runtime",
                "delivery": "path",
                "control_effect": "effect",
                "evidence": "source",
                "assumptions": "none",
                "failure_modes": "none",
                "verdict": "selected",
            }
        ],
        "selected_intervention": {"mechanism": "m", "files": ["a.py"], "dependencies": []},
        "evidence_pack": [],
        "falsifiers": [],
    }
    malformed = base | {"objective_coverage": [{"scope": "FULL", "evidence": "STRUCTURAL"}]}
    repaired = base | {
        "objective_coverage": [{"scope_coverage": "FULL", "evidence_level": "STRUCTURAL"}]
    }
    backend = _SequenceBackend(json.dumps(malformed), json.dumps(repaired))

    out = engine.run_agent(
        spec_writer,
        backend=backend,
        work_dir=tmp_path,
        context="issue body",
        issue_number=2,
        branch="openagents/v02-issue-2",
        mode="AUTHOR",
    )

    assert out["objective_coverage"] == repaired["objective_coverage"]
    assert len(backend.calls) == 2
    assert '"scope_coverage"' in backend.calls[0]["task"]


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


def test_records_redacted_delivery_invocation_for_success(tmp_path, monkeypatch):
    role_runs = tmp_path / "delivery"
    monkeypatch.setenv("ROLE_RUNS_DIR", str(role_runs))
    monkeypatch.setenv("AUTO_DESIGNER_RUN_ID", "run-7")
    monkeypatch.setenv("GITEA_TOKEN", "secret-token")

    engine.run_agent(
        _FakeAgent,
        backend=_CaptureBackend(summary='{"verdict":"PASS","reason":"secret-token handled"}'),
        work_dir=tmp_path,
        context="token=secret-token",
        pr_number=7,
        issue_body="x",
    )

    files = list(role_runs.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["side"] == "delivery"
    assert payload["subject"] == {"kind": "pull_request", "id": "7"}
    assert payload["output"]["status"] == "success"
    assert payload["replayable"] is False
    assert "secret-token" not in json.dumps(payload)
    assert (role_runs / "index.jsonl").is_file()


def test_records_delivery_invocation_for_backend_failure(tmp_path, monkeypatch):
    role_runs = tmp_path / "delivery"
    monkeypatch.setenv("ROLE_RUNS_DIR", str(role_runs))

    with pytest.raises(RuntimeError, match="backend broke"):
        engine.run_agent(
            _FakeAgent,
            backend=_FailingBackend(),
            work_dir=tmp_path,
            pr_number=1,
            issue_body="x",
        )

    payload = json.loads(next(role_runs.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["output"]["status"] == "backend_error"
    assert "backend broke" in payload["output"]["error"]


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
    assert [row["status"] for row in rows] == [
        "protocol_error",
        "protocol_error",
        "protocol_error",
        "protocol_error",
    ]
    assert [row["role"] for row in rows] == [
        "_FakeAgent_protocol_repair",
        "_FakeAgent",
        "_FakeAgent_protocol_repair",
        "_FakeAgent",
    ]


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


def test_role_invocation_is_noop_without_role_runs_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("ROLE_RUNS_DIR", raising=False)
    backend = _CaptureBackend(summary='{"verdict": "PASS", "reason": "ok"}')
    engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")
    assert list(tmp_path.iterdir()) == []


def test_role_invocation_writes_v1_json_on_success(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("AUTO_DESIGNER_RUN_ID", "run-z")
    monkeypatch.setenv("AUTO_DESIGNER_ROUND", "3")
    backend = _CaptureBackend(summary='{"verdict": "PASS", "reason": "ok"}')
    engine.run_agent(
        _FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x", context="ctx"
    )
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["side"] == "delivery"
    assert data["output"]["status"] == "success"
    assert data["output"]["structured"]["verdict"] == "PASS"
    assert data["input"]["prompt"]
    assert "protocol_output" not in data


def test_role_invocation_records_protocol_and_backend_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path))
    with pytest.raises(AgentOutputError):
        engine.run_agent(
            _FakeAgent,
            backend=_CaptureBackend(summary="not-json"),
            work_dir=".",
            pr_number=1,
            issue_body="x",
        )
    proto = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert proto["output"]["status"] == "protocol_error"

    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path / "backend"))
    with pytest.raises(RuntimeError):
        engine.run_agent(
            _FakeAgent, backend=_FailingBackend(), work_dir=".", pr_number=1, issue_body="x"
        )
    back = json.loads(next((tmp_path / "backend").glob("*.json")).read_text(encoding="utf-8"))
    assert back["output"]["status"] == "backend_error"


def test_role_invocation_fail_open_when_dir_unwritable(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked.json"
    blocked.write_text("not-a-dir", encoding="utf-8")
    monkeypatch.setenv("ROLE_RUNS_DIR", str(blocked))
    backend = _CaptureBackend(summary='{"verdict": "PASS", "reason": "ok"}')
    out = engine.run_agent(_FakeAgent, backend=backend, work_dir=".", pr_number=1, issue_body="x")
    assert out["verdict"] == "PASS"


def test_implementer_records_are_not_replayable(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path))

    class _Implementer:
        PROMPT = Template("do $x")
        OUTPUT_SCHEMA = {"verdict": str, "reason": str}

    _Implementer.__name__ = "openagents.agents.implementer"
    backend = _CaptureBackend(summary='{"verdict": "PASS", "reason": "ok"}')
    engine.run_agent(_Implementer, backend=backend, work_dir=".", x="1")
    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert data["role"] == "implementer"
    assert data["replayable"] is False


def test_required_contract_error_never_reaches_backend_or_downgrades(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from openagents.observations import evidence
    from openagents.observations.execution_contracts import ExecutionContractUnavailable
    from openagents.runtime.context import execution_dispatch
    from openagents.runtime.state import RuntimeState

    def missing(**kwargs):
        assert kwargs["execution_required"] is True
        raise ExecutionContractUnavailable("required execution evidence handle missing")

    monkeypatch.setattr(evidence, "prepare", missing)
    module = SimpleNamespace(
        __name__="openagents.agents.architect",
        PROMPT=Template("review"),
        OUTPUT_SCHEMA={"verdict": str},
    )
    backend = _CaptureBackend(summary='{"verdict":"PASS"}')
    state = RuntimeState(path=tmp_path / "state.json")
    with execution_dispatch(state=state, required=True):
        with pytest.raises(ExecutionContractUnavailable):
            engine.run_agent(module, backend=backend, work_dir=tmp_path, issue_number=7)
    assert backend.calls == []
    # Removing the project toggle during recovery does not erase the persisted requirement.
    with execution_dispatch(state=RuntimeState(path=tmp_path / "state.json"), required=False):
        with pytest.raises(ExecutionContractUnavailable):
            engine.run_agent(module, backend=backend, work_dir=tmp_path, issue_number=7)
    assert backend.calls == []
