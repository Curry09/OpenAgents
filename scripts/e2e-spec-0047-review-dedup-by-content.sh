#!/usr/bin/env bash
# Spec-0047 端到端测试启动脚本：评审裁决按「实质内容」去重（同结论·理由不同照发）。
#
# 本组把 orchestrator._decision_already_posted 的去重身份从「抬头+类型+裁决」三行，升级为
# reviewer.extract_decision_content(body=rendered) 得到的 DecisionContent（结论 + 规范化反馈）：
# 仅当 verdict_line 与 feedback_norm 都相同才判重复。这样既保留 PR #61「33 条相同 PASS」的防
# 刷屏去重，又让 issue #116 场景（连续多轮理由各异的 code REWORK）每轮都贴出独立裁决评论，人盯
# PR 能看清卡点怎么演变。
#
# 三段，全程**不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端**（阶段 3 除外，需显式开启）：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 T1（extract_decision_content
#      解析器：render→extract 往返 / 含签名尾巴 comment.body / PASS 空反馈 / 规范化 whitespace 无关 /
#      非裁决→None）与 T2（issue #116 两轮理由不同 REWORK 照发 / PR #61 同 PASS 去重 / 同理由 REWORK
#      去重 / 取最近一条比对 / PASS↔REWORK 翻转照发 / kind 隔离 / list_comments fail-open）。
#   2) 离线成果演练（默认执行，浏览器优先）—— 用**真实**的 reviewer.render_decision +
#      orchestrator._decision_already_posted 跑一段内存评论区场景：round1 code REWORK（理由 A）→
#      round2 code REWORK（理由 B≠A）→ round3/4 相同 PASS，捕获「哪几条真被发出来」，把发出的裁决
#      评论按时间线拼成一份模拟 PR 会话静态 HTML。浏览器（Playwright/chrome-devtools MCP，由 agent 在
#      脚本外驱动）导航 + snapshot + 截图断言：两条 REWORK（理由 A ∧ 理由 B）都可见、PASS 只出现 1
#      条、console/network 无报错。无浏览器 MCP 时本脚本降级为对该 HTML 做文本断言，不跳过成果验证。
#   3) 真实冒烟（可选，OPENAGENTS_E2E_REAL=1）—— 提示如何在 scratch 仓库造一个连续两轮 code
#      REWORK、理由各异的 PR，跑 vigil 观察 PR 评论区出现**两条**不同 REWORK 裁决评论（改前只有 1 条）。
#
# 用法：
#   bash scripts/e2e-spec-0047-review-dedup-by-content.sh
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0047-review-dedup-by-content.sh   # 追加真实冒烟提示
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线成果演练：真实 render_decision + _decision_already_posted 驱动内存评论区 → HTML"

OUT_HTML="docs/evidence/spec-0047/pr-conversation.html"
uv run python - "$OUT_HTML" <<'PY'
# Spec-0047 成果演练：用**真实**产品代码——reviewer.render_decision（渲染裁决评论正文）+
# orchestrator._decision_already_posted（本组升级的按内容去重）——模拟一个 PR 上多轮评审的
# 内存评论区，捕获「去重后实际会被发出来的裁决评论」，再包成静态 HTML 供浏览器/文本断言。
# 脚本只提供内存评论区与 HTML 包裹（测试侧夹具），去重判定与评论正文全部来自产品代码。
import html
import os
import sys

from openagents import github, identity, reviewer
from openagents.github import Comment
from openagents.orchestrator import Orchestrator
from openagents.reviewer import ReviewDecision

PR = 6  # 对应 issue #116 复现的 Drifting12345/LLMwiki4rolePlay PR #6

# --- 内存评论区（替身 github.list_comments / identity.post_signed_comment，其余产品代码不动）---
_comments: list[Comment] = []
_clock = [0]


def _list_comments(*, pr_number):
    return list(_comments)


def _post_signed(*, pr_number, body, agent_id):
    # 模拟 identity 盖章：在裁决正文后追加署名尾巴（extract_decision_content 应把它排除在 feedback 外）。
    _clock[0] += 1
    signed = body + f"\n\n---\n🤖 由 {agent_id} 自动发布 · #{_clock[0]}\n"
    _comments.append(
        Comment(id=f"c{_clock[0]}", author=agent_id, body=signed, created_at=f"2026-07-03T13:{_clock[0]:02d}:00Z")
    )


github.list_comments = _list_comments
identity.post_signed_comment = _post_signed

# _decision_already_posted / _post_review_decision 只用到 github/identity/reviewer/_progress，
# 不触碰其它 self 属性；用未初始化实例挂一个 _progress 记账即可真实跑通产品去重逻辑。
orch = object.__new__(Orchestrator)
orch._agent_id = "agent-0047"
orch._progress = lambda *, message: print(f"    [orchestrator] {message}")

