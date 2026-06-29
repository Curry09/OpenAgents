#!/usr/bin/env bash
# Spec-0031 端到端测试启动脚本：merge 闸 armed 解挂语义的 hermetic 闭环演练。
#
# 本组重设计 merge 闸（PR 与 base 真冲突）的「解挂」语义：人摘掉 needs-human 标签后不即时
# 重挂，而是进入 armed（武装）模式派 agent 有界重试解冲突（新 knob OPENAGENTS_MAX_MERGE_ATTEMPTS，
# 默认 3），用尽仍冲突才重新挂起。首次发现冲突保持现状（试一次、解不了即挂起，留人工兜底）。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh**：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 state 的 block_gate /
#      merge_attempts 计数（test_state_merge_unblock）与 messages 的 armed 解挂/有界重试接线
#      （test_messages_merge_unblock）的单测。
#   2) 离线闭环演练（默认执行）—— 用真实落盘的 State + fake github.has_label/mergeability +
#      fake resolve 驱动一个真实 Messages.poll，按时间顺序演练整条状态轨迹：
#      首次发现冲突→挂起（block_gate=merge）→人解挂 arm（保留标记、回 pr-open）→armed 有界
#      重试（merge-retry，不重挂）→用尽重挂；并单独演练 armed 一次解决即清 armed。
#
# 用法：
#   bash scripts/e2e-spec-0031-merge-unblock-agent-resolve.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闭环演练：merge 闸 armed 解挂整条状态轨迹（fake github / fake resolve）"
uv run --extra dev python - <<'PY'
# Spec-0031/T3：hermetic 演练——不触网、不调真实 LLM、不碰真实 gh。
# 用真实落盘 State + 直接替换 messages 模块里的 github/identity/conflict 函数（非 pytest，
# 故直接赋值而非 monkeypatch；进程退出即销毁，无副作用）。
import tempfile
from pathlib import Path

from openagents import messages as messages_module
from openagents.messages import Messages
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_PR_OPEN,
    State,
)
from openagents.github import PR

ISSUE = 3
PR_NUMBER = 5

# --- 可变控制旋钮：用闭包共享的 holder 控制 fake 的返回值，模拟时间推进 ---------- #
state_box = {"labels": {BLOCKED_LABEL}, "resolve_ok": False}


def fake_is_merged(*, pr_number):
    return False


def fake_is_closed(*, pr_number):
    return False


def fake_has_label(*, pr_number, name):
    return name in state_box["labels"]


def fake_add_label(*, pr_number, name):
    state_box["labels"].add(name)


def fake_mergeability(*, pr_number):
    class _MS:
        merge_state_status = "DIRTY"
        mergeable = "CONFLICTING"

    return _MS()


comments = []


def fake_post_signed_comment(*, pr_number, body, agent_id):
    comments.append({"pr_number": pr_number, "body": body})


def fake_make_resolver(*, work_dir, base, backend, agent_id):
    # 返回一个据 state_box["resolve_ok"] 决定成败的 resolver（不触真实 git / LLM）。
    return lambda *, pr_number: state_box["resolve_ok"]


# 替换 messages 模块里的外部依赖（hermetic）。
messages_module.github.is_merged = fake_is_merged
messages_module.github.is_closed = fake_is_closed
messages_module.github.has_label = fake_has_label
messages_module.github.add_label = fake_add_label
messages_module.github.mergeability = fake_mergeability
messages_module.identity.post_signed_comment = fake_post_signed_comment
messages_module.conflict.make_resolver = fake_make_resolver
# 把上限钉死为 3，演练「未达上限重试 / 达上限重挂」边界。
messages_module.MAX_MERGE_ATTEMPTS = 3


class _DummyBackend:
    name = "dummy"

    def run(self, *, work_dir, task, context):  # pragma: no cover - resolve 已被替换
        raise AssertionError("resolve 已被 fake 替换，不应真起 backend")


def _poll(msgs):
    events = msgs.poll()
    assert len(events) == 1, f"每轮恰一个事件，实得 {events}"
    return events[0]["reason"]


