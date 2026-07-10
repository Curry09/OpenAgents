#!/usr/bin/env bash
# Spec-0064/T1-T6 端到端测试启动脚本：收敛 recipes 到 vigil+issue —— 声明式 stages YAML 定义
# agent/human/skip 阶段归属 + 编排点按三态策略路由 + CI/e2e/review 打回回环 + recipes 层 6→3 收敛。
#
# 证明架构契约在离线确定性链路上成立（intent，见 spec e2e 块）：
#   - 配置层 .openagents/openagents.yml 作单一真源：三态每闸合法取值校验（conflict/merge 拒 skip、
#     rfc 仅 agent/skip、硬闸名进 stages reject）、「不许零闸」守卫拒 review:skip+merge:agent、
#     rfc:skip 显式告警、每仓 override 合并；
#   - 编排层 run_vigil 按注入 config 的三态断言 agent/human/skip 三分支；合并流水线 conflict→ci→
#     e2e→review→merge 序，conflict 在读 CI 前先判 mergeable；CI/e2e/review 失败经统一回环派
#     implementer 迭代（下轮从 conflict 重进）；确定性硬闸（round_cap）不受 stages 关；
#   - 收敛后 recipes/ 仅剩 {stages,vigil,backfill,__init__}.py；对已删 recipe（solve_issue/merge_pr/
#     poll_comments/rfc_lifecycle/fleet）与 agents.planner 的裸 import 零命中；stages 九原子函数均显式
#     收参（关键字-only）；identity.post_signed_comment 漏签 edit 补（非只 warn）闭合防自循环闭环。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯后端配置 + 编排 + CLI 收敛**，无 product-facing 前端
# 可导航；已自检工具列表：无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，沿用前四批离线确定性
# 测法（契约路由单测 + grep 锚点）。真实自主环冒烟（`oa vigil` 用最小 openagents.yml 跑通 issue→PR、
# PR CI 全绿）作为成果验收在 Phase-3 人验/runbook 记录，不塞进本离线脚本。
#
# 用法：
#   bash scripts/e2e-spec-0064-declarative-stages-converge.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] 配置层 + 编排层 + CLI 收敛针对性单测"
uv run --extra dev pytest -q \
  tests/test_agent_config.py \
  tests/test_recipe_stages.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_backfill.py \
  tests/test_cli_new_stack.py \
  tests/test_cli.py \
  tests/test_agents_prompts.py

echo
echo "==> [3/4] spec 校验 + 生成物无漂移"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/4] grep 锚点：recipes 层 6→3 收敛 + 零裸 import + 九原子显式收参 + 签名闭环"

fail() {
  echo "✗ 锚点失败：$1" >&2
  exit 1
}

# 4a. recipes/ 仅剩 {stages,vigil,backfill,__init__}.py（6→3 收敛）。
present="$(cd openagents/recipes && ls -1 *.py | sort | tr '\n' ' ')"
expected="__init__.py backfill.py stages.py vigil.py "
[ "$present" = "$expected" ] || fail "recipes/ 内容应为 {__init__,backfill,stages,vigil}.py，实为：$present"

# 4b. 全库对已删 recipe / agents.planner 的**裸 import** 零命中（docstring/注释里的文字提及不算）。
# 只扫 .py 源（--include）：排除 .pyc 缓存与本脚本自身的文字提及。
if grep -rnE --include='*.py' \
  "from openagents\.recipes\.(solve_issue|merge_pr|poll_comments|rfc_lifecycle|fleet) import|import openagents\.recipes\.(solve_issue|merge_pr|poll_comments|rfc_lifecycle|fleet)|from openagents\.recipes import [a-z_, ]*\b(solve_issue|merge_pr|poll_comments|rfc_lifecycle|fleet)\b|from openagents\.agents import [a-z_, ]*\bplanner\b|import openagents\.agents\.planner|agents\.planner\b" \
  openagents/ tests/ 2>/dev/null; then
  fail "存在对已删 recipe / agents.planner 的裸 import"
fi

# 4c. stages 九原子函数均显式收参（关键字-only：def 行或紧随其后一行含 '*,'）。
for fn in triage rfc implement review deliver conflict ci e2e merge; do
  grep -qE "^def ${fn}\(" openagents/recipes/stages.py || fail "stages.py 缺原子函数 ${fn}"
  sig="$(grep -A1 "^def ${fn}(" openagents/recipes/stages.py | tr -d ' \n')"
  case "$sig" in
    *"*,"*) : ;;
    *) fail "stages.${fn} 非关键字-only（缺 '*,'，可能引入位置参数）" ;;
  esac
done

# 4d. 三条 recipe 不直接 import 原始 github/workspace、无 subprocess 直调（走 utils 稳定面）。
for r in stages vigil backfill; do
  f="openagents/recipes/${r}.py"
  grep -nE 'import subprocess|subprocess\.' "$f" && fail "$f 含 subprocess 直接调用"
  grep -nE 'openagents\.workspace' "$f" && fail "$f 直接 import 原始 workspace（应走 utils）"
done

# 4e. 签名闭环：identity.post_signed_comment 同步后校验漏签 → 补签（非只 warn）。
grep -q "_verify_signature_or_fix" openagents/utils/identity.py \
  || fail "identity 缺同步后校验漏签的 _verify_signature_or_fix（约束③）"
# 补签走 post_comment（真补一条签名评论），非仅 warnings.warn。
awk '/def _verify_signature_or_fix/,/^def [^_]/' openagents/utils/identity.py | grep -q "post_comment" \
  || fail "_verify_signature_or_fix 未真补签（应 post_comment 补一条签名评论，非只 warn）"

echo "✓ grep 锚点全部通过：recipes 6→3、零裸 import、九原子显式收参、签名闭环"
echo
echo "✅ Spec-0064 离线 e2e 全绿"
