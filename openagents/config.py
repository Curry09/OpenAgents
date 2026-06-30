"""RFC-0001 T1: 项目绑定（决策 10）。

OpenAgents 以「当前工作目录」为目标项目：
- resolve_project: 从 cwd 解析 git root 与 origin 远端；非 git 仓库返回 None。
- ensure_project: 各命令的 preflight；缺 git/remote 时，交互模式下提示用户新建，
  非交互模式（CI 等）下抛 ProjectNotReady，绝不擅自创建。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class ProjectNotReady(Exception):
    """cwd 不是就绪的 OpenAgents 项目（缺 git 仓库或 origin 远端）。"""


@dataclass(frozen=True)
class ProjectContext:
    """已就绪的项目上下文。remote 在仅本地仓库时可能为 None。"""

    repo_root: Path
    remote: str | None


def _git_output(args: list[str]) -> str | None:
    """运行 git 子命令，成功返回去空白的 stdout，失败返回 None。"""
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def resolve_project() -> ProjectContext | None:
    """从 cwd 解析项目上下文；非 git 仓库返回 None。"""
    root = _git_output(["rev-parse", "--show-toplevel"])
    if root is None:
        return None
    # 用 `config --get` 读原始配置值，而非 `remote get-url`：后者会展开 insteadOf
    # 重写，可能把全局 git 配置里注入的凭据 token 带进 URL 并泄露到 State/看板。
    remote = _git_output(["config", "--get", "remote.origin.url"])
    return ProjectContext(repo_root=Path(root), remote=remote or None)


def _confirm(question: str) -> bool:
    """交互式 yes/no 提示，默认否。"""
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def _prompt(question: str) -> str:
    return input(question).strip()


def _bootstrap(ctx: ProjectContext | None) -> ProjectContext:
    """交互式补齐缺失的 git 仓库 / 远端（决策 10）。"""
    if ctx is None:
        if not _confirm("当前目录不是 git 仓库，是否执行 git init？"):
            raise ProjectNotReady("用户取消：未初始化 git 仓库")
        subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
        ctx = resolve_project()
    if ctx is None:
        raise ProjectNotReady("git init 后仍无法解析仓库")
    if not ctx.remote:
        if not _confirm("当前仓库没有 origin 远端，是否新建 GitHub 仓库？"):
            raise ProjectNotReady("用户取消：未配置远端")
        try:
            from openagents.github import create_repo
        except ImportError as exc:
            raise ProjectNotReady("新建远端需要 GitHub 集成（RFC-0001 T3）尚未实现") from exc
        name = _prompt("远端仓库名（owner/repo）：")
        private = _confirm("设为私有仓库？")
        remote = create_repo(name=name, private=private)
        # Spec-0033/T1: 把新建的远端写回本地 git config，否则后续 gh 命令找不到
        # 目标仓库（no git remotes found）。复用同函数 git init 的 check=True 校验式
        # 子进程：git 失败立即冒泡、不静默吞错。必须在 create_repo 成功之后、返回 ctx 之前。
        subprocess.run(["git", "remote", "add", "origin", remote], check=True, capture_output=True)
        ctx = ProjectContext(repo_root=ctx.repo_root, remote=remote)
    return ctx


def ensure_project(*, interactive: bool) -> ProjectContext:
    """preflight：返回就绪的项目上下文，否则按 interactive 决定新建或抛错。"""
    ctx = resolve_project()
    if ctx is not None and ctx.remote:
        return ctx
    if not interactive:
        reason = "当前目录不是 git 仓库" if ctx is None else "当前仓库缺少 origin 远端"
        raise ProjectNotReady(reason)
    return _bootstrap(ctx)
