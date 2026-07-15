#!/usr/bin/env bash
# Spec-0017 端到端测试启动脚本：PR 生命周期（create/ready/merge）下放 agent —— draft 升为一等事实的
# level-triggered 自愈转正 + 合并动作下放 merger agent + 不可逆合并硬闸兜底。
#
# 证明架构契约在离线确定性链路上成立（intent，见 spec §e2e）：
#   - (1) deliver agent 的完成判据含「PR 非 draft」（转正归它）——契约单测 tests/test_agents_deliver.py；
#   - (2) 稳态 reconcile 把 is_draft 当每 tick 复检的一等维度：一个 delivered 但仍 draft 的 green+approved
#     PR，在**一次认领**里先经 _ACT_READY 转正（github.mark_ready）、再落 merge——draft 自愈分支**严格排在
#     merge 分支之前**（任何 PR 都不在 draft 态被合；merge:human 时人拿到的是已转正、可直接合的 PR——直闭
#     #168 死角）；
#   - (3) 合并动作下放 merger agent，但「全绿 + review-approved:<head sha7>@head」这道不可逆红线由确定性
#     gates.assert_merge_allowed 兜底：闸不放行 → 决不派 merger、决不合并未审代码。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯后端编排 + agent 提示词**，无 product-facing 前端可导航；
# 已自检工具列表：无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，沿用离线确定性测法（假 GitHub +
# 假 agent 的 reconcile 断言 + 契约/硬闸单测 + grep 锚点）。真实自主环冒烟（oa vigil 在真仓上跑通
# issue→PR，观测 deliver 后 PR 直接非 draft、残留 draft 能被下一轮转正）作为成果验收在 Phase-3 人验/runbook
# 记录，不塞进本离线脚本。
#
# 用法：
#   bash scripts/e2e-spec-0017-pr-lifecycle-delegated-to-agent.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/5] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/5] 快照/提示词/硬闸/分支表 针对性契约单测"
uv run --extra dev pytest -q \
  tests/test_utils_github_vigil.py \
  tests/test_agents_deliver.py \
  tests/test_agents_merger.py \
  tests/test_runtime_gates.py \
  tests/test_recipe_stages.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_vigil_act.py

echo
echo "==> [3/5] spec 校验 + 生成物无漂移"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/5] grep 锚点：生命周期直调已下放（_do_solve 无 mark_ready、stages.merge 无裸 merge_pr）"
uv run --extra dev python - <<'PY'
"""源码级锚点：把「一次性确定性直调」是否已下放钉成可执行断言（与单测互为冗余）。"""

import ast
from pathlib import Path


def _func_node(path, name):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} 找不到函数 {name}")


def _calls(node):
    """函数体里所有形如 `mod.attr(...)` 的调用点名（AST，故不会被注释/文档串里的字面量误伤）。"""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            base = sub.func.value
            if isinstance(base, ast.Name):
                names.add(f"{base.id}.{sub.func.attr}")
            else:
                names.add(sub.func.attr)
    return names


solve_calls = _calls(_func_node("openagents/recipes/vigil.py", "_do_solve"))
assert "github.mark_ready" not in solve_calls, "_do_solve 仍确定性直调 github.mark_ready（转正应归 deliver agent）"
print("  ✓ _do_solve 不再直调 github.mark_ready（转正下放 deliver agent）")

merge_calls = _calls(_func_node("openagents/recipes/stages.py", "merge"))
assert "github.merge_pr" not in merge_calls, "stages.merge 仍裸调 github.merge_pr（合并应下放 merger agent）"
assert "gates.assert_merge_allowed" in merge_calls, "stages.merge 未先过 gates.assert_merge_allowed 硬闸"
assert "engine.run_agent" in merge_calls, "stages.merge 未经 engine.run_agent 派 merger agent"
print("  ✓ stages.merge 无裸 github.merge_pr，先过硬闸再派 merger agent")

