#!/usr/bin/env bash
# Spec-0052 端到端测试启动脚本：统一 agent 上下文注入（所有派单入口带 PR 号 + 注入本 PR 对话历史）。
#
# 本组治理 issue #129 暴露的两类缺口（触发案例：PR #128 e2e 闸反复 FAIL → needs-human）：
#   缺口一 PR 号注入不统一——refine_rfc / implement 的 task 缺 PR 号；本组补上，形成「所有派单
#     入口一律把 PR 号写进 task」的统一约定。
#   缺口二 本 PR 对话历史从不注入——所有 agent 的 context 都看不到历轮评审裁决/作者回复/人类评论；
#     本组抽 build_agent_context 统一拉取、去噪、截断后注入四入口（refine/implement/iterate + reviewer）。
#   reviewer 配套「落盘产物为准、评论仅供参考」rubric：既让它可见历史，又保留其独立读仓库、不被
#     说辞蒙蔽的价值（正是 PR #128 能**正确**判 FAIL 的原因）。
#
# **浏览器 e2e 不适用**：本 feature 是后端 prompt/context 组装改动——改的是喂给 cli-agent 子进程的
# 文本，无任何产品前端界面可驱动（无导航/交互/截图可断言的视觉成果）。据取证判断纪律，这属「UI 看不到
# 但改变产品对外行为」一类，成果测试形态为**确定性文本复现**（pytest 集成测试 + 本 shell 跑它打印
# 证据），而非浏览器 e2e。全程不触网、不调真实 gh/LLM/git 远端。
#
# 用法：
#   bash scripts/e2e-spec-0052-agent-context-injection.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# 优先用 uv（与其它 e2e 脚本一致）；无 uv 时回退到当前环境的 python/pytest/ruff/spec。
if command -v uv >/dev/null 2>&1; then
  PYTHON=(uv run python)
  PYTEST=(uv run --extra dev pytest)
  RUFF=(uv run --extra dev ruff)
  SPEC=(uv run spec)
else
  PYTHON=(python)
  PYTEST=(python -m pytest)
  RUFF=(ruff)
  SPEC=(spec)
fi

echo "==> [1/4] 静态检查（ruff lint + format）"
"${RUFF[@]}" check openagents/agentcontext.py openagents/reviewer.py openagents/orchestrator.py \
  tests/test_agentcontext.py tests/test_reviewer_history.py tests/test_orchestrator_context.py \
  tests/test_agent_context_integration.py
"${RUFF[@]}" format --check openagents/agentcontext.py openagents/reviewer.py \
  openagents/orchestrator.py tests/test_agentcontext.py tests/test_reviewer_history.py \
  tests/test_orchestrator_context.py tests/test_agent_context_integration.py

echo
echo "==> [2/4] 定向单元/集成测试（Spec-0052 T1–T4）+ 既有回归（reviewer / orchestrator 零回归）"
"${PYTEST[@]}" -q \
  tests/test_agentcontext.py \
  tests/test_reviewer_history.py \
  tests/test_orchestrator_context.py \
  tests/test_agent_context_integration.py \
  tests/test_reviewer.py \
  tests/test_orchestrator.py

echo
echo "==> [3/4] 成果证据：用**真实** build_agent_context + orchestrator + reviewer 复现 #128 式历史，打印四条断言证据"
"${PYTHON[@]}" - <<'PY'
# Spec-0052 成果演练：用**真实**产品代码——agentcontext.build_agent_context（拉历史+去噪+截断+PR 号）、
# Orchestrator.refine_rfc/implement/iterate/review_code（四入口收口 build_agent_context）、reviewer.review
# （history 注入 + 落盘产物为准 rubric）——把 issue #129 两类缺口的修复跑出来，打印证据。脚本只提供
# 内存版 GitHub 评论账本（#128 式历史：认领噪声 + 历轮 FAIL 裁决 + 作者「已改 PASS」+ 人类评论）与
# 无 git 的 subprocess 替身；PR 号注入 / 历史组装 / 去噪 / rubric 全部来自产品代码。
import subprocess

from openagents import agentcontext, identity, reviewer
from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Comment
from openagents.reviewer import ReviewDecision
from openagents.state import State

# --- #128 式历史账本（真实产品渲染函数造，drift-catching）--- #
DECISION = identity.sign(
    body=reviewer.render_decision(
        decision=ReviewDecision(
            passed=False, feedback="result.md 仍是 skipped", verdicts=("REWORK",), actionable=True
        ),
        kind="code",
    ),
    agent_id="reviewer-1",
)
REFINE = identity.sign(
    body=orch_module._REFINE_COMMENT.format(summary="已把 result.md 改成 PASS"), agent_id="author-1"
)
HUMAN = "人类补充：以仓库里 result.md 的真实内容为准，别只看评论说辞"
CLAIM = identity.build_claim_note(agent_id="claimer-9")
LEDGER = [
    Comment(id="1", author="claimer", body=CLAIM, created_at="2026-06-01T00:00:00Z"),
    Comment(id="2", author="reviewer", body=DECISION, created_at="2026-06-02T00:00:00Z"),
    Comment(id="3", author="author", body=REFINE, created_at="2026-06-03T00:00:00Z"),
    Comment(id="4", author="alice", body=HUMAN, created_at="2026-06-04T00:00:00Z"),
]


