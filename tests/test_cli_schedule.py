"""Spec-0058/T4：`openagents schedule` 子命令注册与分发的契约测试。

聚焦：schedule 子命令已注册；分发路由到 _cmd_schedule → orchestrator.schedule；入口先自举流程标签
（ensure_prerequisites）；退出码 0。orchestrator/github 全打桩，CLI 单测不触真实 gh/后端。
"""

from pathlib import Path

from openagents.cli import build_parser, main
from openagents.config import ProjectContext


def _patch_ensure(monkeypatch):
    fake = ProjectContext(repo_root=Path("/tmp/x"), remote="https://github.com/x/y.git")
    monkeypatch.setattr("openagents.cli.ensure_project", lambda *, interactive: fake)
    monkeypatch.setattr("openagents.github.ensure_prerequisites", lambda: None)


def test_schedule_command_registered():
    parser = build_parser()
    subparsers = next(a for a in parser._actions if getattr(a, "choices", None))
    assert "schedule" in subparsers.choices


def test_schedule_routes_to_orchestrator_schedule(monkeypatch):
    _patch_ensure(monkeypatch)
    calls = []

    class _FakeOrch:
        def schedule(self):
            calls.append("schedule")

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    code = main(["schedule"])
    assert code == 0
    assert calls == ["schedule"]


def test_schedule_bootstraps_prerequisites_first(monkeypatch):
    _patch_ensure(monkeypatch)
    order = []
    monkeypatch.setattr(
        "openagents.github.ensure_prerequisites", lambda: order.append("prerequisites")
    )

    class _FakeOrch:
        def schedule(self):
            order.append("schedule")

    monkeypatch.setattr("openagents.cli._orchestrator_for", lambda *, ctx: _FakeOrch())
    code = main(["schedule"])
    assert code == 0
    # 预建流程标签必须发生在落 blocked-by/sched-ready 标签之前，恰一次。
    assert order == ["prerequisites", "schedule"]