# --- 四轮评审：R1 code REWORK(理由A) → R2 code REWORK(理由B≠A) → R3/R4 相同 PASS ---
REASON_A = "EntityWithContent 继承不符 / 章-场 pattern 缺失 / _validate_specs CWD bug"
REASON_B = "_validate_specs:65 崩溃 bug + 8 个 task 零实现（与 R1 完全不同的卡点）"
rounds = [
    ("R1", ReviewDecision(passed=False, feedback=REASON_A, verdicts=("REWORK",), actionable=True)),
    ("R2", ReviewDecision(passed=False, feedback=REASON_B, verdicts=("REWORK",), actionable=True)),
    ("R3", ReviewDecision(passed=True, feedback="", verdicts=("PASS",))),
    ("R4", ReviewDecision(passed=True, feedback="", verdicts=("PASS",))),
]
for name, decision in rounds:
    before = len(_comments)
    orch._post_review_decision(pr_number=PR, kind="code", decision=decision)
    verb = "照发" if len(_comments) > before else "去重跳过"
    print(f"  [{name}] {'REWORK' if not decision.passed else 'PASS'} → {verb}")

# --- 成果自检（离线铁证）：改前只留 R1 一条 REWORK；改后 R1+R2 两条不同 REWORK 都在，PASS 仅 1 条 ---
posted_bodies = [c.body for c in _comments]
rework_count = sum(1 for b in posted_bodies if "❌ REWORK" in b)
pass_count = sum(1 for b in posted_bodies if "✅ PASS" in b)
assert any(REASON_A in b for b in posted_bodies), "理由 A（R1 REWORK）缺失"
assert any(REASON_B in b for b in posted_bodies), "理由 B（R2 REWORK）被误去重吞掉——issue #116 未修复"
assert rework_count == 2, f"应有 2 条不同 REWORK 裁决评论，实际 {rework_count}（issue #116 修复点）"
assert pass_count == 1, f"相同 PASS 应去重为 1 条（PR #61 防刷屏），实际 {pass_count}"

# --- 把去重后实际发出的裁决评论按时间线拼成模拟 PR 会话 HTML ---
items = []
for c in _comments:
    items.append(
        "<li class='comment'>"
        f"<div class='meta'>{html.escape(c.author)} · {html.escape(c.created_at)}</div>"
        f"<pre>{html.escape(c.body)}</pre></li>"
    )
page = (
    "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
    "<title>Spec-0047 PR 评论区成果</title>"
    "<style>body{font-family:sans-serif;max-width:820px;margin:24px auto}"
    ".comment{border:1px solid #d0d7de;border-radius:8px;padding:12px;margin:12px 0;list-style:none}"
    ".meta{color:#57606a;font-size:12px;margin-bottom:6px}"
    "pre{white-space:pre-wrap;margin:0}h1{font-size:18px}</style></head><body>"
    f"<h1>模拟 PR #{PR} 评论区：按内容去重后实际发出的裁决评论</h1>"
    f"<ul id='pr-conversation'>{''.join(items)}</ul>"
    "</body></html>"
)
out = sys.argv[1]
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(page)

print(f"  [渲染] 去重后实际发出的 {len(_comments)} 条裁决评论已渲染成静态 HTML：{out}")
print(f"  [文本断言] REWORK 理由 A ∧ 理由 B 各 1 条（共 2 条不同 REWORK）、PASS 仅 1 条 ✓")
PY

echo
echo "  [浏览器成果] 请用浏览器 MCP（Playwright / chrome-devtools）导航并断言（agent 在脚本外驱动）："
echo "    navigate  → file://$(pwd)/$OUT_HTML"
echo "    snapshot/截图 → 断言页面同时出现两条 REWORK 裁决（『理由 A』与『理由 B』正文可见）、"
echo "                    ✅ PASS 裁决只出现 1 条（相同 PASS 已去重）"
echo "    console/network → 断言无报错、无失败请求（纯本地静态页）"
echo "  无浏览器 MCP 时：上面的离线文本断言即为降级成果验证（不跳过）。"

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [可选] 真实冒烟（OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  真实冒烟步骤（需要真实 GitHub 仓库 + gh 登录，会真实建 PR/评论、跑 vigil）：
    1) 在 scratch 仓库造一个会连续两轮拿到「理由各异」code REWORK 的 PR：
       让实现 agent 在 R1 后修掉部分问题、又暴露一批新问题（使第 2 轮 reviewer 反馈 ≠ 第 1 轮）。
    2) 跑 vigil 观察该 PR 的评论区：`oa vigil --once`（连跑到进入 R2 评审）。
       预期（改后）：评论区出现**两条**独立的 `## 评审闸裁决 ❌ REWORK`，两条「反馈摘要」正文不同。
       对照（改前）：R2 与 R1 同为 REWORK，被按结论去重吞掉，评论区只有 R1 一条 REWORK。
    3) 让该 PR 最终评审通过并连跑多轮：验证相同 `✅ PASS` 仍只留 1 条（PR #61 防刷屏未回退）。
  （此段仅打印指引，不自动执行，避免在 CI/离线环境误触真实 gh。）
REAL
fi

echo
echo "✓ Spec-0047 端到端演示完成（默认离线、可重复、不触网、不调真实 LLM/gh）。"
