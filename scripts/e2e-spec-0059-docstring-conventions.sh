#!/usr/bin/env bash
# Spec-0059/T3 端到端测试启动脚本：注释规范对齐 PEP 257/PEP 8/Google —— 模块 + 函数 docstring 两层合规，
# 让流程生成的注释天然合规。
#
# 证明架构契约在离线确定性链路上成立（intent，见 spec e2e 块）：
#   - 提示词层（T2）：会生成/修改 Python 源码的 agent（implementer / drafter / replier）的 PROMPT 注入了
#     两层 docstring 规则锚点——模块层（Exports: / 禁 """# 写法 / spec-id 上移为 # 注释）+ 函数层
#     （Args: / Returns: / Raises: / 祈使句），并溯源三个权威标准（PEP 257 / PEP 8 / Google）；
#   - 样例层（T3）：runtime/engine.py 模块 docstring 去掉 """# 写法、spec-id 上移为文件顶部 # 注释行、
#     首行改干净英文摘要、补 Exports: 列 run_agent/AgentOutputError；recipes/vigil.py::run_vigil 函数
#     docstring 补 Args:（各参数）与 Raises:、summary 压成祈使句一行、spec 引用留第二行。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯文档 + 提示词 + 内部样例**改动，无 product-facing 前端可
# 导航；已自检工具列表无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，沿用 Spec-0060/0064 同款离线
# 确定性测法（针对性 pytest + grep 锚点）。这是一处纯内部改动，相称的自动化测试即足以取证。
#
# 注意（T1 未落地——不可违反的边界）：spec T1 要改的两份 code-comment-conventions.md 都在 `.claude/`
# 权限受控目录下（见 spec Drawbacks / Unresolved「.claude/ 写权限」）。本环境对写该目录有硬约束，故 T1
# 被显式跳过、本脚本不 grep 那两份文件；已落地的 T2（提示词）+ T3（样例）覆盖如下。
#
# 用法：
#   bash scripts/e2e-spec-0059-docstring-conventions.sh
set -euo pipefail

cd "$(dirname "$0")/.."

fail() {
  echo "✗ 锚点失败：$1" >&2
  exit 1
}

echo "==> [1/4] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] 针对性单测（提示词注入 + 样例 docstring，不触真实 LLM/网络/仓库）"
uv run --extra dev pytest -q \
  tests/test_agents_docstring_rule.py \
  tests/test_docstring_samples.py

echo
echo "==> [3/4] grep 锚点：提示词层（T2）两层 docstring 规则已注入三个代码生成 agent"
for f in openagents/agents/implementer.py openagents/agents/drafter.py openagents/agents/replier.py; do
  grep -q "Exports:" "$f" || fail "$f 缺模块层锚点 Exports:"
  # 源码里以转义 \"\"\"# 承载（写字面三引号会提前闭合 Template 串）；renders 到 .template 即 """#。
  grep -qF '\"\"\"#' "$f" || fail "$f 缺『禁 \"\"\"# 写法』措辞"
  grep -q "Args:" "$f" || fail "$f 缺函数层锚点 Args:"
  grep -q "Raises:" "$f" || fail "$f 缺函数层锚点 Raises:"
  grep -q "祈使句" "$f" || fail "$f 缺函数层锚点『祈使句』"
  grep -q "PEP 257" "$f" || fail "$f 缺权威标准引用 PEP 257"
done

echo
echo "==> [4/4] grep 锚点：样例层（T3）engine 模块 docstring 无 \"\"\"# + spec-id 上移 # 注释"
# engine.py 模块 docstring 不再有 """# 序列（# 会原样进 __doc__ 污染 help()）。
grep -q '"""#' openagents/runtime/engine.py && \
  fail 'openagents/runtime/engine.py 仍含 """# 写法（应上移 spec-id 为文件顶部 # 注释）'
# spec-id 落在文件顶部第一行的 # 注释。
head -n 1 openagents/runtime/engine.py | grep -q "^# Spec-0060/T2" || \
  fail "openagents/runtime/engine.py 首行应为 '# Spec-0060/T2' 注释"
# 模块 docstring 补了 Exports: 列导出对象。
grep -q "Exports:" openagents/runtime/engine.py || fail "engine 模块 docstring 缺 Exports:"

echo
echo "✓ Spec-0059 离线确定性 e2e 全绿（T2 提示词 + T3 样例；T1 因 .claude/ 写边界跳过）"
