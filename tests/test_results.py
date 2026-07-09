"""RFC-0001 T6: 成果看板渲染与本地启动（决策 9）的单元测试。

覆盖：render 把 RunRecord 列表渲染为单页 HTML（含 issue 号 / 状态 /
可点 PR 链接 / 摘要），并对文本做 HTML 转义防注入；board 生成文件、
调用 webbrowser.open（被 monkeypatch，不真开浏览器）并返回文件路径。
"""

import openagents.utils.results as results
from openagents.state import RunRecord, State


def _record(*, issue_number, status, pr_url, summary):
    """构造一条用于渲染断言的 RunRecord。"""
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=issue_number * 10,
        pr_url=pr_url,
        status=status,
        summary=summary,
    )


def test_render_returns_html_document():
    html = results.render(runs=[])
    assert "<html" in html.lower()
    assert "</html>" in html.lower()


def test_render_includes_issue_number_and_status_and_pr_url():
    record = _record(
        issue_number=3,
        status="pr-open",
        pr_url="https://github.com/acme/widget/pull/30",
        summary="fixed the bug",
    )
    html = results.render(runs=[record])

    assert "3" in html
    assert "pr-open" in html
    assert "https://github.com/acme/widget/pull/30" in html
    assert "fixed the bug" in html


def test_render_pr_url_is_clickable_anchor():
    record = _record(
        issue_number=5,
        status="done",
        pr_url="https://github.com/acme/widget/pull/50",
        summary="done",
    )
    html = results.render(runs=[record])
    assert 'href="https://github.com/acme/widget/pull/50"' in html


def test_render_escapes_html_in_summary():
    record = _record(
        issue_number=1,
        status="iterating",
        pr_url="https://github.com/acme/widget/pull/10",
        summary="<script>alert('xss')</script>",
    )
    html = results.render(runs=[record])

    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_render_escapes_html_in_status():
    record = _record(
        issue_number=2,
        status="<b>weird</b>",
        pr_url="https://github.com/acme/widget/pull/20",
        summary="ok",
    )
    html = results.render(runs=[record])
    assert "<b>weird</b>" not in html
    assert "&lt;b&gt;weird&lt;/b&gt;" in html


def test_render_multiple_runs_all_present():
    runs = [
        _record(
            issue_number=1,
            status="done",
            pr_url="https://github.com/acme/widget/pull/10",
            summary="one",
        ),
        _record(
            issue_number=2,
            status="pr-open",
            pr_url="https://github.com/acme/widget/pull/20",
            summary="two",
        ),
    ]
    html = results.render(runs=runs)
    assert "one" in html
    assert "two" in html
    assert "pull/10" in html
    assert "pull/20" in html


def test_board_writes_file_and_returns_path(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(results.webbrowser, "open", lambda url: opened.append(url))

    state = State(path=tmp_path / ".openagents" / "state.json")
    state.record_run(
        issue_number=4,
        branch="openagents/issue-4",
        pr=_pr(number=40, url="https://github.com/acme/widget/pull/40"),
    )

    monkeypatch.chdir(tmp_path)
    path = results.board(state=state)

    assert path.exists()
    assert path.read_text(encoding="utf-8").lower().count("<html") == 1
    assert len(opened) == 1


def test_board_does_not_open_real_browser(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(results.webbrowser, "open", lambda url: calls.append(url))

    state = State(path=tmp_path / ".openagents" / "state.json")
    monkeypatch.chdir(tmp_path)
    path = results.board(state=state)

    # 打开的 url 应指向刚写出的看板文件。
    assert calls
    assert str(path) in calls[0]


def _pr(*, number, url):
    """构造 PR（State.record_run 需要 pr.number / pr.url）。"""
    from openagents.utils.github import PR

    return PR(number=number, url=url)
