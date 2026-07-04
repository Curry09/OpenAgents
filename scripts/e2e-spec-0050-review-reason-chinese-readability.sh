#!/usr/bin/env bash
# Spec-0050/T2 端到端测试启动脚本：Review 不通过理由增强可读性——强制 reviewer 反馈输出为一段简短中文。
#
# 本组把「面向人类的裁决理由（REASON/ISSUES/NEXT）必须用一段简短的中文」写成 reviewer 的输出格式
# 硬规约（openagents/reviewer.py 的 _RUBRIC_TAIL，code/rfc 两闸共享，改一处即两闸同时生效）。改动是
# 纯 prompt 文本硬化 + 单测 + 本浏览器成果 e2e，不改任何裁决解析/聚合/渲染/发帖链路的运行时行为。
#
# 【为什么用浏览器成果 e2e（诚实自检工具集，遵循 end-to-end-ui-screenshots skill）】
#   我自检了工具集——本环境**具备** playwright / chrome-devtools MCP。与「纯 reviewer 判断标准变化、
#   无 UI 可见面」的改动不同，**本 feature 的成果恰恰是「渲染出来的评论文字的可读性」**：issue #124 原文
#   「这样人类才能在 github 中直接处理」，成果就落在 GitHub PR 评论这个**浏览器可见界面**上——「反馈摘要」
#   块是不是简短中文，是一个**渲染/视觉属性**。按 skill「有可视化结果的东西，端到端就走可视化那条路」，
#   本组**优先设计浏览器成果 e2e**（渲染页面 + 截图 + 文本断言），而非仅声明 shell 断言。
#
# 【诚实分层：真实理由文本由真 LLM 产出，不可 hermetic】
#   reviewer 的理由是真实 backend 推理产物，CI 内不可跑真 claude。故把「可读性」的验证拆两层，各测其可测：
#   - 离线确定性段（默认执行，hermetic，无网络/无真 claude）——ruff/format/pytest 全套；grep 锚点断言
#     _RUBRIC_TAIL 含 T1 语言/长度硬规则关键字；**浏览器渲染成果演练**：用一个「reviewer 遵守新 prompt 后
#     应产出」的代表性简短中文 feedback fixture 喂**真实** reviewer.render_decision(kind="code") 得到真实
#     评论 markdown → 渲染成 GitHub 风格 HTML 页 → 由 agent 用 playwright 打开、截图存 tracked
#     docs/evidence/spec-0050/、browser_evaluate 抽「反馈摘要」块文本断言 CJK 占比≥阈值 且 长度≤阈值。
#     **RED 反证**：同断言喂「旧式长英文 feedback fixture」应判不通过（CJK 低/超长），对照截图一并存证。
#     诚实标注：本段 feedback 是 fixture，验证的是「render 路径 + 浏览器可读性判据」这条链路与判据本身；
#     理由内容的真实性由下方 REAL 段验证。
#   - 真实成果段（可选，OPENAGENTS_E2E_REAL=1，非默认，非 hermetic）——造有明显缺陷的 scratch PR、跑真
#     reviewer 拿真实 REWORK feedback、render_decision 经 orchestrator/identity 贴真实 GitHub PR，用
#     playwright 打开 PR 页定位「## 评审闸裁决」评论截图、抽反馈摘要断言 CJK 占比+长度。
#
# 用法：
#   bash scripts/e2e-spec-0050-review-reason-chinese-readability.sh
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0050-review-reason-chinese-readability.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] 离线确定性段（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/3] grep 锚点断言：reviewer.py 的 _RUBRIC_TAIL 含 T1 语言/长度硬规则关键字"
REVIEWER="openagents/reviewer.py"
assert_grep() {
  # $1 = 锚点字符串；-F 定长匹配，缺失即 set -e 退出。
  if ! grep -qF -- "$1" "$REVIEWER"; then
    echo "  ✗ 缺锚点：$1" >&2
    exit 1
  fi
  echo "  ✓ $1"
}
assert_grep "面向人类的裁决理由（REASON / ISSUES / NEXT"
assert_grep "一段简短的中文书写：直击要害"
assert_grep "一句话中文说明核对的关键验证标准"
assert_grep "一句话中文点出问题"
assert_grep "一句话中文说明修复方向"

