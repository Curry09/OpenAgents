"""RFC-0001 T1: CLI 子命令注册与 preflight 调用的契约测试。"""

from pathlib import Path

import pytest

from openagents.cli import build_parser, main
from openagents.config import ProjectContext

COMMANDS = ["init", "solve", "poll", "watch", "board"]


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


def test_solve_runs_interactive_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    code = main(["solve", "1"])
    assert code == 0
    assert calls == [True]


def test_init_runs_interactive_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    code = main(["init"])
    assert code == 0
    assert calls == [True]


def test_board_skips_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    code = main(["board"])
    assert code == 0
    assert calls == []
