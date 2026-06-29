"""Spec-0030/T2: init 前端 e2e 环境体检（纯函数、read-only、从不抛、非阻塞）。

理念 8「以成果为中心、模型替人做端到端测试」要求前端类 issue 的真正验证落到浏览器
自动化（Playwright / Chrome DevTools MCP）。但「装了 MCP 插件」≠「守夜派出的 agent 真能
用上浏览器」——经核对 OpenAgents 调 claude 的方式（`backends/claude_code.py`）存在两道关卡：
(1) 工具可见：未传 --mcp-config，claude 继承用户级 ~/.claude.json 注册的 MCP；
(2) 权限放行：headless `-p` 下 acceptEdits 只放行编辑类工具，browser_* 调用会被静默拒。

本模块只**检测 + 渲染报告**，供 init 非阻塞打印（见 Spec-0030 Reference-level (A)）：
- detect_browser_mcp(): 读 ~/.claude.json 顶层 mcpServers 判 playwright / chrome-devtools 在册；
- effective_permission_mode(): 转调 claude_code 的同名访问器（单一真相源——报告里的模式必须
  等于派单实际用的模式，否则告知会撒谎）；
- render_report(): 把两项结果渲染成非阻塞报告文本（缺失项含安装命令 / export 设置方式 / 取舍）。

解耦（理念 10）：只读家目录 ~/.claude.json、读环境变量，不碰 git / github / state，便于单测
打桩。绝不修改 ~/.claude.json（只读家目录文件，不碰仓库 .claude/，呼应全局硬约束）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from openagents.backends.claude_code import (
    PERMISSION_MODE_ENV,
    effective_permission_mode,
)

# Spec-0030/T2: 体检关注的 browser MCP server 名（claude mcp add 时的注册名）。
BROWSER_MCP_NAMES = ("playwright", "chrome-devtools")

# 全放行模式名——headless 下唯有它能放行 browser MCP 工具调用（见 Spec-0030 Motivation 关卡 2）。
_FULL_ACCESS_MODE = "bypassPermissions"

# 安装 / 设置方式：原样复述官方注册命令，不自创（见 Spec-0030 Prior art）。
_INSTALL_HINTS = (
    "claude mcp add playwright -s user -- npx @playwright/mcp@latest",
    "claude mcp add chrome-devtools -s user -- npx chrome-devtools-mcp@latest",
    "npx playwright install chromium",
)
_PERMISSION_HINT = f"export {PERMISSION_MODE_ENV}={_FULL_ACCESS_MODE}"


@dataclass(frozen=True)
class BrowserMcpStatus:
    """Spec-0030/T2: 各 browser MCP server 是否在 ~/.claude.json 注册的快照。"""

    registered: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def all_present(self) -> bool:
        return not self.missing


def _claude_json_path() -> Path:
    # Spec-0030/T2: 用户级 claude 配置固定在家目录顶层 ~/.claude.json。
    return Path.home() / ".claude.json"


def detect_browser_mcp() -> BrowserMcpStatus:
    """Spec-0030/T2: 读 ~/.claude.json 顶层 mcpServers，判断 browser MCP 是否在册。

    文件不存在 / 非法 JSON / 无 mcpServers 键 / mcpServers 非 dict → 一律视为「均未注册」，
    **从不抛**（体检非阻塞，见 Spec-0030 (A)）。只读不写。
    """
    registered_names: set[str] = set()
    try:
        raw = _claude_json_path().read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        servers = data.get("mcpServers")
        if isinstance(servers, dict):
            registered_names = set(servers.keys())
    registered = tuple(name for name in BROWSER_MCP_NAMES if name in registered_names)
    missing = tuple(name for name in BROWSER_MCP_NAMES if name not in registered_names)
    return BrowserMcpStatus(registered=registered, missing=missing)


@dataclass(frozen=True)
class EnvReport:
    """Spec-0030/T2: 体检结果——报告文本 + 是否全通过布尔（非阻塞，不携带退出码）。"""

    text: str
    all_ok: bool


def render_report(*, mcp: BrowserMcpStatus, permission_mode: str) -> EnvReport:
    """Spec-0030/T2: 把检测结果渲染成非阻塞报告文本（纯函数返回字符串，本模块不 print）。

    缺失项输出安装命令 / export 设置方式 / 取舍提示；满足态输出两条 ✓。由调用方（init）
    打印，便于测断言文本。
    """
    full_access = permission_mode == _FULL_ACCESS_MODE
    lines = ["▶ 前端 e2e 环境体检（非阻塞，仅 claude-code 后端）"]

    if mcp.all_present:
        lines.append(f"  ✓ browser MCP 已注册：{', '.join(mcp.registered)}")
    else:
        missing = " / ".join(mcp.missing)
        lines.append(f"  ⚠ 未检测到 browser MCP（{missing} 未在 ~/.claude.json 注册）")
        lines.append("    前端浏览器 e2e 需要浏览器自动化工具。安装方式：")
        lines.extend(f"      {hint}" for hint in _INSTALL_HINTS)

    if full_access:
        lines.append(f"  ✓ 权限模式 {_FULL_ACCESS_MODE}（全放行）：browser MCP 工具调用可被放行")
    else:
        lines.append(f"  ⚠ 当前权限模式为 {permission_mode}（非全放行 {_FULL_ACCESS_MODE}）")
        lines.append(
            "    headless 非交互下 browser MCP 工具调用会被直接拒绝 → 前端浏览器 e2e 将无法运行。"
        )
        lines.append("    要可靠跑起来需全放行（移除无人值守安全栏杆，请知悉取舍后再开）：")
        lines.append(f"      {_PERMISSION_HINT}")

    all_ok = mcp.all_present and full_access
    if not all_ok:
        lines.append("  提示：以上为非阻塞告知；后端类项目无需浏览器，可忽略。")

    return EnvReport(text="\n".join(lines), all_ok=all_ok)


def check() -> EnvReport:
    """Spec-0030/T2: 体检入口——采集两项检测并渲染，供 init 直接取报告打印（T3 接线点）。"""
    return render_report(
        mcp=detect_browser_mcp(),
        permission_mode=effective_permission_mode(),
    )
