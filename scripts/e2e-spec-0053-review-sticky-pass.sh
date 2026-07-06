#!/usr/bin/env bash
# Spec-0053/T4 端到端测试启动脚本：代码评审闸 sticky 短路——代码状态未变时复用上轮 PASS、跳过重审。
#
# 本组给守夜人 poll 循环里的**代码评审闸**引入「PR 净改动指纹」短路：reviewer 全票 PASS 时把当轮
# PR 相对 base 的净 diff 指纹（sha256(gh pr diff)）落进 run state；下一轮进 review_code 前先算一次
# 指纹，与上次 PASS 的指纹一致就直接复用上轮 PASS、跳过重审，不一致才照常重审并更新指纹。这止住了
# 「base 前进（BEHIND → update_branch 拉 main → CI 重跑 → 下一轮 CI 绿）→ 又白跑一遍 N 个 reviewer」
# 的同码空转重审。设计对照 k8s Tide sticky approve / lgtm store_tree_hash（代码没变就别重签）。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端**：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 T1 state 指纹字段/setter
#      （test_state_code_fingerprint）、T2 github 指纹取值（test_github_code_fingerprint）、
#      T3 messages 3c 短路接线（test_messages_review_sticky）。
#   2) 离线成果演练（默认执行）—— 用真实 State + 内存 GitHub 世界驱动 _process_coding 连跑三轮：
#      两轮同码断言 reviewer 只被调一次（第二轮走 sticky）、翻转指纹第三轮断言 reviewer 再被调一次
#      （指纹变 → 重审）。即以「reviewer 调用次数」这一可观测成果验证短路语义（理念 8）。
#
# 测试边界（显式声明，evidence 分层）：本脚本用 stub 的 code_fingerprint 喂「同指纹 / 翻转指纹」，
# 验证的是**编排层短路语义**（同码复用 PASS、变码重审），不去实跑一次真 update_branch 来观察「merge
# main 进 head 后 gh pr diff 果真不变」——那要一个活的 GitHub 服务端 PR 状态（本仓 e2e 无 live GitHub
# lane），而「base...head 三点 diff 在无冲突 merge base 后不变」是 Spec-0053 Reference-level 已由 git
# 三点语义严格推出、并有官方文档背书的前提，不是需要每次 e2e 复验的运行期行为（见 spec Unresolved 3）。
#
# 浏览器 e2e：本 feature 无 product-facing 前端界面（守夜人 poll 循环内部的编排短路，唯一可观测成果
# 是「代码未变时不再起 reviewer 进程」，不经任何 HTTP 前端/看板渲染）。故浏览器 e2e 不适用，成果证据
# 用下面 CLI/pytest 驱动的脚本以「reviewer 调用计数」断言，是此内部行为的正确观测面。
#
# 用法：
#   bash scripts/e2e-spec-0053-review-sticky-pass.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线成果演练：连跑三轮，reviewer 调用次数 1（两轮同码）→ 2（指纹翻转）"
uv run python - <<'PY'
# Spec-0053/T4：真实 State + 内存 GitHub 世界，离线驱动 _process_coding，以「reviewer 调用次数」
# 验证 sticky 短路语义（同码复用 PASS、变码重审）。
import tempfile
from pathlib import Path

from openagents import messages as messages_module
from openagents.github import CheckStatus, Mergeability, PR
from openagents.hold import NONE as NO_HOLD
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import STATUS_PR_OPEN, State

AGENT_ID = "agent-e2e-0053"
ISSUE, PR_NUM = 133, 5

# 可变的 stub 指纹：round 1/2 同码 "fp-A"，round 3 翻转成 "fp-B"（模拟 iterate 改码）。
current_fingerprint = {"value": "fp-A"}


class Orch:
    def __init__(self):
        self.review_code_calls = 0

    def review_code(self, *, pr_number):
        self.review_code_calls += 1
        return ReviewDecision(passed=True, feedback="", verdicts=("PASS",))

    def iterate(self, *, pr_number, reason, detail):  # PASS 路径不触发
        raise AssertionError("PASS 路径不应 iterate")


# 内存 GitHub 世界：可合并、CI 绿、指纹取自 current_fingerprint；merge/close 皆 no-op。
g = messages_module.github
g.mergeability = lambda *, pr_number: Mergeability(mergeable="MERGEABLE", merge_state_status="CLEAN")
g.check_status = lambda *, pr_number: CheckStatus(state="pass", failed_logs=[])
g.code_fingerprint = lambda *, pr_number: current_fingerprint["value"]
g.merge_pr = lambda *, pr_number: None
g.close_issue = lambda *, number: None

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


def run_once():
    # 直接驱动代码评审闸；把 run 复位回 pr-open 以便下一轮再进闸（PASS→merge 会置 done）。
    record = state.find_by_issue(issue_number=ISSUE)
    event = msgs._process_coding(record=record, hold=NO_HOLD)
    state.update_status(issue_number=ISSUE, status=STATUS_PR_OPEN)
    return event


# --- 首轮：无历史指纹 → 照常评审、落盘 "fp-A" ------------------------------------ #
run_once()
assert orch.review_code_calls == 1, f"首轮应评审一次，实际 {orch.review_code_calls}"
assert state.find_by_issue(issue_number=ISSUE).code_passed_fingerprint == "fp-A"
print("  [首轮] 无历史指纹 → 照常评审（reviewer 调用=1）+ 落盘指纹 fp-A")

# --- 次轮：同码 "fp-A" → sticky 命中、reviewer 不被再调 --------------------------- #
run_once()
assert orch.review_code_calls == 1, f"次轮应走 sticky、reviewer 调用次数仍为 1，实际 {orch.review_code_calls}"
print("  [次轮] 指纹未变（fp-A）→ 复用上轮 PASS、跳过重审（reviewer 调用次数仍=1）★sticky 铁证")

# --- 第三轮：翻转指纹 "fp-B" → 重审、落盘新指纹 --------------------------------- #
current_fingerprint["value"] = "fp-B"
run_once()
assert orch.review_code_calls == 2, f"第三轮指纹翻转应重审、reviewer 调用=2，实际 {orch.review_code_calls}"
assert state.find_by_issue(issue_number=ISSUE).code_passed_fingerprint == "fp-B"
print("  [三轮] 指纹翻转（fp-A→fp-B，模拟 iterate 改码）→ 重审（reviewer 调用=2）+ 落盘新指纹 fp-B")

print()
print(f"✓ reviewer 调用次数轨迹：1（两轮同码）→ 2（指纹翻转）")
print("✓ Spec-0053 sticky 短路闭环断言全部通过：同码复用 PASS、变码重审（全程离线、可重复、不触网）。")
PY

echo
echo "✓ Spec-0053/T4 端到端演示完成（默认离线、可重复、不触网、不调真实 LLM/gh）。"
