"""RFC-0001 T1 + RFC-0005: CLI 子命令注册与分发的契约测试。

RFC-0005：solve 已移除，改为 rfc / refine-rfc / implement / iterate 四个原子步骤。
"""

from pathlib import Path

import pytest

from openagents.cli import build_parser, main
from openagents.config import ProjectContext
from openagents.github import Comment, Issue

COMMANDS = [
    "init",
    "rfc",
    "refine-rfc",
    "implement",
    "iterate",
    "issue",
    "poll",
    "watch",
    "board",
    "vigil",
]


def test_parser_registers_all_subcommands():
    parser = build_parser()
    subparsers = next(a for a in parser._actions if getattr(a, "choices", None))
    for cmd in COMMANDS:
        assert cmd in subparsers.choices


def test_solve_command_removed():
    parser = build_parser()
    subparsers = next(a for a in parser._actions if getattr(a, "choices", None))
    assert "solve" not in subparsers.choices


def test_help_exits_zero_and_lists_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for cmd in COMMANDS:
        assert cmd in out


def test_unknown_command_errors():
    with pytest.raises(SystemExit) as exc:
        main(["definitely-not-a-command"])
    assert exc.value.code != 0


def test_no_command_returns_nonzero(capsys):
    code = main([])
    assert code != 0


def _patch_ensure(monkeypatch):
    calls = []
    fake = ProjectContext(repo_root=Path("/tmp/x"), remote="https://github.com/x/y.git")

    def fake_ensure(*, interactive):
        calls.append(interactive)
        return fake

    monkeypatch.setattr("openagents.cli.ensure_project", fake_ensure)
    return calls


class _FakePR:
    url = "https://github.com/x/y/pull/9"


# --------------------------------------------------------------------------- #
# rfc
# --------------------------------------------------------------------------- #


def test_rfc_runs_preflight_then_opens_draft_pr(monkeypatch):
    calls = _patch_ensure(monkeypatch)

    class _FakeOrch:
        def start_rfc(self, *, issue_number, base):
            assert issue_number == 1
            assert base == "main"
            return _FakePR()

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    code = main(["rfc", "1"])
    assert code == 0
    assert calls == [True]


def test_rfc_passes_base_override(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = {}

    class _FakeOrch:
        def start_rfc(self, *, issue_number, base):
            seen.update(issue_number=issue_number, base=base)
            return _FakePR()

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    code = main(["rfc", "7", "--base", "dev"])
    assert code == 0
    assert seen == {"issue_number": 7, "base": "dev"}


def test_rfc_reports_error_cleanly_without_traceback(monkeypatch, capsys):
    _patch_ensure(monkeypatch)
    from openagents.orchestrator import OrchestratorError

    class _Boom:
        def start_rfc(self, *, issue_number, base):
            raise OrchestratorError("push 被拒：non-fast-forward")

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _Boom())
    code = main(["rfc", "3"])

    assert code == 1
    err = capsys.readouterr().err
    assert "✗" in err
    assert "non-fast-forward" in err


# --------------------------------------------------------------------------- #
# refine-rfc
# --------------------------------------------------------------------------- #


def test_refine_rfc_fetches_latest_comment_and_calls_orchestrator(monkeypatch):
    # RFC-0005 决策 6：取最新评论作 detail，不论作者——人与 agent 共用同一账号
    # （这里最新评论作者与 current_login 同为 agent-bot）时仍能触发。
    _patch_ensure(monkeypatch)
    seen = {}

    class _FakeOrch:
        def refine_rfc(self, *, pr_number, detail):
            seen.update(pr_number=pr_number, detail=detail)

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    monkeypatch.setattr("openagents.github.current_login", lambda: "agent-bot")
    monkeypatch.setattr(
        "openagents.github.list_comments",
        lambda *, pr_number: [
            Comment(id="1", author="alice", body="旧评论", created_at="2026-06-03T01:00:00Z"),
            Comment(
                id="2", author="agent-bot", body="改 RFC 设计", created_at="2026-06-03T02:00:00Z"
            ),
        ],
    )

    code = main(["refine-rfc", "9"])
    assert code == 0
    assert seen == {"pr_number": 9, "detail": "改 RFC 设计"}


def test_refine_rfc_without_any_comment_returns_nonzero(monkeypatch, capsys):
    # RFC-0005 决策 6：不再按作者过滤；仅当 PR 上完全没有评论时才报错退出。
    _patch_ensure(monkeypatch)

    class _FakeOrch:
        def refine_rfc(self, *, pr_number, detail):
            raise AssertionError("无评论时不应调用 refine_rfc")

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    monkeypatch.setattr("openagents.github.list_comments", lambda *, pr_number: [])

    code = main(["refine-rfc", "9"])
    assert code == 1
    assert "✗" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# implement
# --------------------------------------------------------------------------- #


