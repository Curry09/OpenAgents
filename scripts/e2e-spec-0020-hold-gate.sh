#!/usr/bin/env bash
# Spec-0020/T5 端到端测试启动脚本：vigil --hold spec 分级监督闸——「停在 spec → 人批 → 继续」。
#
# 演示 issue #59 的核心时间线：流水线写完 spec 后以 `--hold spec` 停在 spec 闸等人；模拟
# 人工给 PR 打上 rfc-approved label 后，下一轮 poll 流水线就继续进入 coding（implement）。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，全程 mock，不触达真实
#      gh/claude（覆盖 align / hold / 两道闸分流 / CLI 接线的单测）。
#   2) 离线闸控时间线演示（默认执行）—— 用打桩 orchestrator/state + 内存 label 集合模拟
#      GitHub，离线驱动 Messages.poll(hold=spec) 两轮，断言「停 → 批 → 继续」并打印轨迹。
#      无需任何凭证、CI 可跑、可重复。
#
# 软依赖（Spec-0020/T3 待解问题）：真实场景里人批 spec 看的是 OVERVIEW 的人类可读 summary
# （issue #58 / Spec-0014 体系提供）；本脚本聚焦闸控时间线，不实现 summary——#58 未就绪时
# hold spec 仍能停/放行，只是人的阅读体验降级。merge 闸（--hold merge）分流由 T3 单测覆盖，
# 本脚本聚焦 issue 验收点名的 spec 闸时间线。
#
# 用法：
#   bash scripts/e2e-spec-0020-hold-gate.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闸控时间线演示：vigil --hold spec 停在 spec → 人批 rfc-approved → 继续 coding"
uv run python - <<'PY'
# Spec-0020/T5：离线驱动 Messages.poll(hold=spec) 两轮，断言 spec 闸的「停 → 批 → 继续」。
from openagents import messages as messages_module
from openagents.hold import parse_hold
from openagents.messages import APPROVAL_LABEL, Messages
from openagents.state import STATUS_RFC_REVIEW, RunRecord


class FakeOrchestrator:
    """记录 implement / review_rfc 调用，不真实调起后端。"""

    def __init__(self):
        self.implement_calls = []
        self.review_rfc_calls = []

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)

    def review_rfc(self, *, pr_number):  # spec 闸 hold 下不该被调到
        self.review_rfc_calls.append(pr_number)
        raise AssertionError("hold spec 下不应触发自动 reviewer")


class FakeState:
    """内存维护单个 run，记录状态更新。"""

    def __init__(self, *, runs):
        self._runs = list(runs)
        self.status_updates = []

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        self.status_updates.append(status)
        for record in self._runs:
            if record.issue_number == issue_number:
                record.status = status

    def increment_rounds(self, *, issue_number):
        return 0

    def reset_rounds(self, *, issue_number):
        pass


# 内存 label 集合模拟 GitHub PR 标签；人工打 rfc-approved 即往集合里加。
pr_labels = set()
messages_module.github.is_merged = lambda *, pr_number: False
messages_module.github.is_closed = lambda *, pr_number: False
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels

record = RunRecord(
    issue_number=59,
    branch="openagents/issue-59",
    pr_number=5,
    pr_url="https://example/pull/5",
    status=STATUS_RFC_REVIEW,
    summary="",
)
orch = FakeOrchestrator()
state = FakeState(runs=[record])
msgs = Messages(orchestrator=orch, state=state, agent_id="agent-e2e")
hold = parse_hold(raw="spec")

# --- 第 1 轮：spec 写完、无 rfc-approved label、--hold spec → 停在 spec 闸 ---
events = msgs.poll(hold=hold)
assert orch.review_rfc_calls == [], "停在 spec 闸不应自动评审"
assert orch.implement_calls == [], "停在 spec 闸不应 implement"
assert record.status == STATUS_RFC_REVIEW, "状态应仍停在 rfc-review"
assert any(e["reason"] == "hold-spec" for e in events), "应产出 hold-spec 事件"
print("  [停] 第 1 轮：--hold spec → 未自动评审、未打 label、未 implement，停在 spec 闸等人批")

# --- 人批：模拟人工给 PR 打上 rfc-approved label ---
pr_labels.add(APPROVAL_LABEL)
print(f"  [批] 人工给 PR #5 打上 {APPROVAL_LABEL} label（真实场景下人对照 OVERVIEW summary 点头，#58）")

# --- 第 2 轮：带人工 label → 继续进入 coding（implement）---
events = msgs.poll(hold=hold)
assert orch.implement_calls == [5], "带人工 rfc-approved label 应继续 implement 进 coding"
assert any(e["reason"] == "approved" for e in events), "应产出 approved 事件"
print("  [继续] 第 2 轮：检出人工 rfc-approved label → implement 进 coding")

print("✓ 闸控时间线断言全部通过：停在 spec → 人批 → 继续。")
PY

echo
echo "✓ Spec-0020/T5 端到端演示完成（离线、可重复）。"
