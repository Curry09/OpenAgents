#!/usr/bin/env bash
# Spec-0041/T4 端到端测试启动脚本：hold-merge PASS 后「夯住待合并」——已通过的 PR 冻结成
# needs-human，消除同码复审震荡。
#
# 本组把 hold-merge 分支从「空操作、下轮重审」改成「夯住」：reviewer PASS 且 --hold merge 时置
# blocked + needs-human + 贴「✅ 已通过评审，待你合并」成功文案 + gate=merge-hold；blocked 不在
# _OPEN_STATUSES → 下一轮 poll 自动跳过、不再重审，从根上消除同一 commit 被非确定 reviewer 反复
# PASS/REWORK 的复审震荡。附带净化挂起评论里泄漏的 reviewer scratchpad。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端**（阶段 2 除外，需显式开启）：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 T2 成功文案
#      （test_blocknote_hold_merge）、T3 scratchpad 净化（test_reviewer_feedback_distill）、T1 夯住 +
#      merge-hold 路由（test_messages_hold_merge_freeze）、T4 集成（test_hold_merge_freeze_integration）。
#   2) 离线成果演练（默认执行）—— 用真实 State + 内存 GitHub 世界驱动 Messages.poll 两轮，断言
#      「首轮冻结 → 次轮不重审」，并渲染两份 board.html 做「冻结后跨轮稳定」的 HTML 文本比对
#      （成果可视化，理念 8；无浏览器 MCP 时的降级路径，不跳过成果验证）。
#   3) 真实冒烟（可选，OPENAGENTS_E2E_REAL=1）—— 提示如何在 scratch 仓库真实开一个可合并 PR、带
#      --hold merge 跑 vigil，验证 PR 被打 needs-human + 成功文案评论、连跑两轮无重复评审评论堆积。
#
# 用法：
#   bash scripts/e2e-spec-0041-hold-merge-freeze.sh
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0041-hold-merge-freeze.sh   # 追加真实冒烟提示
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线成果演练：首轮冻结 → 次轮不重审 → 看板『冻结后稳定』HTML 文本比对"
uv run python - <<'PY'
# Spec-0041/T4：真实 State + 内存 GitHub 世界，离线驱动 Messages.poll，演示反震荡 + 看板稳定。
import tempfile
from pathlib import Path

from openagents import blocknote
from openagents import messages as messages_module
from openagents import results
from openagents.github import CheckStatus, Comment, Mergeability, PR
from openagents.hold import Hold
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import BLOCKED_LABEL, STATUS_BLOCKED, STATUS_PR_OPEN, State

AGENT_ID = "agent-e2e-0041"
ISSUE, PR_NUM = 106, 5
labels, comments = set(), []


class Orch:
    def __init__(self):
        self.review_code_calls = 0

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return ReviewDecision(passed=True, feedback="", verdicts=("PASS",))

    def iterate(self, *, pr_number, reason, detail):  # 本演练不触发
        raise AssertionError("冻结/挂起路径不应 iterate")


g = messages_module.github
g.is_merged = lambda *, pr_number: False
g.is_closed = lambda *, pr_number: False
g.mergeability = lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN")
g.check_status = lambda *, pr_number: CheckStatus(state="pass", failed_logs=[])
g.list_comments = lambda *, pr_number: list(comments)
g.has_label = lambda *, pr_number, name: name in labels
g.add_label = lambda *, pr_number, name: labels.add(name)
g.remove_label = lambda *, pr_number, name: labels.discard(name)


def _post_signed(*, pr_number, body, agent_id):
    stamp = f"2026-07-02T1{len(comments)}:00:00Z"
    signed = messages_module.identity.sign(body=body, agent_id=agent_id)
    comments.append(Comment(id=f"m{len(comments)}", author="bot", body=signed, created_at=stamp))


messages_module.identity.post_signed_comment = _post_signed

