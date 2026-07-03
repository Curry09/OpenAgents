#!/usr/bin/env bash
# Spec-0048/T2 端到端测试启动脚本：Review 防「架构骨架冒充完整实现」。
#
# 本组把「防 design-as-implementation」写成 reviewer 的三处 rubric 文本硬化（均在
# openagents/reviewer.py，纯 prompt/rubric，不改任何运行时模块）：
#   (1) _CODE_REVIEW_TASK 加「自动化完整性硬规则」——PR 声称新增自动化执行链路时，逐条追问
#       主流程触发点 / 被调用证据 / artifact 自动产生并 commit / 正例·反例 / 集成路径而非局部
#       函数，缺任一 → REWORK，理由「只实现骨架，未证明完整链路」；
#   (2) _RFC_REVIEW_TASK 加「自动化 spec 防过度承诺」——spec 承诺自动化链路则 Reference-level 必须
#       声明 触发时机/调用方/artifact 落点/失败路径/正·反例验收，否则只算设计草案（只挂 rfc 闸）；
#   (3) _EVIDENCE_RUBRIC 从「宣称验证过但无证据 → REWORK」延伸到「宣称实现了自动化执行/门控能力
#       却无真实产物或集成证据 → REWORK」（只挂 code 闸）。
#
# 【为什么不是浏览器 e2e（诚实说明，遵循 end-to-end-ui-screenshots skill 的纪律）】
#   我自检了工具集——本环境**具备** playwright / chrome-devtools MCP。但本 spec 是一次**纯
#   reviewer prompt/rubric 文本硬化**，**没有任何产品对外的 UI 界面**被改动：可观测的「成果」是
#   「面对骨架冒充类 PR，reviewer 的裁决被导向 REWORK」，它是评审判断标准的变化，不是页面/交互变化。
#   按 skill「UI 可见→截图 / UI 不可见但改产品行为→运行日志文本 / 纯内部→相称测试」三分类，本改动
#   属**「改产品行为但 UI 不可见」**一类，正确成果证据是**确定性离线断言 + 真实 rubric 文本对照骨架
#   冒充场景**，而非浏览器导航截图。强行套一个浏览器流程会是「有工具 ≠ 有 UI」的自欺。
#
# 【RED 反验做法（事后 revert、不进 PR）】把 openagents/reviewer.py 硬化前的旧 rubric 文本临时还原
#   （删掉 _AUTOMATION_INTEGRITY_RUBRIC / _RFC_AUTOMATION_RUBRIC / _EVIDENCE_RUBRIC 延伸段），再跑本
#   脚本：离线段的三组 grep 锚点应**缺失**、成果演练段的逐缺口断言应**翻红**——证明绿不是恒真。反验
#   完毕 `git checkout openagents/reviewer.py` 还原，不把 RED 脚手架提进 PR。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh**（阶段真实冒烟除外，需显式开启）：
#   1) 离线确定性段（默认执行、hermetic）——ruff check/format + pytest 全套；再 grep 锚点断言
#      openagents/reviewer.py 含 T1 三处硬化关键字（三组）。
#   2) 骨架冒充成果演练段（默认执行、离线、用真实产品代码 reviewer._task_for）——用真实
#      _task_for(kind=code)/_task_for(kind=rfc) 生成实际 review 任务全文，与「PR #105 复刻场景」并排
#      渲染成可读产物写入 tracked docs/evidence/spec-0048/，断言 review 任务文本逐条覆盖该场景每个缺口。
#   3) 真实冒烟（可选，OPENAGENTS_E2E_REAL=1）——提示如何造只加骨架无接线的 PR、跑真 reviewer 观察
#      code 裁决 REWORK 且理由含「只实现骨架，未证明完整链路」。默认不执行（非 hermetic、需真 claude）。
#
# 用法：
#   bash scripts/e2e-spec-0048-anti-design-as-implementation-review.sh
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0048-anti-design-as-implementation-review.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [1/2] grep 锚点断言：reviewer.py 含 T1 三处硬化关键字"
REVIEWER="openagents/reviewer.py"
assert_grep() {
  # $1 = 锚点字符串；-F 定长匹配，缺失即 set -e 退出。
  if ! grep -qF -- "$1" "$REVIEWER"; then
    echo "  ✗ 缺锚点：$1" >&2
    exit 1
  fi
  echo "  ✓ $1"
}
echo "  (a) _CODE_REVIEW_TASK 自动化完整性六问："
assert_grep "自动化完整性"
assert_grep "主流程触发点"
assert_grep "artifact 自动产生并 commit"
assert_grep "正例·反例"
assert_grep "集成路径而非局部函数"
assert_grep "只实现骨架，未证明完整链路"
echo "  (b) _RFC_REVIEW_TASK 自动化 spec 防过度承诺："
assert_grep "自动化 spec 防过度承诺"
assert_grep "触发时机"
assert_grep "调用方"
assert_grep "artifact 落点"
assert_grep "失败路径"
assert_grep "正·反例验收"
echo "  (c) _EVIDENCE_RUBRIC 延伸到自动化能力声明："
assert_grep "宣称实现了自动化执行/门控能力"
assert_grep "无真实产物或集成证据 → REWORK"

