#!/usr/bin/env bash
# Spec-0051 端到端测试启动脚本：统一 agent 执行后回贴 PR 评论（可观测性收口）。
#
# 本组把「派 agent 执行→执行完在 PR 回贴一条署名说明评论」从各方法零散自接、收口到编排层
# （messages）统一：给 executor/evidence_gate/编排步骤各配 render_* 纯函数，在
# _process_rfc_review / _process_coding / _evidence_gate 三个收口点统一「执行完→render_*→
# _post_agent_report（identity.post_signed_comment，带防刷屏去重）」，补齐 implement /
# iterate(ci·review·e2e) / finalize_runbook / run_executor / review_evidence 五处静默步骤。
# 收口后 executor/evidence_gate 保持不 import identity、不碰 IO（理念 10），发评论有唯一出口。
#
# **浏览器 e2e 不适用**：本 feature 的「成果」是 GitHub PR 上的机器评论流（可观测性），本仓库无任何
# 产品前端界面可驱动（无导航/交互/截图可断言的视觉成果），且真发评论需真 GitHub。故成果测试形态为
# **确定性集成复现**（pytest 驱动整条链 + 本 shell 跑它并打印证据），而非浏览器 e2e。全程**不触网、
# 不调真实 gh/LLM/git 远端**。
#
# 用法：
#   bash scripts/e2e-spec-0051-unify-agent-run-report.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] 静态检查（ruff lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] 定向单元/集成测试（Spec-0051 T1–T6）"
uv run --extra dev pytest -q \
  tests/test_executor.py \
  tests/test_evidence_gate.py \
  tests/test_worknote.py \
  tests/test_orchestrator.py \
  tests/test_messages.py \
  tests/test_messages_agent_report.py \
  tests/test_agent_report_integration.py

echo
echo "==> [3/4] 成果证据：用**真实** Messages 收口 + render_* 驱动整条回执链，打印三条断言证据"
uv run python - <<'PY'
# Spec-0051 成果演练：用**真实**产品代码——messages.Messages（含 _post_agent_report/_report_already_posted
# 去重 + 五处收口接线）+ executor.render_result / evidence_gate.render_decision / worknote.render_* 真渲染函数
# ——把「派 agent 执行完→回贴一条署名说明评论」跑出来，打印证据。脚本只提供内存版 GitHub 评论账本 +
# 假 orchestrator（返回可编排 summary/handle）+ 假裁决；回执渲染/去重/收口全部来自产品代码。
from pathlib import Path

from openagents import identity
from openagents import messages as messages_module
from openagents.evidence_gate import EvidenceDecision
from openagents.executor import ExecutorResult
from openagents.github import CheckStatus, Comment, Mergeability
from openagents.messages import Messages
from openagents.orchestrator import RunbookHandle
from openagents.reviewer import ReviewDecision
from openagents.state import (
    STATUS_BLOCKED,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
)

AGENT_ID = "agent-self"


class Ledger:
    """内存假 GitHub 评论账本：post_signed_comment 记盖真签名的 body + 递增 created_at；list_comments 回读。"""

    def __init__(self):
        self.comments = []
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
        out = []
        for c in self.comments:
            for line in c.body.splitlines():
                if line.strip().startswith("## "):
                    out.append(line.strip())
                    break
        return out


class FakeOrch:
    def __init__(self, *, code_decision, handle):
        self._code_decision = code_decision
        self._handle = handle
        self.iterate_calls = []

    def implement(self, *, pr_number):
        return "实现了 issue 的核心逻辑"

    def review_code(self, *, pr_number):
        return self._code_decision

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append(reason)
        return f"据 {reason} 反馈改了代码"

    def finalize_runbook(self, *, pr_number):
        return self._handle

    def commit_evidence(self, *, pr_number):
        pass


class FakeState:
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
        pass

    def set_unblock_detail(self, *, issue_number, detail):
        pass


HANDLE = RunbookHandle(
    worktree=Path("/wt"),
    runbook_path=Path("/wt/docs/e2e-results/5/runbook.md"),
    evidence_dir=Path("/wt/docs/e2e-results/5"),
    intent="意图：x\n验收行为：\n- a",
    form="cli",
)


def run_record(*, status):
    return RunRecord(
        issue_number=3, branch="openagents/issue-3", pr_number=5, pr_url="u/pull/5",
        status=status, summary="", rounds=0,
    )


class Cfg:
    has_approval = True
    ci_state = "success"


def wire(ledger, cfg, *, evidence_decision):
    """把 messages 依赖指向内存账本/假裁决（monkeypatch 等价的手工 setattr，脚本内自恢复无所谓）。"""
    g = messages_module.github
    g.is_merged = lambda *, pr_number: False
    g.is_closed = lambda *, pr_number: False
    g.has_label = lambda *, pr_number, name: cfg.has_approval and name.endswith("approved")
    g.add_label = lambda *, pr_number, name: None
    g.remove_label = lambda *, pr_number, name: None
    g.merge_pr = lambda *, pr_number: None
    g.close_issue = lambda *, number: None
    g.update_branch = lambda *, pr_number: None
    g.mergeability = lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN")
    g.check_status = lambda *, pr_number: CheckStatus(state=cfg.ci_state, failed_logs=["FAIL test_x"])
    g.list_comments = ledger.list_comments
    messages_module.identity.post_signed_comment = ledger.post_signed_comment
    messages_module.identity.new_human_comments = lambda *, pr_number, since: []
    messages_module.executor.run_executor = (
        lambda *, backend, work_dir, runbook_path, evidence_dir, pr_number: ExecutorResult(
            outcome="passed", form="cli", notes="真跑 init，退出码 0"
        )
    )
    messages_module.evidence_gate.review_evidence = (
        lambda *, backend, work_dir, intent, evidence_dir, pr_number: evidence_decision
    )


