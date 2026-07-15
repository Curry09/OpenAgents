"""# Spec-0073/T1: agent 输出按 subject 分流（stream tee）单测。

覆盖：两线程各绑一个 subject 并发 emit → 各自 ring buffer 只含自己的行不串扰；未绑定线程 emit 只打 stdout、
不进 buffer；ring buffer 定长丢最旧 + `read_since` 增量补发；`bind/unbind` 成对后线程回到未绑定态。
"""

from __future__ import annotations

import threading

import pytest

from openagents.utils import streams


@pytest.fixture(autouse=True)
def _clean_streams():
    streams.reset()
    yield
    streams.reset()


def test_unbound_emit_prints_stdout_only(capsys):
    streams.emit(line="hello")
    assert capsys.readouterr().out == "hello\n"
    assert streams.subjects() == []
    assert streams.current_subject() is None


def test_bind_routes_to_subject_buffer(capsys):
    streams.bind(subject="issue:1")
    streams.emit(line="改代码")
    assert capsys.readouterr().out == "改代码\n"  # 照旧打 stdout
    lines, seq = streams.read_since(subject="issue:1", after_seq=-1)
    assert lines == ["改代码"]
    assert seq == 1
    streams.unbind()
    assert streams.current_subject() is None


def test_two_threads_do_not_cross_talk():
    ready = threading.Barrier(2)

    def _worker(*, subject: str, line: str) -> None:
        streams.bind(subject=subject)
        ready.wait()
        for _ in range(50):
            streams.emit(line=line)
        streams.unbind()

    t1 = threading.Thread(target=_worker, kwargs={"subject": "issue:1", "line": "A"})
    t2 = threading.Thread(target=_worker, kwargs={"subject": "issue:2", "line": "B"})
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    a_lines, _ = streams.read_since(subject="issue:1", after_seq=-1)
    b_lines, _ = streams.read_since(subject="issue:2", after_seq=-1)
    assert a_lines == ["A"] * 50
    assert b_lines == ["B"] * 50
    assert set(streams.subjects()) == {"issue:1", "issue:2"}


def test_read_since_is_incremental():
    streams.bind(subject="pr:9")
    streams.emit(line="l1")
    streams.emit(line="l2")
    lines, seq = streams.read_since(subject="pr:9", after_seq=-1)
    assert lines == ["l1", "l2"]
    streams.emit(line="l3")
    more, seq2 = streams.read_since(subject="pr:9", after_seq=seq)
    assert more == ["l3"]
    assert seq2 == seq + 1
    empty, seq3 = streams.read_since(subject="pr:9", after_seq=seq2)
    assert empty == []
    assert seq3 == seq2


def test_read_since_unknown_subject_returns_none():
    assert streams.read_since(subject="pr:404", after_seq=-1) is None


def test_ring_buffer_is_bounded(monkeypatch):
    monkeypatch.setenv("OPENAGENTS_STREAM_CAPACITY", "3")
    streams.bind(subject="issue:5")
    for i in range(5):
        streams.emit(line=f"line-{i}")
    lines, _ = streams.read_since(subject="issue:5", after_seq=-1)
    assert lines == ["line-2", "line-3", "line-4"]  # 只留最新 3 行
