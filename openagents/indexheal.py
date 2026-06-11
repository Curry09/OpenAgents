"""issue #48：索引冲突自愈——同步 base 后自动重渲 OVERVIEW。

每新增一个 spec，`spec render` 都会重渲整张 `docs/specs/OVERVIEW.md`，于是并发 PR 在这个
生成文件上必然文本冲突。合并后自动同步（`github.update_branch`，服务端合并）一撞上即留
「请手动 rebase」，把一个纯机械冲突甩给人——这是 needs-human 积压的来源之一。

本模块在 `update_branch` 冲突后做**本地兜底**：在 PR head 分支的临时 worktree 里把 base
并入；若冲突**仅**落在生成式索引 OVERVIEW.md 上，则重渲该文件（确定性消解）、续 commit
并 push；含其它真实冲突则 `merge --abort`、返回 False 交人工（沿用既有留言路径）。

安全降级（关键）：IO 包装层吞掉一切异常回落到 False——自愈只是优化，失败即退回「留言等人」
的现状，绝不拖垮合并扇出。纯决策逻辑 `heal_branch` 与 IO 解耦（理念 10）：git 走注入的
`run`、render 走注入的 callable，便于 hermetic 单测。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from openagents import github
from openagents.spec import render as spec_render

# spec render 的产物：整表重渲的人读索引，其冲突可由「按合并后的 spec 源重渲」确定性消解。
GENERATED_INDEX = Path("docs/specs/OVERVIEW.md")
_SPECS_SUBDIR = Path("docs/specs")
# 自愈用的临时 worktree 根（.openagents/ 已被 .gitignore 忽略），按分支名隔离、用后即删。
_HEAL_SUBDIR = Path(".openagents") / "heal"


class IndexHealError(Exception):
    """自愈过程中的 git 操作失败（IO 层据此降级为 False）。"""


def heal_branch(
    *,
    worktree: Path,
    base: str,
    render: Callable[[Path], None],
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> bool:
    """在 worktree 内把 `origin/<base>` 并入当前分支，返回是否已自愈（待调用方 push）。

    - 干净合并 → True。
    - 冲突且**仅** GENERATED_INDEX → render 重渲 + add + 续 commit → True。
    - 含其它文件的冲突 → `merge --abort` → False（交人工）。
    """
    merged = run(args=["merge", f"origin/{base}", "--no-edit"], cwd=worktree, check=False)
    if merged.returncode == 0:
        return True
    if _conflicted(worktree=worktree, run=run) == [GENERATED_INDEX]:
        # 两侧的 spec 目录各自独立、极少冲突——按合并后的 spec 源重渲，得到二者并集的规范索引，
        # 既消解冲突又保持与 CI 漂移检查一致（render 幂等）。
        render(worktree)
        run(args=["add", str(GENERATED_INDEX)], cwd=worktree, check=True)
        run(args=["commit", "--no-edit"], cwd=worktree, check=True)
        return True
    run(args=["merge", "--abort"], cwd=worktree, check=False)
    return False


def make_healer(*, work_dir: Path, base: str) -> Callable[..., bool]:
    """构造 `rebase_open_prs` 用的 heal 回调 `(*, pr_number) -> bool`。

    取 PR head 分支 → 建临时 detached worktree → `heal_branch` → 成功则 push 回该分支。
    任何环节失败都吞成 False（安全降级到人工留言路径）。worktree 用后必删（幂等清理）。
    """
    root = Path(work_dir)

    def heal(*, pr_number: int) -> bool:
        try:
            branch = github.pr_head_branch(pr_number=pr_number)
        except github.GithubError:
            return False
        path = root / _HEAL_SUBDIR / branch.replace("/", "-")
        try:
            _git(args=["fetch", "origin", base, branch], cwd=root, check=True)
            _cleanup(root=root, path=path)
            _git(
                args=["worktree", "add", "--force", "--detach", str(path), f"origin/{branch}"],
                cwd=root,
                check=True,
            )
            if not heal_branch(worktree=path, base=base, render=_render_overview, run=_git):
                return False
            _git(args=["push", "origin", f"HEAD:refs/heads/{branch}"], cwd=path, check=True)
            return True
        except IndexHealError:
            return False
        finally:
            _cleanup(root=root, path=path)

    return heal


def _render_overview(worktree: Path) -> None:
    """按 worktree 内合并后的 spec 源重渲 OVERVIEW.md（落盘，供 add/commit）。"""
    spec_render.write_overview(specs_root=worktree / _SPECS_SUBDIR)


def _conflicted(
    *, worktree: Path, run: Callable[..., subprocess.CompletedProcess[str]]
) -> list[Path]:
    out = run(args=["diff", "--name-only", "--diff-filter=U"], cwd=worktree, check=True).stdout
    return [Path(line) for line in out.splitlines() if line.strip()]


def _cleanup(*, root: Path, path: Path) -> None:
    """幂等移除临时 worktree（失败忽略——清理是尽力而为，不应掩盖真实结果）。"""
    _git(args=["worktree", "remove", "--force", str(path)], cwd=root, check=False)
    _git(args=["worktree", "prune"], cwd=root, check=False)


def _git(*, args: list[str], cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise IndexHealError(f"git {' '.join(args)} 失败：{proc.stderr.strip()}")
    return proc
