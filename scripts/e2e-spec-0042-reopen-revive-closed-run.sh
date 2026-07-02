#!/usr/bin/env bash
# Spec-0042/T4 端到端测试启动脚本：PR close→reopen 后复活被冻死的 run——closed 不是真终态。
#
# 本组给本地 closed 的 run 补上「重开复活」：poll 发现某 closed run 对应 PR 在 GitHub 上又变回
# OPEN（reopened）时，按现状复活它（draft→rfc-review / 转正→pr-open）、清 closed_at 续跑既有流程；
# 用 closed_at 复活窗口（默认 7 天）把「每轮对所有历史 closed run 发 gh 查 reopen」的成本上界住，
# 超窗口即硬化成真终态。is_merged 仍是不可逆终态、不参与复活。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端**（阶段 3 除外，需显式开启）：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 T1 closed_at 字段/setter
#      （test_state_closed_at）、T2 is_open/is_draft 封装（test_github_is_open_draft）、T3 复活窗口
#      守卫 + reopen 复活 reconcile（test_messages_reopen_revive）、T4 集成（test_reopen_revive_integration）。
#   2) 离线成果演练（默认执行）—— 用真实 State + 内存 GitHub 世界驱动 Messages.poll 四轮时间线，
#      断言「close→置 closed 打戳 → 仍 closed 跳过不重打戳不复活 → reopen 复活 pr-open → 正常处理」，
#      并渲染各轮 board.html 做「该 PR 行状态随时间线正确翻转（closed→pr-open）」的 HTML 文本断言
#      （成果可视化，理念 8；无浏览器 MCP 时的降级路径，不跳过成果验证）。
#   3) 真实冒烟（可选，OPENAGENTS_E2E_REAL=1）—— 提示如何在 scratch 仓库真实 close 再 reopen 一个 PR、
#      跑 vigil，验证被冻死的 run 被复活回 pr-open/rfc-review。
#
# 用法：
#   bash scripts/e2e-spec-0042-reopen-revive-closed-run.sh
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0042-reopen-revive-closed-run.sh   # 追加真实冒烟提示
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线成果演练：close→打戳 → 仍 closed 不复活 → reopen 复活 pr-open → 正常处理；看板随时间线翻转"
uv run python - <<'PY'
# Spec-0042/T4：真实 State + 内存 GitHub 世界，离线驱动 Messages.poll 四轮，演示复活闭环 + 看板翻转。
import tempfile
from pathlib import Path

from openagents import messages as messages_module
from openagents import results
from openagents.github import PR, CheckStatus, Mergeability
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import STATUS_CLOSED, STATUS_DONE, STATUS_PR_OPEN, State

AGENT_ID = "agent-e2e-0042"
ISSUE, PR_NUM = 108, 105

# 内存 GitHub 世界：可变 PR state / draft。
world = {"pr_state": "OPEN", "draft": False, "merge_pr_calls": [], "closed_issues": []}

g = messages_module.github
g.is_merged = lambda *, pr_number: world["pr_state"] == "MERGED"
g.is_closed = lambda *, pr_number: world["pr_state"] == "CLOSED"
g.is_open = lambda *, pr_number: world["pr_state"] == "OPEN"
g.is_draft = lambda *, pr_number: world["draft"]
g.mergeability = lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN")
g.check_status = lambda *, pr_number: CheckStatus(state="pass", failed_logs=[])
g.merge_pr = lambda *, pr_number: world["merge_pr_calls"].append(pr_number)
g.close_issue = lambda *, number: world["closed_issues"].append(number)


class Orch:
    def __init__(self):
        self.review_code_calls = 0

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return ReviewDecision(passed=True, feedback="", verdicts=("PASS",))


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


def board_row():
    html = results.render(runs=state.all_runs())
    rows = [ln for ln in html.splitlines() if f"#{PR_NUM}" in ln and "<tr>" in ln]
    assert len(rows) == 1
    return rows[0]


