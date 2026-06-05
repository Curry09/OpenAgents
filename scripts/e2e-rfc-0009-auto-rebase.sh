#!/usr/bin/env bash
# RFC-0009 端到端测试启动脚本：合并后自动 rebase（update-branch）其余 open PR。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh。
#   2) 真实同步演练（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 时，在当前已绑定且
#      gh 已登录的仓库里构造两个 open PR、合并其一，再用 `openagents sync-prs --merged <n>`
#      把最新 main 并入另一个 PR，断言它多出一个「Merge ... into ...」提交（CI 因 synchronize
#      重新排队）。演示自动同步对落后 PR 的并入效果。
#
# 用法：
#   bash scripts/e2e-rfc-0009-auto-rebase.sh                          # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-rfc-0009-auto-rebase.sh    # 含真实同步演练（会真实开/合 PR）
#
# 可选环境变量（真实演练段）：
#   E2E_BASE   base 分支，默认 main
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ 离线验证通过。真实同步演练已跳过（设 OPENAGENTS_E2E_REAL=1 开启）。"
  exit 0
fi

echo
echo "==> [2/2] 真实同步演练：建两个 PR → 合并其一 → sync-prs → 断言另一 PR 被并入最新 main"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh 未登录，请先 gh auth login"; exit 1; }

base="${E2E_BASE:-main}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
br_a="openagents/e2e-0009-a-$stamp"   # 这个 PR 将被合并
br_b="openagents/e2e-0009-b-$stamp"   # 这个 PR 落后于 main，待 sync-prs 同步
seed="docs/e2e-rfc-0009-$stamp.md"

git fetch origin "$base"

# --- 步骤 1：从最新 base 拉两个分支，各提一个改动并开 PR --------------------- #
echo "--> 步骤 1：建分支 A/B 并各开一个 open PR（base=$base）"
git worktree prune
for br in "$br_a" "$br_b"; do
  git branch -D "$br" 2>/dev/null || true
done

git switch -c "$br_a" "origin/$base"
printf 'PR A change %s\n' "$stamp" >"${seed}.a"
git add "${seed}.a"
git commit -q -m "test(ci): e2e-0009 PR A $stamp"
git push -u origin "$br_a"
pr_a="$(gh pr create --head "$br_a" --base "$base" --title "[e2e-0009] PR A $stamp" \
  --body "将被合并以触发其余 PR 同步" --json number --jq .number 2>/dev/null \
  || gh pr list --head "$br_a" --state open --json number --jq '.[0].number')"
echo "    PR A = #$pr_a（分支 $br_a）"

git switch -c "$br_b" "origin/$base"
printf 'PR B change %s\n' "$stamp" >"${seed}.b"
git add "${seed}.b"
git commit -q -m "test(ci): e2e-0009 PR B $stamp"
git push -u origin "$br_b"
pr_b="$(gh pr create --head "$br_b" --base "$base" --title "[e2e-0009] PR B $stamp" \
  --body "落后于 main，待 sync-prs 自动并入" --json number --jq .number 2>/dev/null \
  || gh pr list --head "$br_b" --state open --json number --jq '.[0].number')"
echo "    PR B = #$pr_b（分支 $br_b）"

# 记录 PR B 同步前的 head commit，稍后对比是否新增了合并提交。
b_head_before="$(gh pr view "$pr_b" --json headRefOid --jq .headRefOid)"

# --- 步骤 2：合并 PR A，使 main 前进、PR B 落后 ----------------------------- #
echo "--> 步骤 2：合并 PR A（#$pr_a），main 前进 → PR B 落后于 main"
gh pr merge "$pr_a" --merge --delete-branch
git fetch origin "$base"

# --- 步骤 3：手动入口同步其余 open PR（排除刚合并的 PR A）------------------- #
echo "--> 步骤 3：openagents sync-prs --merged $pr_a —— 把最新 main 并入其余 open PR"
uv run openagents sync-prs --merged "$pr_a"

# --- 步骤 4：断言 PR B 的 head 已变（被并入最新 main，CI 因 synchronize 重排）-- #
echo "--> 步骤 4：验证 PR B 已被同步"
b_head_after="$(gh pr view "$pr_b" --json headRefOid --jq .headRefOid)"
if [[ "$b_head_before" == "$b_head_after" ]]; then
  echo "✗ 同步失败：PR B head 未变（$b_head_after）——未并入最新 main"
  exit 1
fi
echo "    ✓ PR B head 已从 ${b_head_before:0:8} 变为 ${b_head_after:0:8}（已并入最新 main，CI 将重跑）"

merge_state="$(gh pr view "$pr_b" --json mergeStateStatus --jq .mergeStateStatus)"
echo "    PR B mergeStateStatus = $merge_state"

echo
echo "✓ 真实同步演练完成：合并 PR A 后，sync-prs 自动把最新 main 并入 PR B。"
echo "  注意：本脚本不会自动关闭/删除 PR B（#$pr_b）与遗留分支，请按需在 GitHub 与本地清理。"
