#!/usr/bin/env bash
# Spec-0036/T6 端到端测试启动脚本：解挂后 agent 读取并正面回应人的评论——
# 「所有闸解挂都把人类评论喂给 agent（含此前丢弃内容的 merge 闸）+ 编排层确定性贴回引用原评论的回应」。
#
# 两段（均离线、确定性、可重复、不触网、不调真实 LLM/gh）：
#   1) 离线确定性验证 —— ruff lint/format + pytest 全套（覆盖 state/replynote/conflict/orchestrator/
#      messages 各 Task 的单测，全程 mock）。
#   2) 离线闭环时间线演示 —— 用 fake github + fake identity + fake orchestrator + fake resolve +
#      fake state，离线驱动 Messages.poll，断言两条轨迹：
#        ① rfc/code 闸解挂 → 引用原评论贴回 agent 回应；
#        ② merge 闸解挂 → 评论作 guidance 喂解冲突器 → armed 跑完引用原评论贴回结论。
#
# 用法：
#   bash scripts/e2e-spec-0036-unblock-comment-read-and-reply.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闭环时间线演示：三闸解挂喂内容 + 引用原评论贴回回应"
uv run python - <<'PY'
# Spec-0036/T6：离线驱动 Messages.poll，演示「读评论 + 正面回应」整条轨迹（rfc/code 同步回应、
# merge 闸喂 guidance + armed 跑完回应）。全程 fake，不触网、不调真实 LLM/gh。
from openagents import messages as messages_module
from openagents.github import Comment
from openagents.messages import Messages
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_PR_OPEN,
    RunRecord,
)

AGENT_ID = "agent-e2e"


class FakeOrchestrator:
    """refine_rfc(announce)/iterate 回传 agent 本轮动作 summary（供 messages 组回应）。"""

    def __init__(self):
        self.refine_calls = []
        self.iterate_calls = []

    def refine_rfc(self, *, pr_number, detail, announce=True):
        self.refine_calls.append({"pr_number": pr_number, "detail": detail, "announce": announce})
        return "已据你的意见补全 spec 的权衡章节"

    def iterate(self, *, pr_number, reason, detail):
        self.iterate_calls.append({"pr_number": pr_number, "reason": reason, "detail": detail})
        return "已按你的指导补了空输入单测，并处理了 None 分支"


class FakeState:
    """内存版 State：维护单个 run，记录解挂/armed 路径会动到的字段。"""

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

    def set_unblock_detail(self, *, issue_number, detail):
        self._find(issue_number).unblock_detail = detail

    def reset_rounds(self, *, issue_number):
        record = self._find(issue_number)
        record.rounds = 0
        record.review_invalid = 0
        record.merge_attempts = 0

    def increment_merge_attempts(self, *, issue_number):
        record = self._find(issue_number)
        record.merge_attempts += 1
        return record.merge_attempts


class FakeBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):  # resolve 已被替换，不应真起 backend
        raise AssertionError("resolve 已被 fake，不应真起 backend")


# --- 内存 GitHub 世界：PR 标签集合 + 评论列表（人/机用签名区分）------------------- #
pr_labels = {BLOCKED_LABEL}
pr_comments = []  # list[Comment]

messages_module.github.is_merged = lambda *, pr_number: False
messages_module.github.is_closed = lambda *, pr_number: False
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels
messages_module.github.add_label = lambda *, pr_number, name: pr_labels.add(name)
messages_module.github.list_comments = lambda *, pr_number: list(pr_comments)


def _remove_label(*, pr_number, name):
    pr_labels.discard(name)


messages_module.github.remove_label = _remove_label


def _post_signed_comment(*, pr_number, body, agent_id):
    stamp = f"2026-06-30T2{len(pr_comments)}:00:00Z"
    signed = messages_module.identity.sign(body=body, agent_id=agent_id)
    pr_comments.append(Comment(id=f"m{len(pr_comments)}", author="openagents", body=signed, created_at=stamp))


messages_module.identity.post_signed_comment = _post_signed_comment
# new_human_comments 用真实实现（读 list_comments + 按签名/水位线过滤）——正是解挂读侧。


def _add_human_comment(body, *, stamp):
    pr_comments.append(Comment(id=f"h{len(pr_comments)}", author="alice", body=body, created_at=stamp))


def _signed_count():
    return sum(1 for c in pr_comments if messages_module.identity.parse_agent_id(body=c.body))


# ======================================================================= #
# 轨迹 ①：code 闸解挂 → 引用原评论贴回 agent 回应（同步回应）
# ======================================================================= #
print("--- 轨迹 ① code 闸解挂：读评论 + 引用原评论贴回 agent 回应 ---")
record_code = RunRecord(
    issue_number=89,
    branch="openagents/issue-89",
    pr_number=7,
    pr_url="https://example/pull/7",
    status=STATUS_BLOCKED,
    summary="",
    rounds=3,
    block_gate="code",
    block_watermark="2026-06-30T00:00:00Z",
)
orch = FakeOrchestrator()
msgs = Messages(orchestrator=orch, state=FakeState(runs=[record_code]), agent_id=AGENT_ID)

_add_human_comment("先补空输入的单测，再处理 None 分支", stamp="2026-06-30T10:00:00Z")
print("  [人回评论] alice：『先补空输入的单测，再处理 None 分支』")