class CaptureBackend:
    name = "capture"

    def __init__(self):
        self.calls = []

    def run(self, *, work_dir, task, context):
        self.calls.append({"task": task, "context": context})
        return AgentResult(changed=True, summary="VERDICT: PASS")


class GitRecorder:
    def __call__(self, args, **kwargs):
        class P:
            returncode = 0
            stdout = '{"comments": []}' if "comments" in args else ""
            stderr = ""

        return P()


import tempfile

tmp = tempfile.mkdtemp()
import pathlib

root = pathlib.Path(tmp)

# monkeypatch 手工版（脚本非 pytest）：直接替模块级函数。
orch_module.github.list_comments = lambda *, pr_number: LEDGER
orch_module.github.post_comment = lambda *, pr_number, body: None
orch_module.github.mark_ready = lambda *, pr_number: None
orch_module.identity.post_signed_comment = lambda *, pr_number, body, agent_id: None
subprocess.run = GitRecorder()

backend = CaptureBackend()
state = State(path=root / ".openagents" / "state.json")
orch = orch_module.Orchestrator(backend=backend, state=state, work_dir=root, agent_id="agent-x")
state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=128, url="u/pull/128"))

# 证据①：build_agent_context 三类历史进 + PR 号 + 噪声出。
ctx = agentcontext.build_agent_context(pr_number=128, extra_detail="本轮反馈X")
c1 = all(s in ctx for s in ("本 PR 是 #128", "评审闸裁决", "已把 result.md 改成 PASS", HUMAN, "本轮反馈X"))
c1_noise = "openagents:claim" not in ctx and "openagents:agent=" not in ctx and "认领本 issue" not in ctx
print("  证据①【三类历史进 + PR 号 + 本轮反馈 / 认领便签+签名噪声出】：", c1 and c1_noise)

# 证据②：refine / implement 的 task 补上 PR 号（缺口一）。
orch.refine_rfc(pr_number=128, detail="reviewer 意见", announce=False)
orch.implement(pr_number=128)
orch.iterate(pr_number=128, reason="ci", detail="CI 反馈")
refine_c, implement_c, iterate_c = backend.calls
c2 = "PR #128" in refine_c["task"] and "PR #128" in implement_c["task"]
print("  证据②【refine/implement 的 task 含 PR 号（缺口一）】：", c2)

# 证据③：三入口 context 都含本 PR 历史（缺口二）。
c3 = all(
    ("本 PR 是 #128" in c["context"] and "评审闸裁决" in c["context"] and HUMAN in c["context"])
    for c in (refine_c, implement_c, iterate_c)
)
print("  证据③【refine/implement/iterate 的 context 含本 PR 历史（缺口二）】：", c3)

# 证据④：reviewer 得历史 + 落盘产物为准 rubric 生效。
backend.calls.clear()
decision = orch.review_code(pr_number=128)
rev_ctx = backend.calls[0]["context"]
c4_hist = "本 PR 是 #128" in rev_ctx and "评审闸裁决" in rev_ctx and HUMAN in rev_ctx
c4_rubric = all(
    ("落盘产物为准" in t and "评论仅供参考" in t)
    for t in (reviewer._RFC_REVIEW_TASK, reviewer._CODE_REVIEW_TASK)
)
print("  证据④【reviewer 得历史 + 落盘产物为准 rubric 生效】：", c4_hist and c4_rubric)

assert c1 and c1_noise, "证据①失败：三类历史/PR 号/噪声过滤"
assert c2, "证据②失败：refine/implement task 缺 PR 号"
assert c3, "证据③失败：入口 context 缺本 PR 历史"
assert c4_hist and c4_rubric, "证据④失败：reviewer 未得历史或 rubric 未生效"
print("  ✓ 四条断言全部通过")
PY

echo
echo "==> [4/4] spec 校验（Spec-0052 组结构 + OVERVIEW/ARCHITECTURE 无漂移）"
"${SPEC[@]}" validate --specs-root docs/specs
# 幂等（无漂移）自检：render/graph 前先存副本，重渲后 diff 应逐字节一致——不依赖 git 提交状态。
cp docs/specs/OVERVIEW.md /tmp/oa-0052-overview.bak
cp docs/specs/ARCHITECTURE.md /tmp/oa-0052-arch.bak
"${SPEC[@]}" render --specs-root docs/specs
"${SPEC[@]}" graph --specs-root docs/specs
diff /tmp/oa-0052-overview.bak docs/specs/OVERVIEW.md
diff /tmp/oa-0052-arch.bak docs/specs/ARCHITECTURE.md

echo
echo "✅ Spec-0052 端到端验证通过：PR 号进 prompt / 三类历史进 context / 噪声被滤 / reviewer 得历史且 rubric 生效（可复现证据见上）。"
