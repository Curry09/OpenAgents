"""Spec-0039/T2: executor（独立运行时验证 agent）单元测试。

打桩 AgentBackend（不触达真实 coding agent），覆盖：
- cli 形态 runbook → 派 backend 真跑、把证据写进 evidence_dir、outcome 随 agent 结论映射 passed/failed；
- backend 抛错 → outcome=failed 且 run_executor 不抛出；
- ui 形态 → skipped 且 notes 标注 Phase 2、不派 agent；
- runbook 缺失 / 形态无法识别 → failed；
- outcome / form 解析鲁棒；证据文件恒被固化。
"""

from pathlib import Path

from openagents.backends.base import AgentResult
from openagents.executor import (
    OUTCOME_FAILED,
    OUTCOME_PASSED,
    OUTCOME_SKIPPED,
    RESULT_FILENAME,
    ExecutorResult,
    _parse_form,
    _parse_outcome,
    run_executor,
)


class _ScriptedBackend:
    """伪后端：返回预设 summary，记录每次 run 的入参（供断言任务模板与是否被调用）。"""

    name = "scripted"

    def __init__(self, *, summary):
        self._summary = summary
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        return AgentResult(changed=False, summary=self._summary)


class _RaisingBackend:
    """伪后端：run 抛错，验证 run_executor 契约上绝不抛错（映射成 failed）。"""

    name = "raising"

    def run(self, *, work_dir, task, context):
        raise RuntimeError("backend 炸了")


def _write_runbook(tmp_path: Path, *, body: str) -> Path:
    path = tmp_path / "runbook.md"
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# cli 形态：派 agent 真跑 + 证据固化 + outcome 映射
# --------------------------------------------------------------------------- #


def test_cli_form_passed_writes_evidence(tmp_path):
    runbook = _write_runbook(tmp_path, body="执行形态：cli\n步骤：跑 init，看退出码。")
    evidence = tmp_path / "e2e-results" / "12"
    backend = _ScriptedBackend(summary="跑了 init，退出码 0，符合预期。\nOUTCOME: PASSED")
    result = run_executor(
        backend=backend,
        work_dir=tmp_path,
        runbook_path=runbook,
        evidence_dir=evidence,
        pr_number=12,
    )
    assert isinstance(result, ExecutorResult)
    assert result.outcome == OUTCOME_PASSED
    assert result.form == "cli"
    # 派了 backend 真跑，任务模板含形态与 runbook 路径。
    assert len(backend.calls) == 1
    assert "cli" in backend.calls[0]["task"]
    assert str(runbook) in backend.calls[0]["task"]
    # 证据固化到 evidence_dir/result.md。
    evidence_file = evidence / RESULT_FILENAME
    assert evidence_file.is_file()
    assert "passed" in evidence_file.read_text(encoding="utf-8")


def test_cli_form_failed_outcome(tmp_path):
    runbook = _write_runbook(tmp_path, body="form: cli\n")
    evidence = tmp_path / "ev"
    backend = _ScriptedBackend(summary="init 静默成功了，验收行为未达成。\nOUTCOME: FAILED")
    result = run_executor(
        backend=backend, work_dir=tmp_path, runbook_path=runbook, evidence_dir=evidence, pr_number=1
    )
    assert result.outcome == OUTCOME_FAILED
    assert (evidence / RESULT_FILENAME).is_file()


def test_backend_raises_maps_to_failed_without_raising(tmp_path):
    runbook = _write_runbook(tmp_path, body="执行形态：backend\n")
    evidence = tmp_path / "ev"
    result = run_executor(
        backend=_RaisingBackend(),
        work_dir=tmp_path,
        runbook_path=runbook,
        evidence_dir=evidence,
        pr_number=3,
    )
    assert result.outcome == OUTCOME_FAILED
    assert result.form == "backend"
    assert "异常" in result.notes
    # 即便 backend 炸了，证据仍固化（failed 也留档）。
    assert (evidence / RESULT_FILENAME).is_file()


# --------------------------------------------------------------------------- #
# ui 形态：skipped + Phase 2 标注，不派 agent
# --------------------------------------------------------------------------- #


def test_ui_form_skipped_notes_phase2(tmp_path):
    runbook = _write_runbook(tmp_path, body="执行形态：ui\n导航到首页截图。")
    evidence = tmp_path / "ev"
    backend = _ScriptedBackend(summary="不该被调用")
    result = run_executor(
        backend=backend, work_dir=tmp_path, runbook_path=runbook, evidence_dir=evidence, pr_number=9
    )
    assert result.outcome == OUTCOME_SKIPPED
    assert result.form == "ui"
    assert "Phase 2" in result.notes
    # ui 形态不派 agent（Phase 1 留白）。
    assert backend.calls == []


# --------------------------------------------------------------------------- #
# runbook 缺失 / 形态无法识别 → failed
# --------------------------------------------------------------------------- #


def test_missing_runbook_is_failed(tmp_path):
    evidence = tmp_path / "ev"
    backend = _ScriptedBackend(summary="x")
    result = run_executor(
        backend=backend,
        work_dir=tmp_path,
        runbook_path=tmp_path / "nope.md",
        evidence_dir=evidence,
        pr_number=1,
    )
    assert result.outcome == OUTCOME_FAILED
    assert result.form == ""
    assert backend.calls == []
    assert (evidence / RESULT_FILENAME).is_file()


def test_unrecognized_form_is_failed(tmp_path):
    runbook = _write_runbook(tmp_path, body="这份说明书没有声明任何形态。")
    evidence = tmp_path / "ev"
    backend = _ScriptedBackend(summary="x")
    result = run_executor(
        backend=backend, work_dir=tmp_path, runbook_path=runbook, evidence_dir=evidence, pr_number=1
    )
    assert result.outcome == OUTCOME_FAILED
    assert result.form == ""
    assert backend.calls == []


# --------------------------------------------------------------------------- #
# 解析鲁棒性
# --------------------------------------------------------------------------- #


def test_parse_form_variants():
    assert _parse_form(runbook="执行形态：cli") == "cli"
    assert _parse_form(runbook="form: API") == "api"
    assert _parse_form(runbook="声明形态 `backend`") == "backend"
    assert _parse_form(runbook="无形态声明") == ""


def test_parse_outcome_variants():
    assert _parse_outcome(summary="...\nOUTCOME: PASSED") == OUTCOME_PASSED
    assert _parse_outcome(summary="OUTCOME: failed") == OUTCOME_FAILED
    assert _parse_outcome(summary="结论 PASSED") == OUTCOME_PASSED
    # 无法解析 → 疑罪从严判 failed。
    assert _parse_outcome(summary="没有明确结论") == OUTCOME_FAILED
