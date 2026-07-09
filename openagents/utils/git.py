"""# Spec-0060/T1: utils.git —— 新栈的确定性 git 稳定 import 面。

给新栈（runtime.gates 硬闸 / runtime.context / recipes）一个**只懂 git、不含业务判断**的
稳定 import 面：

- worktree 生命周期原语（`Workspace` / `WorkspaceError`）——薄再导出现有 `workspace.py`，
  **不复制、不改动其任何一行**（奥卡姆，理念 1）。worktree 建/拉/清是 agent 无法自建沙箱的
  **编排** git，仍归 workspace.py；本模块只做稳定再导出，把「搬迁」留后续批次。
- 只读原语 `head_sha` / `porcelain`——新栈硬闸（head 前移断言）与上下文所需，旧 `workspace.py`
  未公开暴露，故在此以**最薄 subprocess 封装**提供，语义与 `workspace._git` 一致（`git -C <dir>`、
  capture、strip）。这是新栈唯一新增的确定性 git 读原语，非复制旧代码。

本模块允许直接调 subprocess（它属 utils 确定性层，正是 git/gh 机械操作的归口）；agents/recipes
则严禁——判断下放 agent、客观机械留确定性代码，是本重构的分界线。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Spec-0060/T1: 薄再导出 worktree 生命周期原语（不改 workspace.py 任何一行）。
from openagents.workspace import Workspace, WorkspaceError

__all__ = ["Workspace", "WorkspaceError", "head_sha", "porcelain", "remote_branch_exists"]


def head_sha(*, work_dir: Path) -> str:
    """当前 HEAD 的完整 SHA（`git rev-parse HEAD`）；无提交/失败返回空串。

    新栈硬闸 `gates.assert_head_advanced` 与证据溯源戳据此读客观事实——head 到底是哪个 commit，
    是「有没有真交付」这类客观判断的唯一事实源，不含任何业务判断。
    """
    result = _git(args=["rev-parse", "HEAD"], cwd=Path(work_dir))
    return result.stdout.strip()


def porcelain(*, work_dir: Path) -> str:
    """工作区改动的 porcelain 摘要（`git status --porcelain`）；干净工作区返回空串。

    与 backend（claude_code）判定「本轮是否产生改动」同一 git 事实面；供上下文/诊断读取。
    """
    result = _git(args=["status", "--porcelain"], cwd=Path(work_dir))
    return result.stdout.strip()


# Spec-0061/T1: 只读远端分支存在性探针——新栈 vigil recipe 的确定性去重闸（分支已存在=已在飞行中）
# 所需，旧 workspace.py 的同名方法绑在 Workspace 实例上，此处以最薄封装提供免实例的自由函数。
def remote_branch_exists(*, work_dir: Path, branch: str) -> bool:
    """远端是否已有该分支（`git ls-remote --heads origin <branch>` 有输出即存在）。

    vigil recipe 派单前的去重闸：远端分支已存在说明该 issue 已被某后端认领在飞行中，
    recipe 据此跳过、不重复派单。纯读客观事实（远端 ref），不含业务判断。
    """
    result = _git(args=["ls-remote", "--heads", "origin", branch], cwd=Path(work_dir))
    return bool(result.stdout.strip())


def _git(*, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """在 cwd 内运行一条只读 git 子命令并捕获输出（与 workspace._git 同款调用形态）。"""
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
    )
