#!/usr/bin/env bash
# Spec-0043/T4 端到端测试启动脚本：issue 进 RFC 前自检修法方向是否自洽——命中冲突先打
# needs-human 对齐、不直接生成 spec。
#
# 本组在 vigil 发现段派单 start_rfc 起草 spec 之前，插一道轻量自检 issuecheck：用注入 backend
# 判读 issue 标题/正文是否存在「会直接影响修法方向」的内在冲突（issue #106 事故：标题=按 sha 缓存、
# 正文=hold-merge 冻结，若按标题起草会做出与正文/最终实现南辕北辙的 spec）。命中则不起草，改为打
# needs-human + 贴一条列出冲突点与候选修法的署名对齐评论，等人对齐；needs-human 作为持久冻结信号
# 使同一 issue 只判一次、不复审震荡。未命中照常派单（零回归）。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端**（阶段 2 除外，需显式开启）：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 T1（issue_comment 出口）、
#      T2（issuecheck 判读 + 对齐评论渲染 + fail-open）、T3（precheck 接线 + _dispatch_kind 防震荡）、
#      T4 集成（test_issue_precheck_integration：#106 冲突识别+冻结 / 反震荡 / 放行 / 解冻）。
#   2) 离线成果演练（默认执行）—— 用真实 issuecheck.build_alignment_comment 产出的**真实对齐评论
#      正文**渲染成一份静态 HTML，浏览器（Playwright/chrome-devtools MCP，由 agent 在脚本外驱动）
#      导航 + snapshot + 截图断言两个修法方向 / 候选修法 / needs-human 建议可见、console/network 无
#      报错；无浏览器 MCP 时本脚本降级为对该 HTML 做文本断言（grep 两个修法方向 + 候选修法段），
#      不跳过成果验证（理念 8：成果可视化）。
#   3) 真实冒烟（可选，OPENAGENTS_E2E_REAL=1）—— 提示如何在 scratch 仓库真实建一个「标题主张 X、
#      正文主张互斥的 Y」的 issue，带约定标签跑一轮 vigil --once，验证被打 needs-human + 收到一条
#      对齐评论 + 未开 draft PR；再对一个自洽 issue 验证正常起草。
#
# 用法：
#   bash scripts/e2e-spec-0043-issue-conflict-precheck.sh
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0043-issue-conflict-precheck.sh   # 追加真实冒烟提示
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线成果演练：渲染真实对齐评论 → 浏览器/文本断言两个修法方向 + 候选修法 + needs-human"

OUT_HTML="$(mktemp -d)/alignment-comment.html"
uv run python - "$OUT_HTML" <<'PY'
# Spec-0043/T4：用真实 issuecheck 产出 #106 场景的对齐评论正文，包成最小静态 HTML（测试侧包裹，
# 非产品代码）供浏览器导航断言。评论正文本身是产品输出（build_alignment_comment 的返回值）。
import html
import sys

from openagents import issuecheck
from openagents.issuecheck import ConflictVerdict

verdict = ConflictVerdict(
    has_conflict=True,
    conflicts=(
        "标题主张按 commit sha 缓存评审结论；正文主张 hold-merge 后把已 PASS 的 PR 冻结成 needs-human。",
        "两者语义不同——一个保留 PR 在活跃轮询里复用缓存，一个把 PR 移出活跃轮询等人合并。",
    ),
    candidate_fixes=("按 commit sha 缓存评审结论", "hold-merge 冻结 PR"),
)
body = issuecheck.build_alignment_comment(verdict=verdict)

# 成果自检（离线铁证）：两个修法方向 + 候选修法段 + needs-human 建议齐全，不含 PR 失败文案。
assert "按 commit sha 缓存评审结论" in body and "hold-merge 冻结 PR" in body, "缺修法方向"
assert "候选修法" in body, "缺候选修法段"
assert "needs-human" in body and "对齐" in body, "缺 needs-human 对齐指引"
assert "卡住了" not in body and "🤖" not in body, "误混入 PR 级失败文案"

out = sys.argv[1]
page = (
    "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
    "<title>Spec-0043 对齐评论成果</title></head><body>"
    f"<article id='alignment-comment'><pre>{html.escape(body)}</pre></article>"
    "</body></html>"
)
with open(out, "w", encoding="utf-8") as f:
    f.write(page)

print("  [渲染] 真实对齐评论正文已渲染成静态 HTML：", out)
print("  [文本断言] 两个修法方向 + 候选修法段 + needs-human 对齐指引齐全、无 PR 失败文案 ✓")
PY

echo
echo "  [浏览器成果] 请用浏览器 MCP（Playwright / chrome-devtools）导航并断言（agent 在脚本外驱动）："
echo "    navigate  → file://$OUT_HTML"
echo "    snapshot/截图 → 断言页面同时出现『按 commit sha 缓存评审结论』与『hold-merge 冻结 PR』、"
echo "                    出现『候选修法』取舍段、出现『needs-human / 先对齐再进 RFC』建议"
echo "    console/network → 断言无报错、无失败请求（纯本地静态页）"
echo "  无浏览器 MCP 时：上面的离线文本断言即为降级成果验证（不跳过）。"

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [可选] 真实冒烟（OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  真实冒烟步骤（需要真实 GitHub 仓库 + gh 登录，会真实建 issue/评论）：
    1) 在 scratch 仓库建一个「标题主张 X、正文主张互斥的 Y」的 issue，带 openagents 发现标签。
       例：标题「按 sha 缓存评审结论」/ 正文「应改为 hold-merge 冻结 PR」。
    2) 跑一轮 vigil：`oa vigil --once`
       预期：该 issue 被打上 needs-human 标签、收到一条对齐评论（列出两个修法方向 + 候选修法），
             且**未**开出 draft PR（precheck 在建 worktree/起草之前拦下）。
    3) 再连跑一轮：`oa vigil --once`
       预期：无新增评论、无起草——needs-human 在场 → _dispatch_kind 跳过、判读不重跑（反震荡）。
    4) 另建一个标题/正文一致的自洽 issue，跑 vigil --once → 正常起草、开 draft PR（零回归）。
  （此段仅打印指引，不自动执行，避免在 CI/离线环境误触真实 gh。）
REAL
fi

echo
echo "✓ Spec-0043/T4 端到端演示完成（默认离线、可重复、不触网、不调真实 LLM/gh）。"
