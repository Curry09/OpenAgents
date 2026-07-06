#!/usr/bin/env bash
# Spec-0054/T5 端到端测试启动脚本：vigil --skip spec 逐闸旁路——「skip spec → 直接进实现」。
#
# 演示 issue #135 的核心时间线：draft PR 承载 spec 时,以 `--skip spec` 把 spec 评审闸当 PASS
# 直接放行——不调 reviewer、直接打 rfc-approved label 并转入实现(coding);再演示对同一道 spec
# 闸同时 `--hold spec --skip spec`(既停下等人又放行跳过)会被 reconcile_hold_skip 当场报错。
#
# 两段(与 e2e-spec-0020-hold-gate.sh 同构):
#   1) 离线确定性验证(默认执行)—— ruff lint/format + pytest 全套,全程 mock,不触达真实
#      gh/claude(覆盖 skip 解析 / 矛盾检测 / 五道闸短路 / CLI 接线的单测)。
#   2) 离线闸控时间线演示(默认执行)—— 用打桩 orchestrator/state + 内存 label 集合模拟
#      GitHub,离线驱动 Messages.poll(skip=spec) 断言「spec 闸被当 PASS 直接进实现」,并演示
#      --hold spec --skip spec 报错。无需任何凭证、CI 可跑、可重复。
#
# 形态说明:CLI / 离线形态(无 browser MCP,纯内部控制流、无前端)。skip 是自主环内部的闸门
# 旁路旋钮,验收点在「闸控时间线的分流对不对」而非任何可视化成果,故取离线确定性验证。
#
# 用法：
#   bash scripts/e2e-spec-0054-vigil-skip-gate.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证(lint + format + 单元测试)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闸控时间线演示：vigil --skip spec 直接放行 spec 闸 → 进实现;--hold spec --skip spec 报错"
uv run python - <<'PY'
# Spec-0054/T5：离线驱动 Messages.poll(skip=spec),断言 spec 闸被当 PASS 直接进实现。
from openagents import messages as messages_module
from openagents.hold import parse_hold
from openagents.messages import APPROVAL_LABEL, Messages
from openagents.skip import parse_skip, reconcile_hold_skip
from openagents.state import STATUS_RFC_REVIEW, RunRecord


class FakeOrchestrator:
    """记录 implement / review_rfc 调用；skip spec 下 review_rfc 不该被调到。"""

    def __init__(self):
        self.implement_calls = []
        self.review_rfc_calls = []

    def implement(self, *, pr_number):
        self.implement_calls.append(pr_number)
        return "impl-summary"  # Spec-0051/T4：implement 返回本轮实现摘要(None→str)

    def review_rfc(self, *, pr_number):  # skip spec 下不该被调到
        self.review_rfc_calls.append(pr_number)
        raise AssertionError("skip spec 下不应触发自动 reviewer")


class FakeState:
    """内存维护单个 run,记录状态更新。"""

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


# 内存 label 集合模拟 GitHub PR 标签;skip spec 命中时代码会往里加 rfc-approved。
pr_labels = set()
messages_module.github.is_merged = lambda *, pr_number: False
messages_module.github.is_closed = lambda *, pr_number: False
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels
messages_module.github.add_label = lambda *, pr_number, name: pr_labels.add(name)

record = RunRecord(
    issue_number=135,
    branch="openagents/issue-135",
    pr_number=5,
    pr_url="https://example/pull/5",
    status=STATUS_RFC_REVIEW,
    summary="",
)
orch = FakeOrchestrator()
state = FakeState(runs=[record])
msgs = Messages(orchestrator=orch, state=state, agent_id="agent-e2e")
# 收口贴回执是尽力而为的真实 IO(发 PR 评论),与本闸门断言无关 → 打成 no-op。
msgs._post_agent_report = lambda *, pr_number, body: None
skip = parse_skip(raw="spec")

# --- skip spec：spec 闸被当 PASS → 不评审、直接打 rfc-approved label 并进实现 ---
events = msgs.poll(skip=skip)
assert orch.review_rfc_calls == [], "skip spec 不应自动评审"
assert APPROVAL_LABEL in pr_labels, "skip spec 应直接打 rfc-approved label"
assert orch.implement_calls == [5], "skip spec 应直接进实现(implement)"
assert any(e["reason"] == "skip-spec" for e in events), "应产出 skip-spec 事件"
print("  [放行] --skip spec → 未评审、直接打 rfc-approved label、直接 implement 进 coding")

# --- 矛盾演示：--hold spec --skip spec 对同一 spec 闸矛盾 → reconcile_hold_skip 报错 ---
try:
    reconcile_hold_skip(hold=parse_hold(raw="spec"), skip=parse_skip(raw="spec"))
    raise SystemExit("✗ 预期 --hold spec --skip spec 矛盾报错,但未报错")
except ValueError as exc:
    assert "spec" in str(exc)
    print(f"  [矛盾] --hold spec --skip spec → 当场报错(不静默):{exc}")

print("✓ 闸控时间线断言全部通过：skip spec 直接进实现 + hold/skip 同闸矛盾报错。")
PY

echo
echo "✓ Spec-0054/T5 端到端演示完成(离线、可重复)。"
