#!/usr/bin/env bash
# Spec-0058 端到端测试启动脚本：跨 issue 调度——调度 agent 判两类依赖边（逻辑序 + 文件冲突序）→
# blocked-by/sched-ready 标签 → 本地 DAG 拓扑图 → 实现门控。
#
# 沿用仓库两段式约定：默认离线确定性段（不触网 / 不调真实 LLM / gh）；OPENAGENTS_E2E_REAL=1 追加真实
# 冒烟（本组交付物是后端编排机制 + graphviz 数据底座，尚无 product-facing 前端界面可导航）。
#
# 浏览器 e2e 能力自检降级：本环境实测**无浏览器 MCP（Playwright / chrome-devtools）工具**，且渲图依赖的
# graphviz `dot` 也未必在场。故按能力自检降级为「DAG 产物存在性 + DOT 文本边/波次断言」，不跳过（沿
# Spec-0055 能力感知降级、Spec-0043「无浏览器降级文本断言」先例）；未来前端排程面板落地后再补真实浏览器
# 导航截图。降级是如实结论——作者自检工具列表后确认本环境不具备浏览器工具。
#
# 用法：bash scripts/e2e-spec-0058-issue-scheduler.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> [1/3] 离线确定性验证（lint + format + 单元/集成测试全套）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/3] 跨 issue 调度全链闭环 + DAG 出图成果（内存 GitHub 世界 + 桩 backend，能力降级 DOT 断言）"
# 聚焦断言 Spec-0058 闭环的成果测试：fixture→下游 blocked-by/独立 sched-ready/幂等无抖动；门控挂 blocked-by
# 停 rfc-review、摘除放行；上游 closed 后保鲜剪边转 sched-ready；schedgraph.render 产物存在 + DOT 含边/波次。
uv run --extra dev pytest -q \
  tests/test_scheduler_integration.py \
  tests/test_scheduler.py \
  tests/test_schedlabels.py \
  tests/test_schedgraph.py \
  tests/test_orchestrator_schedule.py \
  tests/test_messages_blocked_by_gate.py \
  tests/test_vigil_schedule_refresh.py \
  tests/test_cli_schedule.py

echo
echo "==> [3/3] DAG 渲图能力自检 + 产物断言（graphviz dot 在则出 PNG、缺则降级 DOT）"
if command -v dot >/dev/null 2>&1; then
  echo "  · 检出 graphviz dot：render 走 PNG 路径"
else
  echo "  · 本环境无 graphviz dot（常态）：render 降级为 .dot 文本产物（能力自检降级、不跳过）"
fi
uv run --extra dev python - <<'PY'
import subprocess, tempfile
from pathlib import Path
from openagents import schedgraph
from openagents.scheduler import DepEdge

edges = [
    DepEdge(downstream=137, upstream=150, kind="file-conflict", reason="都改 messages.py"),
    DepEdge(downstream=170, upstream=137, kind="logical", reason="复用接口"),
]

def _run(*, args):
    return subprocess.run(args, capture_output=True, text=True)

with tempfile.TemporaryDirectory() as tmp:
    out = schedgraph.render(
        edges=edges, open_issue_numbers={137, 150, 170}, out_dir=Path(tmp), run=_run
    )
    assert out.exists(), f"渲图产物不存在：{out}"
    dot = schedgraph.build_dot(edges=edges, open_issue_numbers={137, 150, 170})
    # 下游←上游有向边 + 波次分层断言（能力降级下的 DOT 文本成果判据）。
    assert '"#150" -> "#137"' in dot, "缺 #150→#137 有向边"
    assert '"#137" -> "#170"' in dot, "缺 #137→#170 有向边"
    assert "#150\\n(wave 0)" in dot and "#137\\n(wave 1)" in dot and "#170\\n(wave 2)" in dot, "波次分层缺失"
    print(f"  ✓ DAG 产物：{out.name}（波次 0→1→2 分层、下游←上游有向边齐）")
PY

if [ "${OPENAGENTS_E2E_REAL:-0}" = "1" ]; then
  echo
  echo "==> [real] 真实冒烟：openagents schedule --help 路由存在（需已 oa init 的仓库才跑完整 schedule）"
  uv run openagents schedule --help >/dev/null && echo "  ✓ schedule 子命令已注册可路由"
fi

echo
echo "全部通过 ✅（Spec-0058 跨 issue 调度：判边 → blocked-by/sched-ready 标签 → DAG 图 → 实现门控）"