echo
echo "==> [3/3] 浏览器渲染成果演练：真实 render_decision → GitHub 风格 HTML 页 + 可读性判据（GREEN/RED）"

EVIDENCE_DIR="docs/evidence/spec-0050"
GREEN_HTML="$EVIDENCE_DIR/comment-green-short-chinese.html"
RED_HTML="$EVIDENCE_DIR/comment-red-long-english.html"

uv run python - "$GREEN_HTML" "$RED_HTML" <<'PY'
# Spec-0050/T2 成果演练：用**真实**产品代码 reviewer.render_decision(kind="code")（不打桩、不改产品代码）
# 把两个 feedback fixture 渲染成真实评论 markdown，再包成 GitHub 风格 HTML 页；同时在离线侧做「简短中文」
# 的机器可验证操作化判据（CJK 占比 ≥ 阈值 且 长度 ≤ 阈值），断言 GREEN 通过、RED（旧式长英文）不通过——
# 证明判据能区分两者、绿非恒真。浏览器侧（agent 用 playwright）再对同两页导航+截图+browser_evaluate 复核。
import html
import os
import sys

from openagents.reviewer import (
    ReviewDecision,
    _extract_feedback_norm,
    render_decision,
)

# ---- 可读性判据阈值（Spec-0050 Unresolved questions 定稿）----
# CJK 占比 ≥ 0.5：容许夹带文件路径/英文术语（用占比而非「全中文」缓解术语夹带，见 spec Drawbacks）。
# 长度 ≤ 300：单条反馈摘要「一段简短」的上限，够表达结论+下一步又不至长篇堆砌。
CJK_MIN_RATIO = 0.5
MAX_LEN = 300

# GREEN：reviewer 遵守新 _RUBRIC_TAIL 后应产出的「一段简短中文」理由（含少量文件路径/英文 token）。
GREEN_FEEDBACK = (
    "ISSUES:\n"
    "- openagents/reviewer.py:42 空输入未做边界处理，会抛异常\n"
    "NEXT: 补一个空字符串分支的单测并加防御\n"
    "REASON: 核心路径缺失边界覆盖，关键验证标准未满足，判打回"
)
# RED 反证：旧式长篇英文理由（reviewer 无视语言约束时的典型坏输出）——CJK 占比极低且超长，应判不通过。
RED_FEEDBACK = (
    "ISSUES:\n"
    "- The empty-input path in openagents/reviewer.py:42 is not guarded, which means "
    "that when the caller passes an empty string the function will raise an unhandled "
    "exception and crash the whole review pipeline instead of degrading gracefully.\n"
    "NEXT: Please add a dedicated unit test that exercises the empty-string branch and "
    "introduce a defensive guard so that the reviewer never blows up on degenerate input.\n"
    "REASON: The core code path lacks boundary coverage and the key verification criteria "
    "are therefore not satisfied, so this change must be reworked before it can pass."
)


def cjk_ratio(text: str) -> float:
    """CJK 字符占非空白字符的比例（『中文占比』的操作化定义）。"""
    stripped = [c for c in text if not c.isspace()]
    if not stripped:
        return 0.0
    cjk = sum(1 for c in stripped if "一" <= c <= "鿿")
    return cjk / len(stripped)


