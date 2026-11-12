"""Spec-0064/T6: CLI after condense (vigil/issue/backfill-rfc/release + init/board + hide reply-comment)
The sub-orders are registered and distributed in contract tests.

Nine automated cystlic commands (rfc/refine-rfc/implement/iterate/solve/poll/watch/vigil-all/fleet) have been incorporated
vigil, delete them with two stacks, and this document will not assert them. Retain the retention order (init/issue/board/release/reply-comment/)
vigil/backfill-rfc) + Error management contract (poster/recide, hermetic without touching the real gh/backend).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from openagents.cli import build_parser, main
from openagents.utils.align import Alignment
from openagents.utils.config import ProjectContext
from openagents.utils.github import Issue

# Spec-0064/T6: The Retention Order Collection (init/board observation & self-activation, issue/backfill-rfc/vigil/release trigger,
# Reply-comment hides inside.
COMMANDS = ["init", "issue", "backfill-rfc", "vigil", "release", "board", "reply-comment"]


def test_parser_registers_retained_subcommands():
    subparsers = next(a for a in build_parser()._actions if getattr(a, "choices", None))
    for cmd in COMMANDS:
        assert cmd in subparsers.choices


def test_old_nine_commands_absent():
    subparsers = next(a for a in build_parser()._actions if getattr(a, "choices", None))
    for cmd in (
        "rfc",
        "refine-rfc",
        "implement",
        "iterate",
        "solve",
        "poll",
        "watch",
        "vigil-all",
        "fleet",
    ):
        assert cmd not in subparsers.choices


def test_unknown_command_errors():
    with pytest.raises(SystemExit) as exc:
        main(["definitely-not-a-command"])
    assert exc.value.code != 0


def test_no_command_returns_nonzero():
    assert main([]) != 0


def test_backend_factory_selects_nexau_from_environment(monkeypatch):
    import openagents.backends.nexau as nexau_backend
    import openagents.cli as cli

    marker = object()
    monkeypatch.setenv("OPENAGENTS_BACKEND", "nexau")
    monkeypatch.setattr(nexau_backend, "NexAUBackend", lambda: marker)
    assert cli._backend_for() is marker


def _patch_ensure(monkeypatch, *, repo_root="/tmp/x"):
    calls = []
    fake = ProjectContext(repo_root=Path(repo_root), remote="https://github.com/x/y.git")

    def fake_ensure(*, interactive):
        calls.append(interactive)
        return fake

    monkeypatch.setattr("openagents.cli.ensure_project", fake_ensure)
    monkeypatch.setattr("openagents.utils.github.ensure_prerequisites", lambda: None)
    monkeypatch.setattr("openagents.cli._persist_ui_capable", lambda *, ctx: None)
    return calls


# --------------------------------------------------------------------------- #
# vigil: Read config (default default) single-silo run_vigil
# --------------------------------------------------------------------------- #


def test_vigil_dispatches_to_run_vigil(monkeypatch, tmp_path):
    _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    monkeypatch.setattr("openagents.cli._vigil_deps_for", lambda *, ctx: ("BE", "ST", "AID"))
    seen = {}
    import openagents.recipes.vigil as vigil_mod

    def _fake_run_vigil(*, backend, state, work_dir, config, once, concurrency, agent_id):
        seen.update(
            once=once,
            concurrency=concurrency,
            agent_id=agent_id,
            merge_owner=config.stages.owner_of(stage="merge"),
        )

    monkeypatch.setattr(vigil_mod, "run_vigil", _fake_run_vigil)
    code = main(["vigil", "--once"])
    assert code == 0
    assert seen["once"] is True
    assert seen["concurrency"] == 1  # Spec-0065/T2: default K=1, or degradation string
    assert seen["agent_id"] == "AID"
    assert seen["merge_owner"] == "agent"  # Default YaML  → merge=att


def test_vigil_parallel_flag_sets_concurrency(monkeypatch, tmp_path):
    """Spec-0065/T2: `--parallel K` falls directly to `run_vigil(concurrency=K)` (the concurring cap, not another mode)."""
    _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    monkeypatch.setattr("openagents.cli._vigil_deps_for", lambda *, ctx: ("BE", "ST", "AID"))
    seen = {}
    monkeypatch.setattr(
        "openagents.recipes.vigil.run_vigil", lambda **kw: seen.update(k=kw["concurrency"])
    )
    assert main(["vigil", "--once", "--parallel", "4"]) == 0
    assert seen["k"] == 4


def test_vigil_persists_ui_capable(monkeypatch, tmp_path):
    _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    seen = {"n": 0}
    monkeypatch.setattr(
        "openagents.cli._persist_ui_capable", lambda *, ctx: seen.__setitem__("n", seen["n"] + 1)
    )
    monkeypatch.setattr("openagents.cli._vigil_deps_for", lambda *, ctx: ("BE", "ST", "AID"))
    monkeypatch.setattr("openagents.recipes.vigil.run_vigil", lambda **kw: None)
    assert main(["vigil", "--once"]) == 0
    assert seen["n"] == 1


def test_vigil_invalid_config_errors_cleanly(monkeypatch, tmp_path):
    _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    d = tmp_path / ".openagents"
    d.mkdir()
    (d / "openagents.yml").write_text(
        "stages:\n  merge: skip\n", encoding="utf-8"
    )  # Illegal: merge not skip
    code = main(["vigil", "--once"])
    assert code == 1


# --------------------------------------------------------------------------- #
# backfill-rfc
# --------------------------------------------------------------------------- #


def test_backfill_rfc_forwards_path(monkeypatch, tmp_path):
    _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    monkeypatch.setattr("openagents.cli._backend_for", lambda: object())
    seen = {}
    import openagents.recipes.backfill as backfill_mod

    monkeypatch.setattr(
        backfill_mod,
        "backfill_rfc",
        lambda **kw: seen.update(kw) or {"pr_number": 9},
    )
    code = main(["backfill-rfc", "openagents/release.py"])
    assert code == 0
    assert seen["path"] == "openagents/release.py"
    assert seen["base"] == "main"


def test_backfill_rfc_reports_error_cleanly(monkeypatch, tmp_path, capsys):
    _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    monkeypatch.setattr("openagents.cli._backend_for", lambda: object())
    import openagents.recipes.backfill as backfill_mod
    from openagents.recipes.backfill import BackfillError

    def _boom(**kw):
        raise BackfillError("Path does not exist:nope")

    monkeypatch.setattr(backfill_mod, "backfill_rfc", _boom)
    code = main(["backfill-rfc", "nope"])
    assert code == 1
    assert "Path does not exist" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Issue(Signature/ Tab)
# --------------------------------------------------------------------------- #


def test_issue_yes_creates_with_discovery_label(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    seen = {}

    def fake_create_issue(*, title, body, labels):
        seen.update(title=title, body=body, labels=labels)
        return Issue(number=13, title=title, body=body)

    monkeypatch.setattr("openagents.utils.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr("openagents.utils.github.create_issue", fake_create_issue)
    code = main(["issue", "Login broken", "--body", "repro", "--label", "bug", "--yes"])
    assert code == 0
    assert calls == [True]
    assert seen == {"title": "Login broken", "body": "repro", "labels": ["bug", "openagents"]}


def test_issue_alignment_declined_does_not_create(monkeypatch):
    _patch_ensure(monkeypatch)
    monkeypatch.setattr(
        "openagents.utils.align.restate",
        lambda *, draft, backend: Alignment(want="X", boundary="Y", non_goals="Z"),
    )
    monkeypatch.setattr("openagents.cli._backend_for", lambda: object())
    monkeypatch.setattr("builtins.input", lambda _p: "n")
    created = []
    monkeypatch.setattr("openagents.utils.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr(
        "openagents.utils.github.create_issue",
        lambda *, title, body, labels: created.append(title),
    )
    assert main(["issue", "Login function"]) == 1
    assert created == []


# --------------------------------------------------------------------------- #
# reply-comment / release / board / init
# --------------------------------------------------------------------------- #


def test_reply_comment_posts_signed(monkeypatch):
    _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.cli._agent_id_for", lambda *, ctx: "agent-x")
    seen = {}
    monkeypatch.setattr(
        "openagents.utils.identity.post_signed_comment",
        lambda *, pr_number, body, agent_id: seen.update(
            pr_number=pr_number, body=body, agent_id=agent_id
        ),
    )
    code = main(["reply-comment", "--pr", "5", "--body", "Solved Conflict"])
    assert code == 0
    assert seen == {"pr_number": 5, "body": "Solved Conflict", "agent_id": "agent-x"}


def test_release_success(monkeypatch):
    from openagents.utils.release import ReleaseResult

    _patch_ensure(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        "openagents.utils.release.release",
        lambda *, state, bump: (
            seen.update(bump=bump) or ReleaseResult(released=True, version="v1.2.4", reason="ok")
        ),
    )
    assert main(["release"]) == 0
    assert seen["bump"] == "patch"


def test_release_precheck_fail_nonzero(monkeypatch, capsys):
    from openagents.utils.release import ReleaseResult

    _patch_ensure(monkeypatch)
    monkeypatch.setattr(
        "openagents.utils.release.release",
        lambda *, state, bump: ReleaseResult(
            released=False, version="", reason="main branch has not passed CI"
        ),
    )
    assert main(["release"]) == 1
    assert "has not passed CI" in capsys.readouterr().err


def test_board_skips_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.utils.results.board", lambda *, state: Path("/tmp/board.html"))
    code = main(["board"])
    assert code == 0
    assert calls == []


def test_init_runs_preflight_and_envcheck(monkeypatch, tmp_path):
    calls = _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    monkeypatch.setattr("openagents.utils.github.ensure_prerequisites", lambda: None)
    monkeypatch.setattr(
        "openagents.utils.envcheck.check",
        lambda: SimpleNamespace(text="Medical examination", all_ok=True),
    )
    assert main(["init"]) == 0
    assert calls == [True]


# --------------------------------------------------------------------------- #
# Spec-0067/T2: init & scafferdold default. openagents/openagents.yml (Quest / --force overwrite)
# --------------------------------------------------------------------------- #


def _quiet_envcheck(monkeypatch):
    monkeypatch.setattr(
        "openagents.utils.envcheck.check",
        lambda: SimpleNamespace(text="Medical examination", all_ok=True),
    )


def test_parser_registers_init_force_flag():
    subparsers = next(a for a in build_parser()._actions if getattr(a, "choices", None))
    init = subparsers.choices["init"]
    assert any(a.dest == "force" and a.const is True for a in init._actions)


def test_init_generates_default_config_first_run(monkeypatch, tmp_path, capsys):
    _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    _quiet_envcheck(monkeypatch)
    cfg = tmp_path / ".openagents" / "openagents.yml"
    assert not cfg.exists()
    assert main(["init"]) == 0
    assert cfg.exists()
    from openagents.utils.agent_config import _default_template_text

    assert cfg.read_text(encoding="utf-8") == _default_template_text()
    assert "Wrote .openagents/openagents.yml" in capsys.readouterr().out


def test_init_is_idempotent_and_preserves_user_edits(monkeypatch, tmp_path, capsys):
    _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    _quiet_envcheck(monkeypatch)
    cfg = tmp_path / ".openagents" / "openagents.yml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("stages:\n  review: human\n", encoding="utf-8")
    assert main(["init"]) == 0
    assert cfg.read_text(encoding="utf-8") == "stages:\n  review: human\n"
    assert "Kept the existing .openagents/openagents.yml" in capsys.readouterr().out


def test_init_force_overwrites_config(monkeypatch, tmp_path, capsys):
    _patch_ensure(monkeypatch, repo_root=str(tmp_path))
    _quiet_envcheck(monkeypatch)
    cfg = tmp_path / ".openagents" / "openagents.yml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("stages:\n  review: human\n", encoding="utf-8")
    assert main(["init", "--force"]) == 0
    from openagents.utils.agent_config import _default_template_text

    assert cfg.read_text(encoding="utf-8") == _default_template_text()
    assert "Replaced .openagents/openagents.yml" in capsys.readouterr().out


def test_missing_dependency_hint(monkeypatch, capsys):
    _patch_ensure(monkeypatch)

    def _boom(args):
        raise ModuleNotFoundError("No module named 'ruamel'", name="ruamel")

    monkeypatch.setattr("openagents.cli._dispatch", _boom)
    code = main(["issue", "x", "--yes"])
    assert code == 1
    err = capsys.readouterr().err
    assert "ruamel" in err
    assert "uv pip install -e ." in err


def test_internal_module_error_reraises(monkeypatch):
    _patch_ensure(monkeypatch)

    def _boom(args):
        raise ModuleNotFoundError("No module named 'openagents.foo'", name="openagents.foo")

    monkeypatch.setattr("openagents.cli._dispatch", _boom)
    with pytest.raises(ModuleNotFoundError):
        main(["issue", "x", "--yes"])


# --------------------------------------------------------------------------- #
# agent_id connection consistency (RFC-0011 T6)
# --------------------------------------------------------------------------- #


def test_agent_id_stable(monkeypatch, tmp_path):
    from openagents.cli import _agent_id_for

    monkeypatch.delenv("OPENAGENTS_AGENT_ID", raising=False)
    ctx = ProjectContext(repo_root=tmp_path, remote="https://github.com/x/y.git")
    first = _agent_id_for(ctx=ctx)
    assert first and first == _agent_id_for(ctx=ctx)


def test_agent_id_env_override(monkeypatch, tmp_path):
    from openagents.cli import _agent_id_for

    monkeypatch.setenv("OPENAGENTS_AGENT_ID", "alice")
    ctx = ProjectContext(repo_root=tmp_path, remote="https://github.com/x/y.git")
    assert _agent_id_for(ctx=ctx) == "alice"


# --------------------------------------------------------------------------- #
# Spec-0065/T2: `--parallel K` entry and verification (1.32, illegal on-site aggparse error, silent plier)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["1", "2", "32"])
def test_parallel_accepts_valid_k(value):
    """Spec-0065/T2 1: {_MAX_PARALLEL} is legal; the 1 (serial) and 32 (ceiling) borders are required to pass."""
    args = build_parser().parse_args(["vigil", "--once", "--parallel", value])
    assert args.parallel == int(value)


@pytest.mark.parametrize("value", ["0", "-3", "33", "99999", "abc", "1.5", ""])
def test_parallel_rejects_invalid_k(value):
    """Spec-0065/T2: Cross-border/non-integer  →  argparse exits on the spot (code 2).

    Unquieted pliers (`max(1, K)` earlier): `--parallel 0` quietly gives one to turn input errors into performance puzzles.
    """
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["vigil", "--once", "--parallel", value])
    assert exc.value.code == 2


def test_parallel_invalid_k_via_main_exits_two(monkeypatch):
    """Spec-0065/T2: The same is true of the `main()` path (check in parser, before any preflight/ backend)."""
    with pytest.raises(SystemExit) as exc:
        main(["vigil", "--once", "--parallel", "99999"])
    assert exc.value.code == 2


def test_parallel_max_is_thirty_two():
    """Spec-0065/T2: The constant of the guard column is the same as the one used - the ceiling is changed here and then it should be changed (do not snuck up)."""
    from openagents.cli import _MAX_PARALLEL

    assert _MAX_PARALLEL == 32


# --------------------------------------------------------------------------------------------------
# Spec-0069/T1: argcomplete Shell Tab Comply with the Connector Compact. Read the complete as build_parser.
# The list of commands is not copied; autocomplete must be transposed before parse_args, intervene when handshake is completed and normally call zero side effects;
# Argcomplete is not lost when it is missing.
# --------------------------------------------------------------------------------------------------


def test_main_calls_argcomplete_before_parse(monkeypatch):
    """Main() parse_args is tuned to argcomplete.autocomplete (parser) just once, with argparse parser."""
    import argparse

    calls = []

    class _FakeArgcomplete:
        def autocomplete(self, parser):
            calls.append(parser)

    monkeypatch.setattr("openagents.cli.argcomplete", _FakeArgcomplete())
    # No command: parse_args succeeded but args.command is None  →  Print Help, returns 2, without touching any gh/backend.
    assert main([]) == 2
    assert len(calls) == 1
    assert isinstance(calls[0], argparse.ArgumentParser)


def test_argcomplete_missing_degrades_gracefully(monkeypatch):
    """CLI does not fall when argcomplete is missing (top level Import failed None), and the behaviour remains the same word for word."""
    monkeypatch.setattr("openagents.cli.argcomplete", None)
    assert main([]) == 2


def test_completion_covers_vigil_options():
    """Complete the candidate coverage: all options for the vigil sub-command are in parser (argecomplete is the basis for the candidate)."""
    subparsers = next(a for a in build_parser()._actions if getattr(a, "choices", None))
    vigil = subparsers.choices["vigil"]
    options = {opt for action in vigil._actions for opt in action.option_strings}
    for expected in (
        "--interval",
        "--label",
        "--base",
        "--once",
        "--parallel",
        "--skip",
        "--config",
    ):
        assert expected in options
    assert "--" + "hold" not in options
