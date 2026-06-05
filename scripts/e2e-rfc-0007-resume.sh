#!/usr/bin/env bash
# RFC-0007 端到端测试启动脚本：守夜人恢复——激活 solving 为 resume 入口。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest，全程 mock，不触达真实 gh/claude。
#   2) 真实崩溃恢复演练（需显式 opt-in）—— 设 OPENAGENTS_E2E_REAL=1 时，在当前已绑定且
#      gh 已登录的仓库里**人为构造一条 start_rfc 起草阶段崩溃的残局**：
#        - 建一个带门控标签的 issue；
#        - 直接往 .openagents/state.json 写入一条 status=solving / pr_number=0 的孤儿 run；
#        - 用 `git worktree add` 复刻崩溃时残留的 issue worktree（带半成品草稿）。
#      然后跑 `openagents vigil --once`，断言守夜人发现段把它识别为「待恢复」，复用残留
#      worktree 从起草步重跑、最终开出 draft PR、state 翻到 rfc-review——全程无需人工删 state。
#
# 用法：
#   bash scripts/e2e-rfc-0007-resume.sh                          # 仅离线验证
#   OPENAGENTS_E2E_REAL=1 bash scripts/e2e-rfc-0007-resume.sh    # 含真实崩溃恢复演练（会真实开 PR）
#
# 可选环境变量（真实演练段）：
#   VIGIL_LABEL   门控标签，默认 openagents
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元/集成测试）"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ 离线验证通过。真实崩溃恢复演练已跳过（设 OPENAGENTS_E2E_REAL=1 开启）。"
  exit 0
fi

echo
echo "==> [2/2] 真实崩溃恢复演练：构造 solving/pr=0 残局 → vigil --once 自动恢复 → draft PR"
command -v gh >/dev/null || { echo "需要安装并登录 gh CLI"; exit 1; }
gh auth status >/dev/null || { echo "gh 未登录，请先 gh auth login"; exit 1; }
command -v claude >/dev/null || { echo "需要可用的 Claude Code CLI（claude）"; exit 1; }
command -v python3 >/dev/null || { echo "需要 python3 用于写 state.json"; exit 1; }

label="${VIGIL_LABEL:-openagents}"
base="main"
gh label create "$label" --description "openagents vigil 守夜人自动认领" >/dev/null 2>&1 || true

# --- 步骤 1：建带标签 issue（待恢复的目标）-------------------------------- #
title="[e2e] RFC-0007 崩溃恢复 $(date -u +%Y%m%dT%H%M%SZ)"
echo "--> 步骤 1：创建带标签 issue：$title（label=$label）"
uv run openagents issue "$title" \
  --body "由 e2e-rfc-0007 脚本创建：请在 README 末尾追加一行 'resume e2e ok'。" \
  --label "$label"
issue="$(gh issue list --label "$label" --state open --search "$title" --json number --jq '.[0].number')"
[[ -n "${issue:-}" && "$issue" != "null" ]] || { echo "未能定位刚创建的 issue"; exit 1; }
echo "    issue = #$issue"

branch="openagents/issue-$issue"
worktree=".openagents/worktrees/issue-$issue"

# --- 步骤 2：模拟「起草阶段崩溃」——残留 worktree + solving/pr=0 run ----- #
echo "--> 步骤 2：复刻崩溃残局（残留 worktree + state.json 里的 solving/pr=0 孤儿 run）"
git fetch origin "$base"
# 复刻 start_rfc 崩溃前已建好的隔离 worktree（half-drafted），但分支从未 push、PR 从未开。
git worktree remove --force "$worktree" 2>/dev/null || true
git branch -D "$branch" 2>/dev/null || true
git worktree add -b "$branch" "$worktree" "origin/$base"

# 直接把一条 solving/pr=0 的孤儿 run 写进 state.json（模拟 begin_run 落盘后即崩溃）。
python3 - "$issue" "$branch" <<'PY'
import json
import sys
from pathlib import Path

issue_number = int(sys.argv[1])
branch = sys.argv[2]
path = Path(".openagents/state.json")
data = {"runs": [], "cursors": {}}
if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
data.setdefault("runs", [])
data.setdefault("cursors", {})
data["runs"] = [r for r in data["runs"] if r.get("issue_number") != issue_number]
data["runs"].append(
    {
        "issue_number": issue_number,
        "branch": branch,
        "pr_number": 0,
        "pr_url": "",
        "status": "solving",
        "summary": "",
    }
)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"已写入孤儿 run：issue #{issue_number} status=solving pr_number=0")
PY

# --- 步骤 3：跑一轮守夜人，自动恢复 ------------------------------------- #
echo "--> 步骤 3：openagents vigil --once —— 发现段应把该 issue 识别为待恢复并 resume 续跑"
uv run openagents vigil --once --label "$label" --base "$base"

# --- 步骤 4：验证恢复结果（draft PR + state rfc-review）----------------- #
echo "--> 步骤 4：验证自动恢复结果"
pr="$(gh pr list --head "$branch" --state open --json number --jq '.[0].number')"
[[ -n "${pr:-}" && "$pr" != "null" ]] || { echo "✗ 恢复失败：未为 issue #$issue 开出 PR"; exit 1; }
echo "    ✓ 已开出 draft PR = #$pr"

status="$(python3 - "$issue" <<'PY'
import json
import sys
from pathlib import Path

issue_number = int(sys.argv[1])
data = json.loads(Path(".openagents/state.json").read_text(encoding="utf-8"))
rec = next((r for r in data["runs"] if r.get("issue_number") == issue_number), None)
print(rec["status"] if rec else "MISSING")
PY
)"
[[ "$status" == "rfc-review" ]] || { echo "✗ 恢复失败：state 状态为 '$status'，期望 rfc-review"; exit 1; }
echo "    ✓ state 已从 solving 翻到 rfc-review（带 PR #$pr）"

echo
echo "✓ 真实崩溃恢复演练完成：issue #$issue 的孤儿 solving run 被守夜人自动恢复 → draft PR #$pr。"
echo "  全程无需人工删 state.json——这正是 RFC-0007 的目标。"
echo "  注意：本脚本不会自动关闭 PR / 删 issue / 清 worktree，请按需在 GitHub 与本地清理。"