def feedback_text_of(feedback: str) -> str:
    """走**真实**产品渲染路径：ReviewDecision → render_decision 评论 markdown → 抽「反馈摘要」块正文。

    与线上一致：render_decision 把 feedback 裹进「反馈摘要」围栏块，_extract_feedback_norm 反解出块体
    （这正是盯 PR 的人在 GitHub 评论里读到的那段文字）。
    """
    decision = ReviewDecision(
        passed=False, feedback=feedback, verdicts=("REWORK",), actionable=True
    )
    body = render_decision(decision=decision, kind="code")
    return _extract_feedback_norm(lines=body.splitlines())


def render_html(*, title: str, feedback: str, verdict_label: str) -> str:
    """把真实评论 markdown 渲染成 GitHub 风格 HTML 页，「反馈摘要」块放进 id=feedback-summary 供断言。"""
    decision = ReviewDecision(
        passed=False, feedback=feedback, verdicts=("REWORK",), actionable=True
    )
    markdown = render_decision(decision=decision, kind="code")
    fb = feedback_text_of(feedback)
    esc_md = html.escape(markdown)
    esc_fb = html.escape(fb)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ background:#f6f8fa; font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
          color:#1f2328; margin:0; padding:32px; }}
  .comment {{ max-width:760px; margin:0 auto; background:#fff; border:1px solid #d0d7de;
              border-radius:6px; overflow:hidden; }}
  .comment-header {{ background:#f6f8fa; border-bottom:1px solid #d0d7de; padding:8px 16px;
                     font-size:12px; color:#59636e; }}
  .comment-body {{ padding:16px; }}
  h2 {{ font-size:18px; margin:0 0 12px; padding-bottom:6px; border-bottom:1px solid #d8dee4; }}
  ul {{ padding-left:20px; }}
  #feedback-summary {{ background:#f6f8fa; border:1px solid #d0d7de; border-radius:6px;
                       padding:12px; white-space:pre-wrap; font-family:ui-monospace,
                       SFMono-Regular,Menlo,monospace; font-size:13px; line-height:1.6; }}
  .raw {{ margin-top:24px; color:#59636e; font-size:12px; }}
  pre.raw-md {{ background:#f6f8fa; border:1px solid #d0d7de; border-radius:6px; padding:12px;
                white-space:pre-wrap; font-size:12px; }}
</style>
</head>
<body>
  <div class="comment">
    <div class="comment-header">openagents-bot 评论于 GitHub PR · {html.escape(verdict_label)}</div>
    <div class="comment-body">
      <h2>评审闸裁决</h2>
      <ul>
        <li>类型：代码</li>
        <li>裁决：❌ REWORK</li>
        <li>票数：1 票中 0 票 PASS</li>
        <li>票型：REWORK</li>
      </ul>
      <p><strong>反馈摘要：</strong></p>
      <div id="feedback-summary">{esc_fb}</div>
    </div>
  </div>
  <div class="raw">
    <p>—— 上方「反馈摘要」块取自真实 <code>reviewer.render_decision(kind="code")</code> 的评论 markdown 原文（下方折叠）：</p>
    <pre class="raw-md">{esc_md}</pre>
  </div>
</body>
</html>
"""


def check(label: str, feedback: str) -> tuple[float, int]:
    fb = feedback_text_of(feedback)
    ratio = cjk_ratio(fb)
    length = len(fb)
    passed = ratio >= CJK_MIN_RATIO and length <= MAX_LEN
    verdict = "通过（简短中文）" if passed else "不通过（超长/英文）"
    print(f"  [{label}] CJK 占比={ratio:.2f}（阈值≥{CJK_MIN_RATIO}）"
          f" 长度={length}（阈值≤{MAX_LEN}） → {verdict}")
    return ratio, length


green_out, red_out = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(green_out), exist_ok=True)

print("  -- 可读性判据（真实 render 路径抽『反馈摘要』块）：")
g_ratio, g_len = check("GREEN 简短中文", GREEN_FEEDBACK)
r_ratio, r_len = check("RED   长篇英文", RED_FEEDBACK)

# 离线铁证：判据能区分「简短中文」与「旧式长英文」，绿非恒真。
assert g_ratio >= CJK_MIN_RATIO and g_len <= MAX_LEN, (
    "GREEN 简短中文 fixture 竟不通过可读性判据——阈值或渲染路径异常"
)
assert not (r_ratio >= CJK_MIN_RATIO and r_len <= MAX_LEN), (
    "RED 长英文 fixture 竟通过可读性判据——判据不能区分，绿恒真（无效）"
)

with open(green_out, "w", encoding="utf-8") as f:
    f.write(render_html(title="评审评论（简短中文·应通过）",
                        feedback=GREEN_FEEDBACK, verdict_label="GREEN 简短中文"))
with open(red_out, "w", encoding="utf-8") as f:
    f.write(render_html(title="评审评论（长篇英文·应不通过）",
                        feedback=RED_FEEDBACK, verdict_label="RED 长篇英文反证"))

print(f"  [渲染] GitHub 风格评论页已写入 tracked 证据目录：")
print(f"    GREEN → {green_out}")
print(f"    RED   → {red_out}")
print("  [文本断言] 可读性判据区分 GREEN/RED 通过 ✓（绿非恒真）")
PY

echo
echo "  参考页（file:// 打开，不碰任何生产端口/数据）："
echo "    GREEN: file://$(pwd)/$GREEN_HTML"
echo "    RED  : file://$(pwd)/$RED_HTML"
cat <<'RUNBOOK'

  由 agent 用 browser MCP（playwright / chrome-devtools）走浏览器成果闭环（本脚本只渲染页面 + 给说明书）：
    1. navigate  → 打开上面 GREEN 页 file:// URL
    2. screenshot→ 截图存入 docs/evidence/spec-0050/（tracked 证据目录），示人「反馈摘要」是简短中文
    3. browser_evaluate → 取 document.getElementById('feedback-summary').innerText，算 CJK 占比 与 长度，
                          断言 占比 ≥ 0.5 且 长度 ≤ 300；核 list_console_messages 无 error
    4. RED 反证对照 → 对 RED 页重复 1–3，断言同一判据**不通过**（CJK 低/超长），截图一并存证
  若本环境客观无 browser MCP / 无显示：按 end-to-end-ui-screenshots skill 的诚实纪律明写
    「因无浏览器自动化，浏览器成果段未执行」阻塞项，不用离线段顶替声称已跑。
RUNBOOK

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [可选] 真实成果段（OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  真实成果步骤（需真实 GitHub 仓库 + gh 登录 + 真 claude backend，会真实建 PR/评论、跑 reviewer）：
    1) 在 scratch 仓库造一个「有明显缺陷」的 PR（如某函数缺空输入边界、删了在用接口未改调用方）。
    2) 跑一次真 reviewer（code 闸，真 backend）：连跑到进入 code 评审拿到真实 REWORK feedback，
       经 render_decision → orchestrator/identity 贴到真实 GitHub PR。
       预期（改后）：评论「反馈摘要」块是**一段简短中文**（CJK 占比高、篇幅短），盯 PR 的人一眼读懂。
    3) 用 playwright 打开该 PR 页、定位「## 评审闸裁决」评论、截图存 docs/evidence/spec-0050/、
       browser_evaluate 抽反馈摘要文本断言 CJK 占比 ≥ 0.5 且 长度 ≤ 300。
    4) 对照（改前）：同类 PR 的反馈摘要常是长篇英文，CJK 占比低/超长——这才是本 feature 治的病。
  （此段仅打印指引，不自动执行，避免在 CI/离线环境误触真实 gh/claude；真实 LLM 产出的达成度靠本段验。）
REAL
fi

echo
echo "✓ Spec-0050 端到端演示：离线段全绿（ruff+format+pytest+grep 锚点）+ 真实 render 页面已渲染并做可读性判据；"
echo "  浏览器成果闭环（导航+截图+browser_evaluate）由 agent 按上方说明书用 playwright/chrome-devtools MCP 执行。"
