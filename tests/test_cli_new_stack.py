"""Spec-0062/T4: CLI 全量改接新栈后的子命令解析 + 转发契约测试。

两栈合一：poll-comments 收编进 poll（评论回应 + 合并推进两段一次性）、vigil-new 收编进 vigil
（发现→分诊→派单 + 守候段 poll/merge）、vigil-all 收编为 fleet 的别名。薄路由验证（打桩 recipe/
工厂，不真跑守夜/子进程、不触真实 gh/后端）：
  - 收编后旧子命令名 poll-comments / vigil-new 不再注册；poll / watch / vigil / vigil-all / fleet 在册。
  - poll 一次性先 poll_comments 回应评论、再 merge_pr 推进合并，两段共享同一 backend/state/身份。
  - vigil 走 _new_vigil_for（发现+守候 poll）+ _new_merge_for（守候合并，注入本轮解析出的 hold/skip）。
  - fleet / vigil-all 同走新栈 run_fleet，且跳过 cwd preflight（统管别的仓库）。
"""

from openagents.cli import DISCOVERY_LABEL, build_parser, main


def _subparsers(parser):
    return next(a for a in parser._actions if getattr(a, "choices", None))


class _FakeCtx:
    repo_root = "/repo"
    remote = "origin"


def _stub_project(monkeypatch):
    # ensure_project / ensure_prerequisites / _persist_ui_capable 打桩成 no-op；backend/state/身份
    # 工厂返回 sentinel，保证转发测试 hermetic（不触真实 gh / 后端 / state）。
    ctx = _FakeCtx()
    monkeypatch.setattr("openagents.cli.ensure_project", lambda *, interactive: ctx)
    monkeypatch.setattr("openagents.cli.github.ensure_prerequisites", lambda: None)
    monkeypatch.setattr("openagents.cli._persist_ui_capable", lambda *, ctx: None)
    monkeypatch.setattr("openagents.cli._backend_for", lambda: "BE")
    monkeypatch.setattr("openagents.cli._new_runtime_state_for", lambda *, ctx: "ST")
    monkeypatch.setattr("openagents.cli._agent_id_for", lambda *, ctx: "AID")
    return ctx


# --------------------------------------------------------------------------- #
# 解析：收编后旧名下线、canonical 名在册
# --------------------------------------------------------------------------- #


def test_folded_subcommands_no_longer_registered():
    choices = _subparsers(build_parser()).choices
    # Spec-0062/T4：poll-comments 收编进 poll、vigil-new 收编进 vigil，旧名不再注册。
    assert "poll-comments" not in choices
    assert "vigil-new" not in choices


def test_canonical_subcommands_registered():
    choices = _subparsers(build_parser()).choices
    for cmd in ("poll", "watch", "vigil", "vigil-all", "fleet"):
        assert cmd in choices


def test_vigil_parses_new_stack_flags():
    args = build_parser().parse_args(
        ["vigil", "--interval", "5", "--label", "bug", "--base", "dev", "--once", "--hold", "merge"]
    )
    assert args.interval == 5
    assert args.label == ["bug"]
    assert args.base == "dev"
    assert args.once is True
    assert args.hold == "merge"


def test_fleet_defaults_and_flags():
    default = build_parser().parse_args(["fleet"])
    assert default.config == ".openagents/fleet.yml"
    assert default.once is False
    parsed = build_parser().parse_args(["fleet", "--config", "f.yml", "--once"])
    assert parsed.config == "f.yml"
    assert parsed.once is True


# --------------------------------------------------------------------------- #
# 转发：poll = poll_comments 回应评论 + merge_pr 推进合并（一次性）
# --------------------------------------------------------------------------- #


