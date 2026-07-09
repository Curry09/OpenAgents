"""RFC-0001 T6: 成果层——读取 State 渲染本地成果看板并启动查看（决策 9）。

CLAUDE.md 理念 8「以成果为中心，前端用于呈现成果」：MVP 不引入前端框架，
由本模块把 RuntimeState 的 run 记录渲染成单页 HTML，并用标准库 `webbrowser`
在本地打开，零前端依赖。模板从同包 `templates/board.html` 读取，用标准库
`string.Template` 做占位符替换，所有文本经 `html.escape` 转义防注入。

# Spec-0063/T3: 消费方从旧 State/RunRecord 改接新栈 RuntimeState（list_runs() 返回 dict 记录）。
"""

from __future__ import annotations

import html
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Spec-0063/T3: 改接新栈 RuntimeState——其 list_runs() 返回 dict 记录（非旧栈 RunRecord）。
    from openagents.runtime.state import RuntimeState

# 模板与默认输出位置（决策 9：渲染静态 HTML + 本地查看）。
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "board.html"
_OUTPUT_PATH = Path(".openagents") / "board.html"


def render(*, runs: list[dict]) -> str:
    """RFC-0001 T6：把 RuntimeState run 记录列表渲染成单页看板 HTML（决策 9）。

    # Spec-0063/T3: 消费 RuntimeState.list_runs() 的 dict 记录（issue_number/status/branch/
    # pr_number/closed_at），退役旧栈专属列（rounds/fingerprint/summary/pr_url——新记录里根本没有）。
    每条展示 issue 号、状态、PR 号；所有文本经 `html.escape` 转义防注入。
    """
    template = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    rows = "\n".join(_render_row(record=record) for record in runs)
    if not rows:
        rows = '      <tr><td colspan="4" class="empty">暂无成果记录</td></tr>'
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return template.substitute(rows=rows, generated_at=html.escape(generated_at))


def board(*, state: RuntimeState) -> Path:
    """RFC-0001 T6：渲染看板写盘并用本地浏览器打开，返回文件路径（决策 9）。"""
    output = _OUTPUT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    # Spec-0063/T3: all_runs()（RunRecord）→ list_runs()（dict 记录）。
    output.write_text(render(runs=state.list_runs()), encoding="utf-8")
    resolved = output.resolve()
    webbrowser.open(resolved.as_uri())
    return resolved


def _render_row(*, record: dict) -> str:
    """把单条 RuntimeState dict 记录渲染为一行 <tr>，全部字段做 HTML 转义。

    # Spec-0063/T3: 列数（4）与 board.html 表头（Issue/状态/PR/摘要）一致——新记录无 summary，
    # 该列渲染占位「—」；PR 列只显示 pr_number（RuntimeState 无 pr_url，最小改动不派生链接），
    # pr_number 为 None/0 时同样占位「—」。dict 取值一律 .get 容错。
    """
    issue = html.escape(str(record.get("issue_number", "")))
    status = html.escape(str(record.get("status", "")))
    pr_number = record.get("pr_number")
    pr_cell = html.escape(f"#{pr_number}") if pr_number else "—"
    return (
        "      <tr>"
        f"<td>#{issue}</td>"
        f'<td><span class="status">{status}</span></td>'
        f"<td>{pr_cell}</td>"
        "<td>—</td>"
        "</tr>"
    )
