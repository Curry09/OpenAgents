# Spec-0026/T3: vigil-all 子命令解析与转发的契约测试。
#
# 薄路由验证（打桩 Fleet 工厂 + 配置加载，不真跑子进程、不触达真实 gh/后端）：
#   - 子命令注册 + --config/--once 解析（默认 config 路径 .openagents/fleet.yml）。
#   - 转发：load_fleet_config(path) → _fleet_for().run(plans, once)，参数原样直达。
#   - vigil-all 不走 cwd 项目 preflight（统管的是配置里别的仓库，本身可在任意目录跑）。
#   - 现有 vigil 子命令解析不受影响（与 vigil-all 并存）。

from openagents.cli import build_parser, main


def _subparsers(parser):
    return next(a for a in parser._actions if getattr(a, "choices", None))


def test_vigil_all_subcommand_registered():
    assert "vigil-all" in _subparsers(build_parser()).choices


def test_vigil_all_defaults_config_and_once():
    args = build_parser().parse_args(["vigil-all"])
    assert args.config == ".openagents/fleet.yml"
    assert args.once is False


def test_vigil_all_parses_config_and_once():
    args = build_parser().parse_args(["vigil-all", "--config", "f.yml", "--once"])
    assert args.config == "f.yml"
    assert args.once is True


class _FakeFleet:
    def __init__(self):
        self.seen = {}

    def run(self, *, plans, once):
        self.seen.update(plans=plans, once=once)


def _patch_fleet(monkeypatch, plans):
    # 打桩配置加载（返回预置 plans，不读真实 YAML）+ Fleet 工厂（返回假 Fleet，不起子进程）。
    monkeypatch.setattr("openagents.fleet_config.load_fleet_config", lambda *, path: plans)
    fleet = _FakeFleet()
    monkeypatch.setattr("openagents.cli._fleet_for", lambda: fleet)
    return fleet


def test_vigil_all_forwards_plans_and_once(monkeypatch):
    plans = ["plan-a", "plan-b"]  # 仅作 sentinel：转发原样直达，不被 CLI 解释。
    fleet = _patch_fleet(monkeypatch, plans)
    code = main(["vigil-all", "--config", "f.yml", "--once"])
    assert code == 0
    assert fleet.seen == {"plans": plans, "once": True}


def test_vigil_all_skips_project_preflight(monkeypatch):
    # ensure_project 一旦被调用即抛——证明 vigil-all 路由不经 cwd 项目 preflight。
    def _boom(*, interactive):
        raise AssertionError("vigil-all 不应触发 ensure_project preflight")

    monkeypatch.setattr("openagents.cli.ensure_project", _boom)
    fleet = _patch_fleet(monkeypatch, [])
    code = main(["vigil-all"])
    assert code == 0
    assert fleet.seen == {"plans": [], "once": False}


def test_vigil_all_reads_default_config_path(monkeypatch):
    seen_path = {}

    def _capture(*, path):
        seen_path["path"] = path
        return []

    monkeypatch.setattr("openagents.fleet_config.load_fleet_config", _capture)
    monkeypatch.setattr("openagents.cli._fleet_for", lambda: _FakeFleet())
    code = main(["vigil-all"])
    assert code == 0
    # 默认 config 路径 .openagents/fleet.yml（以 Path 形态传给 load_fleet_config）。
    assert str(seen_path["path"]) == ".openagents/fleet.yml"
