#!/usr/bin/env bash
# Spec-0071 端到端测试启动脚本：把「单一 writer」文件所有权从设计期声明硬化为运行期可执行守卫
# （借鉴 Rust 所有权模型：aliasing XOR mutability）。
#
# 证明架构契约在离线确定性链路上成立（intent，见 spec e2e 块）：
#   - 解析层（T1）spec.ownership：从一个 spec 组的 tasks[].files 建单一 writer 索引（path → owner
#     Task），并据它判「一个 changeset 里有哪些写落在无主文件上」（越权写），生成物（spec md /
#     OVERVIEW / ARCHITECTURE）恒放行；
#   - 操作面（T2）spec CLI `ownership`：无 --check 打印所有权表；--check --group --changed 校验
#     changeset，有越权写则退出码 1（CI/harness 可调用的运行期守卫面）；
#   - 硬闸层（T3）runtime.gates.assert_writes_owned：raise 版硬闸，harness 交付后读实际改动集，越权
#     写 → GateError（issue #71 验收：越权写在编排层被拒，而非靠 reviewer 肉眼逮）。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯后端 + CLI**改动，无 product-facing 前端可导航；已自检
# 工具列表无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，沿用 Spec-0059/0060/0064 同款离线确定性
# 测法（针对性 pytest + CLI 真跑 + grep 锚点）。这是一处纯内部机制改动，相称的自动化测试即足以取证。
#
# 用法：
#   bash scripts/e2e-spec-0071-single-writer-ownership-guard.sh
set -euo pipefail

cd "$(dirname "$0")/.."

fail() {
  echo "✗ 锚点失败：$1" >&2
  exit 1
}

echo "==> [1/5] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/5] 针对性单测（解析器 + 硬闸 + CLI，不触真实 LLM/网络/仓库）"
uv run --extra dev pytest -q \
  tests/test_spec_ownership.py \
  tests/test_gates_ownership.py \
  tests/test_spec_cli.py

echo
echo "==> [3/5] spec ownership 真跑：本仓库的单一 writer 表含 0071 三个 Task 的归属"
OWN_TABLE="$(uv run spec ownership)"
echo "$OWN_TABLE" | grep -Eq "0071/T1[[:space:]]+openagents/spec/ownership\.py" \
  || fail "所有权表缺 0071/T1 → openagents/spec/ownership.py"
echo "$OWN_TABLE" | grep -Eq "0071/T2[[:space:]]+openagents/spec/cli\.py" \
  || fail "所有权表缺 0071/T2 → openagents/spec/cli.py"
echo "$OWN_TABLE" | grep -Eq "0071/T3[[:space:]]+openagents/runtime/gates\.py" \
  || fail "所有权表缺 0071/T3 → openagents/runtime/gates.py"

echo
echo "==> [4/5] spec ownership --check：声明文件与生成物放行、无主写被拒（退出码 1）"
uv run spec ownership --check --group 0071 \
  --changed "openagents/spec/ownership.py,docs/specs/OVERVIEW.md" \
  || fail "声明文件 + 生成物应放行（退出码 0）"
if uv run spec ownership --check --group 0071 --changed "openagents/spec/ownership.py,evil.py"; then
  fail "越权写 evil.py 应被拒（退出码 1），但命令返回 0"
fi

echo
echo "==> [5/5] grep 锚点：三层各自的 spec-id 溯源就位"
head -n 1 openagents/spec/ownership.py | grep -q "^# Spec-0071/T1" \
  || fail "openagents/spec/ownership.py 首行应为 '# Spec-0071/T1' 注释"
grep -q "def assert_writes_owned" openagents/runtime/gates.py \
  || fail "openagents/runtime/gates.py 缺硬闸 assert_writes_owned"
grep -q '"ownership"' openagents/spec/cli.py \
  || fail "openagents/spec/cli.py 缺 ownership 子命令"

echo
echo "✓ Spec-0071 离线确定性 e2e 全绿（T1 解析器 + T2 CLI + T3 硬闸）"