# --- 第一轮：人 close 了 PR → 置 closed + 打 closed_at 戳 ---------------------------- #
world["pr_state"] = "CLOSED"
assert msgs.poll() == [{"pr_number": PR_NUM, "reason": "closed"}]
rec = state.find_by_issue(issue_number=ISSUE)
assert rec.status == STATUS_CLOSED and rec.closed_at
stamp = rec.closed_at
row_closed = board_row()
assert '<span class="status">closed</span>' in row_closed
print("  [close] 首轮 poll：置 closed + 打 closed_at 时间戳（复活窗口起点）；看板行=closed")

# --- 第二轮：PR 仍 closed → 被扫描但不复活、不重打戳 -------------------------------- #
assert msgs.poll() == []
rec2 = state.find_by_issue(issue_number=ISSUE)
assert rec2.status == STATUS_CLOSED and rec2.closed_at == stamp, "不得重打戳（窗口不刷新）"
assert board_row() == row_closed, "看板该行跨轮稳定"
print("  [仍closed] 次轮 poll：被扫描但 is_open=False→return None、不复活、closed_at 不刷新（成本有界）")

# --- 第三轮：人 reopen 了 PR（转正）→ 复活到 pr-open、清 closed_at ------------------- #
world["pr_state"] = "OPEN"
world["draft"] = False
assert msgs.poll() == [{"pr_number": PR_NUM, "reason": "reopened", "stage": STATUS_PR_OPEN}]
rec3 = state.find_by_issue(issue_number=ISSUE)
assert rec3.status == STATUS_PR_OPEN and rec3.closed_at == ""
assert orch.review_code_calls == 0, "复活当轮只做状态归位、不续跑闸"
row_reopened = board_row()
assert '<span class="status">pr-open</span>' in row_reopened and row_reopened != row_closed
print("  [reopen] 第三轮 poll：复活到 pr-open + 清 closed_at + 返回 reopened；看板行 closed→pr-open 翻转")

# --- 第四轮：复活后的 pr-open run 走既有代码闸，正常处理到底（PASS→merge→done）-------- #
assert msgs.poll() == [{"pr_number": PR_NUM, "reason": "merged"}]
assert orch.review_code_calls == 1 and world["merge_pr_calls"] == [PR_NUM]
assert world["closed_issues"] == [ISSUE]
assert state.find_by_issue(issue_number=ISSUE).status == STATUS_DONE
print("  [正常处理] 第四轮 poll：复活后的 run 走既有代码闸 → PASS → merge → done（复活即回归既有流程）")

print("  [看板成果] board.html 该 PR 行状态随时间线正确翻转：closed → pr-open（理念 8）")
print("             注：真实浏览器截图成果（Playwright/chrome-devtools MCP）由 agent 在脚本外驱动；")
print("             无浏览器 MCP 时按 T4 spec 降级为此 HTML 文本断言，不跳过成果验证。")

print("✓ Spec-0042 复活闭环断言全部通过：closed 不是真终态 → reopen 复活 → 回归既有流程（全程离线、可重复）。")
PY

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [可选] 真实冒烟（OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  真实冒烟步骤（需要真实 GitHub 仓库 + gh 登录，会真实开/关/重开 PR）：
    1) 在 scratch 仓库真实开一个 PR、跑一轮 vigil 让本地 run 进入 pr-open/rfc-review。
    2) 在 GitHub 上 close 这个 PR（不合并）→ 跑一轮 vigil：`oa vigil --once`
       预期：本地 run 被置 closed（看板行=closed）。
    3) 在 GitHub 上 reopen 这个 PR → 再跑一轮 vigil：`oa vigil --once`
       预期：被冻死的 run 被复活回 pr-open（转正）或 rfc-review（draft），closed_at 清空，看板行翻回。
    4) 再跑一轮：复活后的 run 按既有阶段路由继续推进（评论 / CI / 冲突重新被处理，不再空转）。
  （此段仅打印指引，不自动执行，避免在 CI/离线环境误触真实 gh。）
REAL
fi

echo
echo "✓ Spec-0042/T4 端到端演示完成（默认离线、可重复、不触网、不调真实 LLM/gh）。"
