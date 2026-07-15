#!/usr/bin/env bash
# Spec-0046 端到端测试启动脚本：claude -p 流式调用 idle（停顿）看门狗。
#
# 本组给 ClaudeCodeBackend._run_claude_streaming 的阻塞式 stream-json 逐行读加一道 idle 看门狗守护线程：
#   - 判据是「有没有新输出行（进展）」而非总时长——健康长任务持续吐事件、idle 计时被每行刷新归零，看门狗永不
#     介入读、永不误杀（逐字节零回归）；只有真僵死（挂在对 Anthropic API 的网络请求、等永不到来的输入、进程
#     僵死）才会连续静默超 OPENAGENTS_CLAUDE_IDLE_TIMEOUT 秒 → terminate()→kill() 子进程 → 管道关闭 → 主循环
#     退出 → 抛**既有的** RuntimeError（带「停顿超时」详情），交既有 per-issue/per-round try/except 隔离（这轮
#     这个 agent 失败 → 跳过、下轮重试），绝不掀翻整个守夜进程。
#   - 再设一个远大于 idle 的绝对墙钟兜底 OPENAGENTS_CLAUDE_MAX_WALL，防「每 59s 吐一行垃圾但永不 result」的
#     病态流（idle 判据被它骗过，但总时长撞墙 → 同样杀 + 抛「墙钟超时」）。
#   与 vigil 既有硬超时（_AGENT_TIMEOUT_SECONDS，进展盲、只在 vigil 路径存在）互补：本 spec 落在 backend 层、
#   对所有调用方生效，以「进展」为判据快速判定僵死。#147 管 git 网络硬超时、本 issue 管 agent 流停顿，二者合起来
#   才让「vigil 再也不会无输出地永久卡死」成立。
#
# 形态：纯内部后端进程管理改动，无 product-facing 前端可导航、无对外可见产物；自检工具列表无浏览器 MCP，
# 故不设浏览器 e2e，改用相称的 hermetic 自动化测试（不调真实 claude）——用假 Popen（stdout 为可控节奏行序列
# 生成器 + threading.Event 制造长时间静默，terminate/kill 置 Event 解除阻塞 → 迭代结束）覆盖看门狗四类分支：
#   ① idle 触发（静默流 → terminate 后 kill 被调 + RuntimeError 含「停顿超时」）；
#   ② 墙钟触发（每 tick 吐一行但超绝对上限 → RuntimeError 含「墙钟超时」）；
#   ③ 零回归（连续正常流 → 看门狗不杀、输出/摘要/changed 与「看门狗全关」逐字节一致）；
#   ④ 访问器 effective_idle_timeout/effective_max_wall 解析 env、非法/空白/<=0 落缺省或关闭。
# 测试把 OPENAGENTS_CLAUDE_IDLE_TIMEOUT 设极小值（0.1s / 0.2s）使触发确定性、亚秒级，不真等。
#
# 全程**不触网、不调真实 claude/gh、不连真实 git 远端**。
#
# 用法：
#   bash scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] 静态检查（ruff lint + format --check）"
uv run --extra dev ruff check openagents/backends/claude_code.py tests/test_backend_claude_code.py
uv run --extra dev ruff format --check openagents/backends/claude_code.py tests/test_backend_claude_code.py

echo
echo "==> [2/3] 针对性 hermetic 测试（假 Popen，不触真实 claude）——覆盖看门狗四类分支"
uv run --extra dev pytest tests/test_backend_claude_code.py -q

echo
echo "==> [3/3] 成果演练：真实 backend 访问器 + 看门狗常量的可操作确认"
uv run python - <<'PY'
# Spec-0046 成果演练：用**真实**产品代码——effective_idle_timeout / effective_max_wall（派 claude 时实际
# 使用的阈值单一真相源）——确认两个 env 旋钮「说改就改」，且默认值宽到不误杀正常长任务。
import os

from openagents.backends import claude_code as cc

# 默认态（未设 env）：idle 300s / 墙钟 3600s，远宽于健康长任务，且墙钟远大于 idle。
os.environ.pop(cc.IDLE_TIMEOUT_ENV, None)
os.environ.pop(cc.MAX_WALL_ENV, None)
assert cc.effective_idle_timeout() == 300.0
assert cc.effective_max_wall() == 3600.0
assert cc.effective_max_wall() > cc.effective_idle_timeout()
print(f"  [默认] idle={cc.effective_idle_timeout():.0f}s  墙钟={cc.effective_max_wall():.0f}s  "
      f"(墙钟 > idle ✓，健康长任务不误杀 ✓)")

# 覆写态：两个旋钮各自生效（可操作）。
os.environ[cc.IDLE_TIMEOUT_ENV] = "180"
os.environ[cc.MAX_WALL_ENV] = "5400"
assert cc.effective_idle_timeout() == 180.0
assert cc.effective_max_wall() == 5400.0
print(f"  [覆写] export {cc.IDLE_TIMEOUT_ENV}=180 → idle={cc.effective_idle_timeout():.0f}s；"
      f"export {cc.MAX_WALL_ENV}=5400 → 墙钟={cc.effective_max_wall():.0f}s")

# 关闭态：<=0 视为关闭对应看门狗（返回 0.0）。
os.environ[cc.IDLE_TIMEOUT_ENV] = "0"
assert cc.effective_idle_timeout() == 0.0
print(f"  [关闭] export {cc.IDLE_TIMEOUT_ENV}=0 → idle 看门狗关闭 (0.0)")

print("  [文本断言] 阈值旋钮解析/默认/覆写/关闭全部符合预期 ✓")
PY

echo
echo "✓ Spec-0046 端到端演示完成（默认离线、可重复、不触网、不调真实 claude/gh）。"
