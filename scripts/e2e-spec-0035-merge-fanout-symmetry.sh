#!/usr/bin/env bash
# Spec-0035 端到端测试启动脚本：合并扇出两调用点能力对称的 hermetic 闭环演练。
#
# 守夜人 messages.poll 有两个 rebase.rebase_open_prs 扇出调用点（都把刚进 main 的改动并入其余 open PR）：
#   ① reconcile（下一轮 poll 发现 is_merged）路径——历史上已注入 heal/resolve/diagnose 三层；
#   ② reviewer-PASS 框架自动合并（同轮立即扇出）路径——历史上只注入 diagnose，漏了 heal/resolve。
# 本组给第二处补回 heal=self._make_heal() + resolve=self._make_resolver()，让两处逐字节能力对称，并加
# 回归测试锁定。本脚本演练「两条扇出路径都注入 heal/resolve/diagnose」的对称。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端**：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖
#      test_messages_merge_fanout_symmetry（两调用点对称回归）等单测。
#   2) 离线闭环演练（默认执行）—— 用捕获式 rebase.rebase_open_prs + 齐备 work_dir/base/backend 夹具，
#      用 fake github 分别驱动真实 messages.poll 走 reconcile（is_merged）与 reviewer-PASS 自动合并两条
#      扇出路径，捕获两次调用 kwargs，断言两处 heal/resolve/diagnose 均为非 None callable 且逐键一致。
#
# 用法：
#   bash scripts/e2e-spec-0035-merge-fanout-symmetry.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闭环演练：两条扇出路径能力对称整条轨迹（fake github / 捕获式 rebase_open_prs）"
uv run --extra dev python - <<'PY'
# Spec-0035/T2：hermetic 演练——不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端。
# 直接替换 messages 模块里的 github / 三个能力工厂 / rebase.rebase_open_prs（非 pytest，故直接赋值；
# 进程退出即销毁，无副作用）。驱动真实 messages.poll 走两条扇出路径，捕获注入的 kwargs。
from openagents import messages as m
from openagents.messages import Messages
from openagents.reviewer import ReviewDecision
from openagents.state import STATUS_DONE, STATUS_PR_OPEN, RunRecord

AGENT_ID = "agent-self"

# 三个能力工厂的哨兵 callable——隔离工厂内部，只验 messages 的注入接线（扇出确实拿到这一层）。
HEAL = lambda *, pr_number: True  # noqa: E731
RESOLVE = lambda *, pr_number: True  # noqa: E731
DIAGNOSE = lambda *, pr_number: "diag"  # noqa: E731


class FakeBackend:  # 非 None 占位：放行 _make_resolver 的 backend 门控。
    pass


class FakeOrchestrator:
    def review_code(self, *, pr_number):
        return ReviewDecision(passed=True, feedback="", verdicts=(), actionable=False)


class FakeState:
    def __init__(self, *, runs):
        self._runs = list(runs)

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        for r in self._runs:
            if r.issue_number == issue_number:
                r.status = status


def run(*, pr_number):
    return RunRecord(
        issue_number=3,
        branch="openagents/issue-3",
        pr_number=pr_number,
        pr_url=f"u/pull/{pr_number}",
        status=STATUS_PR_OPEN,
        summary="",
        rounds=0,
        review_invalid=0,
    )


def make_messages(*, runs):
    # work_dir + base + backend 三者齐备：三个工厂门控全部放行，扇出本应注入 heal/resolve/diagnose 三层。
    return Messages(
        orchestrator=FakeOrchestrator(),
        state=FakeState(runs=runs),
        agent_id=AGENT_ID,
        work_dir="/repo",
        base="main",
        backend=FakeBackend(),
    )


# --- 把三个能力工厂换成返回哨兵 callable，并把 rebase_open_prs 换成捕获器（hermetic）-------------- #
m.indexheal.make_healer = lambda *, work_dir, base: HEAL
m.conflict.make_resolver = lambda *, work_dir, base, backend, agent_id: RESOLVE
m.conflictdiag.make_diagnoser = lambda *, work_dir, base: DIAGNOSE

captured = []


def capture(*, merged_pr_number=None, agent_id=None, heal=None, resolve=None, diagnose=None):
    captured.append({"heal": heal, "resolve": resolve, "diagnose": diagnose})
    return []


m.rebase.rebase_open_prs = capture
m.github.close_issue = lambda *, number: None


def assert_all_three(call, *, where):
    for layer in ("heal", "resolve", "diagnose"):
        assert call[layer] is not None, f"{where} 扇出漏注入 {layer}（应与另一调用点对称）"
        assert callable(call[layer]), f"{where} 的 {layer} 应为 callable"


# --- 轨迹 A：reconcile（is_merged）扇出 ------------------------------------------------------ #
m.github.is_merged = lambda *, pr_number: True
events = make_messages(runs=[run(pr_number=5)]).poll()
assert any(e["reason"] == "merged" for e in events), events
assert len(captured) == 1, captured
assert_all_three(captured[0], where="reconcile")
print("  ✓ 轨迹 A：reconcile（is_merged）扇出注入了 heal/resolve/diagnose 三层")

# --- 轨迹 B：reviewer-PASS 框架自动合并扇出（本组补回 heal/resolve 的那一处）------------------- #
m.github.is_merged = lambda *, pr_number: False
m.github.is_closed = lambda *, pr_number: False


class MS:
    merge_state_status = "CLEAN"
    mergeable = "MERGEABLE"


class CS:
    state = "pass"
    failed_logs = []


m.github.mergeability = lambda *, pr_number: MS()
m.github.check_status = lambda *, pr_number: CS()
m.github.merge_pr = lambda *, pr_number: None

msgs_b = make_messages(runs=[run(pr_number=7)])
events = msgs_b.poll()
assert any(e["reason"] == "merged" for e in events), events
assert msgs_b._state.all_runs()[0].status == STATUS_DONE
assert len(captured) == 2, captured
assert_all_three(captured[1], where="auto-merge")
print("  ✓ 轨迹 B：reviewer-PASS 框架自动合并扇出同样注入了 heal/resolve/diagnose 三层")

# --- 对称断言：两处注入的能力集逐键一致 ----------------------------------------------------- #
assert captured[0] == captured[1], (captured[0], captured[1])
print("  ✓ 两调用点逐键对称：reconcile 与 auto-merge 扇出注入的 heal/resolve/diagnose 完全一致")

print()
print("✓ Spec-0035 hermetic 演练通过：两条扇出路径能力对称（都注入 heal/resolve/diagnose），")
print("  全程不触网/无 LLM/无 gh/无真实 git 远端。")
PY

echo
echo "✓ Spec-0035 端到端脚本完成（离线确定性 + 闭环演练两段全过）。"