events = msgs.poll()
assert events == [{"pr_number": 7, "reason": "resumed"}], events
assert orch.iterate_calls == [
    {"pr_number": 7, "reason": "human", "detail": "先补空输入的单测，再处理 None 分支"}
], orch.iterate_calls
reply = pr_comments[-1].body
assert "> 先补空输入的单测，再处理 None 分支" in reply, "回应应引用原评论"
assert "已按你的指导补了空输入单测" in reply, "回应应含 agent summary"
assert messages_module.identity.parse_agent_id(body=reply) == AGENT_ID, "回应应带签名"
assert BLOCKED_LABEL not in pr_labels, "解挂应摘 needs-human"
print("  [解挂+回应] iterate(reason=human, detail=评论) → 引用原评论 + agent summary 的签名回应（恰一条）")

# 防自激：带签名的回应在下一轮解挂读侧被滤掉，不会被当成新人类评论自触发。
fresh = messages_module.identity.new_human_comments(pr_number=7, since="2026-06-30T10:00:00Z")
assert fresh == [], f"agent 自己的签名回应不应被读回，实际 {fresh}"
print("  [防自激] 回应带签名 → 下一轮 new_human_comments 滤除，agent 读不到自己（不自触发）")

# ======================================================================= #
# 轨迹 ②：merge 闸解挂 → 评论作 guidance 喂解冲突器 → armed 跑完引用原评论贴回结论
# ======================================================================= #
print()
print("--- 轨迹 ② merge 闸解挂：评论作 guidance 喂解冲突器 → armed 跑完引用原评论贴回结论 ---")
pr_labels = {BLOCKED_LABEL}
pr_comments.clear()
messages_module.github.has_label = lambda *, pr_number, name: name in pr_labels

record_merge = RunRecord(
    issue_number=84,
    branch="openagents/issue-84",
    pr_number=10,
    pr_url="https://example/pull/10",
    status=STATUS_BLOCKED,
    summary="",
    rounds=3,
    block_gate="merge",
    block_watermark="2026-06-30T00:00:00Z",
)
orch2 = FakeOrchestrator()
state2 = FakeState(runs=[record_merge])
msgs2 = Messages(
    orchestrator=orch2,
    state=state2,
    agent_id=AGENT_ID,
    work_dir="/repo",
    base="main",
    backend=FakeBackend(),
)

# fake 解冲突世界：mergeability 报冲突、诊断器返回静态文案、resolve 记录收到的 guidance。
seen = {"guidance": None}


class _MS:
    merge_state_status = "DIRTY"
    mergeable = "CONFLICTING"


messages_module.github.mergeability = lambda *, pr_number: _MS()
messages_module.conflictdiag.make_diagnoser = (
    lambda *, work_dir, base: lambda *, pr_number: messages_module.rebase.CONFLICT_COMMENT
)


def _make_resolver(*, work_dir, base, backend, agent_id):
    def _resolve(*, pr_number, guidance=""):
        seen["guidance"] = guidance
        return True  # 本轮成功解冲突

    return _resolve


messages_module.conflict.make_resolver = _make_resolver

# 第 1 步：人在 merge 冲突挂起的 PR 下回评论 → 解挂当轮存 detail、不回应、进 armed。
_add_human_comment("先把 OVERVIEW.md 的冲突按保留两边处理，再 rebase state.py", stamp="2026-06-30T10:00:00Z")
print("  [人回评论] alice：『先把 OVERVIEW.md 的冲突按保留两边处理，再 rebase state.py』")

events = msgs2.poll()
assert events == [{"pr_number": 10, "reason": "resumed"}], events
assert record_merge.status == STATUS_PR_OPEN, "merge 解挂应恢复 pr-open 进 armed"
assert record_merge.block_gate == "merge", "armed 标记应保留"
assert record_merge.unblock_detail == "先把 OVERVIEW.md 的冲突按保留两边处理，再 rebase state.py", "应存评论作 guidance"
assert _signed_count() == 0, "merge 解挂当轮不回应（动作尚未发生）"
print("  [解挂当轮] 存 unblock_detail 作 guidance、恢复 pr-open 进 armed、**不回应**（下一轮 armed 才动手）")

# 第 2 步：下一轮 poll → armed 解冲突，评论作 guidance 喂 resolve，跑完引用原评论贴回结论 + 清 detail。
events = msgs2.poll()
assert events == [{"pr_number": 10, "reason": "resolved"}], events
assert seen["guidance"] == "先把 OVERVIEW.md 的冲突按保留两边处理，再 rebase state.py", "评论应作 guidance 喂解冲突器"
reply2 = pr_comments[-1].body
assert "> 先把 OVERVIEW.md 的冲突按保留两边处理，再 rebase state.py" in reply2, "结论回应应引用原评论"
assert messages_module._RESOLVE_REPLY_SUCCESS in reply2, "结论回应应含成功文案"
assert messages_module.identity.parse_agent_id(body=reply2) == AGENT_ID, "结论回应应带签名"
assert record_merge.unblock_detail == "", "armed 跑完应清空 unblock_detail"
print("  [armed 跑完] resolve(guidance=评论) 成功 → 引用原评论 + 成功结论的签名回应（恰一条）+ 清 unblock_detail")

print()
print("✓ 两条轨迹断言全部通过：所有闸解挂都喂内容给 agent + 编排层确定性贴回引用原评论的回应。")
PY

echo
echo "✓ Spec-0036/T6 端到端演示完成（离线、可重复、不触网、不调真实 LLM/gh）。"
