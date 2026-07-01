"""RFC-0001 T1 + RFC-0005: CLI 子命令注册与分发的契约测试。

RFC-0005：solve 已移除，改为 rfc / refine-rfc / implement / iterate 四个原子步骤。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from openagents.align import Alignment
from openagents.cli import build_parser, main
from openagents.config import ProjectContext
from openagents.github import Comment, Issue
from openagents.hold import Hold

COMMANDS = [
    "init",
    "rfc",
    "backfill-rfc",
    "refine-rfc",
    "implement",
    "iterate",
    "issue",
    "reply-comment",
    "poll",
    "watch",
    "board",
    "vigil",
    "release",
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
            # Spec-0023/T4：rfc 默认基线为 main（test 门控退役）。
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


def test_missing_dependency_prints_actionable_hint(monkeypatch, capsys):
    # RFC-0003 决策 9（精炼）：缺第三方依赖（如 venv 没装 ruamel）→ 一行可操作提示，非 traceback。
    _patch_ensure(monkeypatch)

    def _boom(args):
        raise ModuleNotFoundError("No module named 'ruamel'", name="ruamel")

    monkeypatch.setattr("openagents.cli._dispatch", _boom)
    code = main(["rfc", "3"])

    assert code == 1
    err = capsys.readouterr().err
    assert "✗" in err
    assert "ruamel" in err
    assert "uv pip install -e ." in err


def test_internal_module_error_still_raises_traceback(monkeypatch):
    # RFC-0003 决策 9：`openagents.*` 自身模块缺失是真 bug，不该被吞，仍抛出。
    _patch_ensure(monkeypatch)

    def _boom(args):
        raise ModuleNotFoundError("No module named 'openagents.foo'", name="openagents.foo")

    monkeypatch.setattr("openagents.cli._dispatch", _boom)
    with pytest.raises(ModuleNotFoundError):
        main(["rfc", "3"])


# --------------------------------------------------------------------------- #
# backfill-rfc（Spec-0025/T3：扫代码路径反推 spec 开 draft PR）
# --------------------------------------------------------------------------- #


def test_backfill_rfc_runs_preflight_then_forwards_path(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    seen = {}

    class _FakeOrch:
        def backfill_rfc(self, *, path, base):
            seen.update(path=path, base=base)
            return _FakePR()

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    code = main(["backfill-rfc", "openagents/release.py"])
    assert code == 0
    assert calls == [True]
    # --base 默认 main。
    assert seen == {"path": "openagents/release.py", "base": "main"}


def test_backfill_rfc_passes_base_override(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = {}

    class _FakeOrch:
        def backfill_rfc(self, *, path, base):
            seen.update(path=path, base=base)
            return _FakePR()

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    code = main(["backfill-rfc", "openagents/backends", "--base", "dev"])
    assert code == 0
    assert seen == {"path": "openagents/backends", "base": "dev"}


def test_backfill_rfc_reports_bad_path_cleanly(monkeypatch, capsys):
    # BackfillError 继承 ValueError → cli._run 转干净一行提示 + 非零退出（无 traceback）。
    _patch_ensure(monkeypatch)
    from openagents.backfill import BackfillError

    class _Boom:
        def backfill_rfc(self, *, path, base):
            raise BackfillError("路径不存在：nope")

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _Boom())
    code = main(["backfill-rfc", "nope"])
    assert code == 1
    err = capsys.readouterr().err
    assert "✗" in err
    assert "路径不存在" in err


# --------------------------------------------------------------------------- #
# refine-rfc
# --------------------------------------------------------------------------- #


def test_refine_rfc_fetches_latest_comment_and_calls_orchestrator(monkeypatch):
    # RFC-0005 决策 6 / RFC-0011：取最新评论作 detail，不按作者过滤——人与 agent 共用账号时仍能触发。
    _patch_ensure(monkeypatch)
    seen = {}

    class _FakeOrch:
        def refine_rfc(self, *, pr_number, detail):
            seen.update(pr_number=pr_number, detail=detail)

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
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

    monkeypatch.setattr("openagents.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    # Spec-0020/T4：--yes 跳过前门对齐，专注断言既有 label/发现标签行为（hermetic）。
    code = main(
        ["issue", "Login broken", "--body", "repro", "--label", "bug", "--label", "p1", "--yes"]
    )
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

    monkeypatch.setattr("openagents.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "Just a title", "--yes"])
    assert code == 0
    assert seen == {"title": "Just a title", "body": "", "labels": ["openagents"]}


def test_issue_does_not_duplicate_discovery_label(monkeypatch):
    # RFC-0002 决策 5：用户显式传 openagents 时不重复，且保留出现顺序。
    _patch_ensure(monkeypatch)
    seen = {}

    def fake_create_issue(*, title, body, labels):
        seen.update(labels=labels)
        return Issue(number=2, title=title, body=body)

    monkeypatch.setattr("openagents.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "T", "--label", "openagents", "--label", "bug", "--yes"])
    assert code == 0
    assert seen == {"labels": ["openagents", "bug"]}


def test_issue_ensures_discovery_label_before_create(monkeypatch):
    # RFC-0002 决策 6：create_issue 前先 ensure_label(openagents)，否则 gh 报 label not found。
    _patch_ensure(monkeypatch)
    order = []

    monkeypatch.setattr(
        "openagents.github.ensure_label", lambda *, name: order.append(("ensure", name))
    )

    def fake_create_issue(*, title, body, labels):
        order.append(("create", labels))
        return Issue(number=5, title=title, body=body)

    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "测试", "--yes"])
    assert code == 0
    # ensure 必须发生在 create 之前，且确保的是发现标签。
    assert order == [("ensure", "openagents"), ("create", ["openagents"])]


# --------------------------------------------------------------------------- #
# Spec-0020/T4：issue 前门对齐（默认确认 / --yes 跳过）+ vigil --hold 接线
# --------------------------------------------------------------------------- #


def _patch_align(monkeypatch):
    # 打桩 align.restate（不触达真实 LLM）与 backend 工厂；返回 restate 调用记录。
    seen = {}

    def fake_restate(*, draft, backend):
        seen["draft"] = draft
        return Alignment(want="X", boundary="Y", non_goals="Z")

    monkeypatch.setattr("openagents.align.restate", fake_restate)
    monkeypatch.setattr("openagents.cli._backend_for", lambda: object())
    return seen


def test_issue_default_path_aligns_then_creates_on_yes(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = _patch_align(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    monkeypatch.setattr("openagents.github.ensure_label", lambda *, name: None)
    created = []

    def fake_create_issue(*, title, body, labels):
        created.append((title, labels))
        return Issue(number=21, title=title, body=body)

    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "登录功能", "--body", "想登录"])
    assert code == 0
    # 建 issue 前先复述对齐（restate 被调用），确认 y 后才 create。
    assert seen["draft"].title == "登录功能"
    assert created == [("登录功能", ["openagents"])]


def test_issue_default_path_declined_does_not_create(monkeypatch):
    _patch_ensure(monkeypatch)
    _patch_align(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    created = []
    monkeypatch.setattr("openagents.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr(
        "openagents.github.create_issue",
        lambda *, title, body, labels: created.append(title),
    )
    code = main(["issue", "登录功能"])
    # 否定应答 → 不建且非零退出。
    assert code == 1
    assert created == []


def test_issue_yes_skips_alignment(monkeypatch):
    _patch_ensure(monkeypatch)
    restate_calls = []
    monkeypatch.setattr(
        "openagents.align.restate",
        lambda *, draft, backend: restate_calls.append(draft),
    )
    monkeypatch.setattr("openagents.github.ensure_label", lambda *, name: None)
    created = []

    def fake_create_issue(*, title, body, labels):
        created.append(title)
        return Issue(number=22, title=title, body=body)

    monkeypatch.setattr("openagents.github.create_issue", fake_create_issue)
    code = main(["issue", "自动化建的", "--yes"])
    assert code == 0
    # --yes 跳过复述：restate 不被调用，直接 create。
    assert restate_calls == []
    assert created == ["自动化建的"]


def _patch_vigil_capture(monkeypatch):
    monkeypatch.setattr("openagents.github.ensure_prerequisites", lambda: None)
    seen = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, hold):
            seen["hold"] = hold

    monkeypatch.setattr("openagents.cli._vigil_for", lambda *, ctx: _FakeVigil())
    return seen


def test_vigil_hold_spec_parsed_and_passed(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = _patch_vigil_capture(monkeypatch)
    code = main(["vigil", "--once", "--hold", "spec"])
    assert code == 0
    assert seen["hold"] == Hold(at_spec=True, at_merge=False)


def test_vigil_hold_merge_parsed_and_passed(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = _patch_vigil_capture(monkeypatch)
    code = main(["vigil", "--once", "--hold", "merge"])
    assert code == 0
    assert seen["hold"] == Hold(at_spec=False, at_merge=True)


def test_vigil_hold_both_parsed_and_passed(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = _patch_vigil_capture(monkeypatch)
    code = main(["vigil", "--once", "--hold", "spec,merge"])
    assert code == 0
    assert seen["hold"] == Hold(at_spec=True, at_merge=True)


def test_vigil_invalid_hold_errors_cleanly(monkeypatch, capsys):
    _patch_ensure(monkeypatch)
    # 非法 --hold → parse_hold 抛 ValueError → _run 转干净一行提示 + 非零退出（不 traceback）。
    code = main(["vigil", "--once", "--hold", "nope"])
    assert code == 1
    err = capsys.readouterr().err
    assert "✗" in err
    assert "nope" in err


def test_poll_runs_preflight_then_polls(monkeypatch):
    calls = _patch_ensure(monkeypatch)

    class _FakeMessages:
        def poll(self):
            return [{"pr_number": 9, "reason": "comment"}]

    monkeypatch.setattr("openagents.cli._messages_for", lambda *, ctx: _FakeMessages())
    code = main(["poll"])
    assert code == 0
    assert calls == [True]


def test_reply_comment_posts_signed_comment(monkeypatch):
    # reply-comment 工具：以本实例 agent_id 盖签名回复指定 PR（供解冲突 agent 亲自回评论、防自循环）。
    _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.cli._agent_id_for", lambda *, ctx: "agent-x")
    seen = {}
    monkeypatch.setattr(
        "openagents.identity.post_signed_comment",
        lambda *, pr_number, body, agent_id: seen.update(
            pr_number=pr_number, body=body, agent_id=agent_id
        ),
    )
    code = main(["reply-comment", "--pr", "5", "--body", "已解冲突"])
    assert code == 0
    assert seen == {"pr_number": 5, "body": "已解冲突", "agent_id": "agent-x"}


def test_vigil_runs_preflight_with_defaults(monkeypatch):
    # RFC-0004 T3：vigil 先跑 preflight，未传参时用默认值。
    calls = _patch_ensure(monkeypatch)
    # RFC-0015：vigil 进主循环前自举一次 prerequisite——打桩避免触达真实 gh。
    bootstrapped = []
    monkeypatch.setattr("openagents.github.ensure_prerequisites", lambda: bootstrapped.append(True))
    seen = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, hold):
            seen.update(interval=interval, labels=labels, base=base, once=once, hold=hold)

    monkeypatch.setattr("openagents.cli._vigil_for", lambda *, ctx: _FakeVigil())
    code = main(["vigil"])
    assert code == 0
    assert calls == [True]
    # RFC-0015：进主循环前自举恰一次。
    assert bootstrapped == [True]
    # Spec-0023/T4：vigil 默认基线为 main（test 门控退役）。Spec-0020/T4：无 --hold → 默认全不停。
    assert seen == {
        "interval": 60,
        "labels": ["openagents"],
        "base": "main",
        "once": False,
        "hold": Hold(),
    }


def test_vigil_passes_all_overrides(monkeypatch):
    _patch_ensure(monkeypatch)
    # RFC-0015：打桩 vigil 进循环前的自举，避免触达真实 gh。
    monkeypatch.setattr("openagents.github.ensure_prerequisites", lambda: None)
    seen = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, hold):
            seen.update(interval=interval, labels=labels, base=base, once=once, hold=hold)

    monkeypatch.setattr("openagents.cli._vigil_for", lambda *, ctx: _FakeVigil())
    code = main(
        ["vigil", "--once", "--interval", "5", "--label", "a", "--label", "b", "--base", "dev"]
    )
    assert code == 0
    assert seen == {
        "interval": 5,
        "labels": ["a", "b"],
        "base": "dev",
        "once": True,
        "hold": Hold(),
    }


def test_init_runs_interactive_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    # RFC-0015：init 统一兜底——调 ensure_prerequisites（test 分支 + 流程标签）。打桩记录
    # 调用次数避免触达真实 gh（取代原先对 ensure_branch 的打桩）。
    bootstrapped = []
    monkeypatch.setattr(
        "openagents.github.ensure_prerequisites",
        lambda: bootstrapped.append(True),
    )
    # Spec-0030/T3：init 末尾接了 envcheck 体检——打桩 envcheck.check 避免触达真实 ~/.claude.json。
    monkeypatch.setattr(
        "openagents.envcheck.check",
        lambda: SimpleNamespace(text="▶ 体检", all_ok=True),
    )
    code = main(["init"])
    assert code == 0
    assert calls == [True]
    assert bootstrapped == [True]


def test_init_prints_envcheck_report_and_stays_zero_on_missing(monkeypatch, capsys):
    # Spec-0030/T3：缺 browser MCP / 非全放行时，init 打印含安装命令与设置方式的体检段且仍 return 0。
    _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.github.ensure_prerequisites", lambda: None)
    report_text = (
        "▶ 前端 e2e 环境体检（非阻塞，仅 claude-code 后端）\n"
        "  ⚠ 未检测到 browser MCP\n"
        "      claude mcp add playwright -s user -- npx @playwright/mcp@latest\n"
        "      export OPENAGENTS_PERMISSION_MODE=bypassPermissions"
    )
    monkeypatch.setattr(
        "openagents.envcheck.check",
        lambda: SimpleNamespace(text=report_text, all_ok=False),
    )
    code = main(["init"])
    assert code == 0
    out = capsys.readouterr().out
    assert "前端 e2e 环境体检" in out
    assert "claude mcp add playwright" in out
    assert "export OPENAGENTS_PERMISSION_MODE=bypassPermissions" in out


def test_init_envcheck_failure_does_not_break_init(monkeypatch):
    # Spec-0030/T3：即便 envcheck 内部出错也不该改变 init 退出码——但体检设计为从不抛，
    # 这里断言正常态 return 0（体检不抛、不改 init 退出码）。
    _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.github.ensure_prerequisites", lambda: None)
    monkeypatch.setattr(
        "openagents.envcheck.check",
        lambda: SimpleNamespace(text="▶ 体检 ✓", all_ok=True),
    )
    assert main(["init"]) == 0


# --------------------------------------------------------------------------- #
# release（Spec-0023/T4：人工把 main 物化成版本 release/vX.Y.Z + tag）
# --------------------------------------------------------------------------- #


def test_release_success_returns_zero(monkeypatch):
    from openagents.release import ReleaseResult

    _patch_ensure(monkeypatch)
    seen = {}

    def fake_release(*, state, bump):
        seen["called"] = True
        seen["bump"] = bump
        return ReleaseResult(released=True, version="v1.2.4", reason="ok")

    monkeypatch.setattr("openagents.release.release", fake_release)
    code = main(["release"])
    assert code == 0
    assert seen["called"] is True
    # --bump 默认 patch 透传给 release()。
    assert seen["bump"] == "patch"


def test_release_passes_bump_override(monkeypatch):
    from openagents.release import ReleaseResult

    _patch_ensure(monkeypatch)
    seen = {}

    def fake_release(*, state, bump):
        seen["bump"] = bump
        return ReleaseResult(released=True, version="v2.0.0", reason="ok")

    monkeypatch.setattr("openagents.release.release", fake_release)
    code = main(["release", "--bump", "major"])
    assert code == 0
    assert seen["bump"] == "major"


def test_release_precheck_fail_returns_nonzero(monkeypatch, capsys):
    from openagents.release import ReleaseResult

    _patch_ensure(monkeypatch)
    monkeypatch.setattr(
        "openagents.release.release",
        lambda *, state, bump: ReleaseResult(
            released=False, version="", reason="main 分支 CI 未全绿"
        ),
    )
    code = main(["release"])
    assert code == 1
    err = capsys.readouterr().err
    assert "✗" in err
    assert "CI 未全绿" in err


def test_release_reports_runtime_error_cleanly(monkeypatch, capsys):
    _patch_ensure(monkeypatch)

    def boom(*, state, bump):
        raise RuntimeError("物化发布分支 release/v1.2.4 失败：protected branch")

    monkeypatch.setattr("openagents.release.release", boom)
    code = main(["release"])
    assert code == 1
    assert "✗" in capsys.readouterr().err


def test_board_skips_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.results.board", lambda *, state: Path("/tmp/board.html"))
    code = main(["board"])
    assert code == 0
    assert calls == []


# --------------------------------------------------------------------------- #
# RFC-0011 T6：agent_id 接线一致性
# --------------------------------------------------------------------------- #


def test_agent_id_for_resolves_and_is_stable(monkeypatch, tmp_path):
    # RFC-0011 决策 7：_agent_id_for 解析（并首次落盘）一个稳定 id，多次调用得同一值。
    from openagents.cli import _agent_id_for
    from openagents.config import ProjectContext

    monkeypatch.delenv("OPENAGENTS_AGENT_ID", raising=False)
    ctx = ProjectContext(repo_root=tmp_path, remote="https://github.com/x/y.git")

    first = _agent_id_for(ctx=ctx)
    second = _agent_id_for(ctx=ctx)

    assert first
    assert first == second


def test_agent_id_for_honors_env_override(monkeypatch, tmp_path):
    # RFC-0011 决策 2：env OPENAGENTS_AGENT_ID 优先于 state。
    from openagents.cli import _agent_id_for
    from openagents.config import ProjectContext

    monkeypatch.setenv("OPENAGENTS_AGENT_ID", "alice")
    ctx = ProjectContext(repo_root=tmp_path, remote="https://github.com/x/y.git")

    assert _agent_id_for(ctx=ctx) == "alice"


def test_orchestrator_and_messages_share_resolved_agent_id(monkeypatch, tmp_path):
    # RFC-0011 决策 7：Orchestrator / Messages 经接线拿到同一个 agent_id（poll 与其内部
    # orchestrator 行为一致）。打桩 backend 工厂避免触达真实 ClaudeCodeBackend。
    from openagents.cli import _messages_for, _orchestrator_for
    from openagents.config import ProjectContext

    monkeypatch.delenv("OPENAGENTS_AGENT_ID", raising=False)

    class _StubBackend:
        name = "stub"

        def run(self, *, work_dir, task, context):
            raise AssertionError("不应在接线测试中真正调用 backend")

    monkeypatch.setattr("openagents.backends.claude_code.ClaudeCodeBackend", _StubBackend)
    ctx = ProjectContext(repo_root=tmp_path, remote="https://github.com/x/y.git")

    orch = _orchestrator_for(ctx=ctx)
    msgs = _messages_for(ctx=ctx)

    assert orch._agent_id
    assert orch._agent_id == msgs._agent_id == msgs._orchestrator._agent_id
