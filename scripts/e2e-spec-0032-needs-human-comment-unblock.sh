#!/usr/bin/env bash
# Spec-0032/T6 端到端测试启动脚本：needs-human 全程在 GitHub 评论里闭环——
# 「任意闸挂起 → 贴结构化评论 + 记 watermark → 人写新评论 → 下一轮自动摘标签 + 喂 detail + 恢复状态」。
#
# 两段（均离线、确定性、可重复、不触网、不调真实 LLM/gh）：
#   1) 离线确定性验证 —— ruff lint/format + pytest 全套（覆盖 state/github/blocknote/identity/
#      messages 各 Task 的单测，全程 mock）。
#   2) 离线闭环时间线演示 —— 用 fake github（list_comments/has_label/remove_label/add_label）+
#      fake identity（new_human_comments/post_signed_comment）+ fake orchestrator + fake state，
#      离线驱动 Messages.poll 两轮，断言整条解挂轨迹并打印。
#
# 用法：
#   bash scripts/e2e-spec-0032-needs-human-comment-unblock.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闭环时间线演示：挂起留足信息 → 人回评论 → 自动摘标签 + 喂 detail + 恢复流转"
uv run python - <<'PY'
# Spec-0032/T6：离线驱动 Messages.poll，演示「code 闸挂起 → 人回评论 → 自动解挂喂 detail」整条轨迹。
from openagents import blocknote
from openagents import messages as messages_module
from openagents.github import Comment
from openagents.messages import Messages
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    RunRecord,
)


class FakeOrchestrator:
    """记录 iterate / refine_rfc 调用；解挂喂 detail 即在此被观测到。"""

    def __init__(self):
        self.iterate_calls = []
        self.refine_calls = []

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})

    def refine_rfc(self, *, pr_number, detail):
        self.refine_calls.append({"pr_number": pr_number, "detail": detail})


class FakeState:
    """内存版 State：维护单个 run，记录解挂路径会动到的字段。"""

    def __init__(self, *, runs):
        self._runs = list(runs)

    def all_runs(self):
        return list(self._runs)

    def _find(self, issue_number):
        return next(r for r in self._runs if r.issue_number == issue_number)

    def update_status(self, *, issue_number, status):
        self._find(issue_number).status = status

    def set_block_gate(self, *, issue_number, gate):
        self._find(issue_number).block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        self._find(issue_number).block_watermark = watermark

    def reset_rounds(self, *, issue_number):
        record = self._find(issue_number)
        record.rounds = 0
        record.review_invalid = 0
        record.merge_attempts = 0


# --- 内存 GitHub 世界：PR 的标签集合 + 评论列表（人/机用签名区分）---------------- #
AGENT_ID = "agent-e2e"
pr_labels = set()
pr_comments = []  # list[Comment]

messages_module.github.is_merged = lambda *, pr_number: False
messages_module.github.is_closed = lambda *, pr_number: False
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels
messages_module.github.add_label = lambda *, pr_number, name: pr_labels.add(name)
messages_module.github.list_comments = lambda *, pr_number: list(pr_comments)


def _remove_label(*, pr_number, name):
    pr_labels.discard(name)  # 幂等：不在也不报错


messages_module.github.remove_label = _remove_label


def _post_signed_comment(*, pr_number, body, agent_id):
    # 盖签名后入库；created_at 单调递增模拟时序（ISO 8601 字典序即时序）。
    stamp = f"2026-06-29T1{len(pr_comments)}:00:00Z"
    pr_comments.append(
        Comment(id=f"m{len(pr_comments)}", author="openagents", body=blocknote_sign(body), created_at=stamp)
    )


def blocknote_sign(body):
    # 复用真实 identity.sign 给机器评论盖签名（解挂读侧据此把机器评论滤掉）。
    return messages_module.identity.sign(body=body, agent_id=AGENT_ID)


messages_module.identity.post_signed_comment = _post_signed_comment
# new_human_comments 用真实实现（读 list_comments + 按签名/水位线过滤）——正是要演示的读侧。

record = RunRecord(
    issue_number=89,
    branch="openagents/issue-89",
    pr_number=7,
    pr_url="https://example/pull/7",
    status=STATUS_ITERATING,
    summary="",
    rounds=3,
    block_gate="code",
    block_watermark="",
)
orch = FakeOrchestrator()
state = FakeState(runs=[record])
msgs = Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)

# --- 挂起：直接走 _block(gate=code) 模拟代码闸超 K 轮兜底（留足信息 + 记水位线）------ #
msgs._block(record=record, gate="code", blocker="reviewer：补空输入单测；处理 None 分支")
assert BLOCKED_LABEL in pr_labels, "挂起应打 needs-human 标签"
assert record.status == STATUS_BLOCKED
assert len(pr_comments) == 1, "挂起应恰贴一条结构化评论"
note = pr_comments[0].body
for section in ("**原因**", "**我试过**", "**卡在哪**", "**你可以怎么做**"):
    assert section in note, f"结构化评论缺段：{section}"
assert "gate=code" in note
assert record.block_watermark == pr_comments[0].created_at, "水位线应=挂起评论的 createdAt"
print("  [挂起] _block(gate=code)：贴 1 条四段结构化签名评论 + 打 needs-human + 记 watermark")
print(f"         watermark = {record.block_watermark}（含本条挂起评论，故不会自触发解挂）")

# --- 第 1 轮 poll：人还没回评论 + needs-human 仍在 → 保持挂起 --------------------- #
events = msgs.poll()
assert events == [], "无人回评论时应保持挂起、无事件"
assert record.status == STATUS_BLOCKED
print("  [等待] 第 1 轮 poll：无新人类评论 + 标签仍在 → 保持挂起（机器自己的挂起评论被签名滤掉，不自触发）")

# --- 人回一条无签名评论（晚于水位线）----------------------------------------------- #
pr_comments.append(
    Comment(
        id="human-1",
        author="alice",
        body="这里别动 messages，改去 state 加个字段，按这个思路继续",
        created_at="2026-06-29T20:00:00Z",
    )
)
print("  [人回评论] alice 回复：『别动 messages，改去 state 加个字段，按这个思路继续』")

# --- 第 2 轮 poll：检测到新人类评论 → 自动摘标签 + 喂 detail 到 iterate + 恢复流转 --- #
events = msgs.poll()
assert events == [{"pr_number": 7, "reason": "resumed"}], f"应解挂 resumed，实际 {events}"
assert BLOCKED_LABEL not in pr_labels, "解挂应自动摘 needs-human 标签"
assert record.rounds == 0, "解挂应清回合预算"
assert orch.iterate_calls == [
    {"pr_number": 7, "reason": "human", "detail": "这里别动 messages，改去 state 加个字段，按这个思路继续"}
], f"应把人的评论正文当 detail 以 reason=human 喂给 iterate，实际 {orch.iterate_calls}"
assert orch.refine_calls == []
print("  [解挂] 第 2 轮 poll：自动摘 needs-human + reset 预算 + iterate(reason=human, detail=评论正文) + resumed")

print("✓ 闭环轨迹断言全部通过：挂起留足信息 → 人回评论 → 自动解挂喂 detail → 恢复流转（全程在 PR 评论里）。")
PY

echo
echo "✓ Spec-0032/T6 端到端演示完成（离线、可重复、不触网、不调真实 LLM/gh）。"
