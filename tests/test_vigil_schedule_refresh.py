"""Spec-0058/T5：vigil 每轮保鲜——_run_one_round 在发现段之后、守候段之前恰调一次 schedule。

覆盖：一轮内顺序为 discover → schedule → poll，schedule 恰调一次；schedule 抛异常时本轮记日志续跑、
不上抛，守候段（poll）照常执行（best-effort 隔离）。
"""

from pathlib import Path

from openagents.hold import NONE as NO_HOLD
from openagents.skip import NONE as NO_SKIP
from openagents.vigil import Vigil


class _RecordingOrchestrator:
    def __init__(self, *, raise_on_schedule=False):
        self.schedule_calls = 0
        self._raise = raise_on_schedule

    def schedule(self):
        self.schedule_calls += 1
        if self._raise:
            raise RuntimeError("boom schedule")


class _StubMessages:
    def __init__(self):
        self.poll_count = 0

    def poll(self, *, hold=NO_HOLD, skip=NO_SKIP):
        self.poll_count += 1
        return []


def _vigil(orch, msgs, order):
    v = Vigil(orchestrator=orch, messages=msgs, state=object(), work_dir=Path("/repo"))
    # 把发现段打成记录顺序的 no-op（本测聚焦保鲜接线位置，不驱动真实发现）。
    v.discover_and_dispatch = lambda *, labels, base, skip=NO_SKIP: order.append("discover")
    return v


def test_schedule_called_once_between_discover_and_poll():
    order = []
    orch = _RecordingOrchestrator()

    class _Msgs(_StubMessages):
        def poll(self, *, hold=NO_HOLD, skip=NO_SKIP):
            order.append("poll")
            return super().poll(hold=hold, skip=skip)

    orig_schedule = orch.schedule

    def _recording_schedule():
        order.append("schedule")
        orig_schedule()

    orch.schedule = _recording_schedule
    msgs = _Msgs()
    v = _vigil(orch, msgs, order)

    v._run_one_round(labels=["openagents"], base="main", hold=NO_HOLD, skip=NO_SKIP)

    assert order == ["discover", "schedule", "poll"]
    assert orch.schedule_calls == 1
    assert msgs.poll_count == 1


def test_schedule_failure_does_not_break_round():
    order = []
    orch = _RecordingOrchestrator(raise_on_schedule=True)
    msgs = _StubMessages()
    v = _vigil(orch, msgs, order)

    # schedule 抛异常本轮不上抛（best-effort 隔离）——poll 仍被调。
    v._run_one_round(labels=["openagents"], base="main", hold=NO_HOLD, skip=NO_SKIP)

    assert orch.schedule_calls == 1
    assert msgs.poll_count == 1
