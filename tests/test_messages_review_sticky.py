"""Spec-0053/T3：_process_coding 3c 代码闸 sticky 短路的单元测试。

github / identity / orchestrator 全部 hermetic 注入（monkeypatch / fake），不触网、不调真实
LLM/gh。核心断言以「reviewer 调用次数」这一可观测成果验证短路语义，覆盖：
- 指纹与上次 PASS 相同 → review_code 不被调用、仍照进证据闸/merge（sticky 命中）；
- 指纹不同 → review_code 被调一次、PASS 后落盘新指纹（代码变 → 重审）；
- 指纹为空（gh 抖动/失败）→ 照常评审、不落盘空指纹（fail-open）。
"""

import pytest

from openagents import messages as messages_module
from openagents.github import CheckStatus, Mergeability
from openagents.hold import NONE as NO_HOLD
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import STATUS_DONE, STATUS_PR_OPEN, RunRecord

_AGENT_ID = "agent-self"


class _FakeOrchestrator:
    """记录 review_code 调用次数；review_code 恒返回可配置裁决。"""

    def __init__(self, *, decision):
        self._decision = decision
        self.review_code_calls = 0

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return self._decision

    def iterate(self, *, pr_number, reason, detail):
        raise AssertionError("PASS 路径不应调 iterate")


class _FakeState:
    """内存版 State：记录 status/fingerprint 轨迹并应用到记录。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []
        self.fingerprint_sets = []

    def all_runs(self):
        return list(self._runs)

    def _find(self, issue_number):
        for record in self._runs:
            if record.issue_number == issue_number:
                return record
        return None

    def update_status(self, *, issue_number, status):
        self.status_updates.append({"issue_number": issue_number, "status": status})
        record = self._find(issue_number)
        if record is not None:
            record.status = status

    def set_code_fingerprint(self, *, issue_number, fingerprint):
        self.fingerprint_sets.append({"issue_number": issue_number, "fingerprint": fingerprint})
        record = self._find(issue_number)
        if record is not None:
            record.code_passed_fingerprint = fingerprint

    def increment_rounds(self, *, issue_number):
        raise AssertionError("PASS 路径不应调 increment_rounds")


def _run(*, issue_number=3, pr_number=5, code_passed_fingerprint=""):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url=f"u/pull/{pr_number}",
        status=STATUS_PR_OPEN,
        summary="",
        code_passed_fingerprint=code_passed_fingerprint,
    )


def _messages(*, runs, passed=True):
    decision = ReviewDecision(passed=passed, feedback="", verdicts=("PASS",))
    orch = _FakeOrchestrator(decision=decision)
    state = _FakeState(runs=runs)
    msgs = Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID)
    return msgs, orch, state


def _patch_coding_reads(monkeypatch, *, fingerprint):
    """让 poll 走完 _process_coding 到 3c：未合并/未关、MERGEABLE/CLEAN、CI 绿；

    code_fingerprint 恒返回 fingerprint。捕获 merge_pr / close_issue，返回捕获字典。
    """
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        messages_module.github,
        "mergeability",
        lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN"),
    )
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: CheckStatus(state="pass", failed_logs=[]),
    )
    monkeypatch.setattr(
        messages_module.github, "code_fingerprint", lambda *, pr_number: fingerprint
    )
    merged = []
    monkeypatch.setattr(
        messages_module.github, "merge_pr", lambda *, pr_number: merged.append(pr_number)
    )
    closed = []
    monkeypatch.setattr(
        messages_module.github, "close_issue", lambda *, number: closed.append(number)
    )
    return {"merged": merged, "closed": closed}


# --------------------------------------------------------------------------- #
# 指纹与上次 PASS 相同 → sticky 命中：review_code 不被调、仍 merge
# --------------------------------------------------------------------------- #


def test_same_fingerprint_reuses_pass_and_skips_review(monkeypatch):
    captured = _patch_coding_reads(monkeypatch, fingerprint="fp-same")
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, code_passed_fingerprint="fp-same")]
    )

    events = msgs.poll(hold=NO_HOLD)

    # reviewer 未被调（sticky 铁证），但仍照进证据闸/merge → merged + done。
    assert orch.review_code_calls == 0
    assert events == [{"pr_number": 5, "reason": "merged"}]
    assert captured["merged"] == [5]
    assert {"issue_number": 3, "status": STATUS_DONE} in state.status_updates
    # 未重新落盘（指纹没变）。
    assert state.fingerprint_sets == []


# --------------------------------------------------------------------------- #
# 指纹不同 → 重审：review_code 调一次、PASS 后落盘新指纹
# --------------------------------------------------------------------------- #


def test_different_fingerprint_reviews_and_stores_new_fingerprint(monkeypatch):
    captured = _patch_coding_reads(monkeypatch, fingerprint="fp-new")
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, code_passed_fingerprint="fp-old")]
    )

    events = msgs.poll(hold=NO_HOLD)

    # reviewer 被调恰一次（代码变 → 重审），PASS 后落盘新指纹。
    assert orch.review_code_calls == 1
    assert state.fingerprint_sets == [{"issue_number": 3, "fingerprint": "fp-new"}]
    assert events == [{"pr_number": 5, "reason": "merged"}]
    assert captured["merged"] == [5]


def test_first_round_no_history_reviews_and_stores(monkeypatch):
    # 首轮无历史指纹（code_passed_fingerprint="")：短路不命中 → 照常评审 + 落盘。
    _patch_coding_reads(monkeypatch, fingerprint="fp-new")
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, code_passed_fingerprint="")]
    )

    msgs.poll(hold=NO_HOLD)

    assert orch.review_code_calls == 1
    assert state.fingerprint_sets == [{"issue_number": 3, "fingerprint": "fp-new"}]


# --------------------------------------------------------------------------- #
# 指纹为空（gh 抖动/失败）→ fail-open：照常评审、不落盘空指纹
# --------------------------------------------------------------------------- #


def test_empty_fingerprint_fails_open_to_review_without_storing(monkeypatch):
    # 即使已有历史指纹，本轮算不出指纹（"") → 不复用、照常评审、不落盘空指纹（不误清有效指纹）。
    _patch_coding_reads(monkeypatch, fingerprint="")
    msgs, orch, state = _messages(
        runs=[_run(issue_number=3, pr_number=5, code_passed_fingerprint="fp-old")]
    )

    msgs.poll(hold=NO_HOLD)

    assert orch.review_code_calls == 1
    # 空指纹不落盘：既不复用、也不误清 "fp-old"。
    assert state.fingerprint_sets == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
