"""Spec-0050/T6: 整链回执集成测试（成果测试，理念 8）。

用**内存假 GitHub 评论账本**（记 body+created_at、list_comments 回读）+ 假 orchestrator（记录调用、
返回可编排 summary/handle）驱动 messages.poll 走完一条 coding→证据链，断言五处收口各留**一条署名
回执**、已有正例（reason=human）不双贴、重复 poll 不刷屏、发评论故障不阻断编排。

本 feature 的「成果」是 GitHub PR 上的机器评论流（可观测性）；本仓库无产品前端界面可驱动、真发评论
需真 GitHub，故成果测试形态为**确定性集成复现**（非浏览器 e2e，见 Spec-0050 成果测试自检）。
"""

from pathlib import Path

from openagents import identity
from openagents import messages as messages_module
from openagents.evidence_gate import EvidenceDecision
from openagents.executor import ExecutorResult
from openagents.github import CheckStatus, Comment, Mergeability
from openagents.messages import Messages
from openagents.orchestrator import RunbookHandle
from openagents.state import (
    STATUS_BLOCKED,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
)

_AGENT_ID = "agent-self"

# 五处收口各自的稳定抬头（集成断言的锚点）。
_H_IMPLEMENT = "## 实现自述"
_H_ITER_CI = "## 迭代自述（CI 反馈）"
_H_ITER_REVIEW = "## 迭代自述（代码评审反馈）"
_H_ITER_E2E = "## 迭代自述（证据闸反馈）"
_H_RUNBOOK = "## 说明书定稿"
_H_EXEC = "## 证据执行"
_H_DECISION = "## 证据闸判决"


class _Ledger:
    """内存假 GitHub 评论账本：post_signed_comment 记盖真签名的 body + 递增 created_at；list_comments 回读。"""

    def __init__(self):
        self.comments: list[Comment] = []
        self._seq = 0
        self.raise_on_post = False

    def post_signed_comment(self, *, pr_number, body, agent_id):
        if self.raise_on_post:
            raise RuntimeError("gh 发评论挂了")
        self._seq += 1
        self.comments.append(
            Comment(
                id=f"c{self._seq}",
                author="openagents",
                body=identity.sign(body=body, agent_id=agent_id),
                created_at=f"2026-01-01T00:00:{self._seq:02d}Z",
            )
        )

    def list_comments(self, *, pr_number):
        return list(self.comments)

    def headers(self):
        """所有回执评论的标题行（用于断言各收口点各留一条）。"""
        out = []
        for c in self.comments:
            for line in c.body.splitlines():
                if line.strip().startswith("## "):
                    out.append(line.strip())
                    break
        return out

    def count(self, header):
        return self.headers().count(header)


class _FakeOrchestrator:
    """记录原子操作、返回可编排 summary/handle 的假编排器（不碰真 git/backend）。"""

    def __init__(self, *, code_decision, runbook_handle):
        self._code_decision = code_decision
        self._runbook_handle = runbook_handle
        self.implement_calls = []
        self.iterate_calls = []
        self.finalize_calls = []
        self.commit_evidence_calls = []

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)
        return "实现了 issue 的核心逻辑"

    def review_rfc(self, *, pr_number):
        raise AssertionError("本集成走 approval-label 路径，不应调 review_rfc")

    def review_code(self, *, pr_number):
        return self._code_decision

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"reason": reason, "detail": detail})
        return f"据 {reason} 反馈改了代码"

    def finalize_runbook(self, *, pr_number):
        self.finalize_calls.append(pr_number)
        return self._runbook_handle

    def commit_evidence(self, *, pr_number):
        self.commit_evidence_calls.append(pr_number)


class _FakeState:
    def __init__(self, *, runs):
        self._runs = list(runs)

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.status = status

    def increment_rounds(self, *, issue_number):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.rounds += 1
                return r.rounds
        return 0

    def increment_review_invalid(self, *, issue_number):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.review_invalid += 1
                return r.review_invalid
        return 0

    def reset_rounds(self, *, issue_number):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.rounds = r.review_invalid = r.merge_attempts = 0

    def set_block_gate(self, *, issue_number, gate):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.block_watermark = watermark

    def set_unblock_detail(self, *, issue_number, detail):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.unblock_detail = detail


def _run(*, status, rounds=0):
    return RunRecord(
        issue_number=3,
        branch="openagents/issue-3",
        pr_number=5,
        pr_url="u/pull/5",
        status=status,
        summary="",
        rounds=rounds,
    )


def _handle():
    return RunbookHandle(
        worktree=Path("/wt"),
        runbook_path=Path("/wt/docs/e2e-results/5/runbook.md"),
        evidence_dir=Path("/wt/docs/e2e-results/5"),
        intent="意图：x\n验收行为：\n- a",
        form="cli",
    )