def test_implement_calls_orchestrator(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = {}

    class _FakeOrch:
        def implement(self, *, pr_number):
            seen.update(pr_number=pr_number)

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    code = main(["implement", "9"])
    assert code == 0
    assert seen == {"pr_number": 9}


# --------------------------------------------------------------------------- #
# iterate
# --------------------------------------------------------------------------- #


def test_iterate_comment_fetches_latest_human_comment(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = {}

    class _FakeOrch:
        def iterate(self, *, pr_number, reason, detail):
            seen.update(pr_number=pr_number, reason=reason, detail=detail)

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    monkeypatch.setattr("openagents.github.current_login", lambda: "agent-bot")
    monkeypatch.setattr(
        "openagents.github.list_comments",
        lambda *, pr_number: [
            Comment(id="2", author="alice", body="修一下", created_at="2026-06-03T02:00:00Z")
        ],
    )

    code = main(["iterate", "9"])
    assert code == 0
    assert seen == {"pr_number": 9, "reason": "comment", "detail": "修一下"}


def test_iterate_ci_uses_check_status(monkeypatch):
    from openagents.github import CheckStatus

    _patch_ensure(monkeypatch)
    seen = {}

    class _FakeOrch:
        def iterate(self, *, pr_number, reason, detail):
            seen.update(pr_number=pr_number, reason=reason, detail=detail)

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    monkeypatch.setattr(
        "openagents.github.check_status",
        lambda *, pr_number: CheckStatus(state="fail", failed_logs=["lint [FAILURE] http://x"]),
    )

    code = main(["iterate", "9", "--reason", "ci"])
    assert code == 0
    assert seen["pr_number"] == 9
    assert seen["reason"] == "ci"
    assert "lint" in seen["detail"]


# --------------------------------------------------------------------------- #
# issue / poll / init / board（既有，保持）
# --------------------------------------------------------------------------- #


def test_issue_runs_preflight_then_creates_issue(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    seen = {}

    def fake_create_issue(*, title, body, labels):
        seen.update(title=title, body=body, labels=labels)
        return Issue(number=13, title=title, body=body)

    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "Login broken", "--body", "repro", "--label", "bug", "--label", "p1"])
    assert code == 0
    assert calls == [True]
    # RFC-0002 决策 5：用户标签之外总会追加发现标签 openagents（去重）。
    assert seen == {"title": "Login broken", "body": "repro", "labels": ["bug", "p1", "openagents"]}


def test_issue_defaults_empty_body_and_attaches_discovery_label(monkeypatch):
    # RFC-0002 决策 5：不传 --label 时，issue 仍自动带上 openagents 标签（供 vigil 发现）。
    _patch_ensure(monkeypatch)
    seen = {}

    def fake_create_issue(*, title, body, labels):
        seen.update(title=title, body=body, labels=labels)
        return Issue(number=1, title=title, body=body)

    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "Just a title"])
    assert code == 0
    assert seen == {"title": "Just a title", "body": "", "labels": ["openagents"]}


def test_issue_does_not_duplicate_discovery_label(monkeypatch):
    # RFC-0002 决策 5：用户显式传 openagents 时不重复，且保留出现顺序。
    _patch_ensure(monkeypatch)
    seen = {}

    def fake_create_issue(*, title, body, labels):
        seen.update(labels=labels)
        return Issue(number=2, title=title, body=body)

    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "T", "--label", "openagents", "--label", "bug"])
    assert code == 0
    assert seen == {"labels": ["openagents", "bug"]}


def test_poll_runs_preflight_then_polls(monkeypatch):
    calls = _patch_ensure(monkeypatch)

    class _FakeMessages:
        def poll(self):
            return [{"pr_number": 9, "reason": "comment"}]

    monkeypatch.setattr("openagents.cli._messages_for", lambda *, ctx: _FakeMessages())
    code = main(["poll"])
    assert code == 0
    assert calls == [True]


def test_vigil_runs_preflight_with_defaults(monkeypatch):
    # RFC-0004 T3：vigil 先跑 preflight，未传参时用默认值。
    calls = _patch_ensure(monkeypatch)
    seen = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once):
            seen.update(interval=interval, labels=labels, base=base, once=once)

    monkeypatch.setattr("openagents.cli._vigil_for", lambda *, ctx: _FakeVigil())
    code = main(["vigil"])
    assert code == 0
    assert calls == [True]
    assert seen == {"interval": 60, "labels": ["openagents"], "base": "main", "once": False}


def test_vigil_passes_all_overrides(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once):
            seen.update(interval=interval, labels=labels, base=base, once=once)

    monkeypatch.setattr("openagents.cli._vigil_for", lambda *, ctx: _FakeVigil())
    code = main(
        ["vigil", "--once", "--interval", "5", "--label", "a", "--label", "b", "--base", "dev"]
    )
    assert code == 0
    assert seen == {"interval": 5, "labels": ["a", "b"], "base": "dev", "once": True}


def test_init_runs_interactive_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    code = main(["init"])
    assert code == 0
    assert calls == [True]


def test_board_skips_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.results.board", lambda *, state: Path("/tmp/board.html"))
    code = main(["board"])
    assert code == 0
    assert calls == []