def test_poll_runs_comments_then_merge_sharing_wiring(monkeypatch):
    _stub_project(monkeypatch)
    order = []

    def _fake_poll(*, backend, state, agent_id, work_dir):
        order.append(("poll_comments", backend, state, agent_id))
        return [{"pr_number": 1, "reason": "replied"}]

    def _fake_merge(*, backend, state, agent_id, work_dir):
        order.append(("merge_pr", backend, state, agent_id))
        return [{"pr_number": 2, "reason": "merged"}]

    monkeypatch.setattr("openagents.recipes.poll_comments.poll_comments", _fake_poll)
    monkeypatch.setattr("openagents.recipes.merge_pr.merge_pr", _fake_merge)
    code = main(["poll"])
    assert code == 0
    # 先回应评论、后推进合并；两段共享同一 backend/state/身份（同进程一致）。
    assert [step[0] for step in order] == ["poll_comments", "merge_pr"]
    assert order[0][1:] == ("BE", "ST", "AID")
    assert order[1][1:] == ("BE", "ST", "AID")


# --------------------------------------------------------------------------- #
# 转发：vigil = 新栈 _new_vigil_for（发现+守候 poll）+ _new_merge_for（守候合并）
# --------------------------------------------------------------------------- #


def test_vigil_forwards_to_new_vigil_run_with_poll_and_merge(monkeypatch):
    _stub_project(monkeypatch)
    ran = {}
    poll_sentinel = object()
    merge_sentinel = object()

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, poll, merge):
            ran.update(
                interval=interval, labels=labels, base=base, once=once, poll=poll, merge=merge
            )

    monkeypatch.setattr(
        "openagents.cli._new_vigil_for", lambda *, ctx: (_FakeVigil(), poll_sentinel)
    )
    monkeypatch.setattr("openagents.cli._new_merge_for", lambda *, ctx, hold, skip: merge_sentinel)
    code = main(["vigil", "--interval", "7", "--label", "bug", "--base", "dev", "--once"])
    assert code == 0
    assert ran == {
        "interval": 7,
        "labels": ["bug"],
        "base": "dev",
        "once": True,
        "poll": poll_sentinel,
        "merge": merge_sentinel,
    }


def test_vigil_defaults_label_to_discovery(monkeypatch):
    _stub_project(monkeypatch)
    ran = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, poll, merge):
            ran.update(labels=labels)

    monkeypatch.setattr("openagents.cli._new_vigil_for", lambda *, ctx: (_FakeVigil(), None))
    monkeypatch.setattr("openagents.cli._new_merge_for", lambda *, ctx, hold, skip: None)
    code = main(["vigil", "--once"])
    assert code == 0
    assert ran["labels"] == [DISCOVERY_LABEL]


def test_vigil_forwards_hold_skip_to_merge_factory(monkeypatch):
    from openagents.utils.hold import Hold
    from openagents.utils.skip import Skip

    _stub_project(monkeypatch)

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, poll, merge):
            pass

    monkeypatch.setattr("openagents.cli._new_vigil_for", lambda *, ctx: (_FakeVigil(), None))
    seen = {}
    monkeypatch.setattr(
        "openagents.cli._new_merge_for",
        lambda *, ctx, hold, skip: seen.update(hold=hold, skip=skip),
    )
    code = main(["vigil", "--once", "--hold", "merge", "--skip", "ci"])
    assert code == 0
    # --hold/--skip 解析成值对象后经 _new_merge_for 注入守候段 merge_pr（对称短路落地点）。
    assert seen["hold"] == Hold(at_merge=True)
    assert seen["skip"] == Skip(at_ci=True)


# --------------------------------------------------------------------------- #
# 转发：fleet / vigil-all 同走新栈 run_fleet，跳过 cwd preflight
# --------------------------------------------------------------------------- #


def test_fleet_forwards_plans_and_skips_preflight(monkeypatch):
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


def test_vigil_all_aliases_new_stack_fleet(monkeypatch):
    # Spec-0062/T4：vigil-all 收编为 fleet 别名——同走新栈 run_fleet、同跳过 cwd preflight。
    def _boom(*, interactive):
        raise AssertionError("vigil-all 不应触发 ensure_project preflight")

    monkeypatch.setattr("openagents.cli.ensure_project", _boom)
    plans = ["p"]
    monkeypatch.setattr("openagents.utils.fleet_config.load_fleet_config", lambda *, path: plans)
    seen = {}
    monkeypatch.setattr(
        "openagents.recipes.fleet.run_fleet",
        lambda *, plans, once: seen.update(plans=plans, once=once),
    )
    code = main(["vigil-all", "--once"])
    assert code == 0
    assert seen == {"plans": plans, "once": True}
