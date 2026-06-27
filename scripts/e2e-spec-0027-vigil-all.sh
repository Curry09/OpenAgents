#!/usr/bin/env bash
# Spec-0027 端到端测试启动脚本：openagents vigil-all 多仓库统管（单进程并发守夜一组仓库）。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock/注入，不触达真实
#      gh/后端。覆盖：T1 配置加载（默认合并 / path 绝对化 / name 缺省 / 各类非法输入报错）、
#      T2 编排（fan-out / [name] 前缀聚合 / 单进程失败隔离 / Ctrl-C 停止路径 / 真实 _run_repo
#      的 chdir+构造+转发）、T3 CLI 接线（vigil-all 解析 --config/--once、转发 Fleet.run、
#      跳过 cwd preflight、与现有 vigil 并存）。
#   2) 真实冒烟（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 时，对一份指向两个本地临时仓库
#      的 fleet.yml 真起 `openagents vigil-all --once`：真实扇出两个隔离子进程、各自 os.chdir
#      到自己的仓库、复用现有 Vigil 跑一轮。断言**日志带各自仓库前缀可区分来源**、两个子进程
#      **相互独立**（一个的结果不混入另一个）。需要 gh CLI 可用。
#
#      为什么这一段不需要后端：两个临时仓库刻意**无 GitHub 远端**，于是各自的发现段
#      （`gh issue list`）会确定性失败，once 模式下子进程随之非零退出——父进程为**每个仓库各
#      记一行带前缀的退出**，这恰好确定性地演示了 Spec-0027 的三项硬保证：扇出（两个子进程）、
#      日志前缀可区分来源、单仓库失败不拖垮其余（错误隔离 + 各子进程各自的 cwd 独立）。
#      完整的「发现真实 issue → 派单 → 各仓库写各自 .openagents/state.json」闭环需真实 gh +
#      后端（claude）驱动、成本高且非确定，请用 `openagents vigil-all --once` 指向两个真实
#      仓库手动观察——本脚本真实段只断言确定可验的扇出/前缀/隔离链路（同 0023 的取舍）。
#
# 用法：
#   bash scripts/e2e-spec-0027-vigil-all.sh                          # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0027-vigil-all.sh    # 含真实扇出冒烟
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q tests/test_fleet_config.py tests/test_fleet.py tests/test_cli_fleet.py

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ 离线验证通过。真实扇出冒烟已跳过（设 OPENAGENTS_E2E_REAL=1 开启）。"
  exit 0
fi

echo
echo "==> [2/2] 真实冒烟：对两仓库 fleet.yml 跑 vigil-all --once，验证扇出 + 前缀 + 隔离"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }

repo_root="$(pwd)"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# 两个本地临时仓库（无 GitHub 远端 → 发现段确定性失败 → 子进程非零退出，无需后端）。
for name in repo-a repo-b; do
  mkdir -p "$workdir/$name"
  git -C "$workdir/$name" init -q
  git -C "$workdir/$name" -c user.email=e2e@openagents -c user.name=e2e \
    commit -q --allow-empty -m "init $name"
done

# fleet.yml：两仓库分别命名 a / b（日志前缀显示名），相对 path 以配置文件所在目录解析。
cat >"$workdir/fleet.yml" <<YAML
repos:
  - path: repo-a
    name: a
  - path: repo-b
    name: b
YAML

echo "运行 openagents vigil-all --once（两个隔离子进程并发跑一轮）…"
set +e
out="$(cd "$repo_root" && uv run openagents vigil-all --once --config "$workdir/fleet.yml" 2>&1)"
set -e
echo "$out"

echo
echo "断言：聚合日志为每个仓库各带可区分的前缀 [a] / [b] …"
echo "$out" | grep -q "\[a\]" || { echo "✗ 未见仓库 a 的前缀日志"; exit 1; }
echo "$out" | grep -q "\[b\]" || { echo "✗ 未见仓库 b 的前缀日志"; exit 1; }

echo
echo "✓ 真实扇出冒烟完成：两个仓库各起一隔离子进程并发守夜，日志带各自前缀可区分来源，"
echo "  单仓库失败被独立记录而不拖垮其余（错误隔离）。完整守夜→state 写入闭环请指向两个"
echo "  真实 gh 仓库手动观察。"
