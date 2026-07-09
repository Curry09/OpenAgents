"""# Spec-0061/T1: utils.config —— 项目绑定 preflight 的稳定 import 面。

从 cwd 解析 git 根 + origin 远端、preflight 确保是就绪的 OpenAgents 项目，是确定性机制，归 utils。
recipes.fleet 的每仓库子进程 chdir 后靠 `resolve_project` 定位 ctx。薄再导出现有 `config.py`
（含 ProjectNotReady 异常 + ProjectContext 类型），不复制、不改动。
"""

from __future__ import annotations

# Spec-0061/T1: 再导出项目绑定原语 + 异常（不改 config.py）。
from openagents.config import (
    ProjectContext,
    ProjectNotReady,
    ensure_project,
    resolve_project,
)

__all__ = ["ProjectContext", "ProjectNotReady", "ensure_project", "resolve_project"]