class _Cfg:
    """poll 各阶段的 github 观测配置——测试在两次 poll 之间改这里模拟阶段推进。"""

    def __init__(self):
        self.has_approval = True
        self.ci_state = "success"
        self.failed_logs = ["FAIL test_x"]


def _wire(monkeypatch, *, ledger, cfg, code_decision, evidence_decision):
    """接线 messages 依赖：github/identity 模块函数 + executor/evidence_gate 用假账本/假裁决。"""
    from openagents import evidence_gate as eg
    from openagents import executor as ex

    g = messages_module.github
    monkeypatch.setattr(g, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(g, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(
        g, "has_label", lambda *, pr_number, name: cfg.has_approval and name.endswith("approved")
    )
    monkeypatch.setattr(g, "add_label", lambda *, pr_number, name: None)
    monkeypatch.setattr(g, "remove_label", lambda *, pr_number, name: None)
    monkeypatch.setattr(g, "merge_pr", lambda *, pr_number: None)
    monkeypatch.setattr(g, "close_issue", lambda *, number: None)
    monkeypatch.setattr(g, "update_branch", lambda *, pr_number: None)
    monkeypatch.setattr(
        g,
        "mergeability",
        lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN"),
    )
    monkeypatch.setattr(
        g,
        "check_status",
        lambda *, pr_number: CheckStatus(state=cfg.ci_state, failed_logs=cfg.failed_logs),
    )
    monkeypatch.setattr(g, "list_comments", ledger.list_comments)
    monkeypatch.setattr(messages_module.identity, "post_signed_comment", ledger.post_signed_comment)
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )
    # executor 真跑 / 证据闸判决用假结果（render_* 是真函数）。
    monkeypatch.setattr(
        messages_module.executor,
        "run_executor",
        lambda *, backend, work_dir, runbook_path, evidence_dir, pr_number: ExecutorResult(
            outcome="passed", form="cli", notes="真跑 init，退出码 0"
        ),
    )
    monkeypatch.setattr(
        messages_module.evidence_gate,
        "review_evidence",
        lambda *, backend, work_dir, intent, evidence_dir, pr_number: evidence_decision,
    )
    _ = (ex, eg)  # 保留 import（render_* 由 messages 内部调真函数）


def _messages(*, orch, state):
    # backend 非 None 才激活证据闸（object() 占位——证据闸内的 executor/review_evidence 已被打桩）。
    return Messages(orchestrator=orch, state=state, agent_id=_AGENT_ID, backend=object())


# --------------------------------------------------------------------------- #
# 五处收口各留一条署名回执（rfc-approved→implement→ci→review→证据闸 FAIL→e2e）
# --------------------------------------------------------------------------- #


def test_full_chain_posts_one_signed_report_per_step(monkeypatch):
    from openagents.reviewer import ReviewDecision

    ledger = _Ledger()
    cfg = _Cfg()
    orch = _FakeOrchestrator(
        code_decision=ReviewDecision(passed=True, feedback=""), runbook_handle=_handle()
    )
    record = _run(status=STATUS_RFC_REVIEW)
    state = _FakeState(runs=[record])
    _wire(
        monkeypatch,
        ledger=ledger,
        cfg=cfg,
        code_decision=orch._code_decision,
        evidence_decision=EvidenceDecision(passed=False, feedback="验收行为①未达成"),
    )
    msgs = _messages(orch=orch, state=state)

    # ① rfc-approved → implement → 「## 实现自述」。
    cfg.has_approval = True
    msgs.poll()
    record.status = STATUS_PR_OPEN  # implement 的真实副作用（fake 不改 state）

    # ② CI 失败 → iterate(ci) → 「## 迭代自述（CI 反馈）」。
    cfg.has_approval = False
    cfg.ci_state = "fail"
    msgs.poll()
    record.status = STATUS_ITERATING

    # ③ CI 绿 + reviewer REWORK → iterate(review) → 「## 迭代自述（代码评审反馈）」。
    cfg.ci_state = "success"
    orch._code_decision = ReviewDecision(passed=False, feedback="补单测", actionable=True)
    msgs.poll()

    # ④ CI 绿 + reviewer PASS → 证据闸：finalize→executor→judge FAIL→iterate(e2e)。
    orch._code_decision = ReviewDecision(passed=True, feedback="")
    msgs.poll()

    headers = ledger.headers()
    for expected in (
        _H_IMPLEMENT,
        _H_ITER_CI,
        _H_ITER_REVIEW,
        _H_RUNBOOK,
        _H_EXEC,
        _H_DECISION,
        _H_ITER_E2E,
    ):
        assert headers.count(expected) == 1, f"{expected} 应恰一条，实得 {headers.count(expected)}"
    # 每条回执都带本实例签名（署名可溯源）。
    for c in ledger.comments:
        assert identity.parse_agent_id(body=c.body) == _AGENT_ID


# --------------------------------------------------------------------------- #
# 重复 poll 同内容不刷屏（_report_already_posted 命中）
# --------------------------------------------------------------------------- #


def test_repeat_evidence_poll_does_not_spam(monkeypatch):
    from openagents.reviewer import ReviewDecision

    ledger = _Ledger()
    cfg = _Cfg()
    orch = _FakeOrchestrator(
        code_decision=ReviewDecision(passed=True, feedback=""), runbook_handle=_handle()
    )
    record = _run(status=STATUS_PR_OPEN)
    state = _FakeState(runs=[record])
    _wire(
        monkeypatch,
        ledger=ledger,
        cfg=cfg,
        code_decision=orch._code_decision,
        evidence_decision=EvidenceDecision(passed=False, feedback="同一条反馈"),
    )
    cfg.has_approval = False
    msgs = _messages(orch=orch, state=state)

    # 连续两轮证据闸（内容不变）→ 说明书/执行/判决/迭代各恰一条（去重命中）。
    msgs.poll()
    record.status = STATUS_ITERATING
    msgs.poll()

    assert ledger.count(_H_RUNBOOK) == 1
    assert ledger.count(_H_EXEC) == 1
    assert ledger.count(_H_DECISION) == 1
    assert ledger.count(_H_ITER_E2E) == 1


# --------------------------------------------------------------------------- #
# reason=human 不双贴（保持既有正例：只走 _post_comment_reply）
# --------------------------------------------------------------------------- #


def test_human_unblock_does_not_double_post_iterate_note(monkeypatch):
    ledger = _Ledger()
    cfg = _Cfg()
    orch = _FakeOrchestrator(code_decision=None, runbook_handle=None)
    record = _run(status=STATUS_BLOCKED)
    record.block_gate = "code"
    record.block_watermark = ""
    state = _FakeState(runs=[record])
    _wire(
        monkeypatch,
        ledger=ledger,
        cfg=cfg,
        code_decision=None,
        evidence_decision=EvidenceDecision(passed=True, feedback=""),
    )
    # 人回了一条新评论 → 触发解挂。
    monkeypatch.setattr(
        messages_module.identity,
        "new_human_comments",
        lambda *, pr_number, since: [
            Comment(id="h1", author="human", body="请改一下 X", created_at="2026-02-01T00:00:00Z")
        ],
    )
    msgs = _messages(orch=orch, state=state)

    msgs.poll()

    # 解挂走 iterate(reason="human")，但**不**贴「## 迭代自述」——只贴一条引用回应（replynote）。
    assert orch.iterate_calls == [{"reason": "human", "detail": "请改一下 X"}]
    headers = ledger.headers()
    assert (
        _H_ITER_CI not in headers and _H_ITER_REVIEW not in headers and _H_ITER_E2E not in headers
    )
    assert "## 迭代自述" not in " ".join(headers)
    # 恰贴一条回应（replynote 引用原评论，非 `## ` 抬头回执）。
    assert len(ledger.comments) == 1
    assert "↩️ 回应你的这条评论" in ledger.comments[0].body


# --------------------------------------------------------------------------- #
# 发评论故障不阻断编排（回执尽力而为旁路）
# --------------------------------------------------------------------------- #


def test_post_failure_does_not_block_orchestration(monkeypatch):
    from openagents.reviewer import ReviewDecision

    ledger = _Ledger()
    ledger.raise_on_post = True  # 所有回执发送都抛错
    cfg = _Cfg()
    cfg.has_approval = False
    cfg.ci_state = "fail"
    orch = _FakeOrchestrator(
        code_decision=ReviewDecision(passed=True, feedback=""), runbook_handle=_handle()
    )
    record = _run(status=STATUS_PR_OPEN)
    state = _FakeState(runs=[record])
    _wire(
        monkeypatch,
        ledger=ledger,
        cfg=cfg,
        code_decision=orch._code_decision,
        evidence_decision=EvidenceDecision(passed=True, feedback=""),
    )
    msgs = _messages(orch=orch, state=state)

    # CI 失败路径：即便回执发送全抛错，iterate 仍被调、poll 返回 ci 事件、不抛异常。
    events = msgs.poll()

    assert orch.iterate_calls == [{"reason": "ci", "detail": "FAIL test_x"}]
    assert events == [{"pr_number": 5, "reason": "ci"}]
    assert ledger.comments == []  # 发送全失败，账本为空，但编排照常推进
