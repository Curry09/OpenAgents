#!/usr/bin/env bash
# Spec-0067 端到端测试启动脚本：oa init 自动生成默认 .openagents/openagents.yml。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest（agent_config/cli 全 mock，不触真实 gh）。
#   2) init 冒烟（默认执行，纯离线、无网络）—— 在一个临时 git 仓库里真跑 `openagents init` 的
#      scaffold 落盘出口：首次生成 → 幂等不覆盖 → --force 重置回模板，全程断言。
#
# 用法：
#   bash scripts/e2e-spec-0067-init-scaffold-config.sh
set -euo pipefail

cd "$(dirname "$0")/.."
repo_root="$(pwd)"

echo "==> [1/2] 离线确定性验证（lint + format + agent_config/cli 单元测试）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/test_agent_config.py tests/test_cli.py

echo
echo "==> [2/2] scaffold 冒烟：临时 git 仓库里跑 init → 断言生成/幂等/--force"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
git init -q
git config user.email e2e@openagents.local
git config user.name e2e
git remote add origin https://github.com/openagents/e2e-smoke.git

cfg=".openagents/openagents.yml"

# --- ①首次：生成默认配置，且能被加载器解析 ---
# 直接调用 scaffold 出口（等价 `openagents init` 的落盘那步，绕开 gh 就绪校验，保持纯离线）。
run_init() { uv run --project "$repo_root" python - "$@" <<'PY'
import sys
from pathlib import Path
from openagents.utils.agent_config import scaffold_default_config, load_agent_config

force = "--force" in sys.argv[1:]
path = Path(".openagents/openagents.yml")
wrote = scaffold_default_config(path=path, force=force)
# 生成物必须能被既有加载器无错解析（round-trip）。
load_agent_config(path=path)
print("wrote" if wrote else "skipped")
PY
}

out="$(run_init)"
[[ "$out" == "wrote" ]] || { echo "✗ 首次 init 应生成配置，实际：$out"; exit 1; }
[[ -f "$cfg" ]] || { echo "✗ 未生成 $cfg"; exit 1; }
grep -q "OpenAgents 声明式配置" "$cfg" || { echo "✗ 生成物缺注释模板头"; exit 1; }
echo "✓ ①首次生成 $cfg 并成功解析"

# --- ②幂等：改一行后再跑，不覆盖用户改动 ---
printf 'stages:\n  review: human\n' > "$cfg"
out="$(run_init)"
[[ "$out" == "skipped" ]] || { echo "✗ 已存在时应跳过，实际：$out"; exit 1; }
grep -q "review: human" "$cfg" || { echo "✗ 幂等跑覆盖了用户改动"; exit 1; }
echo "✓ ②幂等：已存在则跳过、保留用户改动"

# --- ③--force：重置回打包模板 ---
out="$(run_init --force)"
[[ "$out" == "wrote" ]] || { echo "✗ --force 应重写，实际：$out"; exit 1; }
grep -q "OpenAgents 声明式配置" "$cfg" || { echo "✗ --force 未重置回模板"; exit 1; }
# 注意模板里带一行注释示例 `#   review: human`——只否定「未注释的」用户改动残留。
grep -Eq '^\s*review: human' "$cfg" && { echo "✗ --force 未清掉用户改动"; exit 1; }
echo "✓ ③--force：重置回打包默认模板"

echo
echo "✓ Spec-0067 端到端验证全部通过。"
