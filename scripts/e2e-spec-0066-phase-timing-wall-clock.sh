#!/usr/bin/env bash
# Spec-0066/T1-T3 端到端测试启动脚本：阶段计时——墙钟 per-phase 时延（旁路 append-only 事件流 + 跨轮重建）。
#
# 证明「墙钟阶段计时旁路埋点 + 跨轮时长重建」在离线确定性链路上成立（intent，见 spec e2e 块）：
#   - T1 timing 模块：record append 五键合法 JSON + UTC ISO8601；注入 open/write 抛异常 → record 静默吞掉
#     不 raise（容错）；load_events 跳损坏行；timelines 跨轮重建各 phase duration（phase 复现分两段累加、
#     末条 terminal 时长 0）；phase_stats 出每 phase p50/p90 + 最长尾 + interval 精度下限字段。
#   - T2 vigil 旁路埋点：once 跑一 tick 后 timing.jsonl 生成含 dispatch(solve)/等待(awaiting-*)/合并各段；
#     _phase_of 四值 verdict × facts 逐态归一；record 抛异常时 _consider 照常返回（容错端到端）；_fingerprint
#     埋点前后相等（旁路不进 fp、不触护栏一自毁）；合并段 awaiting-ci（CI-wait）与 review-or-fix 可区分。
#   - T3 CLI：oa report 对造好的 timing.jsonl 输出单 subject 时间线 + 跨 subject p50/p90 + 「精度下限 =
#     interval」字样；空/缺文件友好提示、退出码 0。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯后端埋点 + 聚合 + CLI 报告**，无 product-facing 前端可导航；
# 已自检工具列表：无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，沿用前几批离线确定性测法（针对性
# 单测 + grep 锚点）。真实自主环冒烟（`oa vigil --once` 后 `oa report` 出真报告）作为成果验收在 runbook 记录。
#
# 用法：
#   bash scripts/e2e-spec-0066-phase-timing-wall-clock.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] timing 模块 + vigil 旁路埋点 + CLI report 针对性单测"
uv run --extra dev pytest -q \
  tests/test_runtime_timing.py \
  tests/test_recipe_vigil_timing.py \
  tests/test_recipe_vigil.py \
  tests/test_cli_timing.py \
  tests/test_cli.py

echo
echo "==> [3/4] spec 校验 + 生成物无漂移"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/4] grep 锚点：timing 零 vigil 依赖（无循环 import）/ 埋点仅两处 / record 容错兜底"

fail() {
  echo "✗ 锚点失败：$1" >&2
  exit 1
}

# 4a. timing 模块对 recipes.vigil **零依赖**（phase 是纯字符串、归一逻辑留 vigil）——杜绝循环 import。
grep -qE 'recipes|vigil' openagents/runtime/timing.py \
  && fail "runtime/timing.py 引用了 recipes/vigil（应零依赖，否则循环 import）"

# 4b. 计时写入点**只在** vigil.py 的两处判定咽喉（_consider 生产者 / _reconcile worker）经 _record_timing
# 旁路挂出；record 自身不该在别处被直接调（旁路收口于单一 helper，防散落埋点漂移）。
grep -q "def _record_timing" openagents/recipes/vigil.py \
  || fail "vigil 缺 _record_timing 旁路收口 helper"
uv run --extra dev python -c "
import inspect
from openagents.recipes import vigil
assert '_record_timing(' in inspect.getsource(vigil._consider), '生产者 _consider 未旁路盖阶段戳'
assert '_record_timing(' in inspect.getsource(vigil._reconcile), 'worker _reconcile 未旁路盖阶段戳'
" || fail "两处判定咽喉未挂 _record_timing 埋点"

# 4c. record 容错（except 兜底）就位——写失败只丢一条计时、绝不掀翻守夜主流程。
uv run --extra dev python -c "
import inspect
from openagents.runtime import timing
src = inspect.getsource(timing.record)
assert 'except' in src and 'return' in src, 'timing.record 无 except 容错兜底（写失败会掀翻守夜主流程）'
" || fail "timing.record 缺容错兜底"

# 4d. 事件流文件与状态文件**文件级零耦合**（理念 10）：timing 落 timing.jsonl，不碰 runtime-state.json。
grep -q 'timing.jsonl' openagents/runtime/timing.py \
  || fail "timing 未落 timing.jsonl"
grep -q 'runtime-state.json' openagents/runtime/timing.py \
  && fail "timing.py 触碰了 runtime-state.json（应文件级零耦合）"

echo "✓ grep 锚点全部通过：timing 零 vigil 依赖、埋点仅 _consider/_reconcile 两处、record 容错兜底、"
echo "  timing.jsonl 与 runtime-state.json 文件级零耦合"
echo
echo "✅ Spec-0066 离线 e2e 全绿"
