"""Spec-0061/T3: recipes.fleet 多仓库并发守夜控制流单测——注入假 spawn / 假 worker 依赖。

证明架构契约：run_fleet 复用旧 Fleet 监管器（注入新栈 spawn），一 plan 一 spawn；子进程目标
`_run_repo` 锁 cwd → 经 cli._new_vigil_for 构造**新栈** vigil → 跑 vigil.run(poll=守候段)。全程注入假
实现，不起真子进程、不触真实 git/gh/后端。
"""

from __future__ import annotations

import queue as _queue_mod
from pathlib import Path

import pytest

from openagents.recipes import fleet as fleet_recipe
from openagents.recipes.fleet import run_fleet
from openagents.utils.fleet_config import RepoPlan


def _plan(name, **over):
    return RepoPlan(
        path=Path(f"/repos/{name}"),
        name=name,
        interval=over.get("interval", 60),
        labels=over.get("labels", ["openagents"]),
        base=over.get("base", "main"),
        hold=over.get("hold", None),
    )


class _FakeHandle:
    def __init__(self, *, name):
        self.name = name
        self.exitcode = 0
        self.terminated = False
        self.joined = 0

    def is_alive(self):
        return False

    def join(self, timeout=None):
        self.joined += 1

    def terminate(self):
        self.terminated = True


class _FakeQueue:
    def __init__(self, items=()):
        self._items = list(items)

    def put(self, item):
        self._items.append(item)

    def get(self, timeout=None):
        if self._items:
            return self._items.pop(0)
        raise _queue_mod.Empty


def test_run_fleet_spawns_one_process_per_plan():
    plans = [_plan("a"), _plan("b"), _plan("c")]
    handles = {p.name: _FakeHandle(name=p.name) for p in plans}
    spawned = []

    def _fake_spawn(*, plan, log_queue, once):
        spawned.append((plan.name, once))
        return handles[plan.name]

    run_fleet(plans=plans, once=True, spawn=_fake_spawn, queue_factory=lambda: _FakeQueue())

    assert [name for name, _ in spawned] == ["a", "b", "c"]
    assert all(once is True for _, once in spawned)
    assert all(h.joined >= 1 for h in handles.values())


def test_run_repo_chdirs_builds_new_vigil_and_runs(monkeypatch):
    # 子进程 worker：os.chdir → resolve_project → cli._new_vigil_for 构造新栈 vigil → vigil.run(poll)。
    plan = _plan("r", interval=120, labels=["x"], base="dev")
    chdir_to = {}
    monkeypatch.setattr(fleet_recipe.os, "chdir", lambda p: chdir_to.update(path=p))

    fake_ctx = object()
    monkeypatch.setattr("openagents.utils.config.resolve_project", lambda: fake_ctx)

    ran = {}
    poll_sentinel = object()

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, poll):
            ran.update(interval=interval, labels=labels, base=base, once=once, poll=poll)

    def _fake_new_vigil_for(*, ctx):
        assert ctx is fake_ctx
        return _FakeVigil(), poll_sentinel

    monkeypatch.setattr("openagents.cli._new_vigil_for", _fake_new_vigil_for)

    fleet_recipe._run_repo(plan=plan, log_queue=_FakeQueue(), once=True)

    assert chdir_to["path"] == plan.path
    assert ran == {
        "interval": 120,
        "labels": ["x"],
        "base": "dev",
        "once": True,
        "poll": poll_sentinel,
    }


def test_run_repo_raises_when_not_a_repo(monkeypatch):
    plan = _plan("r")
    monkeypatch.setattr(fleet_recipe.os, "chdir", lambda p: None)
    monkeypatch.setattr("openagents.utils.config.resolve_project", lambda: None)

    with pytest.raises(RuntimeError):
        fleet_recipe._run_repo(plan=plan, log_queue=_FakeQueue(), once=True)


def test_run_repo_entry_turns_failure_into_clean_line_and_nonzero_exit(monkeypatch):
    plan = _plan("r")
    monkeypatch.setattr(fleet_recipe.os, "chdir", lambda p: None)
    monkeypatch.setattr("openagents.utils.config.resolve_project", lambda: None)
    q = _FakeQueue()

    with pytest.raises(SystemExit) as exc:
        fleet_recipe._run_repo_entry(plan=plan, log_queue=q, once=True)

    assert exc.value.code == 1
    name, line = q.get()
    assert name == "r"
    assert "守夜失败" in line


def test_run_repo_entry_passes_through_keyboard_interrupt(monkeypatch):
    plan = _plan("r")

    def _boom(*, plan, log_queue, once):
        raise KeyboardInterrupt

    monkeypatch.setattr(fleet_recipe, "_run_repo", _boom)
    with pytest.raises(KeyboardInterrupt):
        fleet_recipe._run_repo_entry(plan=plan, log_queue=_FakeQueue(), once=False)
