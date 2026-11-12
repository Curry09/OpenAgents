# Spec-0030/T2
"""Check optional browser verification prerequisites without changing the environment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from openagents.backends.claude_code import (
    PERMISSION_MODE_ENV,
    effective_permission_mode,
)

# Spec-0030/T2: Names used to register browser MCP servers with claude mcp add.
BROWSER_MCP_NAMES = ("playwright", "chrome-devtools")

# Permission mode required to call browser MCP tools headlessly.
_FULL_ACCESS_MODE = "bypassPermissions"

# Registration commands from the references in Spec-0030.
_INSTALL_HINTS = (
    "claude mcp add playwright -s user -- npx @playwright/mcp@latest",
    "claude mcp add chrome-devtools -s user -- npx chrome-devtools-mcp@latest",
    "npx playwright install chromium",
)
_PERMISSION_HINT = f"export {PERMISSION_MODE_ENV}={_FULL_ACCESS_MODE}"


@dataclass(frozen=True)
class BrowserMcpStatus:
    """Spec-0030/T2: Record which browser MCP servers are registered in ~/.claude.json."""

    registered: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def all_present(self) -> bool:
        return not self.missing


def _claude_json_path() -> Path:
    # Spec-0030/T2: Claude Code stores user-level configuration in ~/.claude.json.
    return Path.home() / ".claude.json"


def detect_browser_mcp() -> BrowserMcpStatus:
    """Spec-0030/T2: Read the top-level mcpServers mapping without changing the file.

    Treat absent, unreadable, or invalid configuration as unregistered.
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
    """Spec-0030/T2: Hold the advisory text and whether all checks passed."""

    text: str
    all_ok: bool


def render_report(*, mcp: BrowserMcpStatus, permission_mode: str) -> EnvReport:
    """Spec-0030/T2: Format the advisory checks and remediation without printing."""
    full_access = permission_mode == _FULL_ACCESS_MODE
    lines = ["▶ Optional browser test prerequisites (Claude Code only)"]

    if mcp.all_present:
        lines.append(f"  ✓ Browser MCP servers registered: {', '.join(mcp.registered)}")
    else:
        missing = " / ".join(mcp.missing)
        lines.append(f"  ⚠ Missing browser MCP registration in ~/.claude.json: {missing}")
        lines.append("    Browser tests require browser automation. To install it:")
        lines.extend(f"      {hint}" for hint in _INSTALL_HINTS)

    if full_access:
        lines.append(f"  ✓ Permission mode {_FULL_ACCESS_MODE} allows browser MCP tool calls")
    else:
        lines.append(
            f"  ⚠ Current permission mode is {permission_mode}; browser tests require {_FULL_ACCESS_MODE}"
        )
        lines.append("    Headless Claude Code will block browser MCP tool calls in this mode.")
        lines.append(
            "    Enable the mode only in a trusted environment; it bypasses permission prompts:"
        )
        lines.append(f"      {_PERMISSION_HINT}")

    all_ok = mcp.all_present and full_access
    if not all_ok:
        lines.append(
            "  These checks are advisory. Skip browser setup for projects that do not need browser tests."
        )

    return EnvReport(text="\n".join(lines), all_ok=all_ok)


def check() -> EnvReport:
    """Spec-0030/T2: Collect browser registration and permission mode, then render the report."""
    return render_report(
        mcp=detect_browser_mcp(),
        permission_mode=effective_permission_mode(),
    )


def ui_capable() -> bool:
    """Return whether headless browser verification is available.
    Spec-0055/T1.

    Both a registered browser MCP tool and the required permission mode are
    necessary. The CLI records this read-only check for verification planning.
    """
    return detect_browser_mcp().all_present and effective_permission_mode() == _FULL_ACCESS_MODE
