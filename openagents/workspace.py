"""RFC-0005 T1: worktree 生命周期 + git 封装（从 orchestrator 抽出）。

把 issue 求解所需的 git/worktree 机制收敛到一个**只懂 git** 的模块：不感知
GitHub / backend / state。orchestrator 的原子操作借本模块完成「确保工作区」与
「提交推送」，从而把 git 关注点与 GitHub/状态等关注点解耦（RFC-0005 决策 3）。

RFC-0003 的 worktree 隔离与基线锁定语义在此原样保留：每 issue 独立 worktree、
从 `origin/<base>` 拉分支；iterate/续写复用既有 worktree、缺失则重建；
push 一律普通 push（决策 7：绝不 force-push）。所有 git 操作走 subprocess。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# RFC-0003 决策 1：每 issue 的隔离 worktree 根目录（.openagents/ 已被 .gitignore 忽略）。
_WORKTREE_SUBDIR = Path(".openagents") / "worktrees"


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
        """git add -A → commit → push（决策 7：普通 push，绝不 force-push），均在 worktree 内。

        无改动可提交（后端可能未改文件）则跳过 commit（check=False），仍执行 push 以
        补推历史中尚未推送的 commit；远端已最新时 push 为幂等空操作。
        """
        self._git(args=["add", "-A"], cwd=worktree, check=True)
        self._git(args=["commit", "-m", message], cwd=worktree, check=False)
        self._git(args=["push", "-u", "origin", branch], cwd=worktree, check=True)

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