ready_calls = _calls(_func_node("openagents/recipes/vigil.py", "_do_ready"))
assert "github.mark_ready" in ready_calls, "_do_ready 应确定性 github.mark_ready（level-triggered 安全网）"
print("  ✓ _do_ready 确定性 github.mark_ready（level-triggered 自愈安全网）")
PY

echo
echo "==> [5/5] reconcile 走查：draft green+approved PR 先转正再合；merge:human 先转正再 park（人拿非 draft PR）"
uv run --extra dev python - <<'PY'
"""Spec-0017 §e2e 的可执行版：假 GitHub（内存）+ 假 merger agent + 真 vigil（sense/classify/_act 一字不改）。

被替换的只有**外部世界**：GitHub 读写 + merger 那次 LLM 调用（换成按剧本行事的假 agent，它照样只能通过
GitHub 说话）。`_sense` / `_classify` / `_fingerprint` / `_reconcile` / `_do_ready` / `_do_merge` /
`stages.merge` / `gates.assert_merge_allowed` 全是**生产代码原件**。
"""

import io
import sys
from contextlib import redirect_stderr
from datetime import UTC, datetime
from pathlib import Path
import tempfile

from openagents.recipes import stages, vigil
from openagents.runtime import engine
from openagents.runtime.state import RuntimeState
from openagents.utils import agent_config, github, identity

NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)
HEAD = "300" + "a" * 37  # 40 位 head；sha7 = "300aaaa"
SHA7 = HEAD[:7]
PR = 300


class World:
    """一个可变的内存 PR 世界。裸 PR（分支不带 openagents/issue- 前缀）→ subject `pr:300`。"""

    def __init__(self):
        self.is_draft = True  # 已交付但残留 draft（deliver 那一枪脱靶）
        self.labels = {f"review-approved:{SHA7}"}  # reviewer 已审过、裁决绑当前 head
        self.merged = False
        self.open = True
        self.comments = []  # (body, at)


W = World()
ACTS = []  # `_act` 每被叫起记一笔 verdict.action —— 断言「ready 严格先于 merge」


def spy_act(**kw):
    ACTS.append(kw["verdict"].action)
    return real_act(**kw)


real_act = vigil._act
vigil._act = spy_act


def fake_pr_snapshot(*, pr_number):
    state = "MERGED" if W.merged else ("OPEN" if W.open else "CLOSED")
    return github.PRSnapshot(
        number=pr_number,
        state=state,
        head_sha=HEAD,
        labels=tuple(sorted(W.labels)),
        mergeable="MERGEABLE",
        merge_state_status="CLEAN",
        head_pushed_at="2026-07-15T11:00:00Z",
        is_draft=W.is_draft,
    )


def fake_mark_ready(*, pr_number):
    W.is_draft = False  # 转正：level-triggered 安全网把残留 draft 顶正


def fake_run_agent(agent_module, *, backend, **kw):
    name = agent_module.__name__.rsplit(".", 1)[-1]
    if name == "merger":
        W.merged = True
        W.open = False
        return {"merged": True, "summary": "已合并"}
    raise AssertionError(f"走查不该派 {name} agent")


FAKES = {
    "list_issues": lambda *, labels, state="open": [],
    "list_open_prs": lambda: [github.PR(PR, f"u/{PR}")] if W.open else [],
    "pr_head_branch": lambda *, pr_number: f"iter/{pr_number}",  # 裸 PR（不带 issue 前缀）
    "pr_snapshot": fake_pr_snapshot,
    "check_snapshot": lambda *, pr_number: github.CheckSnapshot("pass", 3, "2026-07-15T11:00:00Z"),
    "list_comments": lambda *, pr_number: [
        github.Comment(i, "bot", body, at) for i, (body, at) in enumerate(W.comments)
    ],
    "post_comment": lambda *, pr_number, body: W.comments.append((body, "2026-07-15T11:30:00Z")),
    "mark_ready": fake_mark_ready,
    "merge_pr": lambda *, pr_number, method="merge": (_ for _ in ()).throw(
        AssertionError("stages.merge 不该裸调 github.merge_pr——合并下放 merger agent")
    ),
    "add_label": lambda *, pr_number, name: W.labels.add(name),
    "remove_label": lambda *, pr_number, name: W.labels.discard(name),
    "ensure_label": lambda *, name, description="": None,
    "close_issue": lambda *, number: None,
}
for name, impl in FAKES.items():
    setattr(github, name, impl)
