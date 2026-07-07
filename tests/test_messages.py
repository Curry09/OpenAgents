"""RFC-0001 T5 + RFC-0005 + RFC-0012: Messages 按阶段路由 GitHub 事件的单元测试。

RFC-0012 把两处「等人」换成「调 reviewer 闸 + 自动推进」，本测试相应改为 reviewer 驱动：

外部副作用全部 mock/注入：
- orchestrator：注入伪 Orchestrator，review_rfc / review_code 返回可配 ReviewDecision，
  并记录 implement / refine_rfc / iterate 调用。
- state：注入伪 State（all_runs / update_status / increment_rounds / reset_rounds）。
- github.*：monkeypatch（is_merged / is_closed / has_label / check_status / merge_pr / add_label）。
- time.sleep：桩为 no-op（拉式同步重构后合并不再扇出，rebase 模块已删）。

覆盖：merged→done+扇出（优先级最高）；closed→closed；rfc 闸 标签/reviewer PASS→implement、
reviewer 非 PASS→refine+rounds++、超 K→BLOCKED+needs-human(PR 不关)；coding 闸 CI fail→
iterate(ci)、CI pending→等待、CI 绿+reviewer PASS→merge+done+扇出、reviewer 非 PASS→
iterate(review)+rounds++、超 K→BLOCKED；仅 open 状态被轮询；MAX_ROUNDS 边界；watch 循环。
"""

import time

import pytest

from openagents import blocknote
from openagents import messages as messages_module
from openagents.github import CheckStatus, GithubError, Mergeability
from openagents.hold import Hold
from openagents.messages import APPROVAL_LABEL, Messages, _configured_max_rounds
from openagents.reviewer import ReviewDecision
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
)

_AGENT_ID = "agent-self"

_PASS = ReviewDecision(passed=True, feedback="")
# Spec-0021/T2：真 REWORK（actionable）—— reviewer 解析出 REWORK 且带可操作反馈正文。
_FAIL = ReviewDecision(passed=False, feedback="补单测；处理空输入", actionable=True)
# Spec-0021/T2：评审无效—— 非 PASS 但 actionable=False（裁决无法解析/无可操作反馈）。
_INVALID = ReviewDecision(
    passed=False, feedback="（reviewer 未给出可解析的裁决）", actionable=False
)


class _FakeOrchestrator:
    """记录原子操作调用、并按预设裁决回应 review_rfc / review_code 的伪编排器。"""

    def __init__(self, *, rfc_decision=_PASS, code_decision=_PASS, e2e_result=None):
        self.implement_calls = []
        self.refine_calls = []
        self.iterate_calls = []
        self.review_rfc_calls = []
        self.review_code_calls = []
        self._rfc_decision = rfc_decision
        self._code_decision = code_decision
        # Spec-0055/T6：run_e2e 接线——返回预设 E2ERunResult（None = 无 e2e 计划，空过）。
        self._e2e_result = e2e_result
        self.run_e2e_calls = []

    def implement(self, *, pr_number):
        # Spec-0051/T4：implement 返回本轮实现摘要（None→str），供 messages 渲「## 实现自述」回执。
        self.implement_calls.append(pr_number)
        return "实现了 X 与 Y"

    def refine_rfc(self, *, pr_number, detail):
        self.refine_calls.append({"pr_number": pr_number, "detail": detail})

    def iterate(self, *, pr_number, reason, detail):
        # Spec-0040/T5：iterate 返回 result.summary；Spec-0051/T5：ci/review/e2e 收口点据此渲迭代自述。
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})
        return f"据 {reason} 反馈改了代码"

    def review_rfc(self, *, pr_number):
        self.review_rfc_calls.append(pr_number)
        return self._rfc_decision

    def review_code(self, *, pr_number):
        self.review_code_calls.append(pr_number)
        return self._code_decision

    def run_e2e(self, *, pr_number):
        # Spec-0055/T6：返回预设 E2ERunResult（None=无 e2e 计划空过 / reused=True 复用 / reused=False 真跑）。
        self.run_e2e_calls.append(pr_number)
        return self._e2e_result