tmp = Path(tempfile.mkdtemp())
state = State(path=tmp / "state.json")
state.record_run(
    issue_number=ISSUE,
    branch=f"openagents/issue-{ISSUE}",
    pr=PR(number=PR_NUM, url=f"https://example/pull/{PR_NUM}"),
    status=STATUS_PR_OPEN,
)
orch = Orch()
msgs = Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)
hold = Hold(at_merge=True)


def board_row():
    html = results.render(runs=state.all_runs())
    rows = [ln for ln in html.splitlines() if f"#{PR_NUM}" in ln and "<tr>" in ln]
    assert len(rows) == 1
    return rows[0]


# --- 首轮 poll：夯住 ------------------------------------------------------------- #
events1 = msgs.poll(hold=hold)
assert events1 == [{"pr_number": PR_NUM, "reason": "hold-merge", "gate": "merge-hold"}]
assert orch.review_code_calls == 1
rec = state.find_by_issue(issue_number=ISSUE)
assert rec.status == STATUS_BLOCKED and rec.block_gate == "merge-hold" and rec.block_watermark
assert BLOCKED_LABEL in labels
note = [c for c in comments if c.author == "bot"][0].body
assert blocknote.build_hold_merge_pass() in note and "卡住了" not in note
row1 = board_row()
assert '<span class="status">blocked</span>' in row1
print("  [冻结] 首轮 poll：blocked + needs-human + 成功文案（非失败模板）+ gate=merge-hold；reviewer 审 1 次")

# --- 次轮 poll：不重审 ----------------------------------------------------------- #
events2 = msgs.poll(hold=hold)
assert events2 == [], f"次轮应保持挂起、无事件，实际 {events2}"
assert orch.review_code_calls == 1, "反震荡铁证：reviewer 桩不得再被调"
rec2 = state.find_by_issue(issue_number=ISSUE)
assert rec2.status == STATUS_BLOCKED and rec2.rounds == 0
assert len([c for c in comments if c.author == "bot"]) == 1, "次轮不得再贴评论"
row2 = board_row()
assert row2 == row1, "看板该 PR 行应跨轮完全一致（冻结后稳定，无震荡）"
print("  [不重审] 次轮 poll：reviewer 桩调用次数仍为 1、状态仍 blocked、无新评论、rounds 不增")
print("  [看板成果] 两轮渲染的 board.html 该 PR 行状态=blocked 且逐字节一致 → 冻结后跨轮稳定（理念 8）")
print("             注：真实浏览器截图成果（Playwright/chrome-devtools MCP）由 agent 在脚本外驱动；")
print("             无浏览器 MCP 时按 T4 spec 降级为此 HTML 文本比对，不跳过成果验证。")

print("✓ Spec-0041 反震荡闭环断言全部通过：PASS 后夯住 → 不再重审 → 看板稳定（全程离线、可重复）。")
PY

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [可选] 真实冒烟（OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  真实冒烟步骤（需要真实 GitHub 仓库 + gh 登录，会真实开 PR）：
    1) 在 scratch 仓库真实开一个可合并的 PR（CI 绿、rfc-approved）。
    2) 带 --hold merge 跑一轮 vigil：`oa vigil --hold merge --once`
       预期：PR 被打上 needs-human 标签、收到一条「✅ 已通过评审，待你合并」评论（非「🤖 卡住了」）。
    3) 再连跑一轮：`oa vigil --hold merge --once`
       预期：无新增评审评论、状态稳定（反震荡）——PR 未被重新评审、评论未堆积。
    4) 在 GitHub 上手动合并 → 下一轮 vigil 的 is_merged 分支 reconcile 成 done + 关 issue。
  （此段仅打印指引，不自动执行，避免在 CI/离线环境误触真实 gh。）
REAL
fi

echo
echo "✓ Spec-0041/T4 端到端演示完成（默认离线、可重复、不触网、不调真实 LLM/gh）。"
