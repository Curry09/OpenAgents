"""RFC-0001 T6: 成果看板渲染与本地启动（决策 9）的单元测试。

# Spec-0063/T3: 消费 RuntimeState 的 dict run 记录（issue_number/status/branch/pr_number/
# closed_at），退役旧栈专属列（summary/pr_url/rounds/fingerprint）。
覆盖：render 把 dict 记录列表渲染为单页 HTML（含 issue 号 / 状态 / PR 号占位），
并对文本做 HTML 转义防注入；空 runs 渲染「暂无成果记录」空行；board 生成文件、
调用 webbrowser.open（被 monkeypatch，不真开浏览器）并返回文件路径。
"""

import openagents.utils.results as results
from openagents.runtime.state import RuntimeState


def _record(*, issue_number, status, pr_number=None):
    """构造一条用于渲染断言的 RuntimeState dict run 记录。"""
    return {
        "issue_number": issue_number,
        "status": status,
        "branch": f"openagents/issue-{issue_number}",
        "pr_number": pr_number if pr_number is not None else issue_number * 10,
        "closed_at": "",
    }


def test_render_returns_html_document():
    html = results.render(runs=[])
    assert "<html" in html.lower()
    assert "</html>" in html.lower()


def test_render_empty_runs_shows_placeholder_row():
    html = results.render(runs=[])
    assert "暂无成果记录" in html


def test_render_includes_issue_number_and_status_and_pr_number():
    record = _record(issue_number=3, status="pr-open", pr_number=30)
    html = results.render(runs=[record])

    assert "#3" in html
    assert "pr-open" in html
    assert "#30" in html  # PR 号占位（RuntimeState 无 pr_url，只显示 pr_number）


def test_render_missing_pr_number_shows_dash():
    record = _record(issue_number=7, status="solving", pr_number=0)
    html = results.render(runs=[record])
    # pr_number 为 0/None → PR 列占位「—」，不渲染 #0（`>#0<` 精确匹配单元格内容，
    # 避开模板 CSS 里的 #0f1117 等色值）。
    assert "#7" in html
    assert ">#0<" not in html


def test_render_escapes_html_in_status():
    record = _record(issue_number=2, status="<b>weird</b>", pr_number=20)
    html = results.render(runs=[record])
    assert "<b>weird</b>" not in html
    assert "&lt;b&gt;weird&lt;/b&gt;" in html


def test_render_multiple_runs_all_present():
    runs = [
        _record(issue_number=1, status="done", pr_number=10),
        _record(issue_number=2, status="pr-open", pr_number=20),
    ]
    html = results.render(runs=runs)
    assert "#1" in html
    assert "#2" in html
    assert "#10" in html
    assert "#20" in html


def test_board_writes_file_and_returns_path(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(results.webbrowser, "open", lambda url: opened.append(url))

    state = RuntimeState(path=tmp_path / ".openagents" / "runtime-state.json")
    state.set_run(
        issue_number=4,
        branch="openagents/issue-4",
        pr_number=40,
        status="pr-open",
    )

    monkeypatch.chdir(tmp_path)
    path = results.board(state=state)

    assert path.exists()
    assert path.read_text(encoding="utf-8").lower().count("<html") == 1
    assert len(opened) == 1


def test_board_does_not_open_real_browser(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(results.webbrowser, "open", lambda url: calls.append(url))

    state = RuntimeState(path=tmp_path / ".openagents" / "runtime-state.json")
    monkeypatch.chdir(tmp_path)
    path = results.board(state=state)

    # 打开的 url 应指向刚写出的看板文件。
    assert calls
    assert str(path) in calls[0]