# --- 证据① 五处收口各留一条署名回执 ---------------------------------------- #
ledger = Ledger()
cfg = Cfg()
orch = FakeOrch(code_decision=ReviewDecision(passed=True, feedback=""), handle=HANDLE)
rec = run_record(status=STATUS_RFC_REVIEW)
state = FakeState(runs=[rec])
wire(ledger, cfg, evidence_decision=EvidenceDecision(passed=False, feedback="验收行为①未达成"))
msgs = Messages(orchestrator=orch, state=state, agent_id=AGENT_ID, backend=object())

cfg.has_approval = True
msgs.poll()                       # rfc-approved → implement
rec.status = STATUS_PR_OPEN
cfg.has_approval = False
cfg.ci_state = "fail"
msgs.poll()                       # CI fail → iterate(ci)
rec.status = STATUS_ITERATING
cfg.ci_state = "success"
orch._code_decision = ReviewDecision(passed=False, feedback="补单测", actionable=True)
msgs.poll()                       # reviewer REWORK → iterate(review)
orch._code_decision = ReviewDecision(passed=True, feedback="")
msgs.poll()                       # reviewer PASS → 证据闸 FAIL → iterate(e2e)

expected = [
    "## 实现自述",
    "## 迭代自述（CI 反馈）",
    "## 迭代自述（代码评审反馈）",
    "## 说明书定稿",
    "## 证据执行",
    "## 证据闸判决",
    "## 迭代自述（证据闸反馈）",
]
headers = ledger.headers()
counts = {h: headers.count(h) for h in expected}
all_signed = all(identity.parse_agent_id(body=c.body) == AGENT_ID for c in ledger.comments)
print("  证据①【五处收口各一条署名回执】：七类回执各恰一条且全带签名 =",
      all(v == 1 for v in counts.values()) and all_signed)
for h in expected:
    print(f"      {h}：{counts[h]} 条")
assert all(v == 1 for v in counts.values()), f"某类回执数量异常：{counts}"
assert all_signed, "存在未署名回执"

# --- 证据② 重复 poll 同内容不刷屏 ------------------------------------------ #
ledger2 = Ledger()
cfg2 = Cfg()
cfg2.has_approval = False
orch2 = FakeOrch(code_decision=ReviewDecision(passed=True, feedback=""), handle=HANDLE)
rec2 = run_record(status=STATUS_PR_OPEN)
state2 = FakeState(runs=[rec2])
wire(ledger2, cfg2, evidence_decision=EvidenceDecision(passed=False, feedback="同一条反馈"))
msgs2 = Messages(orchestrator=orch2, state=state2, agent_id=AGENT_ID, backend=object())
msgs2.poll()
rec2.status = STATUS_ITERATING
msgs2.poll()                      # 连续两轮证据闸、内容不变
h2 = ledger2.headers()
dedup_ok = (
    h2.count("## 说明书定稿") == 1
    and h2.count("## 证据执行") == 1
    and h2.count("## 证据闸判决") == 1
    and h2.count("## 迭代自述（证据闸反馈）") == 1
)
print("  证据②【重复 poll 不刷屏】：两轮同内容证据闸后每类回执仍恰一条（_report_already_posted 命中）=",
      dedup_ok)
assert dedup_ok, f"去重失效：{h2}"

# --- 证据③ 发评论故障不阻断编排 -------------------------------------------- #
ledger3 = Ledger()
ledger3.raise_on_post = True
cfg3 = Cfg()
cfg3.has_approval = False
cfg3.ci_state = "fail"
orch3 = FakeOrch(code_decision=ReviewDecision(passed=True, feedback=""), handle=HANDLE)
rec3 = run_record(status=STATUS_PR_OPEN)
state3 = FakeState(runs=[rec3])
wire(ledger3, cfg3, evidence_decision=EvidenceDecision(passed=True, feedback=""))
msgs3 = Messages(orchestrator=orch3, state=state3, agent_id=AGENT_ID, backend=object())
events = msgs3.poll()             # 回执发送全抛错，编排应照常推进
not_blocked = (
    orch3.iterate_calls == ["ci"]
    and events == [{"pr_number": 5, "reason": "ci"}]
    and ledger3.comments == []
)
print("  证据③【发评论故障不阻断】：post 全抛错时 iterate 仍被调、poll 返回 ci 事件、账本为空 =",
      not_blocked)
assert not_blocked, "发评论故障阻断了编排"

print("  ✓ 三条断言全部通过")
PY

echo
echo "==> [4/4] spec 校验（Spec-0051 组结构 + OVERVIEW/ARCHITECTURE 无漂移）"
uv run spec validate --specs-root docs/specs
# 幂等（无漂移）自检：render/graph 前先存副本，重渲后 diff 应逐字节一致——不依赖 git 提交状态。
cp docs/specs/OVERVIEW.md /tmp/oa-0051-overview.bak
cp docs/specs/ARCHITECTURE.md /tmp/oa-0051-arch.bak
uv run spec render --specs-root docs/specs
uv run spec graph --specs-root docs/specs
diff /tmp/oa-0051-overview.bak docs/specs/OVERVIEW.md
diff /tmp/oa-0051-arch.bak docs/specs/ARCHITECTURE.md
uv run spec graph --specs-root docs/specs --check

echo
echo "✅ Spec-0051 端到端验证通过：五处收口各一条署名回执 + 重复 poll 不刷屏 + 发评论故障不阻断（可复现证据见上）。"
