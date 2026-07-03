"""Spec-0040/T3: 证据闸（evidence_gate）单元测试。

打桩 AgentBackend（不触达真实 coding agent），覆盖：
- evidence_dir_for 路径约定（pr=12 → docs/e2e-results/12）；
- 证据显示意图达成 → passed=True、feedback 空；
- 证据与意图不符 / 避重就轻 → passed=False、feedback 非空；
- 证据缺失（无 result.md）→ passed=False 且不派 agent（无证据即未达成）；
- 裁决无法解析 → 疑罪从严 FAIL；backend 抛错 → FAIL 不抛出。
"""

from pathlib import Path

from openagents.backends.base import AgentResult
from openagents.evidence_gate import (
    RESULT_FILENAME,
    EvidenceDecision,
    evidence_dir_for,
    review_evidence,
)


class _ScriptedBackend:
    """伪后端：返回预设 summary，记录 run 入参（供断言任务模板与是否被调用）。"""

    name = "scripted"

    def __init__(self, *, summary):
        self._summary = summary
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        return AgentResult(changed=False, summary=self._summary)


class _RaisingBackend:
    name = "raising"

    def run(self, *, work_dir, task, context):
        raise RuntimeError("boom")


def _write_evidence(evidence_dir: Path, *, body: str) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / RESULT_FILENAME).write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# evidence_dir_for 路径约定
# --------------------------------------------------------------------------- #


def test_evidence_dir_for_path_convention():
    assert evidence_dir_for(pr_number=12) == Path("docs/e2e-results/12")


# --------------------------------------------------------------------------- #
# review_evidence 裁决
# --------------------------------------------------------------------------- #


def test_evidence_meets_intent_passes(tmp_path):
    evidence = tmp_path / "ev"
    _write_evidence(evidence, body="init 在无 origin 时非零退出并提示，符合意图。")
    backend = _ScriptedBackend(summary="VERDICT: PASS\n证据逐条对上意图。")
    decision = review_evidence(
        backend=backend,
        work_dir=tmp_path,
        intent="init 无 origin 必须显式失败",
        evidence_dir=evidence,
        pr_number=7,
    )
    assert isinstance(decision, EvidenceDecision)
    assert decision.passed is True
    assert decision.feedback == ""
    # 派了证据闸 agent，任务模板含意图。
    assert len(backend.calls) == 1
    assert "init 无 origin 必须显式失败" in backend.calls[0]["task"]


def test_evidence_mismatch_fails_with_feedback(tmp_path):
    evidence = tmp_path / "ev"
    _write_evidence(evidence, body="只跑了 --help，没验无 origin 的报错。")
    backend = _ScriptedBackend(
        summary="VERDICT: FAIL\n验收行为①未达成：证据避重就轻，只跑了 --help。"
    )
    decision = review_evidence(
        backend=backend,
        work_dir=tmp_path,
        intent="init 无 origin 必须显式失败",
        evidence_dir=evidence,
        pr_number=7,
    )
    assert decision.passed is False
    assert "未达成" in decision.feedback


def test_missing_evidence_fails_without_backend(tmp_path):
    evidence = tmp_path / "ev"  # 不写 result.md
    backend = _ScriptedBackend(summary="不该被调用")
    decision = review_evidence(
        backend=backend,
        work_dir=tmp_path,
        intent="任意意图",
        evidence_dir=evidence,
        pr_number=1,
    )
    assert decision.passed is False
    assert decision.feedback
    # 证据缺失是硬 FAIL，不派 agent。
    assert backend.calls == []


def test_unparseable_verdict_is_fail(tmp_path):
    evidence = tmp_path / "ev"
    _write_evidence(evidence, body="some evidence")
    backend = _ScriptedBackend(summary="我觉得大概达成了吧，没有明确裁决")
    decision = review_evidence(
        backend=backend, work_dir=tmp_path, intent="x", evidence_dir=evidence, pr_number=1
    )
    assert decision.passed is False
    assert decision.feedback


def test_backend_raises_maps_to_fail(tmp_path):
    evidence = tmp_path / "ev"
    _write_evidence(evidence, body="some evidence")
    decision = review_evidence(
        backend=_RaisingBackend(), work_dir=tmp_path, intent="x", evidence_dir=evidence, pr_number=1
    )
    assert decision.passed is False
    assert "异常" in decision.feedback
