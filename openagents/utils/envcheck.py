"""# Spec-0061/T1: utils.envcheck —— 前端 e2e 环境体检的稳定 import 面（只读、不抛、非阻塞）。

检测 browser MCP 注册 + 权限模式、判本机能否真跑前端 e2e，是确定性只读机制，归 utils。
新栈起草/评审阶段据 `ui_capable()` 分流测法要求（Spec-0055 能力感知），CLI 启动时固化进 state。
薄再导出现有 `envcheck.py`，不复制、不改动。
"""

from __future__ import annotations

# Spec-0061/T1: 再导出环境体检原语 + 类型（不改 envcheck.py）。
from openagents.envcheck import (
    BrowserMcpStatus,
    EnvReport,
    check,
    detect_browser_mcp,
    render_report,
    ui_capable,
)

__all__ = [
    "BrowserMcpStatus",
    "EnvReport",
    "check",
    "detect_browser_mcp",
    "render_report",
    "ui_capable",
]
