#!/usr/bin/env bash
# Spec-0044 端到端测试启动脚本：「端到端跑真 app 并截图」验证 skill（issue #113）。
#
# 两段：
#   1) 离线确定性段（默认执行，hermetic，无网络 / 无真 claude）—— ruff lint/format + pytest 全套，
#      再 grep 断言三处落地：(a) 移植的 SKILL.md 含核心纪律锚点（反惰性 / rationalization /
#      诚实报阻塞 / 完成判据），证明是原文移植而非空壳；(b) reviewer.py 含「宣称验证过但无证据
#      → REWORK」检查项字样；(c) orchestrator.py 实现 prompt 含三分类判断字样 + skill 指路。
#   2) 浏览器自演示段（成果测试，理念 8；说明书形式，需 agent 用 browser MCP 执行）—— 对 tracked
#      的自包含参考页 reference-app.html 走「导航 → 交互 → 截图 → console/network 断言」闭环，
#      截图入 docs/evidence/spec-0044/，含 RED 反验对照。无 browser MCP 时诚实报阻塞、不用离线段顶替。
#
# 用法：
#   bash scripts/e2e-spec-0044-e2e-screenshot-skill.sh
set -euo pipefail

cd "$(dirname "$0")/.."

SKILL_DIR="docs/skills/end-to-end-ui-screenshots"
SKILL_MD="$SKILL_DIR/SKILL.md"
REF_APP="$SKILL_DIR/examples/reference-app.html"

echo "==> [1/2] 离线确定性段（lint + format + 单元/集成测试 + grep 锚点断言）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "  -- grep 断言 (a)：SKILL.md 原文移植锚点（非空壳）"
test -f "$SKILL_MD" || { echo "✗ 缺 $SKILL_MD"; exit 1; }
for anchor in "反惰性" "rationalization" "诚实报阻塞" "完成判据" \
              "case 2 vs case 3" "端到端就走可视化那条路"; do
  grep -qF "$anchor" "$SKILL_MD" || { echo "✗ SKILL.md 缺锚点：$anchor"; exit 1; }
done
# runbook 范例 + 模板齐备（原文移植 + 填空模板）。
test -f "$SKILL_DIR/references/north-coder.md" || { echo "✗ 缺 north-coder.md"; exit 1; }
grep -qF "项目专属命令" "$SKILL_DIR/references/_runbook-template.md" \
  || { echo "✗ _runbook-template.md 缺「项目专属命令」分区"; exit 1; }
grep -qF "通用方法" "$SKILL_DIR/references/_runbook-template.md" \
  || { echo "✗ _runbook-template.md 缺「通用方法」分区"; exit 1; }
echo "  ✓ SKILL.md / north-coder.md / _runbook-template.md 锚点全命中"

echo
echo "  -- grep 断言 (b)：reviewer.py 含「宣称验证过但无证据 → REWORK」检查项"
grep -qF "宣称验证过但无证据 → REWORK" openagents/reviewer.py \
  || { echo "✗ reviewer.py 缺无证据=REWORK 检查项"; exit 1; }
echo "  ✓ reviewer rubric 含无证据=REWORK 检查项"

echo
echo "  -- grep 断言 (c)：orchestrator.py 实现 prompt 含三分类判断 + skill 指路"
grep -qF "分三类" openagents/orchestrator.py \
  || { echo "✗ orchestrator.py 缺三分类判断字样"; exit 1; }
grep -qF "$SKILL_DIR/" openagents/orchestrator.py \
  || { echo "✗ orchestrator.py 缺 skill 原文指路"; exit 1; }
echo "  ✓ orchestrator 派单/实现 prompt 含三分类判断 + skill 指路"

echo
echo "  ✓ 离线段全绿（ruff + pytest + 全部 grep 锚点命中）"

echo
echo "==> [2/2] 浏览器自演示段（成果测试；需 agent 用 playwright / chrome-devtools MCP 执行）"
test -f "$REF_APP" || { echo "✗ 缺参考页 $REF_APP"; exit 1; }
REF_URL="file://$(pwd)/$REF_APP"
cat <<EOF
  参考页（file:// 打开，不碰任何生产端口/数据）：
    $REF_URL

  由 agent 用 browser MCP 走 skill 规定的闭环（本脚本不驱动浏览器，仅给出说明书）：
    1. navigate  → 打开 $REF_URL
    2. snapshot  → 取「应用配置」按钮 + #status 元素句柄
    3. interact  → click「应用配置」按钮
    4. wait_for  → 等 #status 出现「已生效」文案
    5. screenshot→ 截图存入 docs/evidence/spec-0044/（tracked 证据目录）
    6. console·network 断言 → list_console_messages 无 error；list_network_requests 无失败请求
    7. RED 反验对照 → 临时把 reference-app.html 里 status.textContent="已生效" 改成不赋值，
                     重跑一遍：wait_for 应超时 / 截图显示旧态（空 #status），证明证据非空过；
                     反验脚手架事后 revert、不进 PR。

  若本环境客观无 browser MCP / 无显示：按 skill 的诚实纪律明写
    「因无浏览器自动化，浏览器自演示段未执行」阻塞项，不用离线段顶替声称已跑。
EOF

echo
echo "✓ Spec-0044 离线段通过；浏览器自演示段说明书已输出（按上述步骤取证入库）。"
