"""Spec-0064/T6: CLI 收敛后（vigil/issue/backfill-rfc/release + init/board + 隐藏 reply-comment）
子命令注册与分发契约测试。

九条自动化环切片命令（rfc/refine-rfc/implement/iterate/solve/poll/watch/vigil-all/fleet）已并入
vigil、随两栈合一删除，本文件不再断言它们。保留对留存命令（init/issue/board/release/reply-comment/
vigil/backfill-rfc）的路由 + 错误处理契约（打桩工厂/recipe，hermetic 不触真实 gh/后端）。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from openagents.cli import build_parser, main
from openagents.utils.align import Alignment
from openagents.utils.config import ProjectContext
from openagents.utils.github import Issue

# Spec-0064/T6：收敛后人面向留存命令集（init/board 观测·自举，issue/backfill-rfc/vigil/release 触发，
# reply-comment 隐藏内部）。
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
# vigil：读 config（缺省默认）→ 单仓走 run_vigil
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
    assert seen["concurrency"] == 1  # Spec-0065/T2：缺省 K=1，即退化串行
    assert seen["agent_id"] == "AID"
    assert seen["merge_owner"] == "agent"  # 缺省 YAML → 默认 merge=agent


def test_vigil_parallel_flag_sets_concurrency(monkeypatch, tmp_path):
    """Spec-0065/T2：`--parallel K` 直接落到 `run_vigil(concurrency=K)`（并发上限，不是另一种模式）。"""
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
    )  # 非法：merge 不可 skip
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
        raise BackfillError("路径不存在：nope")

    monkeypatch.setattr(backfill_mod, "backfill_rfc", _boom)
    code = main(["backfill-rfc", "nope"])
    assert code == 1
    assert "路径不存在" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# issue（对齐 / 标签）
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
    assert main(["issue", "登录功能"]) == 1
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
    code = main(["reply-comment", "--pr", "5", "--body", "已解冲突"])
    assert code == 0
    assert seen == {"pr_number": 5, "body": "已解冲突", "agent_id": "agent-x"}


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
            released=False, version="", reason="main 分支 CI 未全绿"
        ),
    )
    assert main(["release"]) == 1
    assert "CI 未全绿" in capsys.readouterr().err


def test_board_skips_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.utils.results.board", lambda *, state: Path("/tmp/board.html"))
    code = main(["board"])
    assert code == 0
    assert calls == []


def test_init_runs_preflight_and_envcheck(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.utils.github.ensure_prerequisites", lambda: None)
    monkeypatch.setattr(
        "openagents.utils.envcheck.check", lambda: SimpleNamespace(text="▶ 体检", all_ok=True)
    )
    assert main(["init"]) == 0
    assert calls == [True]


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
# agent_id 接线一致性（RFC-0011 T6）
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
# Spec-0065/T2：`--parallel K` 的入参校验（1..32，非法当场 argparse 报错，不静默钳位）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["1", "2", "32"])
def test_parallel_accepts_valid_k(value):
    """Spec-0065/T2：1..{_MAX_PARALLEL} 合法；边界 1（串行）与 32（上限）都必须过。"""
    args = build_parser().parse_args(["vigil", "--once", "--parallel", value])
    assert args.parallel == int(value)


@pytest.mark.parametrize("value", ["0", "-3", "33", "99999", "abc", "1.5", ""])
def test_parallel_rejects_invalid_k(value):
    """Spec-0065/T2：越界/非整数 → argparse 当场退出（code 2）。

    不静默钳位（早前是 `max(1, K)`）：`--parallel 0` 悄悄给成 1 会把输入错误变成性能谜题。
    """
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["vigil", "--once", "--parallel", value])
    assert exc.value.code == 2


def test_parallel_invalid_k_via_main_exits_two(monkeypatch):
    """Spec-0065/T2：走 `main()` 全路径也一样（校验在 parser 里，早于任何 preflight / 后端接线）。"""
    with pytest.raises(SystemExit) as exc:
        main(["vigil", "--once", "--parallel", "99999"])
    assert exc.value.code == 2


def test_parallel_max_is_thirty_two():
    """Spec-0065/T2：护栏常量与用例同源——上限改了这里就该跟着改（别偷偷放大）。"""
    from openagents.cli import _MAX_PARALLEL

    assert _MAX_PARALLEL == 32
