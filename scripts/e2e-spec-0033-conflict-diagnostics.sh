#!/usr/bin/env bash
# Spec-0033 端到端测试启动脚本：冲突/挂起通知带可定位诊断 + 合并扇出重发收敛的 hermetic 闭环演练。
#
# 本组让所有「合并冲突」通知从无诊断的静态罐头变成可定位诊断（冲突文件清单 + 关键 hunk 摘要），
# 并堵住唯一还在机械重发罐头的通道——合并扇出对已 needs-human 的 PR 跳过留言（把对话交回 #89 读侧）。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端**：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 conflictdiag 采集/格式化
#      （test_conflictdiag）、rebase 带诊断/抑制重发（test_rebase_conflict_diag）、messages merge 闸
#      blocker 带诊断 + 扇出注入诊断器（test_messages_conflict_diag）的单测。
#   2) 离线闭环演练（默认执行）—— 用 fake run（喂固定 git merge-tree 输出 + git show blob）驱动真实
#      conflictdiag 管线，再用 fake github.has_label / post_signed_comment 驱动真实 rebase_open_prs，
#      按轨迹演练：冲突→采集诊断→带文件清单+hunk 摘要的签名评论；已 needs-human 的 PR 扇出→跳过不
#      重发；诊断为空→退回泛化 CONFLICT_COMMENT。全程不触真实 git 远端 / gh / LLM。
#
# 用法：
#   bash scripts/e2e-spec-0033-conflict-diagnostics.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闭环演练：诊断采集 + 扇出带诊断/抑制重发整条轨迹（fake run / fake github）"
uv run --extra dev python - <<'PY'
# Spec-0033/T4：hermetic 演练——不触网、不调真实 LLM、不碰真实 gh、不连真实 git 远端。
# 直接替换 rebase 模块里的 github/identity 函数（非 pytest，故直接赋值；进程退出即销毁，无副作用）。
import subprocess

from openagents import conflictdiag, rebase
from openagents.github import PR, GithubError

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
    "<<<<<<< (ours)\n| 0032 | 评论闭环 |\n=======\n| 0033 | 冲突诊断 |\n>>>>>>> origin/main\n"
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
assert conflictdiag.format_blocker(diag=empty, step="x") == rebase.CONFLICT_COMMENT
print("  ✓ 步骤 2：诊断为空（干净合并/采集失败）→ 退回泛化 CONFLICT_COMMENT，绝不上抛")

# --- 接线 fake github / identity（hermetic），驱动真实 rebase.rebase_open_prs ----------------- #
state_box = {"labels": set()}  # PR5 是否已 needs-human
comments = []


def fake_list_open_prs():
    return [PR(number=5, url="u/pull/5")]


def fake_update_branch(*, pr_number, rebase):
    raise GithubError("merge conflict")  # 扇出对 PR5 撞冲突，回落降级路径


def fake_has_label(*, pr_number, name):
    return name in state_box["labels"]


def fake_post_comment(*, pr_number, body):
    comments.append({"pr_number": pr_number, "body": body})


rebase.github.list_open_prs = fake_list_open_prs
rebase.github.update_branch = fake_update_branch
rebase.github.has_label = fake_has_label
rebase.github.post_comment = fake_post_comment


def diagnose(*, pr_number):
    # 真实 conflictdiag.format_blocker（注入 fake run），不取真实 PR head / 不 fetch 远端。
    d = conflictdiag.collect(base="main", head="feature", run=fake_run_conflict)
    return conflictdiag.format_blocker(diag=d, step="自动合并目标分支 origin/main 时")


# --- 步骤 3：PR5 尚未 needs-human → 扇出首发一条带诊断的签名评论 ----------------------------- #
state_box["labels"] = set()
comments.clear()
events = rebase.rebase_open_prs(agent_id="agent-self", diagnose=diagnose)
assert events == [{"pr_number": 5, "result": rebase.RESULT_CONFLICT}], events
assert len(comments) == 1
assert "冲突文件清单" in comments[0]["body"]
assert "openagents:agent=agent-self" in comments[0]["body"]  # 盖了本实例签名
print("  ✓ 步骤 3：未 needs-human 的 PR → 扇出留一条带诊断（清单+hunk）的签名评论")

# --- 步骤 4：PR5 已 needs-human（人已介入、#89 读侧在管）→ 扇出跳过不重发 -------------------- #
state_box["labels"] = {rebase.github.BLOCKED_LABEL}
comments.clear()
events = rebase.rebase_open_prs(agent_id="agent-self", diagnose=diagnose)
assert events == [{"pr_number": 5, "result": rebase.RESULT_CONFLICT_SUPPRESSED}], events
assert comments == []  # 不再贴第二/三句罐头淹没人的追问
print("  ✓ 步骤 4：已 needs-human 的 PR → 扇出跳过留言（不机械重发），对话交回 #89 读侧闭环")

# --- 步骤 5：无诊断器（diagnose=None，如手动 sync-prs）→ 退回静态 CONFLICT_COMMENT ----------- #
state_box["labels"] = set()
comments.clear()
events = rebase.rebase_open_prs(agent_id="agent-self")  # diagnose 缺省 None
assert events == [{"pr_number": 5, "result": rebase.RESULT_CONFLICT}], events
assert rebase.CONFLICT_COMMENT in comments[0]["body"]
print("  ✓ 步骤 5：无诊断器（手动 sync-prs）→ 退回静态 CONFLICT_COMMENT，向后兼容")

print()
print("✓ Spec-0033 hermetic 演练通过：诊断采集→带诊断评论→已 needs-human 抑制重发→空诊断降级，")
print("  全程不触网/无 LLM/无 gh/无真实 git 远端。")
PY

echo
echo "✓ Spec-0033 端到端脚本完成（离线确定性 + 闭环演练两段全过）。"
