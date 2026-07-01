#!/usr/bin/env bash
# Spec-0034 端到端测试启动脚本：冲突/挂起通知带可定位诊断的 hermetic 闭环演练。
#
# 本组让所有「合并冲突」通知从无诊断的静态罐头变成可定位诊断（冲突文件清单 + 关键 hunk 摘要）。
# 注：拉式同步重构（删 push 扇出 / rebase 模块）后，原「合并扇出带诊断 / 抑制重发」演练已随扇出移除；
# 诊断采集与格式化（conflictdiag）保留，仍服务 merge 闸挂起评论的「卡在哪」段。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端**：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 conflictdiag 采集/格式化
#      （test_conflictdiag）、messages merge 闸 blocker 带诊断（test_messages_conflict_diag）的单测。
#   2) 离线闭环演练（默认执行）—— 用 fake run（喂固定 git merge-tree 输出 + git show blob）驱动真实
#      conflictdiag 管线：冲突→采集诊断→带文件清单+hunk 摘要的「卡在哪」段；诊断为空→退回泛化
#      CONFLICT_COMMENT。全程不触真实 git 远端 / gh / LLM。
#
# 用法：
#   bash scripts/e2e-spec-0034-conflict-diagnostics.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闭环演练：诊断采集 + 格式化（fake run，真实 conflictdiag 管线）"
uv run --extra dev python - <<'PY'
# Spec-0034/T4：hermetic 演练——不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端。
import subprocess

from openagents import conflictdiag

# 实测 git 2.39 `git merge-tree --write-tree` 冲突 stdout：首行 tree OID + stage 行 + 信息段。
MERGE_TREE_CONFLICT = (
    "024c0515807b89dc52f29f54d0025ae41eee4aca\n"
    "100644 83db48f84ec878fbfb30b46d16630e944e34f205 1\tdocs/specs/OVERVIEW.md\n"
    "100644 39aa102c5896143ea31aaf3404efe59b6b91f62e 2\tdocs/specs/OVERVIEW.md\n"
    "100644 f80d8ff774d980e0c4b0899c6f0e6a737b06938e 3\tdocs/specs/OVERVIEW.md\n"
    "\nAuto-merging docs/specs/OVERVIEW.md\n"
    "CONFLICT (content): Merge conflict in docs/specs/OVERVIEW.md\n"
)
MERGE_TREE_CLEAN = "024c0515807b89dc52f29f54d0025ae41eee4aca\n"
BLOB_WITH_CONFLICT = (
    "| 0031 | merge 解挂 |\n"
    "<<<<<<< (ours)\n| 0032 | 评论闭环 |\n=======\n| 0034 | 冲突诊断 |\n>>>>>>> origin/main\n"
)


def _cp(*, returncode, stdout):
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr="")


def fake_run_conflict(*, args):
    # fake git：merge-tree 给冲突输出、show 给含冲突标记的 blob，其余成功——不触真实 git 远端。
    if args[0] == "merge-tree":
        return _cp(returncode=1, stdout=MERGE_TREE_CONFLICT)
    if args[0] == "show":
        return _cp(returncode=0, stdout=BLOB_WITH_CONFLICT)
    return _cp(returncode=0, stdout="")


def fake_run_clean(*, args):
    if args[0] == "merge-tree":
        return _cp(returncode=0, stdout=MERGE_TREE_CLEAN)
    return _cp(returncode=0, stdout="")


# --- 步骤 1：conflictdiag.collect + format_blocker 真实管线（注入 fake run）------------------- #
diag = conflictdiag.collect(base="main", head="feature", run=fake_run_conflict)
assert diag.files == ["docs/specs/OVERVIEW.md"], diag.files
assert "<<<<<<<" in diag.hunks["docs/specs/OVERVIEW.md"]
blocker = conflictdiag.format_blocker(diag=diag, step="自动合并目标分支 origin/main 时")
assert "冲突文件清单（1）" in blocker
assert "docs/specs/OVERVIEW.md" in blocker
assert "关键 hunk 摘要" in blocker
print("  ✓ 步骤 1：collect 采出冲突文件清单 + 关键 hunk 摘要，format_blocker 渲出带诊断「卡在哪」段")

# --- 步骤 2：诊断为空（干净合并）→ format_blocker 退回泛化 CONFLICT_COMMENT（安全降级）-------- #
empty = conflictdiag.collect(base="main", head="feature", run=fake_run_clean)
assert empty.is_empty()
assert conflictdiag.format_blocker(diag=empty, step="x") == conflictdiag.CONFLICT_COMMENT
print("  ✓ 步骤 2：诊断为空（干净合并/采集失败）→ 退回泛化 CONFLICT_COMMENT，绝不上抛")

print()
print("✓ Spec-0034 hermetic 演练通过：诊断采集→带诊断「卡在哪」段→空诊断降级，")
print("  全程不触网/无 LLM/无 gh/无真实 git 远端。")
PY

echo
echo "✓ Spec-0034 端到端脚本完成（离线确定性 + 闭环演练两段全过）。"