engine.run_agent = fake_run_agent
identity.post_signed_comment = lambda *, pr_number, body, agent_id: W.comments.append(
    (identity.sign(body=body, agent_id=agent_id or "oa"), "2026-07-15T11:30:00Z")
)


def build_config(*, merge_owner):
    # e2e:skip 把证据戳归一成 head（走查不测 e2e 支）；review 留 agent、用真 review-approved label；
    # merge owner 由场景切换（agent=下放 merger / human=停在闸等人）。
    return agent_config.AgentConfig(
        version=1,
        agents=agent_config.AgentPolicy(backends={}),
        stages=agent_config.StagePolicy(owners={"e2e": "skip", "merge": merge_owner}),
        release=agent_config.ReleasePolicy(),
        interval=1,
        base="main",
        labels=["openagents"],
        repos=[],
    )


def run_once(config, work):
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        vigil.run_vigil(
            backend=None,
            state=RuntimeState(path=work / "runtime-state.json"),
            work_dir=work,
            config=config,
            once=True,
            concurrency=1,
            agent_id="oa-e2e",
            now_fn=lambda: NOW,
        )
    return buffer.getvalue()


def check(label, cond, detail=""):
    if not cond:
        print(f"✗ {label}{(' —— ' + detail) if detail else ''}")
        sys.exit(1)
    print(f"  ✓ {label}")


# ---- 场景 A：merge:agent —— delivered 但 draft 的 green+approved PR 先转正、再下放 merger 合 ----------
W = World()
ACTS.clear()
work_a = Path(tempfile.mkdtemp(prefix="oa-0017-a-"))
run_once(build_config(merge_owner="agent"), work_a)
check("A draft 自愈支严格排在 merge 前：ACTS == [ready, merge]", ACTS == ["ready", "merge"], str(ACTS))
check("A 转正发生在合并之前：merge 落地时 PR 已非 draft（任何 PR 都不在 draft 态被合）", not W.is_draft)
check("A 合并动作下放 merger agent（闸放行后）→ PR 已 merged", W.merged and not W.open)

# ---- 场景 B：merge:human —— 先转正、再 park needs-human：人拿到的是**已转正、可直接合**的 PR --------------
W = World()
ACTS.clear()
work_b = Path(tempfile.mkdtemp(prefix="oa-0017-b-"))
run_once(build_config(merge_owner="human"), work_b)
check("B 仍先转正再触 merge 支：ACTS == [ready, merge]", ACTS == ["ready", "merge"], str(ACTS))
check("B 人拿到的是**非 draft** PR（转正先于 human 合并动作，直闭 #168 人被 draft 墙挡住）", not W.is_draft)
check("B merge:human → 停在闸打 needs-human、**绝不自动合**", "needs-human" in W.labels and not W.merged)

# ---- 场景 C：合并硬闸兜底 —— head 前移使 review-approved 裁决作废 → 闸抛、决不合并未审的新代码 ------------
from openagents.runtime import gates  # noqa: E402

W = World()
W.is_draft = False  # 已转正，其余全绿
try:
    gates.assert_merge_allowed(pr_number=PR, head_sha="f" * 40)  # head 前移 → label sha 对不上
    check("C 硬闸应对 head 前移的陈旧裁决抛 GateError", False)
except gates.GateError:
    check("C 合并硬闸绑 head sha：head 前移使裁决作废 → 抛 GateError，决不合并未审代码", True)

print("\n✅ Spec-0017 离线 e2e 全绿：PR 生命周期下放 agent + draft level-triggered 自愈 + 合并硬闸兜底")
PY

echo
echo "✅ Spec-0017 端到端离线验证全部通过"