with tempfile.TemporaryDirectory() as tmp:
    state = State(path=Path(tmp) / ".openagents" / "state.json")
    state.record_run(
        issue_number=ISSUE,
        branch=f"openagents/issue-{ISSUE}",
        pr=PR(number=PR_NUMBER, url=f"u/pull/{PR_NUMBER}"),
        status=STATUS_PR_OPEN,
    )
    msgs = Messages(
        orchestrator=object(),  # 冲突预检在 reviewer 之前短路，永不触达 orchestrator
        state=state,
        agent_id="agent-self",
        work_dir="/repo",
        base="main",
        backend=_DummyBackend(),
    )

    def record():
        return state.find_by_issue(issue_number=ISSUE)

    # 1) 首次发现冲突，resolve 失败 → 挂起：留言 + blocked + block_gate=merge。
    state_box["resolve_ok"] = False
    assert _poll(msgs) == "unmergeable"
    assert record().status == STATUS_BLOCKED
    assert record().block_gate == "merge"
    assert len(comments) == 1
    assert BLOCKED_LABEL in state_box["labels"]
    print("  ✓ 步骤 1：首次发现冲突解不了 → 留言 + 挂起（block_gate=merge），保留人工兜底")

    # 2) 下一轮 poll 仍带 needs-human → 软挂起，状态不动（零回归）。
    assert msgs.poll() == []
    assert record().status == STATUS_BLOCKED
    print("  ✓ 步骤 2：needs-human 仍在 → 软挂起，poll 跳过（不重试、不空转）")

    # 3) 人摘掉 needs-human → 解挂并 arm：回 pr-open、保留 block_gate=merge、merge_attempts 清零。
    state_box["labels"].discard(BLOCKED_LABEL)
    assert _poll(msgs) == "resumed"
    assert record().status == STATUS_PR_OPEN
    assert record().block_gate == "merge"  # armed 标记保留
    assert record().merge_attempts == 0
    print("  ✓ 步骤 3：人摘 needs-human → arm（回 pr-open、保留 merge 标记、给满预算），不即时重挂")

    # 4) armed 有界重试：resolve 仍失败 → merge-retry，保持 pr-open、不重挂、不留言；计数累加。
    comments.clear()
    state_box["resolve_ok"] = False
    assert _poll(msgs) == "merge-retry"
    assert record().status == STATUS_PR_OPEN and record().merge_attempts == 1
    assert _poll(msgs) == "merge-retry"
    assert record().status == STATUS_PR_OPEN and record().merge_attempts == 2
    assert comments == []  # 未挂起不留言
    print("  ✓ 步骤 4：armed 解不了 → 跨轮 merge-retry（保持 pr-open、不重挂、不留言），有界累加")

    # 5) 第 3 次（达 MAX_MERGE_ATTEMPTS=3）仍失败 → 重新挂起：留言 + blocked + block_gate=merge。
    assert _poll(msgs) == "unmergeable"
    assert record().status == STATUS_BLOCKED
    assert record().block_gate == "merge"  # 再次置 merge，下次人解挂可再 arm
    assert record().merge_attempts == 3
    assert len(comments) == 1
    print("  ✓ 步骤 5：armed 用尽上限（3 次）→ 重新挂起等人（可再解挂再 arm，闭环）")

    # 6) 演练 armed 一次解决即清 armed：人再解挂 → arm，下一轮 resolve 成功 → resolved + 清标记。
    state_box["labels"].discard(BLOCKED_LABEL)
    assert _poll(msgs) == "resumed"  # 再 arm
    state_box["resolve_ok"] = True
    comments.clear()
    assert _poll(msgs) == "resolved"
    assert record().block_gate == ""  # armed 清除
    assert record().merge_attempts == 0  # 预算重置
    assert record().status == STATUS_PR_OPEN
    assert comments == []  # 解决了不留言
    print("  ✓ 步骤 6：armed 一次解决 → resolved + 清 armed（block_gate=''、预算归零），自然推进")

print()
print("✓ Spec-0031 hermetic 演练通过：merge 闸 armed 解挂整条状态轨迹，全程不触网/无 LLM/无 gh。")
PY

echo
echo "✓ Spec-0031 端到端脚本完成（离线确定性 + 闭环演练两段全过）。"