echo
echo "==> [2/2] 骨架冒充成果演练：真实 reviewer._task_for 对照 PR #105 复刻场景 → tracked 产物"

OUT_MD="docs/evidence/spec-0048/skeleton-impersonation-drill.md"
uv run python - "$OUT_MD" <<'PY'
# Spec-0048/T2 成果演练：用**真实**产品代码 reviewer._task_for（不打桩、不改产品代码）生成实际会
# 喂给 reviewer 的 review 任务全文，与一段「PR #105 复刻场景描述」（只新增 executor/evidence_gate
# 模块、门控位置对、只有模块级单测、无主流程接线证据）并排渲染成可读 Markdown，断言 review 任务文本
# **逐条覆盖**该骨架冒充场景的每个缺口——即证明换成这份新 prompt 后，reviewer 拿到的对照清单足以把
# PR #105 那类 PR 导向 REWORK（受限于 reviewer 依赖真 backend 推理不可 hermetic，这里断言的是「引导
# 文本齐备」而非真跑一个 agent，见 spec Drawbacks）。
import os
import sys

from openagents import reviewer

PR = 105  # PR #105 / issue #104：e2e 新链路只交付骨架、未证明完整闭环的导火索。

code_task = reviewer._task_for(kind="code", pr_number=PR)
rfc_task = reviewer._task_for(kind="rfc", pr_number=PR)

# PR #105 复刻场景：每个缺口 → 新 rubric 里逐条对照的追问锚点（必须出现在 code review 任务全文里）。
GAPS = [
    (
        "只新增 openagents/executor.py 模块，但主流程无任何函数/状态分支走到它（无接线）",
        "主流程触发点",
        code_task,
    ),
    (
        "executor 只被自己的模块级单测调用，不被既有编排链路调用（dead / unwired module）",
        "被调用证据",
        code_task,
    ),
    (
        "声称 executor 会自动产出 result.md 并 commit 回 PR，但 diff 里没有任何自动产出/提交证据",
        "artifact 自动产生并 commit",
        code_task,
    ),
    (
        "没有正例证明 e2e PASS 放行、也没有反例证明 e2e FAIL 阻止 merge",
        "正例·反例",
        code_task,
    ),
    (
        "只测了 parser/render/decision 等局部函数，未覆盖真实集成路径",
        "集成路径而非局部函数",
        code_task,
    ),
    (
        "缺任一闭环证据时应判 REWORK，理由固定话术",
        "只实现骨架，未证明完整链路",
        code_task,
    ),
    (
        "设计闸前移把关：spec 承诺自动化链路却没把闭环讲清（触发时机/调用方/artifact 落点/失败路径/正·反例验收）",
        "自动化 spec 防过度承诺",
        rfc_task,
    ),
    (
        "声明诚信：宣称实现了自动化执行/门控能力却拿不出真实产物或集成证据",
        "宣称实现了自动化执行/门控能力",
        code_task,
    ),
]

# --- 离线铁证：review 任务文本逐条覆盖 PR #105 骨架冒充场景的每个缺口 ---
rows = []
for gap, anchor, task_text in GAPS:
    covered = anchor in task_text
    assert covered, f"review 任务未覆盖缺口：{gap}（缺锚点『{anchor}』——硬化未生效或被回退）"
    rows.append((gap, anchor, "code" if task_text is code_task else "rfc"))

# 闸别隔离双检：rfc 专属规则不漏进 code 闸、evidence 延伸不漏进 rfc 闸。
assert "自动化 spec 防过度承诺" not in code_task, "rfc 专属规则误漏进 code 闸"
assert "宣称实现了自动化执行/门控能力" not in rfc_task, "evidence 延伸误漏进 rfc 闸"

