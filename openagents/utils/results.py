"""RFC-0001 T6: 成果层——读取 State 渲染本地成果看板并启动查看（决策 9）。

CLAUDE.md 理念 8「以成果为中心，前端用于呈现成果」：MVP 不引入前端框架，
由本模块把 State 中的 RunRecord 渲染成单页 HTML，并用标准库 `webbrowser`
在本地打开，零前端依赖。模板从同包 `templates/board.html` 读取，用标准库
`string.Template` 做占位符替换，所有文本经 `html.escape` 转义防注入。
"""

from __future__ import annotations

import html
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openagents.state import RunRecord, State

# 模板与默认输出位置（决策 9：渲染静态 HTML + 本地查看）。
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "board.html"
_OUTPUT_PATH = Path(".openagents") / "board.html"


def render(*, runs: list[RunRecord]) -> str:
    """RFC-0001 T6：把 RunRecord 列表渲染成单页看板 HTML（决策 9）。

    每条展示 issue 号、状态、可点击的 PR 链接与摘要；所有文本经
    `html.escape` 转义，PR 链接同时转义为属性值，防止注入。
    """
    template = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    rows = "\n".join(_render_row(record=record) for record in runs)
    if not rows:
        rows = '      <tr><td colspan="4" class="empty">暂无成果记录</td></tr>'
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return template.substitute(rows=rows, generated_at=html.escape(generated_at))


def board(*, state: State) -> Path:
    """RFC-0001 T6：渲染看板写盘并用本地浏览器打开，返回文件路径（决策 9）。"""
    output = _OUTPUT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(runs=state.all_runs()), encoding="utf-8")
    resolved = output.resolve()
    webbrowser.open(resolved.as_uri())
    return resolved


def _render_row(*, record: RunRecord) -> str:
    """把单条 RunRecord 渲染为一行 <tr>，全部字段做 HTML 转义。"""
    issue = html.escape(str(record.issue_number))
    status = html.escape(record.status)
    summary = html.escape(record.summary) or "—"
    pr_url = html.escape(record.pr_url, quote=True)
    pr_label = html.escape(f"#{record.pr_number}")
    pr_cell = f'<a href="{pr_url}">{pr_label}</a>' if record.pr_url else "—"
    return (
        "      <tr>"
        f"<td>#{issue}</td>"
        f'<td><span class="status">{status}</span></td>'
        f"<td>{pr_cell}</td>"
        f"<td>{summary}</td>"
        "</tr>"
    )
