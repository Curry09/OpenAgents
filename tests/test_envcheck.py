"""Spec-0030/T2: envcheck medical check module single test.

Pile a hoME (Jean ~/. claude.json to tmp_path) + env over branches; assert that detect_browser_mcp
Whether mcpServers is in place, missing files, illegal JSON returns the correct and undiscarded mark, render_report is missing/
Meets the two-state output of the correct text and the module never changes ~/. claude.json.
"""

from __future__ import annotations

import json

from openagents.backends.claude_code import PERMISSION_MODE_ENV
from openagents.utils import envcheck


def _write_claude_json(home, payload):
    """Write a copy of ~/. claude.json under a stake HOME."""
    path = home / ".claude.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _patch_home(monkeypatch, home):
    monkeypatch.setenv("HOME", str(home))


# --------------------------------------------------------------------------- #
# detect_browser_mcp: Data branches
# --------------------------------------------------------------------------- #


def test_detect_both_registered(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(
        tmp_path,
        {"mcpServers": {"playwright": {}, "chrome-devtools": {}, "other": {}}},
    )
    status = envcheck.detect_browser_mcp()
    assert status.all_present is True
    assert set(status.registered) == {"playwright", "chrome-devtools"}
    assert status.missing == ()


def test_detect_partial_registered(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(tmp_path, {"mcpServers": {"playwright": {}}})
    status = envcheck.detect_browser_mcp()
    assert status.all_present is False
    assert status.registered == ("playwright",)
    assert status.missing == ("chrome-devtools",)


def test_detect_no_mcp_servers_key(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(tmp_path, {"somethingElse": 1})
    status = envcheck.detect_browser_mcp()
    assert status.all_present is False
    assert status.registered == ()
    assert set(status.missing) == {"playwright", "chrome-devtools"}


def test_detect_missing_file(monkeypatch, tmp_path):
    # ~. claude.json does not exist  →  and is considered not registered, not dropped.
    _patch_home(monkeypatch, tmp_path)
    status = envcheck.detect_browser_mcp()
    assert status.all_present is False
    assert status.registered == ()


def test_detect_invalid_json(monkeypatch, tmp_path):
    # Illegal JSON Zone is considered not registered, not dropped.
    _patch_home(monkeypatch, tmp_path)
    (tmp_path / ".claude.json").write_text("{ not valid json", encoding="utf-8")
    status = envcheck.detect_browser_mcp()
    assert status.all_present is False
    assert status.registered == ()


def test_detect_mcp_servers_not_dict(monkeypatch, tmp_path):
    # mcpServers is listed instead of dict thi is considered not registered, not dropped.
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(tmp_path, {"mcpServers": ["playwright"]})
    status = envcheck.detect_browser_mcp()
    assert status.all_present is False


def test_detect_does_not_modify_claude_json(monkeypatch, tmp_path):
    # Medical examination is not read or written: no bytes change before or after ~/.claude.json.
    _patch_home(monkeypatch, tmp_path)
    path = _write_claude_json(tmp_path, {"mcpServers": {"playwright": {}}})
    before = path.read_bytes()
    envcheck.detect_browser_mcp()
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- #
# render_report: Missing / Satisfactory
# --------------------------------------------------------------------------- #


def test_render_missing_state_has_install_and_export_hints():
    mcp = envcheck.BrowserMcpStatus(registered=(), missing=("playwright", "chrome-devtools"))
    report = envcheck.render_report(mcp=mcp, permission_mode="acceptEdits")
    assert report.all_ok is False
    text = report.text
    # The installation command and the export settings are both in the missing report.
    assert "claude mcp add playwright" in text
    assert f"export {PERMISSION_MODE_ENV}=bypassPermissions" in text
    assert "⚠" in text


def test_render_satisfied_state_two_checks_no_install():
    mcp = envcheck.BrowserMcpStatus(registered=("playwright", "chrome-devtools"), missing=())
    report = envcheck.render_report(mcp=mcp, permission_mode="bypassPermissions")
    assert report.all_ok is True
    text = report.text
    assert text.count("✓") == 2
    assert "claude mcp add" not in text
    assert "export " not in text


def test_render_partial_mcp_present_but_not_full_access():
    # MCP is fully registered but not fully released is still not fully adopted and still alerts to the report.
    mcp = envcheck.BrowserMcpStatus(registered=("playwright", "chrome-devtools"), missing=())
    report = envcheck.render_report(mcp=mcp, permission_mode="acceptEdits")
    assert report.all_ok is False
    assert f"export {PERMISSION_MODE_ENV}=bypassPermissions" in report.text


def test_check_integrates_detection_and_mode(monkeypatch, tmp_path):
    # Check() Thread + Permission to Read: two bares of content.
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(tmp_path, {"mcpServers": {"playwright": {}, "chrome-devtools": {}}})
    monkeypatch.setenv(PERMISSION_MODE_ENV, "bypassPermissions")
    report = envcheck.check()
    assert report.all_ok is True
    assert report.text.count("✓") == 2


# --------------------------------------------------------------------------- #
# Spec-0055/T1: ui_capable - Browner MCP Book  →  All permissions are granted only to True
# --------------------------------------------------------------------------- #


def test_ui_capable_true_when_mcp_and_full_access(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(tmp_path, {"mcpServers": {"playwright": {}, "chrome-devtools": {}}})
    monkeypatch.setenv(PERMISSION_MODE_ENV, "bypassPermissions")
    assert envcheck.ui_capable() is True


def test_ui_capable_false_when_missing_mcp(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(tmp_path, {"mcpServers": {"playwright": {}}})  # Chrome-devtools missing
    monkeypatch.setenv(PERMISSION_MODE_ENV, "bypassPermissions")
    assert envcheck.ui_capable() is False


def test_ui_capable_false_when_not_full_access(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(tmp_path, {"mcpServers": {"playwright": {}, "chrome-devtools": {}}})
    monkeypatch.setenv(PERMISSION_MODE_ENV, "acceptEdits")
    assert envcheck.ui_capable() is False


def test_ui_capable_false_when_no_claude_json(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)  # None ~/. claude.json
    monkeypatch.setenv(PERMISSION_MODE_ENV, "bypassPermissions")
    assert envcheck.ui_capable() is False
