"""RFC-0001 T1 + RFC-0005: CLI 子命令注册与分发的契约测试。

RFC-0005：一站式 solve 已移除，旧栈改为 rfc / refine-rfc / implement / iterate 四个原子步骤。
Spec-0060/T6：**新栈** additive 重新引入 `solve` 子命令——走 solve_issue recipe（plan→implement→
review 循环→deliver），与旧四步原子命令并存（旧路由不动）。故不再断言「solve 不存在」。
Spec-0062/T4：CLI 全量改接新栈——rfc/backfill-rfc/refine-rfc/implement/iterate 走 recipes.rfc_lifecycle，
poll/watch 走 poll_comments+merge_pr 一次性，vigil 走新栈 _new_vigil_for + _new_merge_for（hold/skip
经守候段 merge_pr 落地）。本文件路由用例随之打桩到新栈 recipe/工厂入口（旧 _orchestrator_for/
_messages_for/_vigil_for 工厂已删）。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from openagents.cli import build_parser, main
from openagents.utils.align import Alignment
from openagents.utils.config import ProjectContext
from openagents.utils.github import Comment, Issue
from openagents.utils.hold import Hold
from openagents.utils.skip import NONE as NO_SKIP

COMMANDS = [
    "init",
    "rfc",
    "backfill-rfc",
    "refine-rfc",
    "implement",
    "solve",
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


def test_solve_is_new_stack_additive_subcommand():
    # Spec-0060/T6：新栈 solve 子命令 additive 存在（取 issue 号 + --base/--pr），与旧四步并存。
    parser = build_parser()
    args = parser.parse_args(["solve", "145"])
    assert args.command == "solve"
    assert args.issue == 145
    assert args.base == "main"
    assert args.pr is None


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
    # Spec-0039/T3：rfc/vigil 入口现会自举 ensure_prerequisites（预建流程标签）——默认打成 no-op
    # 保持 CLI 单测不触达真实 gh；需要观测调用的用例（如 rfc/vigil preflight）再各自 re-patch 记录。
    monkeypatch.setattr("openagents.utils.github.ensure_prerequisites", lambda: None)
    # Spec-0055/T1：poll/watch/vigil 入口现会固化 e2e 能力状态量——默认打成 no-op 保持 CLI 单测
    # 不触真实 ~/.claude.json / 不写真实 state；需要观测该调用的用例再各自 re-patch 记录。
    monkeypatch.setattr("openagents.cli._persist_ui_capable", lambda *, ctx: None)
    return calls


def _stub_rfc_factories(monkeypatch):
    # Spec-0062/T4：RFC recipe 接线参数（_rfc_kwargs）会实构造 backend/身份/RuntimeState——打桩成
    # sentinel 保持路由测试 hermetic（不触真实 ClaudeCodeBackend、不读写真实 runtime-state.json）。
    monkeypatch.setattr("openagents.cli._backend_for", lambda: object())
    monkeypatch.setattr("openagents.cli._agent_id_for", lambda *, ctx: "agent-x")
    monkeypatch.setattr("openagents.cli._new_runtime_state_for", lambda *, ctx: object())


# --------------------------------------------------------------------------- #
# rfc
# --------------------------------------------------------------------------- #


def test_rfc_runs_preflight_then_opens_draft_pr(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)

    def _fake_draft(*, issue_number, base, backend, state, work_dir, agent_id):
        assert issue_number == 1
        # Spec-0023/T4：rfc 默认基线为 main（test 门控退役）。
        assert base == "main"
        return {"pr_number": 9}

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.draft_rfc", _fake_draft)
    code = main(["rfc", "1"])
    assert code == 0
    assert calls == [True]


def test_rfc_bootstraps_prerequisites_before_draft(monkeypatch):
    # Spec-0039/T3：draft_rfc 现走 _claim 给 issue 打 DISPATCH_LABEL 认领标签，而
    # `gh issue edit --add-label` 对仓库中不存在的标签报 not found。故 `oa rfc` 必须像 vigil 一样
    # 在入口先幂等预建流程标签——否则未 `oa init` 的仓库上 rfc 首派单必抛 GithubError（回归）。
    _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)
    order = []
    monkeypatch.setattr(
        "openagents.utils.github.ensure_prerequisites", lambda: order.append("prerequisites")
    )

    def _fake_draft(*, issue_number, base, backend, state, work_dir, agent_id):
        order.append("draft_rfc")
        return {"pr_number": 9}

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.draft_rfc", _fake_draft)
    code = main(["rfc", "1"])
    assert code == 0
    # 预建流程标签必须发生在起草（→ 认领打标）之前，恰一次。
    assert order == ["prerequisites", "draft_rfc"]


def test_rfc_passes_base_override(monkeypatch):
    _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)
    seen = {}

    def _fake_draft(*, issue_number, base, backend, state, work_dir, agent_id):
        seen.update(issue_number=issue_number, base=base)
        return {"pr_number": 9}

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.draft_rfc", _fake_draft)
    code = main(["rfc", "7", "--base", "dev"])
    assert code == 0
    assert seen == {"issue_number": 7, "base": "dev"}


def test_rfc_reports_error_cleanly_without_traceback(monkeypatch, capsys):
    _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)
    from openagents.recipes.rfc_lifecycle import RfcLifecycleError

    def _boom(*, issue_number, base, backend, state, work_dir, agent_id):
        raise RfcLifecycleError("push 被拒：non-fast-forward")

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.draft_rfc", _boom)
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
    _stub_rfc_factories(monkeypatch)
    seen = {}

    def _fake_backfill(*, path, base, backend, state, work_dir, agent_id):
        seen.update(path=path, base=base)
        return {"pr_number": 9}

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.backfill_rfc", _fake_backfill)
    code = main(["backfill-rfc", "openagents/release.py"])
    assert code == 0
    assert calls == [True]
    # --base 默认 main。
    assert seen == {"path": "openagents/release.py", "base": "main"}


def test_backfill_rfc_passes_base_override(monkeypatch):
    _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)
    seen = {}

    def _fake_backfill(*, path, base, backend, state, work_dir, agent_id):
        seen.update(path=path, base=base)
        return {"pr_number": 9}

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.backfill_rfc", _fake_backfill)
    code = main(["backfill-rfc", "openagents/backends", "--base", "dev"])
    assert code == 0
    assert seen == {"path": "openagents/backends", "base": "dev"}


def test_backfill_rfc_reports_bad_path_cleanly(monkeypatch, capsys):
    # Spec-0062/T4：反推失败（如路径不存在）由 recipe 抛 RfcLifecycleError → cli._run 转干净一行
    # 提示 + 非零退出（无 traceback）。
    _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)
    from openagents.recipes.rfc_lifecycle import RfcLifecycleError

    def _boom(*, path, base, backend, state, work_dir, agent_id):
        raise RfcLifecycleError("路径不存在：nope")

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.backfill_rfc", _boom)
    code = main(["backfill-rfc", "nope"])
    assert code == 1
    err = capsys.readouterr().err
    assert "✗" in err
    assert "路径不存在" in err


# --------------------------------------------------------------------------- #
# refine-rfc
# --------------------------------------------------------------------------- #


def test_refine_rfc_fetches_latest_comment_and_calls_recipe(monkeypatch):
    # RFC-0005 决策 6 / RFC-0011：取最新评论作 detail，不按作者过滤——人与 agent 共用账号时仍能触发。
    _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)
    seen = {}

    def _fake_refine(*, pr_number, detail, backend, state, work_dir, agent_id):
        seen.update(pr_number=pr_number, detail=detail)

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.refine_rfc", _fake_refine)
    monkeypatch.setattr(
        "openagents.utils.github.list_comments",
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

    def _fake_refine(*, pr_number, detail, backend, state, work_dir, agent_id):
        raise AssertionError("无评论时不应调用 refine_rfc")

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.refine_rfc", _fake_refine)
    monkeypatch.setattr("openagents.utils.github.list_comments", lambda *, pr_number: [])

    code = main(["refine-rfc", "9"])
    assert code == 1
    assert "✗" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# implement
# --------------------------------------------------------------------------- #


def test_implement_calls_recipe(monkeypatch):
    _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)
    seen = {}

    def _fake_impl(*, pr_number, backend, state, work_dir, agent_id):
        seen.update(pr_number=pr_number)

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.implement", _fake_impl)
    code = main(["implement", "9"])
    assert code == 0
    assert seen == {"pr_number": 9}


# --------------------------------------------------------------------------- #
# iterate
# --------------------------------------------------------------------------- #


def test_iterate_comment_fetches_latest_human_comment(monkeypatch):
    _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)
    seen = {}

    def _fake_iter(*, pr_number, reason, detail, backend, state, work_dir, agent_id):
        seen.update(pr_number=pr_number, reason=reason, detail=detail)

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.iterate", _fake_iter)
    monkeypatch.setattr(
        "openagents.utils.github.list_comments",
        lambda *, pr_number: [
            Comment(id="2", author="alice", body="修一下", created_at="2026-06-03T02:00:00Z")
        ],
    )

    code = main(["iterate", "9"])
    assert code == 0
    assert seen == {"pr_number": 9, "reason": "comment", "detail": "修一下"}


def test_iterate_ci_uses_check_status(monkeypatch):
    from openagents.utils.github import CheckStatus

    _patch_ensure(monkeypatch)
    _stub_rfc_factories(monkeypatch)
    seen = {}

    def _fake_iter(*, pr_number, reason, detail, backend, state, work_dir, agent_id):
        seen.update(pr_number=pr_number, reason=reason, detail=detail)

    monkeypatch.setattr("openagents.recipes.rfc_lifecycle.iterate", _fake_iter)
    monkeypatch.setattr(
        "openagents.utils.github.check_status",
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

    monkeypatch.setattr("openagents.utils.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr("openagents.utils.github.create_issue", fake_create_issue)
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

    monkeypatch.setattr("openagents.utils.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr("openagents.utils.github.create_issue", fake_create_issue)
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

    monkeypatch.setattr("openagents.utils.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr("openagents.utils.github.create_issue", fake_create_issue)
    code = main(["issue", "T", "--label", "openagents", "--label", "bug", "--yes"])
    assert code == 0
    assert seen == {"labels": ["openagents", "bug"]}


def test_issue_ensures_discovery_label_before_create(monkeypatch):
    # RFC-0002 决策 6：create_issue 前先 ensure_label(openagents)，否则 gh 报 label not found。
    _patch_ensure(monkeypatch)
    order = []

    monkeypatch.setattr(
        "openagents.utils.github.ensure_label", lambda *, name: order.append(("ensure", name))
    )

    def fake_create_issue(*, title, body, labels):
        order.append(("create", labels))
        return Issue(number=5, title=title, body=body)

    monkeypatch.setattr("openagents.utils.github.create_issue", fake_create_issue)
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

    monkeypatch.setattr("openagents.utils.align.restate", fake_restate)
    monkeypatch.setattr("openagents.cli._backend_for", lambda: object())
    return seen


def test_issue_default_path_aligns_then_creates_on_yes(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = _patch_align(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    monkeypatch.setattr("openagents.utils.github.ensure_label", lambda *, name: None)
    created = []

    def fake_create_issue(*, title, body, labels):
        created.append((title, labels))
        return Issue(number=21, title=title, body=body)

    monkeypatch.setattr("openagents.utils.github.create_issue", fake_create_issue)
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
    monkeypatch.setattr("openagents.utils.github.ensure_label", lambda *, name: None)
    monkeypatch.setattr(
        "openagents.utils.github.create_issue",
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
        "openagents.utils.align.restate",
        lambda *, draft, backend: restate_calls.append(draft),
    )
    monkeypatch.setattr("openagents.utils.github.ensure_label", lambda *, name: None)
    created = []

    def fake_create_issue(*, title, body, labels):
        created.append(title)
        return Issue(number=22, title=title, body=body)

    monkeypatch.setattr("openagents.utils.github.create_issue", fake_create_issue)
    code = main(["issue", "自动化建的", "--yes"])
    assert code == 0
    # --yes 跳过复述：restate 不被调用，直接 create。
    assert restate_calls == []
    assert created == ["自动化建的"]


def _patch_vigil_capture(monkeypatch):
    # Spec-0062/T4：vigil 全量改接新栈——发现/守候 poll 走 _new_vigil_for（返回 (Vigil, poll) 二元组），
    # 守候合并走 _new_merge_for（本轮解析出的 hold/skip 经此注入 merge_pr，新 Vigil.run 不再收 hold/skip）。
    monkeypatch.setattr("openagents.utils.github.ensure_prerequisites", lambda: None)
    seen = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, poll, merge):
            seen.update(interval=interval, labels=labels, base=base, once=once)

    monkeypatch.setattr("openagents.cli._new_vigil_for", lambda *, ctx: (_FakeVigil(), object()))

    def _fake_merge_for(*, ctx, hold, skip):
        seen["hold"] = hold
        seen["skip"] = skip
        return object()

    monkeypatch.setattr("openagents.cli._new_merge_for", _fake_merge_for)
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
    # Spec-0062/T4：poll 一次性守候——收编旧 poll-comments，走 _poll_once（poll_comments + merge_pr）。
    calls = _patch_ensure(monkeypatch)
    monkeypatch.setattr(
        "openagents.cli._poll_once", lambda *, ctx: [{"pr_number": 9, "reason": "merged"}]
    )
    code = main(["poll"])
    assert code == 0
    assert calls == [True]


def test_reply_comment_posts_signed_comment(monkeypatch):
    # reply-comment 工具：以本实例 agent_id 盖签名回复指定 PR（供解冲突 agent 亲自回评论、防自循环）。
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


def test_vigil_runs_preflight_with_defaults(monkeypatch):
    # RFC-0004 T3：vigil 先跑 preflight，未传参时用默认值。
    calls = _patch_ensure(monkeypatch)
    # RFC-0015：vigil 进主循环前自举一次 prerequisite——打桩避免触达真实 gh。
    bootstrapped = []
    monkeypatch.setattr(
        "openagents.utils.github.ensure_prerequisites", lambda: bootstrapped.append(True)
    )
    seen = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, poll, merge):
            seen.update(interval=interval, labels=labels, base=base, once=once)

    monkeypatch.setattr("openagents.cli._new_vigil_for", lambda *, ctx: (_FakeVigil(), object()))

    def _fake_merge_for(*, ctx, hold, skip):
        seen.update(hold=hold, skip=skip)
        return object()

    monkeypatch.setattr("openagents.cli._new_merge_for", _fake_merge_for)
    code = main(["vigil"])
    assert code == 0
    assert calls == [True]
    # RFC-0015：进主循环前自举恰一次。
    assert bootstrapped == [True]
    # Spec-0023/T4：vigil 默认基线为 main（test 门控退役）。Spec-0020/T4：无 --hold → 默认全不停。
    # Spec-0054/T3：无 --skip → 默认全闸开启 NONE。
    assert seen == {
        "interval": 60,
        "labels": ["openagents"],
        "base": "main",
        "once": False,
        "hold": Hold(),
        "skip": NO_SKIP,
    }


def test_vigil_passes_all_overrides(monkeypatch):
    _patch_ensure(monkeypatch)
    # RFC-0015：打桩 vigil 进循环前的自举，避免触达真实 gh。
    monkeypatch.setattr("openagents.utils.github.ensure_prerequisites", lambda: None)
    seen = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, poll, merge):
            seen.update(interval=interval, labels=labels, base=base, once=once)

    monkeypatch.setattr("openagents.cli._new_vigil_for", lambda *, ctx: (_FakeVigil(), object()))

    def _fake_merge_for(*, ctx, hold, skip):
        seen.update(hold=hold, skip=skip)
        return object()

    monkeypatch.setattr("openagents.cli._new_merge_for", _fake_merge_for)
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
        "skip": NO_SKIP,
    }


def test_init_runs_interactive_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    # RFC-0015：init 统一兜底——调 ensure_prerequisites（test 分支 + 流程标签）。打桩记录
    # 调用次数避免触达真实 gh（取代原先对 ensure_branch 的打桩）。
    bootstrapped = []
    monkeypatch.setattr(
        "openagents.utils.github.ensure_prerequisites",
        lambda: bootstrapped.append(True),
    )
    # Spec-0030/T3：init 末尾接了 envcheck 体检——打桩 envcheck.check 避免触达真实 ~/.claude.json。
    monkeypatch.setattr(
        "openagents.utils.envcheck.check",
        lambda: SimpleNamespace(text="▶ 体检", all_ok=True),
    )
    code = main(["init"])
    assert code == 0
    assert calls == [True]
    assert bootstrapped == [True]


def test_init_prints_envcheck_report_and_stays_zero_on_missing(monkeypatch, capsys):
    # Spec-0030/T3：缺 browser MCP / 非全放行时，init 打印含安装命令与设置方式的体检段且仍 return 0。
    _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.utils.github.ensure_prerequisites", lambda: None)
    report_text = (
        "▶ 前端 e2e 环境体检（非阻塞，仅 claude-code 后端）\n"
        "  ⚠ 未检测到 browser MCP\n"
        "      claude mcp add playwright -s user -- npx @playwright/mcp@latest\n"
        "      export OPENAGENTS_PERMISSION_MODE=bypassPermissions"
    )
    monkeypatch.setattr(
        "openagents.utils.envcheck.check",
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
    monkeypatch.setattr("openagents.utils.github.ensure_prerequisites", lambda: None)
    monkeypatch.setattr(
        "openagents.utils.envcheck.check",
        lambda: SimpleNamespace(text="▶ 体检 ✓", all_ok=True),
    )
    assert main(["init"]) == 0


# --------------------------------------------------------------------------- #
# release（Spec-0023/T4：人工把 main 物化成版本 release/vX.Y.Z + tag）
# --------------------------------------------------------------------------- #


def test_release_success_returns_zero(monkeypatch):
    from openagents.utils.release import ReleaseResult

    _patch_ensure(monkeypatch)
    seen = {}

    def fake_release(*, state, bump):
        seen["called"] = True
        seen["bump"] = bump
        return ReleaseResult(released=True, version="v1.2.4", reason="ok")

    monkeypatch.setattr("openagents.utils.release.release", fake_release)
    code = main(["release"])
    assert code == 0
    assert seen["called"] is True
    # --bump 默认 patch 透传给 release()。
    assert seen["bump"] == "patch"


def test_release_passes_bump_override(monkeypatch):
    from openagents.utils.release import ReleaseResult

    _patch_ensure(monkeypatch)
    seen = {}

    def fake_release(*, state, bump):
        seen["bump"] = bump
        return ReleaseResult(released=True, version="v2.0.0", reason="ok")

    monkeypatch.setattr("openagents.utils.release.release", fake_release)
    code = main(["release", "--bump", "major"])
    assert code == 0
    assert seen["bump"] == "major"


def test_release_precheck_fail_returns_nonzero(monkeypatch, capsys):
    from openagents.utils.release import ReleaseResult

    _patch_ensure(monkeypatch)
    monkeypatch.setattr(
        "openagents.utils.release.release",
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

    monkeypatch.setattr("openagents.utils.release.release", boom)
    code = main(["release"])
    assert code == 1
    assert "✗" in capsys.readouterr().err


def test_board_skips_preflight(monkeypatch):
    calls = _patch_ensure(monkeypatch)
    monkeypatch.setattr("openagents.utils.results.board", lambda *, state: Path("/tmp/board.html"))
    code = main(["board"])
    assert code == 0
    assert calls == []


# --------------------------------------------------------------------------- #
# RFC-0011 T6：agent_id 接线一致性
# --------------------------------------------------------------------------- #


def test_agent_id_for_resolves_and_is_stable(monkeypatch, tmp_path):
    # RFC-0011 决策 7：_agent_id_for 解析（并首次落盘）一个稳定 id，多次调用得同一值。
    from openagents.cli import _agent_id_for
    from openagents.utils.config import ProjectContext

    monkeypatch.delenv("OPENAGENTS_AGENT_ID", raising=False)
    ctx = ProjectContext(repo_root=tmp_path, remote="https://github.com/x/y.git")

    first = _agent_id_for(ctx=ctx)
    second = _agent_id_for(ctx=ctx)

    assert first
    assert first == second


def test_agent_id_for_honors_env_override(monkeypatch, tmp_path):
    # RFC-0011 决策 2：env OPENAGENTS_AGENT_ID 优先于 state。
    from openagents.cli import _agent_id_for
    from openagents.utils.config import ProjectContext

    monkeypatch.setenv("OPENAGENTS_AGENT_ID", "alice")
    ctx = ProjectContext(repo_root=tmp_path, remote="https://github.com/x/y.git")

    assert _agent_id_for(ctx=ctx) == "alice"


# Spec-0062/T4：旧 test_orchestrator_and_messages_share_resolved_agent_id 已删除——Orchestrator/
# Messages 工厂随两栈合一移除，「同进程解析出同一 agent_id」的不变量现由 _agent_id_for 幂等性
# 单独保证（见 test_agent_id_for_resolves_and_is_stable），新栈各 recipe 经 _rfc_kwargs/_poll_once
# 复用同一 _agent_id_for，无需再跨两个已删对象断言身份一致。


# --------------------------------------------------------------------------- #
# Spec-0055/T1: poll/watch/vigil 入口启动时固化 e2e 能力状态量
# --------------------------------------------------------------------------- #


def _capture_persist(monkeypatch):
    """re-patch _persist_ui_capable 记录调用（覆盖 _patch_ensure 的 no-op）。"""
    seen = {"called": 0}

    def _rec(*, ctx):
        seen["called"] += 1

    monkeypatch.setattr("openagents.cli._persist_ui_capable", _rec)
    return seen


def test_poll_persists_ui_capable(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = _capture_persist(monkeypatch)
    monkeypatch.setattr("openagents.cli._poll_once", lambda *, ctx: [])
    code = main(["poll"])
    assert code == 0
    assert seen["called"] == 1


def test_vigil_persists_ui_capable(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = _capture_persist(monkeypatch)
    _patch_vigil_capture(monkeypatch)
    code = main(["vigil", "--once"])
    assert code == 0
    assert seen["called"] == 1