# --- 把真实 review 任务全文 + 场景对照渲染成可读 tracked 产物 ---
lines = []
lines.append("# Spec-0048 成果演练：reviewer rubric 对照 PR #105 骨架冒充场景\n")
lines.append(
    "> 本文件由 `scripts/e2e-spec-0048-anti-design-as-implementation-review.sh` 自动生成（成果测试，"
    "理念 8）。所有 review 任务文本均取自**真实产品代码** `openagents/reviewer._task_for(...)`，"
    "非人工誊抄。\n"
)
lines.append("## PR #105 复刻场景（骨架冒充完整实现）\n")
lines.append(
    "PR #105 声称把 e2e 升级为一条新链路（spec 声明 e2e 意图 → implement 写代码 → finalize_runbook "
    "定稿说明书 → executor agent 独立真跑 → 固化证据 → evidence_gate 门控 merge），并**确实**新增了 "
    "`executor.py`/`evidence_gate.py`、把证据闸插在 `review_code PASS` 后 `merge_pr` 前、补了一批"
    "模块级单测——**看起来像已实现**。但 diff/评论没有证明最关键的产品闭环：executor 是否被主流程"
    "**自动触发**？`result.md` 是否**自动产生并 commit**？evidence_gate 读的是真实证据还是假设证据？"
    "有没有正/反例 fixture？——即「架构骨架冒充完整实现」。\n"
)
lines.append("## 新 rubric 逐条覆盖每个缺口\n")
lines.append("| PR #105 场景缺口 | reviewer 对照追问锚点 | 挂在哪道闸 |")
lines.append("| --- | --- | --- |")
for gap, anchor, gate in rows:
    lines.append(f"| {gap} | `{anchor}` | {gate} |")
lines.append("")
lines.append(
    "结论：换成硬化后的 rubric，reviewer 拿到的对照清单**逐条命中** PR #105 骨架冒充场景的每个缺口，"
    "足以把这类 PR 导向 `VERDICT: REWORK`，理由「只实现骨架，未证明完整链路」——不再靠 reviewer "
    "恰好较真才发现。\n"
)
lines.append("## 真实 code review 任务全文（reviewer._task_for(kind=\"code\")）\n")
lines.append("```text")
lines.append(code_task)
lines.append("```")
lines.append("## 真实 rfc review 任务全文（reviewer._task_for(kind=\"rfc\")）\n")
lines.append("```text")
lines.append(rfc_task)
lines.append("```")

out = sys.argv[1]
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print(f"  [渲染] 真实 review 任务文本 + PR #105 场景对照已写入 tracked 产物：{out}")
print(f"  [文本断言] {len(GAPS)} 个缺口逐条被 review 任务覆盖 ✓（闸别隔离双检通过）")
PY

if [[ "${OPENAGENTS_E2E_REAL:-}" == "1" ]]; then
  echo
  echo "==> [可选] 真实冒烟（OPENAGENTS_E2E_REAL=1）"
  cat <<'REAL'
  真实冒烟步骤（需要真实 GitHub 仓库 + gh 登录 + 真 claude backend，会真实建 PR/评论、跑 reviewer）：
    1) 在 scratch 仓库造一个「骨架冒充完整实现」的 PR：只新增一个 executor/evidence_gate 骨架模块、
       把门控插在正确位置、只补模块级单测，但**不接主流程、不自动产出/commit artifact、无正反例 fixture**，
       PR 正文声称「已实现自动执行/门控链路」。
    2) 跑一次真 reviewer（code 闸，真 backend）：`oa vigil --once`（连跑到进入 code 评审）。
       预期（改后）：code 裁决为 `VERDICT: REWORK`，ISSUES 逐条点出 触发点缺失/未接线/artifact 未自动
       产出/无正反例/只测局部，理由含「只实现骨架，未证明完整链路」。
    3) 对照（改前）：同一 PR 的 code 闸易误判 PASS（模块存在 + 单测绿 + 门控位置对）。
  （此段仅打印指引，不自动执行，避免在 CI/离线环境误触真实 gh/claude。）
REAL
fi

echo
echo "✓ Spec-0048 端到端演示完成（默认离线、可重复、不触网、不调真实 LLM/gh；无 UI 可见面故不用浏览器 e2e）。"
