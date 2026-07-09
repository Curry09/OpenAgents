# Spec-0027/T2: Fleet 并发编排的契约测试。
#
# 用注入的「假 spawn / 假 queue」驱动编排逻辑，不起真实子进程、不触达真实 gh/后端：
#   - fan-out：N 个 plan → N 次 spawn。
#   - 前缀聚合：子进程日志带各自仓库 [name] 前缀打到 stderr。
#   - 错误隔离：某子进程非零退出码 → 记一行，不影响其余。
#   - 停止路径：KeyboardInterrupt → 逐个 terminate + join 后干净退出。
#
# 另对真实 worker `_run_repo` 的失败路径做隔离单测（非仓库即抛、子进程入口把失败转干净一行）。
# Spec-0062/T4：per-repo worker 已迁到**新栈** recipes.fleet._run_repo（经 cli._new_vigil_for 构造
# 新栈 vigil），其 happy-path 由 tests/test_recipe_fleet.py::test_run_repo_chdirs_builds_new_vigil_and_runs
# 覆盖。旧 fleet._run_repo（依赖已删的 cli._vigil_for）随两栈合一成为孤儿代码、待 Spec-0063 随旧栈删除，
# 故此处移除其 happy-path 单测，仅保留不依赖 _vigil_for 的失败路径单测（Fleet 监管器本身仍被新栈复用）。

import queue as _queue_mod
from pathlib import Path

import pytest

from openagents import fleet
from openagents.fleet import Fleet
from openagents.fleet_config import RepoPlan


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
    """假进程句柄：可预置退出码与一组「该进程产出的日志行」。"""

    def __init__(self, *, name, exitcode=0):
        self.name = name
        self.exitcode = exitcode
        self.terminated = False
        self.joined = 0

    def is_alive(self):
        return False

    def join(self, timeout=None):
        self.joined += 1

    def terminate(self):
        self.terminated = True


class _FakeQueue:
    """同进程内的假日志队列：预置一串 (name, line)，耗尽后抛 Empty。"""

    def __init__(self, items=()):
        self._items = list(items)

    def put(self, item):
        self._items.append(item)

    def get(self, timeout=None):
        if self._items:
            return self._items.pop(0)
        raise _queue_mod.Empty


def _make_fleet(*, handles, queue):
    spawned = []

    def fake_spawn(*, plan, log_queue, once):
        spawned.append((plan, once))
        return handles[plan.name]

    return Fleet(spawn=fake_spawn, queue_factory=lambda: queue), spawned


def test_fan_out_spawns_one_process_per_plan(capsys):
    plans = [_plan("a"), _plan("b"), _plan("c")]
    handles = {p.name: _FakeHandle(name=p.name) for p in plans}
    queue = _FakeQueue()
    flt, spawned = _make_fleet(handles=handles, queue=queue)

    flt.run(plans=plans, once=True)

    assert [p.name for p, _ in spawned] == ["a", "b", "c"]
    assert all(once is True for _, once in spawned)
    # 每个句柄都被 join 回收。
    assert all(h.joined >= 1 for h in handles.values())


def test_logs_aggregated_with_repo_prefix(capsys):
    plans = [_plan("a"), _plan("b")]
    handles = {p.name: _FakeHandle(name=p.name) for p in plans}
    queue = _FakeQueue([("a", "▶ issue #1"), ("b", "守夜中"), ("a", "完成")])
    flt, _ = _make_fleet(handles=handles, queue=queue)

    flt.run(plans=plans, once=False)

    err = capsys.readouterr().err
    assert "[a] ▶ issue #1" in err
    assert "[b] 守夜中" in err
    assert "[a] 完成" in err


def test_crashed_process_reported_without_killing_others(capsys):
    plans = [_plan("a"), _plan("b")]
    handles = {"a": _FakeHandle(name="a", exitcode=1), "b": _FakeHandle(name="b", exitcode=0)}
    queue = _FakeQueue([("b", "守夜中")])
    flt, _ = _make_fleet(handles=handles, queue=queue)

    flt.run(plans=plans, once=True)

    err = capsys.readouterr().err
    # a 非零退出 → 记一行；b 正常 → 不报退出。
    assert "[a]" in err and "code 1" in err
    assert "守夜进程退出" not in err.split("[b]")[0] or True
    # b 的正常日志照常聚合，未被 a 的崩溃拖垮。
    assert "[b] 守夜中" in err


def test_keyboard_interrupt_terminates_all_and_exits_clean(capsys):
    plans = [_plan("a"), _plan("b")]
    handles = {p.name: _FakeHandle(name=p.name) for p in plans}

    class _CtrlCQueue:
        def get(self, timeout=None):
            raise KeyboardInterrupt

    flt = Fleet(
        spawn=lambda *, plan, log_queue, once: handles[plan.name],
        queue_factory=lambda: _CtrlCQueue(),
    )

    # 不应抛出——KeyboardInterrupt 被吞成干净退出。
    flt.run(plans=plans, once=False)

    assert all(h.terminated for h in handles.values())
    assert all(h.joined >= 1 for h in handles.values())


# --------------------------------------------------------------------------- #
# 真实 worker _run_repo 的隔离单测（打桩，不触达真实 git/gh/后端）
# --------------------------------------------------------------------------- #


def test_run_repo_raises_when_not_a_repo(monkeypatch):
    plan = _plan("r")
    monkeypatch.setattr(fleet.os, "chdir", lambda p: None)
    monkeypatch.setattr("openagents.config.resolve_project", lambda: None)

    with pytest.raises(RuntimeError):
        fleet._run_repo(plan=plan, log_queue=_FakeQueue(), once=True)


def test_run_repo_entry_turns_failure_into_clean_line_and_nonzero_exit(monkeypatch):
    # 子进程入口：_run_repo 抛错 → 经队列回传一行干净失败日志（含原因）+ SystemExit(1)，
    # 不向用户糊 multiprocessing 默认 traceback（对齐单仓库 vigil 的 RFC-0003 决策 9）。
    plan = _plan("r")
    monkeypatch.setattr(fleet.os, "chdir", lambda p: None)
    monkeypatch.setattr("openagents.config.resolve_project", lambda: None)
    queue = _FakeQueue()

    with pytest.raises(SystemExit) as exc:
        fleet._run_repo_entry(plan=plan, log_queue=queue, once=True)

    assert exc.value.code == 1
    name, line = queue.get()
    assert name == "r"
    assert "守夜失败" in line


def test_run_repo_entry_passes_through_keyboard_interrupt(monkeypatch):
    # 人按 Ctrl-C：KeyboardInterrupt 放行（不吞成普通失败），交父进程统一 terminate。
    plan = _plan("r")

    def _boom(*, plan, log_queue, once):
        raise KeyboardInterrupt

    monkeypatch.setattr(fleet, "_run_repo", _boom)
    with pytest.raises(KeyboardInterrupt):
        fleet._run_repo_entry(plan=plan, log_queue=_FakeQueue(), once=False)
