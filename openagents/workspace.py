"""RFC-0005 T1: worktree 生命周期 + git 封装（从 orchestrator 抽出）。

把 issue 求解所需的 git/worktree 机制收敛到一个**只懂 git** 的模块：不感知
GitHub / backend / state。orchestrator 的原子操作借本模块完成「确保工作区」与
「提交推送」，从而把 git 关注点与 GitHub/状态等关注点解耦（RFC-0005 决策 3）。

RFC-0003 的 worktree 隔离与基线锁定语义在此原样保留：每 issue 独立 worktree、
从 `origin/<base>` 拉分支；iterate/续写复用既有 worktree、缺失则重建。所有 git 操作走 subprocess。

# Spec-0056/T1（决策 7 修订）：由「绝不 force-push」改为**绝不裸 force-push；允许
`--force-with-lease`，且仅限 agent 自己的工作分支（派单/迭代 `openagents/issue-<n>`、反向补全
`openagents/backfill-<slug>`），不得作用于 main / 受保护分支 / 他人分支**。交付（含分叉后
rebase 解冲突 + `push --force-with-lease`）
下放给 agent（prompt 软约束，见 orchestrator._GIT_DELIVERY_PROTOCOL）；harness 自身
**不执行** force-with-lease，只留一道只读硬闸 `assert_delivered`（断言成果真的推上远端）。
`commit_and_push` 保留原样，仅供 harness 自著文件（证据/runbook 等无 agent turn 的收尾）
的普通 push 路径，其行为逐字节不变。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# RFC-0003 决策 1：每 issue 的隔离 worktree 根目录（.openagents/ 已被 .gitignore 忽略）。
_WORKTREE_SUBDIR = Path(".openagents") / "worktrees"

# 2026-06-24 spec-markdown-form：spec 组 = 单文件 NNNN-slug.md（slug 以字母起，
# 排除 dated 设计文档 YYYY-MM-DD-*.md）。
_SPEC_GROUP_FILE_RE = re.compile(r"^\d{4}-[A-Za-z].*\.md$")


def _short_sha(*, sha: str) -> str:
    """# Spec-0056/T1：把完整 SHA 截成短摘要用于硬闸报错（空则显式标注，便于人工定位）。"""
    return sha[:12] if sha else "（空）"


class WorkspaceError(Exception):
    """git / worktree 操作失败时抛出，携带 git 的 stderr 摘要。"""


