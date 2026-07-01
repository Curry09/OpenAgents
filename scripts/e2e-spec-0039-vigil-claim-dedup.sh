#!/usr/bin/env bash
# Spec-0039/T4 端到端成果测试启动脚本：vigil 多后端并发派单去重——「已派发」认领标签
# 把「两后端同时抢同一新 issue」从『各建分支/各开 PR 撞车』压到『恰一个后端派单』，
# 并用标签事件时戳做过期回收兜底僵尸认领。
#
# 两段（均离线、确定性、可重复、不触网、不调真实 gh/LLM）：
#   1) 离线确定性验证 —— ruff lint/format + pytest 全套（覆盖 T1 github 认领原语 /
#      T2 vigil 第 3 道闸+回收 / T3 orchestrator 打标清理 / T4 两后端竞态集成，全程 mock）。
#   2) 离线竞态成果演示 —— 用内存版 GitHub 世界 + 两份独立 State 复现「A 先领、B 起草窗口内
#      到达即跳过」，断言：恰一个分支/一次派单、认领标签生命周期、B 跳过、A/B 两块看板成果
#      （A 有 issue#N 行、B 无）+ 过期回收子用例。看板断言走 results.render 的 HTML 文本断言
#      （成果呈现层的降级路径——无浏览器 MCP 环境时不跳过成果验证，见 Spec-0039 Reference-level）。
#
# 用法：
#   bash scripts/e2e-spec-0039-vigil-claim-dedup.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线竞态成果演示：A 先领 → B 起草窗口内到达即跳过 → 恰一个派单 + 看板成果 + 过期回收"
uv run python - <<'PY'
# Spec-0039/T4：直接复用集成测试里的内存世界与竞态骨架，离线驱动一次两后端竞态并打印成果轨迹。
from pathlib import Path
from unittest.mock import patch

from openagents import github, results
from openagents.github import DISPATCH_LABEL
from openagents.state import State
from openagents.vigil import CLAIM_EXPIRY_SECONDS, Vigil
from tests.test_claim_dedup_integration import (
    FakeGitHubWorld,
    RaceOrchestrator,
    RecordingOrchestrator,
)

ISSUE = 42
world = FakeGitHubWorld(issues=[(ISSUE, "并发去重", "body")])


def _in_memory(state):
    store = {"runs": [], "cursors": {}}
    state._load = lambda: store
    state._save = lambda *, data: store.update(data)
    return state


state_a = _in_memory(State(path=Path("/tmp/oa-e2e-0039-a")))
state_b = _in_memory(State(path=Path("/tmp/oa-e2e-0039-b")))


def _vigil(*, orchestrator, state):
    return Vigil(orchestrator=orchestrator, messages=object(), state=state, work_dir=Path("/repo"))


with (
    patch.object(github, "list_issues", world.list_issues),
    patch.object(github, "issue_stamp_label", world.issue_stamp_label),
    patch.object(github, "issue_remove_label", world.issue_remove_label),
    patch.object(github, "issue_add_label", world.issue_add_label),
    patch.object(github, "issue_label_age_seconds", world.issue_label_age_seconds),
    patch.object(Vigil, "_remote_branch_exists", lambda self, *, branch: world.branch_exists(branch=branch)),
):
    b_seen = {}

    def b_runs_during_a_drafting():
        # A 已认领、尚未推分支：B 扫描发现段应读到认领标签 → 跳过。
        labels_now = set(world.issue_labels.get(ISSUE, set()))
        b_disp = _vigil(orchestrator=RecordingOrchestrator(), state=state_b).discover_and_dispatch(
            labels=["openagents"], base="main"
        )
        b_seen["labels"] = labels_now
        b_seen["dispatched"] = b_disp

    orch_a = RaceOrchestrator(world=world, state=state_a, on_draft=b_runs_during_a_drafting)
    a_disp = _vigil(orchestrator=orch_a, state=state_a).discover_and_dispatch(
        labels=["openagents"], base="main"
    )

    assert a_disp == [ISSUE], f"A 应恰派单 issue#{ISSUE}，实际 {a_disp}"
    print(f"  [A 派单] A 判 fresh、认领 issue#{ISSUE} 并起草 → 派单 {a_disp}")
    assert DISPATCH_LABEL in b_seen["labels"], "B 到达时 issue 应带认领标签"
    assert b_seen["dispatched"] == [], f"B 应据认领标签跳过，实际 {b_seen['dispatched']}"
    print(f"  [B 跳过] B 在起草窗口内到达，读到 {DISPATCH_LABEL} 标签 → 跳过（不重复派单）")

    assert world.branches == {f"openagents/issue-{ISSUE}"}, f"应恰一个分支，实际 {world.branches}"
    assert DISPATCH_LABEL not in world.issue_labels.get(ISSUE, set()), "PR 开出后认领标签应已摘"
    print(f"  [去重成果] 远端恰一个 openagents/issue-{ISSUE} 分支；PR 开出后认领标签已摘")

    # 看板成果（理念 8）：A 看板有 issue#N 行，B 看板无。
    board_a = results.render(runs=state_a.all_runs())
    board_b = results.render(runs=state_b.all_runs())
    assert f"#{ISSUE}" in board_a, "A 看板应有 issue#N 行"
    assert f"#{ISSUE}" not in board_b and "暂无成果记录" in board_b, "B 看板应无 issue#N 行"
    print("  [看板成果] A 看板有 issue#N 行、B 看板『暂无成果记录』（一个 issue 只被一个后端领取，直观成立）")

    # 过期回收子用例：僵尸认领超 T 判 fresh、未超 T 跳过。
    world2 = FakeGitHubWorld(issues=[(43, "僵尸认领", "body")])
    state_c = _in_memory(State(path=Path("/tmp/oa-e2e-0039-c")))
    with (
        patch.object(github, "list_issues", world2.list_issues),
        patch.object(github, "issue_label_age_seconds", world2.issue_label_age_seconds),
        patch.object(Vigil, "_remote_branch_exists", lambda self, *, branch: world2.branch_exists(branch=branch)),
        patch.object(github, "issue_stamp_label", world2.issue_stamp_label),
        patch.object(github, "issue_add_label", world2.issue_add_label),
        patch.object(github, "issue_remove_label", world2.issue_remove_label),
    ):
        world2.clock = 0
        github.issue_stamp_label(number=43, name=DISPATCH_LABEL)  # 僵尸认领占坑，不建分支
        world2.clock = CLAIM_EXPIRY_SECONDS - 1
        d_fresh = _vigil(orchestrator=RecordingOrchestrator(), state=state_c).discover_and_dispatch(
            labels=["openagents"], base="main"
        )
        assert d_fresh == [], "未超 T：应跳过（别人可能仍在慢起草）"
        world2.clock = CLAIM_EXPIRY_SECONDS + 1
        d_recover = _vigil(orchestrator=RecordingOrchestrator(), state=state_c).discover_and_dispatch(
            labels=["openagents"], base="main"
        )
        assert d_recover == [43], "超 T：应判僵尸认领并回收（视同 fresh 派单）"
    print("  [过期回收] 认领龄未超 T 跳过、超 T 判僵尸认领并回收派单")

print("✓ Spec-0039/T4 竞态成果断言全部通过：两后端抢同一 issue → 恰一个派单 + 看板成果 + 过期回收兜底。")
PY

echo
echo "✓ Spec-0039/T4 端到端演示完成（离线、可重复、不触网、不调真实 gh/LLM）。"
