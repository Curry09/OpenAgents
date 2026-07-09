"""Spec-0061/T4: 新栈三子命令（poll-comments / vigil-new / fleet）解析与转发的契约测试。

薄路由验证（打桩 recipe/工厂，不真跑守夜/子进程、不触真实 gh/后端）：
  - 子命令注册 + 参数解析（vigil-new 的 --interval/--label/--base/--once、fleet 的 --config/--once）。
  - poll-comments / vigil-new 走 cwd 项目 ctx；fleet 同 vigil-all 跳过 cwd preflight（统管别的仓库）。
  - 转发：各 handler 把参数原样直达 recipe（poll_comments / Vigil.run / run_fleet）。
"""

from openagents.cli import build_parser, main


def _subparsers(parser):
    return next(a for a in parser._actions if getattr(a, "choices", None))


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #


def test_new_subcommands_registered():
    choices = _subparsers(build_parser()).choices
    assert "poll-comments" in choices
    assert "vigil-new" in choices
    assert "fleet" in choices


def test_vigil_new_defaults():
    args = build_parser().parse_args(["vigil-new"])
    assert args.interval == 60
    assert args.label is None
    assert args.base == "main"
    assert args.once is False


def test_vigil_new_parses_flags():
    args = build_parser().parse_args(
        [
            "vigil-new",
            "--interval",
            "5",
            "--label",
            "bug",
            "--label",
            "feat",
            "--base",
            "dev",
            "--once",
        ]
    )
    assert args.interval == 5
    assert args.label == ["bug", "feat"]
    assert args.base == "dev"
    assert args.once is True


def test_fleet_defaults_and_flags():
    default = build_parser().parse_args(["fleet"])
    assert default.config == ".openagents/fleet.yml"
    assert default.once is False
    parsed = build_parser().parse_args(["fleet", "--config", "f.yml", "--once"])
    assert parsed.config == "f.yml"
    assert parsed.once is True


# --------------------------------------------------------------------------- #
# 转发
# --------------------------------------------------------------------------- #


class _FakeCtx:
    repo_root = "/repo"
    remote = "origin"


def _stub_project(monkeypatch):
    # ensure_project / ensure_prerequisites 打桩成 no-op，返回一个 sentinel ctx（含 repo_root）。
    ctx = _FakeCtx()
    monkeypatch.setattr("openagents.cli.ensure_project", lambda *, interactive: ctx)
    monkeypatch.setattr("openagents.cli.github.ensure_prerequisites", lambda: None)
    return ctx


def test_poll_comments_forwards_to_recipe(monkeypatch):
    _stub_project(monkeypatch)
    monkeypatch.setattr("openagents.cli._backend_for", lambda: "BE")
    monkeypatch.setattr("openagents.cli._new_runtime_state_for", lambda *, ctx: "ST")
    monkeypatch.setattr("openagents.cli._agent_id_for", lambda *, ctx: "AID")
    seen = {}

    def _fake_poll(*, backend, state, agent_id, work_dir):
        seen.update(backend=backend, state=state, agent_id=agent_id)
        return [{"pr_number": 1, "reason": "replied"}]

    monkeypatch.setattr("openagents.recipes.poll_comments.poll_comments", _fake_poll)
    code = main(["poll-comments"])
    assert code == 0
    assert seen == {"backend": "BE", "state": "ST", "agent_id": "AID"}


def test_vigil_new_forwards_to_vigil_run(monkeypatch):
    _stub_project(monkeypatch)
    ran = {}
    poll_sentinel = object()

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, poll):
            ran.update(interval=interval, labels=labels, base=base, once=once, poll=poll)

    monkeypatch.setattr(
        "openagents.cli._new_vigil_for", lambda *, ctx: (_FakeVigil(), poll_sentinel)
    )
    code = main(["vigil-new", "--interval", "7", "--label", "bug", "--base", "dev", "--once"])
    assert code == 0
    assert ran == {
        "interval": 7,
        "labels": ["bug"],
        "base": "dev",
        "once": True,
        "poll": poll_sentinel,
    }


def test_vigil_new_defaults_label_to_discovery(monkeypatch):
    _stub_project(monkeypatch)
    from openagents.cli import DISCOVERY_LABEL

    ran = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, poll):
            ran.update(labels=labels)

    monkeypatch.setattr("openagents.cli._new_vigil_for", lambda *, ctx: (_FakeVigil(), None))
    code = main(["vigil-new", "--once"])
    assert code == 0
    assert ran["labels"] == [DISCOVERY_LABEL]


def test_fleet_forwards_plans_and_skips_preflight(monkeypatch):
    # fleet 不走 cwd 项目 preflight（ensure_project 被调即抛证明）。
    def _boom(*, interactive):
        raise AssertionError("fleet 不应触发 ensure_project preflight")

    monkeypatch.setattr("openagents.cli.ensure_project", _boom)
    plans = ["plan-a", "plan-b"]  # sentinel：原样直达。
    monkeypatch.setattr("openagents.utils.fleet_config.load_fleet_config", lambda *, path: plans)
    seen = {}

    def _fake_run_fleet(*, plans, once):
        seen.update(plans=plans, once=once)

    monkeypatch.setattr("openagents.recipes.fleet.run_fleet", _fake_run_fleet)
    code = main(["fleet", "--config", "f.yml", "--once"])
    assert code == 0
    assert seen == {"plans": plans, "once": True}