class Workspace:
    """RFC-0005 T1：只懂 git 的 worktree 工作区管理器（按 work_dir 构造）。"""

    def __init__(self, *, work_dir: Path) -> None:
        self._work_dir = Path(work_dir)

    def prepare(self, *, issue_number: int, branch: str, base: str) -> Path:
        """RFC-0003 决策 2/4：同步最新基线、幂等清理残留、再从 origin/<base> 拉新 worktree。"""
        path = self._worktree_path(issue_number=issue_number)
        # 决策 2：起草前先拉最新 base（fetch 不触碰用户当前检出）。
        self._git(args=["fetch", "origin", base], cwd=self._work_dir, check=True)
        # 决策 4：幂等清理同 issue 可能残留的 worktree 与本地分支（失败忽略）。
        self._git(
            args=["worktree", "remove", "--force", str(path)], cwd=self._work_dir, check=False
        )
        self._git(args=["worktree", "prune"], cwd=self._work_dir, check=False)
        self._git(args=["branch", "-D", branch], cwd=self._work_dir, check=False)
        # 一条 worktree add 同时完成「建隔离工作树」+「从最新 origin/<base> 拉分支」。
        self._git(
            args=["worktree", "add", "-b", branch, str(path), f"origin/{base}"],
            cwd=self._work_dir,
            check=True,
        )
        return path

    def ensure(self, *, issue_number: int, branch: str) -> Path:
        """RFC-0003 决策 5：复用既有 worktree；缺失则从远端分支重建。"""
        path = self._worktree_path(issue_number=issue_number)
        if path.exists():
            return path
        self._git(args=["fetch", "origin", branch], cwd=self._work_dir, check=False)
        self._git(args=["worktree", "add", str(path), branch], cwd=self._work_dir, check=True)
        return path

    def commit_and_push(self, *, worktree: Path, branch: str, message: str) -> None:
        """git add -A → commit → push（普通 push，绝不裸 force-push），均在 worktree 内。

        无改动可提交（后端可能未改文件）则跳过 commit（check=False），仍执行 push 以
        补推历史中尚未推送的 commit；远端已最新时 push 为幂等空操作。

        # Spec-0056/T1：本方法仍是**普通 push**，只服务 harness 自著文件（证据/runbook 等
        无 agent turn 的收尾）——分叉风险低。agent 自著路径的交付（含分叉后 rebase +
        force-with-lease）改由 agent 按交付协议自负、harness 以 assert_delivered 硬闸兜底。
        """
        self._git(args=["add", "-A"], cwd=worktree, check=True)
        self._git(args=["commit", "-m", message], cwd=worktree, check=False)
        self._git(args=["push", "-u", "origin", branch], cwd=worktree, check=True)

    def assert_delivered(self, *, worktree: Path, branch: str) -> None:
        """# Spec-0056/T1：head 前移硬闸——断言 agent 的成果真的推上远端 <branch>，不等即抛。

        agent 交付后（commit → 记 fetch 前 BASE → rebase 解冲突 → push --force-with-lease）由
        harness 调用：`git fetch origin <branch>`（check=False，远端无分支时不报错）后取
        `git rev-parse origin/<branch>` 与 `git rev-parse HEAD` 对比——相等 = 已交付放行；
        不等 = agent 自判完成却没推上去（正是 issue #140 的复现场景）→ 抛 WorkspaceError（携双
        SHA 摘要）。远端无该分支（rev-parse 失败）视作「未交付」→ 抛（agent 理应已 push 建分支）。

        纯读，不改工作区、不感知 GitHub/backend（守 RFC-0005「只懂 git」边界）；harness 绝不代
        agent force-push（决策 7），本闸只判「到没到」。routing（打 needs-human）留在 orchestrator。
        """
        self._git(args=["fetch", "origin", branch], cwd=worktree, check=False)
        remote = self._git(args=["rev-parse", f"origin/{branch}"], cwd=worktree, check=False)
        head = self._git(args=["rev-parse", "HEAD"], cwd=worktree, check=False)
        head_sha = head.stdout.strip()
        remote_sha = remote.stdout.strip()
        if remote.returncode != 0 or not remote_sha:
            raise WorkspaceError(
                f"分支 {branch} 未交付：远端无 origin/{branch}"
                f"（本地 HEAD={_short_sha(sha=head_sha)}，疑似 agent 未 push）"
            )
        if remote_sha != head_sha:
            raise WorkspaceError(
                f"分支 {branch} head 未前移、疑似未交付："
                f"origin/{branch}={_short_sha(sha=remote_sha)} ≠ 本地 HEAD={_short_sha(sha=head_sha)}"
            )

    def changed_spec_group(self, *, worktree: Path, base: str) -> Path | None:
        """Locate the spec group markdown file this branch touches, via git diff vs base.

        2026-06-24 spec-markdown-form：spec 组现为单文件 docs/specs/NNNN-slug.md。用
        `git diff --name-only origin/<base>...HEAD -- docs/specs/` 取本分支改动的首个组文件
        （排除 OVERVIEW.md / ARCHITECTURE.md / README.md / dated 设计文档），返回其在 worktree
        下的绝对路径；无则 None。只读 git，不抛业务错。
        """
        # 1. 列出本分支相对 base 改动的 docs/specs/ 文件（三点 diff：仅本分支侧的改动）。
        result = self._git(
            args=["diff", "--name-only", f"origin/{base}...HEAD", "--", "docs/specs/"],
            cwd=worktree,
            check=False,
        )
        # 2. 取首个 NNNN-slug.md 组文件（路径第三段；排除生成物/README/dated 文档）。
        for line in result.stdout.splitlines():
            rel = line.strip()
            if not rel:
                continue
            parts = Path(rel).parts
            if len(parts) == 3 and parts[0] == "docs" and parts[1] == "specs":
                if _SPEC_GROUP_FILE_RE.match(parts[2]):
                    return worktree / "docs" / "specs" / parts[2]
        return None

    def remote_branch_exists(self, *, branch: str) -> bool:
        """远端是否已存在该分支（`git ls-remote --heads`）。"""
        result = self._git(
            args=["ls-remote", "--heads", "origin", branch],
            cwd=self._work_dir,
            check=False,
        )
        return bool(result.stdout.strip())

    def _worktree_path(self, *, issue_number: int) -> Path:
        """RFC-0003 决策 1：每 issue 的 worktree 确定式派生路径（不持久化）。"""
        return self._work_dir / _WORKTREE_SUBDIR / f"issue-{issue_number}"

    def _git(self, *, args: list[str], cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        """在 cwd 内运行一条 git 子命令；check=True 时非零退出抛 WorkspaceError。"""
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            reason = result.stderr.strip() or f"git {' '.join(args)} 返回码 {result.returncode}"
            raise WorkspaceError(reason)
        return result
