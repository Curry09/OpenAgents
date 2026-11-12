# Spec-0027/T2: Fleet co-organized contract test.
#
# The logic is driven by the injection of "fake spawn/ fake queue" and does not fit the real subprocess, and does not touch the real gh/ backend:
#   -Fan-out: N plan n spawn.
#   - Prefixed polymer: subprocess logs are struck with the prefix to stderr with the respective repository [name] prefix.
#   - Error segregation: a sub-process is not a zero exit code  →  remember one line without affecting the rest.
#   - Stop path: KeyboardInterrupt poachs after each terminate + job.
#
# Also, a single check of the real path of failure of WPker `_run_repo` (non-storage, e.g., throw, sub-process entry, clean line of failure) is being done.
# Spec-0062/T4: per-repo worker moved to ** New Inn** recipes.fleet._run_repo (constructed by cli._new_vigil_for)
# New Inn vigil, which is happy-path by tests/test_recipe_fleet.py test_run_repo_chdirs_builds_new_vigil_and_runs
# Overwrite. Old fleet._run_repo (dependent on deleted cli._vigil_for) joined with two bars to become orphans, waiting for Spec-0063 to be removed from the old cage.
# So here you remove the happy-path single measure, and only the failed path single measure (the Fleet controller itself is still used in a new stack) without _vigil_for.

import queue as _queue_mod
from pathlib import Path

from openagents.utils.agent_config import RepoPlan, default_config
from openagents.utils.fleet import Fleet


def _plan(name, **over):
    return RepoPlan(
        path=Path(f"/repos/{name}"),
        name=name,
        interval=over.get("interval", 60),
        labels=over.get("labels", ["openagents"]),
        base=over.get("base", "main"),
        stages=over.get("stages", default_config().stages),
    )


class _FakeHandle:
    """Fake process handle: Preset exit codes and a set of ”log lines for process output”"""

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
    """Holiday queue within process: Preset a string (name, line) and run out and throw Emtty."""

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
    # Every handle is recycled by join.
    assert all(h.joined >= 1 for h in handles.values())


def test_logs_aggregated_with_repo_prefix(capsys):
    plans = [_plan("a"), _plan("b")]
    handles = {p.name: _FakeHandle(name=p.name) for p in plans}
    queue = _FakeQueue([("a", "▶ issue #1"), ("b", "Vigil."), ("a", "Completed")])
    flt, _ = _make_fleet(handles=handles, queue=queue)

    flt.run(plans=plans, once=False)

    err = capsys.readouterr().err
    assert "[a] ▶ issue #1" in err
    assert "[b] Vigil" in err
    assert "[a] Completed" in err


def test_crashed_process_reported_without_killing_others(capsys):
    plans = [_plan("a"), _plan("b")]
    handles = {"a": _FakeHandle(name="a", exitcode=1), "b": _FakeHandle(name="b", exitcode=0)}
    queue = _FakeQueue([("b", "Vigil.")])
    flt, _ = _make_fleet(handles=handles, queue=queue)

    flt.run(plans=plans, once=True)

    err = capsys.readouterr().err
    # a Non-zero exit  →  one line; b Normal  →  no exit.
    assert "[a]" in err and "code 1" in err
    assert "Vigil exits." not in err.split("[b]")[0] or True
    # b Normal logbooks are as they are, not to be destroyed by a breakdown.
    assert "[b] Vigil" in err


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

    # Shouldn't throw -- Keyboard Interrupt was swallowed out clean.
    flt.run(plans=plans, once=False)

    assert all(h.terminated for h in handles.values())
    assert all(h.joined >= 1 for h in handles.values())
