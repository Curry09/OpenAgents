"""RFC-0001 T1: CLI 子命令注册与 preflight 调用的契约测试。"""

from pathlib import Path

import pytest

from openagents.cli import build_parser, main
from openagents.config import ProjectContext
from openagents.github import Issue

COMMANDS = ["init", "solve", "issue", "poll", "watch", "board"]


def test_parser_registers_all_subcommands():
    parser = build_parser()
    subparsers = next(a for a in parser._actions if getattr(a, "choices", None))
    for cmd in COMMANDS:
        assert cmd in subparsers.choices


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


def test_solve_runs_preflight_then_opens_pr(monkeypatch):
    calls = _patch_ensure(monkeypatch)

    class _FakeOrch:
        def solve(self, *, issue_number, base):
            assert issue_number == 1
            # RFC-0003：未传 --base 时默认 main。
            assert base == "main"
            return _FakePR()

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    code = main(["solve", "1"])
    assert code == 0
    assert calls == [True]


def test_solve_passes_base_override(monkeypatch):
    # RFC-0003 决策 3：--base 透传给 Orchestrator.solve。
    _patch_ensure(monkeypatch)
    seen = {}

    class _FakeOrch:
        def solve(self, *, issue_number, base):
            seen.update(issue_number=issue_number, base=base)
            return _FakePR()

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    code = main(["solve", "7", "--base", "dev"])
    assert code == 0
    assert seen == {"issue_number": 7, "base": "dev"}


def test_solve_reports_error_cleanly_without_traceback(monkeypatch, capsys):
    # RFC-0003 决策 9：业务异常转成干净的一行提示 + 非零退出，不吐 traceback。
    _patch_ensure(monkeypatch)
    from openagents.orchestrator import OrchestratorError

    class _Boom:
        def solve(self, *, issue_number, base):
            raise OrchestratorError("push 被拒：non-fast-forward")

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _Boom())
    code = main(["solve", "3"])

    assert code == 1
    err = capsys.readouterr().err
    assert "✗" in err
    assert "non-fast-forward" in err


def test_issue_runs_preflight_then_creates_issue(monkeypatch):
    # RFC-0002 T2：issue 命令先跑 preflight，再把 title/body/labels 透传给 github.create_issue。
    calls = _patch_ensure(monkeypatch)
    seen = {}

    def fake_create_issue(*, title, body, labels):
        seen.update(title=title, body=body, labels=labels)
        return Issue(number=13, title=title, body=body)

    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "Login broken", "--body", "repro", "--label", "bug", "--label", "p1"])
    assert code == 0
    assert calls == [True]
    assert seen == {"title": "Login broken", "body": "repro", "labels": ["bug", "p1"]}


def test_issue_defaults_empty_body_and_labels(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = {}

    def fake_create_issue(*, title, body, labels):
        seen.update(title=title, body=body, labels=labels)
        return Issue(number=1, title=title, body=body)

    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "Just a title"])
    assert code == 0
    assert seen == {"title": "Just a title", "body": "", "labels": []}


def test_poll_runs_preflight_then_polls(monkeypatch):
    calls = _patch_ensure(monkeypatch)

    class _FakeMessages:
        def poll(self):
            return [{"pr_number": 9, "reason": "comment"}]

    monkeypatch.setattr("openagents.cli._messages_for", lambda *, ctx: _FakeMessages())
    code = main(["poll"])
    assert code == 0
    assert calls == [True]


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