class _FakeState:
    """伪 State：内存维护 runs，记录状态更新与回合数。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        self.status_updates.append({"issue_number": issue_number, "status": status})
        for record in self._runs:
            if record.issue_number == issue_number:
                record.status = status

    def increment_rounds(self, *, issue_number):
        for record in self._runs:
            if record.issue_number == issue_number:
                record.rounds += 1
                return record.rounds
        return 0

    def increment_review_invalid(self, *, issue_number):
        # Spec-0021/T2：镜像 increment_rounds，但计「评审无效」轮次（独立于 rounds）。
        for record in self._runs:
            if record.issue_number == issue_number:
                record.review_invalid += 1
                return record.review_invalid
        return 0

    def reset_rounds(self, *, issue_number):
        # Spec-0021/T2：reset_rounds 同点把 review_invalid 一并归零。
        # Spec-0031/T2：同点把 merge_attempts 一并归零（但不动 block_gate）。
        for record in self._runs:
            if record.issue_number == issue_number:
                record.rounds = 0
                record.review_invalid = 0
                record.merge_attempts = 0

    def set_block_gate(self, *, issue_number, gate):
        # Spec-0031/T2：落盘某 run 的 block_gate（""/rfc/code/merge/*-unparseable）。
        for record in self._runs:
            if record.issue_number == issue_number:
                record.block_gate = gate

    def set_code_fingerprint(self, *, issue_number, fingerprint):
        # Spec-0053/T3：代码闸 PASS 后落盘 PR 净 diff 指纹（sticky 短路用）。
        for record in self._runs:
            if record.issue_number == issue_number:
                record.code_passed_fingerprint = fingerprint

    def set_block_watermark(self, *, issue_number, watermark):
        # Spec-0032/T1：_block 现会落「解挂水位线」（挂起时刻最新评论 createdAt）。
        for record in self._runs:
            if record.issue_number == issue_number:
                record.block_watermark = watermark

    def set_closed_at(self, *, issue_number, when):
        # Spec-0042/T3：is_closed 分支置 closed 同时打 closed_at 时间戳（复活窗口起点）。
        for record in self._runs:
            if record.issue_number == issue_number:
                record.closed_at = when

    def increment_merge_attempts(self, *, issue_number):
        # Spec-0031/T2：镜像 increment_rounds，但计 armed 模式 agent 解冲突重试次数。
        for record in self._runs:
            if record.issue_number == issue_number:
                record.merge_attempts += 1
                return record.merge_attempts
        return 0


def _run(*, issue_number, pr_number, status, rounds=0, review_invalid=0, e2e_ran_fingerprint=""):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url=f"https://github.com/acme/widget/pull/{pr_number}",
        status=status,
        summary="",
        rounds=rounds,
        review_invalid=review_invalid,
        e2e_ran_fingerprint=e2e_ran_fingerprint,
    )


def _make(
    *,
    runs,
    rfc_decision=_PASS,
    code_decision=_PASS,
    agent_id=_AGENT_ID,
    e2e_result=None,
    backend=None,
):
    orch = _FakeOrchestrator(
        rfc_decision=rfc_decision, code_decision=code_decision, e2e_result=e2e_result
    )
    state = _FakeState(runs=runs)
    # Spec-0055/T6：run_e2e 归编排器（本 fake 返回预设结果）；messages 只据其 reused/None 决定流转。
    msgs = Messages(orchestrator=orch, state=state, agent_id=agent_id, backend=backend)
    return msgs, orch, state


def _patch_github(
    monkeypatch,
    *,
    merged=False,
    closed=False,
    has_label=False,
    check=None,
    mergeable="MERGEABLE",
    merge_state_status="CLEAN",
):
    """统一 monkeypatch github 模块函数；返回 merge_pr / add_label / close_issue 调用的记录器。

    Spec-0022/T2：默认 mergeable=MERGEABLE / merge_state_status=CLEAN，使 _process_coding 的
    可合并性预检默认放行（既有 coding 用例零回归）；冲突/UNKNOWN 用例显式传参覆盖。
    identity.post_signed_comment 桩为记录器（rec["comments"]），断言 rebase 提示恰发一次。
    """
    rec = {"merged": [], "labels": [], "closed_issues": [], "comments": []}
    monkeypatch.setattr(
        messages_module.github,
        "mergeability",
        lambda *, pr_number: Mergeability(
            mergeable=mergeable, merge_state_status=merge_state_status
        ),
    )
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: rec["comments"].append(
            {"pr_number": pr_number, "body": body, "agent_id": agent_id}
        ),
    )
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: merged)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: closed)
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: has_label)
    # Spec-0032/T5：_block 落水位线要读最新评论 createdAt；blocked 解挂主路径要读新人类评论。
    # 默认桩为空（无评论 / 无新人类评论），使既有 block / blocked 用例零回归（走标签兜底路径）。
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )
    monkeypatch.setattr(
        messages_module.github,
        "check_status",
        lambda *, pr_number: check or CheckStatus(state="pass", failed_logs=[]),
    )
    # Spec-0053/T3：代码闸 sticky 短路会先算 PR 净 diff 指纹。默认桩返回 ""（fail-open）——落回照常
    # 评审，使既有 coding 用例逐字节零回归；sticky 命中/落盘的专项断言见 test_messages_review_sticky。
    monkeypatch.setattr(messages_module.github, "code_fingerprint", lambda *, pr_number: "")
    monkeypatch.setattr(
        messages_module.github,
        "merge_pr",
        lambda *, pr_number, method="merge": rec["merged"].append(pr_number),
    )
    monkeypatch.setattr(
        messages_module.github,
        "add_label",
        lambda *, pr_number, name: rec["labels"].append((pr_number, name)),
    )
    # RFC-0017：两条 STATUS_DONE 路径会显式关 issue；桩为记录器，断言以正确 issue_number 调用。
    monkeypatch.setattr(
        messages_module.github,
        "close_issue",
        lambda *, number: rec["closed_issues"].append(number),
    )
    # 拉式同步重构后合并分支不再主动扇出（push 扇出已撤），无需再桩合并后同步入口。
    return rec


# --------------------------------------------------------------------------- #
# merged / closed 终止
# --------------------------------------------------------------------------- #


def test_merged_pr_set_done_and_not_routed(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    rec = _patch_github(monkeypatch, merged=True, has_label=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert orch.implement_calls == []
    assert any(e["reason"] == "merged" for e in events)
    # RFC-0017 T2：检测到已合并（合进 test）分支同样显式关联 issue（以 issue_number 调一次）。
    assert rec["closed_issues"] == [3]


def test_closed_pr_set_closed_and_not_routed(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, closed=True, has_label=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_CLOSED}]
    assert orch.implement_calls == []
    assert any(e["reason"] == "closed" for e in events)


def test_merged_takes_precedence_over_closed(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, merged=True, closed=True)

    events = msgs.poll()

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert any(e["reason"] == "merged" for e in events)


def test_terminal_runs_not_polled(monkeypatch):
    # closed / done / solving 都不在轮询范围，poll 跳过（issue #49 后 blocked 仍被扫描，单独测）。
    msgs, orch, state = _make(
        runs=[
            _run(issue_number=1, pr_number=11, status=STATUS_DONE),
            _run(issue_number=2, pr_number=22, status="solving"),
            _run(issue_number=3, pr_number=33, status=STATUS_CLOSED),
        ]
    )
    seen = []
    monkeypatch.setattr(
        messages_module.github, "is_merged", lambda *, pr_number: seen.append(pr_number) or False
    )

    events = msgs.poll()

    assert seen == []
    assert events == []


# --------------------------------------------------------------------------- #
# RFC 评审闸（RFC-0012 决策 1/3）
# --------------------------------------------------------------------------- #


def test_rfc_existing_label_triggers_implement(monkeypatch):
    # 已带 rfc-approved（人/上一轮 reviewer 打的）→ 直接 implement，不再评审（向后兼容）。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, has_label=True)

    events = msgs.poll()

    assert orch.implement_calls == [5]
    assert orch.review_rfc_calls == []
    assert any(e["reason"] == "approved" for e in events)


def test_rfc_reviewer_pass_labels_and_implements(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)], rfc_decision=_PASS
    )
    rec = _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert orch.review_rfc_calls == [5]
    assert (5, APPROVAL_LABEL) in rec["labels"]
    assert orch.implement_calls == [5]
    assert any(e["reason"] == "rfc-pass" for e in events)


def test_rfc_reviewer_fail_refines_and_increments_rounds(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)], rfc_decision=_FAIL
    )
    _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert orch.refine_calls == [{"pr_number": 5, "detail": _FAIL.feedback}]
    assert orch.implement_calls == []
    assert state.all_runs()[0].rounds == 1
    assert any(e["reason"] == "refine" for e in events)


def test_rfc_reviewer_fail_over_k_blocks(monkeypatch):
    # rounds 预置到 K-1，本轮非 PASS 使其达 K → BLOCKED + needs-human + PR 不关。
    monkeypatch.setattr(messages_module, "MAX_ROUNDS", 3)
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW, rounds=2)],
        rfc_decision=_FAIL,
    )
    rec = _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert orch.refine_calls == []  # 超 K 不再 refine
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_BLOCKED}]
    assert (5, BLOCKED_LABEL) in rec["labels"]
    blocked = next(e for e in events if e["reason"] == "blocked")
    assert blocked["gate"] == "rfc"


# --------------------------------------------------------------------------- #
# 代码评审闸（RFC-0012 决策 1）
# --------------------------------------------------------------------------- #


def test_coding_ci_fail_triggers_iterate_ci_no_round(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(
        monkeypatch, check=CheckStatus(state="fail", failed_logs=["lint [FAILURE] http://x"])
    )

    events = msgs.poll()

    assert len(orch.iterate_calls) == 1
    assert orch.iterate_calls[0]["reason"] == "ci"
    assert orch.review_code_calls == []
    # CI 回合不计入 rounds（行为保持）。
    assert state.all_runs()[0].rounds == 0
    assert any(e["reason"] == "ci" for e in events)


def test_coding_ci_pending_waits(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    _patch_github(monkeypatch, check=CheckStatus(state="pending", failed_logs=[]))

    events = msgs.poll()

    assert orch.review_code_calls == []
    assert orch.iterate_calls == []
    assert events == []


def test_coding_ci_green_reviewer_pass_merges_no_fanout(monkeypatch):
    # 拉式同步取代 push 扇出：PASS → merge_pr + 置 done + 关 issue，本轮**不再扇出**；其余 open PR
    # 各自轮到时在 _process_coding 的 BEHIND 分支 update_branch 跟上（rebase 模块已删，无从扇出）。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)], code_decision=_PASS
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.review_code_calls == [5]
    assert rec["merged"] == [5]
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    # RFC-0017 T2：代码闸 PASS → merge_pr 合进 test → 显式关联 issue（以 issue_number 调一次）。
    assert rec["closed_issues"] == [3]
    merged_event = next(e for e in events if e["reason"] == "merged")
    assert "synced" not in merged_event  # 拉式同步后 merged 事件不再带扇出结果


def test_coding_reviewer_fail_iterates_review_and_increments(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)], code_decision=_FAIL
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.iterate_calls == [{"pr_number": 5, "reason": "review", "detail": _FAIL.feedback}]
    assert rec["merged"] == []
    assert state.all_runs()[0].rounds == 1
    assert any(e["reason"] == "review" for e in events)


def test_coding_reviewer_fail_over_k_blocks(monkeypatch):
    monkeypatch.setattr(messages_module, "MAX_ROUNDS", 2)
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_ITERATING, rounds=1)],
        code_decision=_FAIL,
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.iterate_calls == []
    assert rec["merged"] == []
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_BLOCKED}]
    assert (5, BLOCKED_LABEL) in rec["labels"]
    blocked = next(e for e in events if e["reason"] == "blocked")
    assert blocked["gate"] == "code"


# --------------------------------------------------------------------------- #
# Spec-0055/T6: e2e——CI 绿后 run_e2e（在 review 前）+ 收敛/bad_ci_after_e2e
# --------------------------------------------------------------------------- #


def _e2e_ran(*, outcome="passed"):
    """一个「本轮真跑了 executor」的 E2ERunResult（reused=False，带结果供渲回执）。"""
    from openagents.executor import ExecutorResult
    from openagents.orchestrator import E2ERunResult

    return E2ERunResult(reused=False, result=ExecutorResult(outcome=outcome, notes="n"))


def _e2e_reused():
    """一个「源码未变、复用上轮证据」的 E2ERunResult（reused=True，无新结果）。"""
    from openagents.orchestrator import E2ERunResult

    return E2ERunResult(reused=True, result=None)


def test_run_e2e_ran_this_round_defers_merge(monkeypatch):
    # Spec-0055/T6：本轮真跑了 executor（reused=False）→ 证据是新 docs commit，本轮不 review/merge，
    # 返回 reason="e2e" 让证据 commit 过一遍 CI；review_code 本轮不调。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)],
        code_decision=_PASS,
        e2e_result=_e2e_ran(),
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.run_e2e_calls == [5]
    assert orch.review_code_calls == []  # review 不在本轮（executor 真跑后先让证据过 CI）
    assert rec["merged"] == []
    assert any(e["reason"] == "e2e" for e in events)


def test_run_e2e_reused_proceeds_to_review_and_merge(monkeypatch):
    # Spec-0055/T6：源码未变、run_e2e 复用（reused=True）→ 继续 review_code → PASS → merge。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)],
        code_decision=_PASS,
        e2e_result=_e2e_reused(),
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.run_e2e_calls == [5]
    assert orch.review_code_calls == [5]
    assert rec["merged"] == [5]
    assert any(e["reason"] == "merged" for e in events)


def test_run_e2e_none_no_plan_proceeds_to_merge(monkeypatch):
    # 无 e2e 计划（run_e2e 返 None）→ 非交互 PR，直接 review + merge（零回归）。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)],
        code_decision=_PASS,
        e2e_result=None,
    )
    rec = _patch_github(monkeypatch)

    msgs.poll()

    assert orch.run_e2e_calls == [5]
    assert orch.review_code_calls == [5]
    assert rec["merged"] == [5]


def test_bad_ci_after_e2e_blocks_not_iterate(monkeypatch):
    # Spec-0055/T6：源码自 e2e 真跑后未变（e2e_ran_fingerprint == 当前源码指纹），CI 却变红 →
    # 走 bad_ci_after_e2e：不 iterate(ci)（源码没错），打 needs-human + bad_ci_after_e2e 标签 + blocked。
    msgs, orch, state = _make(
        runs=[
            _run(
                issue_number=3,
                pr_number=5,
                status=STATUS_PR_OPEN,
                e2e_ran_fingerprint="fp-x",
            )
        ],
        code_decision=_PASS,
    )
    rec = _patch_github(monkeypatch, check=CheckStatus(state="fail", failed_logs=["boom"]))
    monkeypatch.setattr(messages_module.github, "code_fingerprint", lambda *, pr_number: "fp-x")

    events = msgs.poll()

    assert orch.iterate_calls == []  # 不当普通 CI fail 打回 iterate
    assert state.status_updates[-1] == {"issue_number": 3, "status": STATUS_BLOCKED}
    assert (5, BLOCKED_LABEL) in rec["labels"]
    assert (5, "bad_ci_after_e2e") in rec["labels"]
    blocked = next(e for e in events if e["reason"] == "blocked")
    assert blocked["gate"] == "bad-ci-after-e2e"


def test_ci_fail_with_changed_source_still_iterates_ci(monkeypatch):
    # 反例：源码指纹与 e2e_ran_fingerprint 不同（源码真的改了/挂了）→ 照常 iterate(ci)，非 bad_ci。
    msgs, orch, state = _make(
        runs=[
            _run(
                issue_number=3,
                pr_number=5,
                status=STATUS_PR_OPEN,
                e2e_ran_fingerprint="fp-old",
            )
        ],
        code_decision=_PASS,
    )
    _patch_github(monkeypatch, check=CheckStatus(state="fail", failed_logs=["real lint error"]))
    monkeypatch.setattr(messages_module.github, "code_fingerprint", lambda *, pr_number: "fp-new")

    events = msgs.poll()

    assert orch.iterate_calls == [{"pr_number": 5, "reason": "ci", "detail": "real lint error"}]
    assert any(e["reason"] == "ci" for e in events)


def test_run_e2e_ran_increments_rounds(monkeypatch):
    # Spec-0055/T6：本轮真跑（reused=False）记一轮——健康 PR 只真跑一次，rounds 0→1（< K 不挂起），
    # 仍返回 reason="e2e"。回合上限是「源码指纹每轮 churn 无界重跑」的收敛兜底。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)],
        code_decision=_PASS,
        e2e_result=_e2e_ran(),
    )
    _patch_github(monkeypatch)

    events = msgs.poll()

    assert state._runs[0].rounds == 1  # 真跑一次记一轮
    assert any(e["reason"] == "e2e" for e in events)
    assert not any(e["reason"] == "blocked" for e in events)


def test_run_e2e_churn_blocks_at_max_rounds(monkeypatch):
    # Spec-0055/T6：executor 在证据目录外留改动 → 源码指纹每轮 churn → run_e2e 永远 reused=False。
    # rounds 攒到 MAX_ROUNDS → 不再无界重跑，走 _block(gate="e2e")（needs-human + blocked）。
    msgs, orch, state = _make(
        runs=[
            _run(
                issue_number=3,
                pr_number=5,
                status=STATUS_PR_OPEN,
                rounds=messages_module.MAX_ROUNDS - 1,
            )
        ],
        code_decision=_PASS,
        e2e_result=_e2e_ran(),
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.review_code_calls == []  # 挂起短路，不进 review
    assert rec["merged"] == []
    assert state.status_updates[-1] == {"issue_number": 3, "status": STATUS_BLOCKED}
    assert (5, BLOCKED_LABEL) in rec["labels"]
    blocked = next(e for e in events if e["reason"] == "blocked")
    assert blocked["gate"] == "e2e"


# --------------------------------------------------------------------------- #
# Spec-0022/T2：代码闸可合并性预检 + poll 单 record 错误隔离
# --------------------------------------------------------------------------- #


def test_coding_unmergeable_blocks_and_posts_one_rebase_comment(monkeypatch):
    # 真冲突（DIRTY/CONFLICTING）：不评审、不 merge；恰发一次结构化挂起评论（Spec-0032/T5：由
    # _block 经 blocknote 统一出，merge 闸把 CONFLICT_COMMENT 当 blocker 包进「卡在哪」段）；
    # record 置 BLOCKED + needs-human；事件 reason == "unmergeable"。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    rec = _patch_github(monkeypatch, mergeable="CONFLICTING", merge_state_status="DIRTY")

    events = msgs.poll()

    assert orch.review_code_calls == []
    assert rec["merged"] == []
    assert len(rec["comments"]) == 1
    body = rec["comments"][0]["body"]
    assert "gate=merge" in body  # 结构化挂起评论（按 gate 出原因短语）
    assert (
        messages_module.conflictdiag.CONFLICT_COMMENT in body
    )  # 冲突提示作 blocker 嵌在「卡在哪」段
    assert rec["comments"][0]["agent_id"] == _AGENT_ID
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_BLOCKED}]
    assert (5, BLOCKED_LABEL) in rec["labels"]
    assert any(e["reason"] == "unmergeable" for e in events)


def test_coding_unmergeable_then_blocked_skips_next_round(monkeypatch):
    # 「恰一条」回归：第一轮 block 后，record 变 BLOCKED 且 needs-human 仍在 → 第二轮 poll
    # 对该 record return None（不再发评论、不评审、不动状态）。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    rec = _patch_github(
        monkeypatch, mergeable="CONFLICTING", merge_state_status="DIRTY", has_label=True
    )

    msgs.poll()  # 第一轮：进 blocked，发一条评论
    events2 = msgs.poll()  # 第二轮：blocked + 仍有 needs-human → 跳过

    assert len(rec["comments"]) == 1  # 未再次发评论
    assert orch.review_code_calls == []
    assert events2 == []


def test_coding_mergeable_unknown_waits(monkeypatch):
    # UNKNOWN（GitHub 异步未算完）：本轮不评审、不 block、不发评论；下一轮再查。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    rec = _patch_github(monkeypatch, mergeable="UNKNOWN", merge_state_status="UNKNOWN")

    events = msgs.poll()

    assert orch.review_code_calls == []
    assert rec["merged"] == []
    assert rec["comments"] == []
    assert state.status_updates == []
    assert events == []


def test_coding_clean_passes_precheck_and_merges(monkeypatch):
    # 可合并放行：CLEAN/MERGEABLE → 走既有 CI→reviewer→merge 路径，行为零回归。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)], code_decision=_PASS
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.review_code_calls == [5]
    assert rec["merged"] == [5]
    assert rec["comments"] == []
    assert any(e["reason"] == "merged" for e in events)


def test_poll_error_isolation_skips_failing_record(monkeypatch):
    # 错误隔离：两个 open record，第一个 merge_pr 抛 GithubError → poll 不抛、第一个产出
    # reason=="error" 事件、第二个 record 照常处理产出其事件。不改 state（不擅自 block）。
    msgs, orch, state = _make(
        runs=[
            _run(issue_number=1, pr_number=11, status=STATUS_PR_OPEN),
            _run(issue_number=2, pr_number=22, status=STATUS_PR_OPEN),
        ],
        code_decision=_PASS,
    )
    rec = _patch_github(monkeypatch)

    def _boom(*, pr_number, method="merge"):
        if pr_number == 11:
            raise GithubError("merge 冲突")
        rec["merged"].append(pr_number)

    monkeypatch.setattr(messages_module.github, "merge_pr", _boom)

    events = msgs.poll()

    error_event = next(e for e in events if e["reason"] == "error")
    assert error_event["pr_number"] == 11
    # 第二个 record 不受影响、照常 merge。
    assert rec["merged"] == [22]
    assert any(e["reason"] == "merged" and e["pr_number"] == 22 for e in events)
    # 不改 state 为 blocked（失败可能瞬时，下轮自然重试）。
    assert all(u["status"] != STATUS_BLOCKED for u in state.status_updates)


# --------------------------------------------------------------------------- #
# MAX_ROUNDS 边界（K-1 不 block、K block）
# --------------------------------------------------------------------------- #


def test_rounds_boundary_k_minus_one_does_not_block(monkeypatch):
    monkeypatch.setattr(messages_module, "MAX_ROUNDS", 3)
    # rounds 起始 1，本轮非 PASS → rounds=2 < 3 → refine（不 block）。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW, rounds=1)],
        rfc_decision=_FAIL,
    )
    _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert len(orch.refine_calls) == 1
    assert state.all_runs()[0].rounds == 2
    assert any(e["reason"] == "refine" for e in events)
    assert all(e["reason"] != "blocked" for e in events)


# --------------------------------------------------------------------------- #
# Spec-0021/T2：评审无效不吃 round、不空转、独立重试上限后诚实升级
# --------------------------------------------------------------------------- #


def test_spec_gate_invalid_review_no_round_no_refine(monkeypatch):
    # 截断好评（passed=False、actionable=False）在 spec 闸：不 increment_rounds、不 refine_rfc，
    # 返回 review-invalid 事件；只递增独立的 review_invalid 计数。
    monkeypatch.setattr(messages_module, "MAX_REVIEW_RETRIES", 2)
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)], rfc_decision=_INVALID
    )
    _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert orch.refine_calls == []
    assert orch.implement_calls == []
    assert state.all_runs()[0].rounds == 0  # 不吃 round
    assert state.all_runs()[0].review_invalid == 1  # 独立计数 +1
    assert any(e["reason"] == "review-invalid" for e in events)


def test_merge_gate_invalid_review_no_round_no_iterate(monkeypatch):
    # 截断好评在 merge 闸：CI 绿但 reviewer 评审无效 → 不 iterate、不计 round、不 merge。
    monkeypatch.setattr(messages_module, "MAX_REVIEW_RETRIES", 2)
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)], code_decision=_INVALID
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert orch.iterate_calls == []
    assert rec["merged"] == []
    assert state.all_runs()[0].rounds == 0
    assert state.all_runs()[0].review_invalid == 1
    assert any(e["reason"] == "review-invalid" for e in events)


def test_invalid_review_over_retries_blocks_with_unparseable_gate(monkeypatch):
    # 连续达 MAX_REVIEW_RETRIES 次评审无效 → _block 打 needs-human，gate 标识为 reviewer 输出无法解析
    # （可断言区别于真 REWORK 的 block：gate=rfc-unparseable，而非 rfc）。
    monkeypatch.setattr(messages_module, "MAX_REVIEW_RETRIES", 2)
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW, review_invalid=1)],
        rfc_decision=_INVALID,
    )
    rec = _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()

    assert orch.refine_calls == []
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_BLOCKED}]
    assert (5, BLOCKED_LABEL) in rec["labels"]
    blocked = next(e for e in events if e["reason"] == "blocked")
    assert blocked["gate"] == "rfc-unparseable"
    # rounds 始终不被评审无效偷吃。
    assert state.all_runs()[0].rounds == 0


def test_code_gate_invalid_over_retries_blocks_code_unparseable(monkeypatch):
    monkeypatch.setattr(messages_module, "MAX_REVIEW_RETRIES", 2)
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_ITERATING, review_invalid=1)],
        code_decision=_INVALID,
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()

    assert rec["merged"] == []
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_BLOCKED}]
    blocked = next(e for e in events if e["reason"] == "blocked")
    assert blocked["gate"] == "code-unparseable"


def test_real_rework_still_increments_rounds_not_review_invalid(monkeypatch):
    # 零回归 + 预算独立：真 REWORK（actionable）照旧吃 rounds，且绝不动 review_invalid 计数。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)], rfc_decision=_FAIL
    )
    _patch_github(monkeypatch, has_label=False)

    msgs.poll()

    assert state.all_runs()[0].rounds == 1
    assert state.all_runs()[0].review_invalid == 0
    assert orch.refine_calls == [{"pr_number": 5, "detail": _FAIL.feedback}]


def test_configured_max_review_retries_env(monkeypatch):
    monkeypatch.delenv(messages_module.MAX_REVIEW_RETRIES_ENV, raising=False)
    assert messages_module._configured_max_review_retries() == 2
    monkeypatch.setenv(messages_module.MAX_REVIEW_RETRIES_ENV, "4")
    assert messages_module._configured_max_review_retries() == 4
    monkeypatch.setenv(messages_module.MAX_REVIEW_RETRIES_ENV, "oops")
    assert messages_module._configured_max_review_retries() == 2
    monkeypatch.setenv(messages_module.MAX_REVIEW_RETRIES_ENV, "0")
    assert messages_module._configured_max_review_retries() == 2


# --------------------------------------------------------------------------- #
# 轮询范围 / watch / 常量
# --------------------------------------------------------------------------- #


def test_only_open_runs_are_polled(monkeypatch):
    msgs, orch, state = _make(
        runs=[
            _run(issue_number=1, pr_number=11, status=STATUS_DONE),
            _run(issue_number=2, pr_number=22, status="solving"),
            _run(issue_number=3, pr_number=33, status=STATUS_RFC_REVIEW),
            _run(issue_number=4, pr_number=44, status=STATUS_PR_OPEN),
        ]
    )
    # 全量打桩 github（含 check_status / merge_pr），再覆盖 is_merged 为记录器。
    _patch_github(monkeypatch, has_label=True)
    seen = []
    monkeypatch.setattr(
        messages_module.github, "is_merged", lambda *, pr_number: seen.append(pr_number) or False
    )

    msgs.poll()

    # rfc-review(33) 走 has_label→implement；pr-open(44) 走 coding；done/solving 跳过。
    assert seen == [33, 44]


# --------------------------------------------------------------------------- #
# Spec-0020/T3：分级监督闸——hold.at_spec / hold.at_merge 分流（默认 Hold 零回归）
# --------------------------------------------------------------------------- #

_HOLD_SPEC = Hold(at_spec=True, at_merge=False)
_HOLD_MERGE = Hold(at_spec=False, at_merge=True)
_HOLD_BOTH = Hold(at_spec=True, at_merge=True)


def test_spec_gate_hold_without_label_stays_and_does_nothing(monkeypatch):
    # spec 闸 hold：无 rfc-approved label → 不调自动 reviewer、不打 label、不 implement，
    # 停在 rfc-review（状态不变）。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    rec = _patch_github(monkeypatch, has_label=False)

    events = msgs.poll(hold=_HOLD_SPEC)

    assert orch.review_rfc_calls == []
    assert orch.implement_calls == []
    assert rec["labels"] == []
    assert state.status_updates == []
    assert any(e["reason"] == "hold-spec" for e in events)


def test_spec_gate_hold_with_human_label_still_implements(monkeypatch):
    # spec 闸 hold：带人工 rfc-approved label → 照常 implement 进 coding（复用 label 门控）。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)])
    _patch_github(monkeypatch, has_label=True)

    events = msgs.poll(hold=_HOLD_SPEC)

    assert orch.implement_calls == [5]
    assert orch.review_rfc_calls == []
    assert any(e["reason"] == "approved" for e in events)


def test_merge_gate_hold_does_not_merge_and_freezes(monkeypatch):
    # Spec-0041/T1：merge 闸 hold + reviewer PASS → 不调 merge_pr，但**夯住**（取代旧的「状态不变、
    # 停在 pr-open 空转」）：置 blocked + 打 needs-human + 贴成功文案 + gate=merge-hold。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)], code_decision=_PASS
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll(hold=_HOLD_MERGE)

    # reviewer 评审照跑，但不自动合并、不关 issue。
    assert orch.review_code_calls == [5]
    assert rec["merged"] == []
    assert rec["closed_issues"] == []
    # 夯住：blocked + needs-human + 成功文案（非失败模板）。
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_BLOCKED}]
    assert (5, BLOCKED_LABEL) in rec["labels"]
    assert state.all_runs()[0].block_gate == "merge-hold"
    assert len(rec["comments"]) == 1
    assert rec["comments"][0]["body"] == blocknote.build_hold_merge_pass()
    assert "卡住了" not in rec["comments"][0]["body"]
    assert events == [{"pr_number": 5, "reason": "hold-merge", "gate": "merge-hold"}]


def test_merge_gate_hold_human_merge_reconciles_done_next_round(monkeypatch):
    # merge 闸 hold 后人手动 merge → 下一轮 is_merged 分支照常 reconcile 成 done（既有逻辑）。
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    rec = _patch_github(monkeypatch, merged=True)

    events = msgs.poll(hold=_HOLD_MERGE)

    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert rec["closed_issues"] == [3]
    assert any(e["reason"] == "merged" for e in events)


def test_both_gates_hold_stop_at_each(monkeypatch):
    # spec,merge 组合：rfc-review 停在 spec 闸（不动状态）；pr-open PASS 后停在 merge 闸——
    # Spec-0041/T1：merge 闸从「不动状态」改为「夯住」，故 issue 4 转 blocked。
    msgs, orch, state = _make(
        runs=[
            _run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW),
            _run(issue_number=4, pr_number=6, status=STATUS_PR_OPEN),
        ]
    )
    rec = _patch_github(monkeypatch, has_label=False)

    events = msgs.poll(hold=_HOLD_BOTH)

    assert orch.review_rfc_calls == []
    assert orch.implement_calls == []
    assert rec["merged"] == []
    # spec 闸不动 issue 3；merge 闸夯住 issue 4。
    assert state.status_updates == [{"issue_number": 4, "status": STATUS_BLOCKED}]
    assert state.all_runs()[1].block_gate == "merge-hold"
    reasons = {e["reason"] for e in events}
    assert reasons == {"hold-spec", "hold-merge"}


def test_default_hold_keeps_auto_spec_review(monkeypatch):
    # 零回归：默认 Hold（全不停）下 spec 闸照旧自动评审 + 打标 + implement。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_RFC_REVIEW)], rfc_decision=_PASS
    )
    rec = _patch_github(monkeypatch, has_label=False)

    events = msgs.poll()  # 默认 hold

    assert orch.review_rfc_calls == [5]
    assert (5, APPROVAL_LABEL) in rec["labels"]
    assert orch.implement_calls == [5]
    assert any(e["reason"] == "rfc-pass" for e in events)


def test_default_hold_keeps_auto_merge(monkeypatch):
    # 零回归：默认 Hold 下 merge 闸照旧 CI 绿 + reviewer PASS → 自动合并 → done。
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)], code_decision=_PASS
    )
    rec = _patch_github(monkeypatch)

    events = msgs.poll()  # 默认 hold

    assert rec["merged"] == [5]
    assert state.status_updates == [{"issue_number": 3, "status": STATUS_DONE}]
    assert any(e["reason"] == "merged" for e in events)


def test_approval_label_constant():
    assert APPROVAL_LABEL == "rfc-approved"


def test_configured_max_rounds_default(monkeypatch):
    monkeypatch.delenv(messages_module.MAX_ROUNDS_ENV, raising=False)
    assert _configured_max_rounds() == 3


def test_configured_max_rounds_reads_env(monkeypatch):
    monkeypatch.setenv(messages_module.MAX_ROUNDS_ENV, "5")
    assert _configured_max_rounds() == 5


def test_configured_max_rounds_invalid_falls_back(monkeypatch):
    monkeypatch.setenv(messages_module.MAX_ROUNDS_ENV, "oops")
    assert _configured_max_rounds() == 3


def test_configured_max_rounds_below_one_falls_back(monkeypatch):
    monkeypatch.setenv(messages_module.MAX_ROUNDS_ENV, "0")
    assert _configured_max_rounds() == 3


def test_watch_loops_then_exits_when_no_open_pr(monkeypatch):
    runs = [_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)]
    msgs, orch, state = _make(runs=runs)

    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    poll_count = {"n": 0}
    real_poll = msgs.poll

    def _counting_poll():
        poll_count["n"] += 1
        if poll_count["n"] == 2:
            state.update_status(issue_number=3, status=STATUS_DONE)
        return real_poll()

    monkeypatch.setattr(msgs, "poll", _counting_poll)
    _patch_github(monkeypatch)

    msgs.watch(interval=7)

    assert poll_count["n"] >= 1
    assert all(s == 7 for s in sleeps)


def test_watch_exits_on_keyboard_interrupt(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=3, pr_number=5, status=STATUS_PR_OPEN)])
    monkeypatch.setattr(time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    _patch_github(monkeypatch)

    msgs.watch(interval=1)


# --------------------------------------------------------------------------- #
# RFC-0012 集成：真实 Messages + 真实 Orchestrator 的 RFC 闸自动放行
# --------------------------------------------------------------------------- #


def test_integration_real_orchestrator_rfc_pass_implements(monkeypatch, tmp_path):
    """端到端一轮 rfc-review poll（真实 Messages ↔ 真实 Orchestrator）：

    reviewer backend 返回 PASS → review_rfc 聚合 passed=True → 自动打 rfc-approved →
    implement（写码 + mark_ready + pr-open + reset_rounds）。验证跨 messages → orchestrator
    → reviewer → state 的整条放行链路。
    """
    from openagents.backends.base import AgentResult
    from openagents.github import PR
    from openagents.orchestrator import Orchestrator
    from openagents.state import State

    agent_id = "agent-integration"

    class _StubBackend:
        name = "stub"

        def run(self, *, work_dir, task, context):
            # reviewer 评 RFC 时返回 PASS；implement 写码时返回普通摘要。
            summary = "VERDICT: PASS" if "审核员" in task else "已实现"
            return AgentResult(changed=True, summary=summary)

    class _StubWorkspace:
        def ensure(self, *, issue_number, branch):
            return tmp_path / f"wt-{issue_number}"

        def commit_and_push(self, *, worktree, branch, message):
            pass

        def changed_spec_group(self, *, worktree, base):
            # issue #53：implement 转正前实跑 e2e 需先定位本分支 spec 组；本用例只验放行链路，
            # 返回 None 让脚本定位降级为 skipped（不起子进程）。
            return None

    state = State(path=tmp_path / ".openagents" / "state.json")
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="u/pull/5"),
        status=STATUS_RFC_REVIEW,
    )
    state.increment_rounds(issue_number=3)  # 预置一回合，验证 implement 会清零
    orch = Orchestrator(backend=_StubBackend(), state=state, work_dir=tmp_path, agent_id=agent_id)
    orch._workspace = _StubWorkspace()
    msgs = Messages(orchestrator=orch, state=state, agent_id=agent_id)

    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "has_label", lambda *, pr_number, name: False)
    added = []
    monkeypatch.setattr(
        messages_module.github, "add_label", lambda *, pr_number, name: added.append(name)
    )
    monkeypatch.setattr("openagents.orchestrator.github.mark_ready", lambda *, pr_number: None)
    # RFC-0013：implement 旁路实跑 e2e 后发签名评论；本用例只验放行链路，桩掉评论发送避免真打 gh。
    monkeypatch.setattr(
        "openagents.orchestrator.identity.post_signed_comment",
        lambda *, pr_number, body, agent_id: None,
    )

    events = msgs.poll()

    assert any(e["reason"] == "rfc-pass" for e in events)
    assert APPROVAL_LABEL in added
    run = state.all_runs()[0]
    assert run.status == STATUS_PR_OPEN
    assert run.rounds == 0  # implement 清零


# --------------------------------------------------------------------------- #
# issue #47：_block 先打标签后落盘——add_label 失败不留下「state=blocked 但无标签」
# --------------------------------------------------------------------------- #


def test_block_label_failure_leaves_status_unblocked(monkeypatch):
    monkeypatch.setattr(messages_module, "MAX_ROUNDS", 2)
    msgs, orch, state = _make(
        runs=[_run(issue_number=3, pr_number=5, status=STATUS_ITERATING, rounds=1)],
        code_decision=_FAIL,
    )
    _patch_github(monkeypatch)

    def _boom(*, pr_number, name):
        raise messages_module.github.GithubError("gh 瞬时失败 / 标签缺失")

    monkeypatch.setattr(messages_module.github, "add_label", _boom)

    # Spec-0022/T2：poll 现对单 record 做错误隔离——add_label 失败不再冒泡掀翻整轮，而是被
    # 收成一条 error 事件。issue #47 的核心不变量仍成立：_block 先标签后落盘，标签失败时
    # state 尚未变 blocked → 下一轮仍当 open 重试整个 _block。
    events = msgs.poll()

    assert any(e["reason"] == "error" and e["pr_number"] == 5 for e in events)
    # 关键：异常被隔离时 state 仍未变 blocked（先标签后落盘）——下一轮 poll 仍当 open 重试整个 _block。
    assert {"issue_number": 3, "status": STATUS_BLOCKED} not in state.status_updates
    assert state.all_runs()[0].status == STATUS_ITERATING


# --------------------------------------------------------------------------- #
# issue #49：blocked 可恢复——merged/closed reconcile + 人摘 needs-human 标签后解挂
# --------------------------------------------------------------------------- #


def _patch_github_labels(monkeypatch, *, merged=False, closed=False, labels=()):
    """name 感知的 github 桩：labels 为 PR 当前所带标签集合（供解挂分支区分 needs-human / rfc-approved）。"""
    rec = {"closed_issues": [], "labels": []}
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: merged)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: closed)
    monkeypatch.setattr(
        messages_module.github, "has_label", lambda *, pr_number, name: name in labels
    )
    # Spec-0032/T5：blocked 解挂主路径先读「block 之后的新人类评论」；这些用例专测「人手动摘标签」
    # 兜底路径，故桩为无新评论，使解挂走既有 label 分支（零回归）。
    monkeypatch.setattr(
        messages_module.identity, "new_human_comments", lambda *, pr_number, since: []
    )
    monkeypatch.setattr(
        messages_module.github,
        "close_issue",
        lambda *, number: rec["closed_issues"].append(number),
    )
    monkeypatch.setattr(
        messages_module.github,
        "add_label",
        lambda *, pr_number, name: rec["labels"].append((pr_number, name)),
    )
    # 拉式同步重构后合并分支不再主动扇出，无需再桩合并后同步入口。
    return rec


def test_blocked_pr_merged_reconciled_to_done(monkeypatch):
    msgs, orch, state = _make(runs=[_run(issue_number=4, pr_number=44, status=STATUS_BLOCKED)])
    rec = _patch_github_labels(monkeypatch, merged=True)

    events = msgs.poll()

    assert state.all_runs()[0].status == STATUS_DONE
    assert rec["closed_issues"] == [4]
    assert any(e["reason"] == "merged" for e in events)


def test_blocked_label_cleared_resumes_to_coding(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=4, pr_number=44, status=STATUS_BLOCKED, rounds=3)]
    )
    # needs-human 已摘、rfc-approved 仍在 → 回到代码闸（pr-open），rounds 清零。
    _patch_github_labels(monkeypatch, labels=(APPROVAL_LABEL,))

    events = msgs.poll()

    run = state.all_runs()[0]
    assert run.status == STATUS_PR_OPEN
    assert run.rounds == 0
    assert any(e["reason"] == "resumed" for e in events)


def test_blocked_label_cleared_resumes_to_rfc_review(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=4, pr_number=44, status=STATUS_BLOCKED, rounds=3)]
    )
    # needs-human 与 rfc-approved 都不在 → 回到 RFC 闸。
    _patch_github_labels(monkeypatch, labels=())

    events = msgs.poll()

    assert state.all_runs()[0].status == STATUS_RFC_REVIEW
    assert any(e["reason"] == "resumed" for e in events)


def test_blocked_label_present_stays_blocked(monkeypatch):
    msgs, orch, state = _make(
        runs=[_run(issue_number=4, pr_number=44, status=STATUS_BLOCKED, rounds=3)]
    )
    # needs-human 仍在 → 保持挂起：不动状态、不产生事件。
    _patch_github_labels(monkeypatch, labels=(BLOCKED_LABEL,))

    events = msgs.poll()

    run = state.all_runs()[0]
    assert run.status == STATUS_BLOCKED
    assert run.rounds == 3
    assert events == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
