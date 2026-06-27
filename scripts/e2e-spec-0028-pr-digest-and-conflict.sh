#!/usr/bin/env bash
# Spec-0028 端到端测试启动脚本：PR 自动化两处改进的 hermetic 闭环演练。
#
# 改进 1：spec 草稿 PR 正文内嵌组级 9 段总览的三段摘要（Summary / Motivation / Reference-level）。
# 改进 2：merge 真冲突派 coding agent 语义解冲突，分层降级 indexheal → agent → 人工。
#
# 两段，全程**不触网、不调真实 LLM、不碰真实 gh**：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 digest 抽取、conflict
#      resolve_branch 三分支、rebase/messages 分层降级接线的单测。
#   2) 离线闭环演练（默认执行）—— 用真实落盘的 spec 组演练 overview_digest_for_group 抽三段，
#      再用 fake backend / fake run 驱动 conflict.resolve_branch 的「干净合并 / agent 解决 / 残留
#      冲突回落」三条路径。无需任何凭证、CI 可跑、可重复。
#
# 用法：
#   bash scripts/e2e-spec-0028-pr-digest-and-conflict.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线闭环演练：digest 抽三段 + resolve_branch 分层降级（fake backend / fake run）"
uv run --extra dev python - <<'PY'
# Spec-0028/T4：hermetic 演练——不触网、不调真实 LLM、不碰真实 gh。
import tempfile
from pathlib import Path
from subprocess import CompletedProcess

from openagents.backends.base import AgentResult
from openagents.conflict import resolve_branch
from openagents.spec import model as spec_model
from openagents.spec.model import Group, Metadata, Overview, Task
from openagents.spec.signpost import overview_digest_for_group

# --- 改进 1：把一份真实 spec 组落盘，再抽组级总览三段摘要 -------------------- #
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    group = Group(
        number="0028",
        metadata=Metadata(
            title="PR 自动化两处改进", issue=79, slug="pr-digest-and-conflict-agent", summary="TL;DR"
        ),
        tasks=[Task(id="T1", title="digest", status="done", priority="P1")],
        overview=Overview(
            summary="源自实跑 PR #76 的两个相互独立的观察。",
            motivation="两个痛点都在 PR 自动化链路上：正文读不到设计、冲突一律甩人工。",
            reference_level="离线跑 `scripts/e2e-spec-0028-pr-digest-and-conflict.sh`（ruff + pytest）。",
            drawbacks="这一段不应进 digest（只取三段）。",
        ),
    )
    path = spec_model.group_path(
        specs_root=root, number="0028", slug="pr-digest-and-conflict-agent"
    )
    spec_model.dump_group(group=group, path=path)

    digest = overview_digest_for_group(group_path=path)
    assert digest is not None, "digest 不应为 None"
    assert digest.startswith("## spec 总览（摘自 docs/specs/0028-pr-digest-and-conflict-agent.md）")
    assert "### Summary" in digest and "源自实跑 PR #76 的两个相互独立的观察。" in digest
    assert "### Motivation" in digest and "### Reference-level explanation" in digest
    # 只取三段，不含 Drawbacks。
    assert "Drawbacks" not in digest and "不应进 digest" not in digest
    # spec 不可读 → None（零回归）。
    assert overview_digest_for_group(group_path=root / "missing.md") is None
    print("  ✓ 改进 1：overview_digest 抽取 Summary/Motivation/Reference-level 三段、缺失返 None")


# --- 改进 2：fake backend / fake run 驱动 resolve_branch 分层降级三条路径 ----- #
def cp(*, returncode=0, stdout=""):
    return CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr="")


class FakeGit:
    """伪 git：按命令分发；conflicts 可变，供 fake backend 解完冲突后清空。"""

    def __init__(self, *, merge_rc, conflicts):
        self.merge_rc = merge_rc
        self.conflicts = list(conflicts)
        self.calls = []

    def __call__(self, *, args, cwd, check):
        self.calls.append(args)
        if args[0] == "merge" and args[1] != "--abort":
            return cp(returncode=self.merge_rc)
        if args[:3] == ["diff", "--name-only", "--diff-filter=U"]:
            return cp(stdout="\n".join(str(c) for c in self.conflicts))
        return cp(returncode=0)


class FakeBackend:
    """伪 coding 后端：调 on_run 模拟 agent 语义解冲突（绝不调真实 LLM）。"""

    name = "fake"

    def __init__(self, *, on_run):
        self._on_run = on_run

    def run(self, *, work_dir, task, context):
        self._on_run(work_dir)
        return AgentResult(changed=True, summary="resolved")


with tempfile.TemporaryDirectory() as tmp:
    wt = Path(tmp)

    # 路径 A：干净合并（无需 agent）→ True。
    git_a = FakeGit(merge_rc=0, conflicts=[])
    assert resolve_branch(worktree=wt, base="main", backend=FakeBackend(on_run=lambda d: None), run=git_a) is True
    assert ["merge", "origin/main", "--no-edit"] in git_a.calls
    print("  ✓ 改进 2 路径 A：干净合并 → resolved（不调 agent）")

    # 路径 B：冲突 → agent 解干净 + 自测过 → add/commit → True。
    git_b = FakeGit(merge_rc=1, conflicts=["a.py"])

    def resolve_clean(d):
        (d / "a.py").write_text("clean\n", encoding="utf-8")
        git_b.conflicts = []

    assert resolve_branch(worktree=wt, base="main", backend=FakeBackend(on_run=resolve_clean), run=git_b) is True
    assert ["add", "-A"] in git_b.calls and ["commit", "--no-edit"] in git_b.calls
    print("  ✓ 改进 2 路径 B：agent 语义解决 + 自测过 → add/commit → resolved")

    # 路径 C：冲突 → agent 留残标（自测失败）→ merge --abort → False（回落人工）。
    git_c = FakeGit(merge_rc=1, conflicts=["a.py"])

    def leave_marker(d):
        (d / "a.py").write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>>\n", encoding="utf-8")
        git_c.conflicts = []

    assert resolve_branch(worktree=wt, base="main", backend=FakeBackend(on_run=leave_marker), run=git_c) is False
    assert ["merge", "--abort"] in git_c.calls and ["commit", "--no-edit"] not in git_c.calls
    print("  ✓ 改进 2 路径 C：残留冲突标记 / 自测失败 → merge --abort → 回落人工")

print()
print("✓ Spec-0028 hermetic 演练通过：改进 1 digest 抽取 + 改进 2 resolve 分层降级，全程不触网/无 LLM/无 gh。")
PY

echo
echo "✓ Spec-0028 端到端脚本完成（离线确定性 + 闭环演练两段全过）。"
