"""Spec-0055/T3: executor（单一自主运行时验证 agent）单元测试。

打桩 AgentBackend（不触达真实 coding agent），覆盖：
- run_executor 把 spec 的 prose 测法 method + intent 喂进任务模板、派 backend 真跑、把证据写进 evidence_dir；
- outcome 随 agent 自报的 OUTCOME 映射 passed/failed（无法解析 → failed 疑罪从严）；
- backend 抛错 → outcome=failed 且 run_executor 不抛出；证据文件恒被固化；
- 无 form 形参 / 无 runbook 文件（method 直接入参）；render_result 去 form。
"""

from openagents.backends.base import AgentResult
from openagents.executor import (
    OUTCOME_FAILED,
    OUTCOME_PASSED,
    RESULT_FILENAME,
    ExecutorResult,
    _parse_outcome,
    render_result,
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


# --------------------------------------------------------------------------- #
# 派 agent 真跑 + 证据固化 + outcome 映射（method 直接入参，无 form / 无 runbook 文件）
# --------------------------------------------------------------------------- #


def test_passed_feeds_method_and_writes_evidence(tmp_path):
    evidence = tmp_path / "e2e-results" / "12"
    backend = _ScriptedBackend(summary="真开浏览器选了 done，列表只剩 done。\nOUTCOME: PASSED")
    result = run_executor(
        backend=backend,
        work_dir=tmp_path,
        method="1. 起看板；2. 选 done → 截图确认列表只剩 done。",
        evidence_dir=evidence,
        pr_number=12,
        ui_intent="看板能按状态筛选。",
    )
    assert isinstance(result, ExecutorResult)
    assert result.outcome == OUTCOME_PASSED
    # 派了 backend 真跑；任务模板含 method prose 与 intent 与 evidence_dir（无 form/runbook 概念）。
    assert len(backend.calls) == 1
    task = backend.calls[0]["task"]
    assert "选 done → 截图确认列表只剩 done" in task
    assert "看板能按状态筛选。" in task
    assert str(evidence) in task
    # 证据固化到 evidence_dir/result.md。
    evidence_file = evidence / RESULT_FILENAME
    assert evidence_file.is_file()
    assert "passed" in evidence_file.read_text(encoding="utf-8")


def test_failed_outcome_still_writes_evidence(tmp_path):
    evidence = tmp_path / "ev"
    backend = _ScriptedBackend(summary="选 done 后列表没变，筛选未生效。\nOUTCOME: FAILED")
    result = run_executor(
        backend=backend,
        work_dir=tmp_path,
        method="选 done 看列表。",
        evidence_dir=evidence,
        pr_number=1,
        ui_intent="筛选生效。",
    )
    assert result.outcome == OUTCOME_FAILED
    assert (evidence / RESULT_FILENAME).is_file()


def test_backend_raises_maps_to_failed_without_raising(tmp_path):
    evidence = tmp_path / "ev"
    result = run_executor(
        backend=_RaisingBackend(),
        work_dir=tmp_path,
        method="跑一下。",
        evidence_dir=evidence,
        pr_number=3,
        ui_intent="x",
    )
    assert result.outcome == OUTCOME_FAILED
    assert "异常" in result.notes
    # 即便 backend 炸了，证据仍固化（failed 也留档）。
    assert (evidence / RESULT_FILENAME).is_file()


def test_unparseable_outcome_is_failed(tmp_path):
    # agent 没给明确 OUTCOME → 疑罪从严判 failed（没确认跑通就不算通过）。
    evidence = tmp_path / "ev"
    backend = _ScriptedBackend(summary="我随便跑了跑，没说结论。")
    result = run_executor(
        backend=backend,
        work_dir=tmp_path,
        method="m",
        evidence_dir=evidence,
        pr_number=2,
        ui_intent="i",
    )
    assert result.outcome == OUTCOME_FAILED


def test_evidence_write_failure_does_not_raise(tmp_path):
    """契约：evidence 写失败也绝不抛错（_write_evidence 在 try/except 之外被调用）。

    evidence_dir 的父路径是一个文件 → mkdir 抛 OSError；run_executor 必须吞掉、正常返回 result。
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("我是文件，占了 evidence_dir 的父路径", encoding="utf-8")
    evidence = blocker / "ev"  # 父路径是文件 → mkdir 必抛 NotADirectoryError(OSError)
    backend = _ScriptedBackend(summary="跑通了。\nOUTCOME: PASSED")
    result = run_executor(
        backend=backend,
        work_dir=tmp_path,
        method="m",
        evidence_dir=evidence,
        pr_number=7,
        ui_intent="i",
    )
    assert result.outcome == OUTCOME_PASSED  # 写失败不改 outcome
    assert not evidence.exists()  # 确实没写成


# --------------------------------------------------------------------------- #
# 解析鲁棒性
# --------------------------------------------------------------------------- #


def test_parse_outcome_variants():
    assert _parse_outcome(summary="...\nOUTCOME: PASSED") == OUTCOME_PASSED
    assert _parse_outcome(summary="OUTCOME: failed") == OUTCOME_FAILED
    assert _parse_outcome(summary="结论 PASSED") == OUTCOME_PASSED
    # 无法解析 → 疑罪从严判 failed。
    assert _parse_outcome(summary="没有明确结论") == OUTCOME_FAILED


# --------------------------------------------------------------------------- #
# Spec-0051/T1（Spec-0055 去 form）: render_result 纯函数
# --------------------------------------------------------------------------- #


def test_render_result_passed_has_header_and_outcome():
    body = render_result(result=ExecutorResult(outcome=OUTCOME_PASSED, notes="跑通了"))
    assert body.startswith("## 证据执行")
    assert "✅ 通过" in body
    # notes 非空 → 附代码块体现。
    assert "```" in body and "跑通了" in body


def test_render_result_failed_no_notes_no_codeblock():
    failed = render_result(result=ExecutorResult(outcome=OUTCOME_FAILED, notes=""))
    assert failed.startswith("## 证据执行")
    assert "❌ 未通过" in failed
    # notes 为空 → 不附代码块。
    assert "```" not in failed


def test_render_result_is_deterministic_pure():
    result = ExecutorResult(outcome=OUTCOME_PASSED, notes="n")
    # 纯函数：同输入恒同输出、无副作用。
    assert render_result(result=result) == render_result(result=result)
