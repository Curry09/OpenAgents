"""Spec-0030/T2: envcheck 体检模块单测。

打桩 HOME（让 ~/.claude.json 指向 tmp_path）+ env 覆盖各分支；断言 detect_browser_mcp
对含 / 缺 mcpServers、缺文件、非法 JSON 各返回正确在册标志且不抛，render_report 在缺失 /
满足两态输出正确文本，且模块从不修改 ~/.claude.json。
"""

from __future__ import annotations

import json

from openagents import envcheck
from openagents.backends.claude_code import PERMISSION_MODE_ENV


def _write_claude_json(home, payload):
    """在打桩 HOME 下写一份 ~/.claude.json。"""
    path = home / ".claude.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _patch_home(monkeypatch, home):
    monkeypatch.setenv("HOME", str(home))


# --------------------------------------------------------------------------- #
# detect_browser_mcp：各数据分支
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
    # ~/.claude.json 不存在 → 视为均未注册，不抛。
    _patch_home(monkeypatch, tmp_path)
    status = envcheck.detect_browser_mcp()
    assert status.all_present is False
    assert status.registered == ()


def test_detect_invalid_json(monkeypatch, tmp_path):
    # 非法 JSON → 视为均未注册，不抛。
    _patch_home(monkeypatch, tmp_path)
    (tmp_path / ".claude.json").write_text("{ not valid json", encoding="utf-8")
    status = envcheck.detect_browser_mcp()
    assert status.all_present is False
    assert status.registered == ()


def test_detect_mcp_servers_not_dict(monkeypatch, tmp_path):
    # mcpServers 是 list 而非 dict → 视为均未注册，不抛。
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(tmp_path, {"mcpServers": ["playwright"]})
    status = envcheck.detect_browser_mcp()
    assert status.all_present is False


def test_detect_does_not_modify_claude_json(monkeypatch, tmp_path):
    # 体检只读不写：调用前后 ~/.claude.json 字节不变。
    _patch_home(monkeypatch, tmp_path)
    path = _write_claude_json(tmp_path, {"mcpServers": {"playwright": {}}})
    before = path.read_bytes()
    envcheck.detect_browser_mcp()
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- #
# render_report：缺失 / 满足两态
# --------------------------------------------------------------------------- #


def test_render_missing_state_has_install_and_export_hints():
    mcp = envcheck.BrowserMcpStatus(registered=(), missing=("playwright", "chrome-devtools"))
    report = envcheck.render_report(mcp=mcp, permission_mode="acceptEdits")
    assert report.all_ok is False
    text = report.text
    # 安装命令与 export 设置方式都在缺失态报告里。
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
    # MCP 全在册但权限非全放行 → 仍非全通过、仍提示 export。
    mcp = envcheck.BrowserMcpStatus(registered=("playwright", "chrome-devtools"), missing=())
    report = envcheck.render_report(mcp=mcp, permission_mode="acceptEdits")
    assert report.all_ok is False
    assert f"export {PERMISSION_MODE_ENV}=bypassPermissions" in report.text


def test_check_integrates_detection_and_mode(monkeypatch, tmp_path):
    # check() 串起检测 + 权限读取：满足态两条 ✓。
    _patch_home(monkeypatch, tmp_path)
    _write_claude_json(tmp_path, {"mcpServers": {"playwright": {}, "chrome-devtools": {}}})
    monkeypatch.setenv(PERMISSION_MODE_ENV, "bypassPermissions")
    report = envcheck.check()
    assert report.all_ok is True
    assert report.text.count("✓") == 2
