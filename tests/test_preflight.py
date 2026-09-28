"""Spec-0091: advisory failures never become delivery failures or barriers."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from openagents.backends.base import AgentResult, TokenUsage
from openagents.recipes import vigil
from openagents.runtime import preflight
from openagents.utils import agent_config

NOW = datetime(2026, 9, 11, tzinfo=UTC)
PLAN = {
    "clusters": [{"issues": [1, 2], "first_issue": 1, "advice": "reuse", "region": "loop"}],
    "suggested_order": [{"issue": 2, "after": 1, "reason": "reuse"}],
    "notes": [],
}


class Backend:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        assert not (kwargs["work_dir"] / ".git").exists()
        return AgentResult(
            changed=False, summary=self.output, usage=TokenUsage(input_tokens=20, output_tokens=10)
        )


def issues():
    return [
        SimpleNamespace(number=n, title=f"issue {n}", body=f"acceptance {n}", labels=["ready"])
        for n in range(1, 4)
    ]


def save_plan(path, plan, items):
    preflight.write(
        work_dir=path,
        data={
            "version": 1,
            "plan": plan,
            "fingerprints": {str(i.number): preflight.fingerprint(issue=i) for i in items},
        },
    )


def queue(path, subjects):
    db = path / ".openagents" / "vigil-queue.db"
    vigil._init_db(db_path=db)
    conn = vigil._connect(db_path=db)
    for subject, priority in subjects:
        vigil._enqueue(conn=conn, subject=subject, priority=priority, now=NOW)
    return conn


def claim(conn, path, now):
    return vigil._claim_next(conn=conn, work_dir=path, worker_id="test", now=now)


def finish(conn, result):
    row, fd = result
    vigil._mark_done(conn=conn, task_id=row["id"], fd=fd)


def test_advisory_round_cache_edits_and_usage(tmp_path):
    backend = Backend(json.dumps(PLAN))
    items = issues()
    original = [i.body for i in items]
    assert (
        preflight.refresh(work_dir=tmp_path, issues=items, backend=backend, now=1000) == "success"
    )
    assert [i.body for i in items] == original
    assert len(backend.calls) == 1
    assert "NOT requirements" in preflight.advice_for(work_dir=tmp_path, issue=items[0])
    assert (
        preflight.refresh(work_dir=tmp_path, issues=items[1:], backend=backend, now=1500)
        == "cached"
    )
    assert preflight.refresh(work_dir=tmp_path, issues=items, backend=backend, now=2000) == "cached"
    items[0].body += " edited"
    assert preflight.advice_for(work_dir=tmp_path, issue=items[0]) == ""
    assert (
        preflight.refresh(work_dir=tmp_path, issues=items, backend=backend, now=1100) == "cooldown"
    )
    assert (
        preflight.refresh(work_dir=tmp_path, issues=items, backend=backend, now=1200) == "success"
    )
    assert len(backend.calls) == 2
    ledger = tmp_path / ".openagents" / "token-usage.jsonl"
    assert len(ledger.read_text().splitlines()) == 2


@pytest.mark.parametrize("output", ["bad json", '{"clusters": 2}', '{"edges": []}'])
def test_bad_output_one_call_then_durable_fallback(tmp_path, output):
    backend = Backend(output)
    assert (
        preflight.refresh(work_dir=tmp_path, issues=issues(), backend=backend, now=1000)
        == "fallback"
    )
    assert (
        preflight.refresh(work_dir=tmp_path, issues=issues(), backend=backend, now=3000) == "cached"
    )
    assert len(backend.calls) == 1  # no expensive protocol repair
    assert preflight.hints(data=preflight.read(work_dir=tmp_path)) == {}


def test_cache_write_failure_is_fail_open(tmp_path, monkeypatch):
    backend = Backend(json.dumps(PLAN))

    def broken_write(**kwargs):
        raise OSError("cache is unavailable")

    monkeypatch.setattr(preflight, "write", broken_write)
    assert (
        preflight.refresh(work_dir=tmp_path, issues=issues(), backend=backend, now=1000)
        == "fallback"
    )
    assert backend.calls == []


def test_final_cache_write_failure_is_fail_open(tmp_path, monkeypatch):
    backend = Backend(json.dumps(PLAN))
    original_write = preflight.write
    calls = 0

    def fail_final_write(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("cache became read-only")
        return original_write(**kwargs)

    monkeypatch.setattr(preflight, "write", fail_final_write)
    assert (
        preflight.refresh(work_dir=tmp_path, issues=issues(), backend=backend, now=1000)
        == "fallback"
    )
    assert len(backend.calls) == 1


def test_timeout_does_not_hold_queue_or_repair(tmp_path):
    release = threading.Event()

    class SlowBackend:
        def run(self, **kwargs):
            release.wait(timeout=2)
            return AgentResult(changed=False, summary=json.dumps(PLAN))

    timed = vigil._TimedBackend(inner=SlowBackend(), timeout_seconds=0.01, lock_fd=None)
    try:
        assert (
            preflight.refresh(work_dir=tmp_path, issues=issues(), backend=timed, now=1000)
            == "fallback"
        )
        conn = queue(tmp_path, [("issue:1", 1)])
        finish(conn, claim(conn, tmp_path, NOW))
        conn.close()
    finally:
        release.set()


def test_invalid_refs_bounds_and_cycles(tmp_path):
    plan = preflight.sanitize(
        payload={
            "clusters": [{"issues": [1, 2, {}, True, 999], "first_issue": {}, "advice": "x" * 999}],
            "suggested_order": [
                {"issue": 1, "after": 2},
                {"issue": 2, "after": 1},
                {"issue": [], "after": 2},
                {"issue": 1, "after": 1},
            ],
            "notes": [{"issues": [3], "advice": "x"}] * 100,
        },
        known={1, 2, 3},
    )
    assert plan["clusters"][0]["issues"] == [1, 2]
    assert len(plan["clusters"][0]["advice"]) == 400
    assert len(plan["notes"]) == 8
    assert len(plan["suggested_order"]) == 2
    save_plan(tmp_path, plan, issues())
    conn = queue(tmp_path, [(f"issue:{n}", 1) for n in [1, 2, 3]])
    results = [claim(conn, tmp_path, NOW) for _ in range(3)]
    assert {r[0]["subject"] for r in results} == {"issue:1", "issue:2", "issue:3"}
    for result in results:
        finish(conn, result)
    conn.close()


def test_priority_spread_and_fifo_aging(tmp_path):
    save_plan(tmp_path, PLAN, issues())
    conn = queue(tmp_path, [("issue:2", 1), ("issue:1", 1), ("issue:3", 1), ("pr:9", 5)])
    merge = claim(conn, tmp_path, NOW)
    assert merge[0]["subject"] == "pr:9"
    first = claim(conn, tmp_path, NOW)
    assert first[0]["subject"] == "issue:1"
    different = claim(conn, tmp_path, NOW)
    assert different[0]["subject"] == "issue:3"
    same = claim(conn, tmp_path, NOW)
    assert same[0]["subject"] == "issue:2"  # no empty slot despite shared active region
    for result in [merge, first, different, same]:
        finish(conn, result)
    for n in [2, 1]:
        vigil._enqueue(conn=conn, subject=f"issue:{n}", priority=1, now=NOW)
    aged = claim(conn, tmp_path, NOW + timedelta(seconds=preflight.AGE_SECONDS))
    assert aged[0]["subject"] == "issue:2"
    finish(conn, aged)
    conn.close()


@pytest.mark.parametrize(
    "raw",
    [
        "invalid",
        "[]",
        '{"version":1,"fingerprints":[]}',
        '{"version":1,"fingerprints":{},"plan":[]}',
        " " * 130000,
    ],
)
def test_corrupt_cache_falls_back_to_fifo(tmp_path, raw):
    conn = queue(tmp_path, [("issue:2", 1), ("issue:1", 1)])
    preflight.cache_path(work_dir=tmp_path).write_text(raw)
    result = claim(conn, tmp_path, NOW)
    assert result[0]["subject"] == "issue:2"
    finish(conn, result)
    conn.close()


def test_soft_intake_never_calls_curator_or_writes_dependencies(tmp_path, monkeypatch):
    config = replace(agent_config.default_config(), coordination="soft")
    monkeypatch.setattr(vigil.github, "ensure_label", lambda **kw: None)
    monkeypatch.setattr(vigil.github, "list_issues", lambda **kw: issues())
    monkeypatch.setattr(vigil, "_order_edges", lambda **kw: pytest.fail("hard curator called"))
    monkeypatch.setattr(
        vigil.github, "add_blocked_by", lambda **kw: pytest.fail("hard edge written")
    )
    backend = Backend(json.dumps(PLAN))
    vigil._intake(backend=backend, work_dir=tmp_path, config=config, agent_id="test", now=NOW)
    assert len(backend.calls) == 1
    assert preflight.read(work_dir=tmp_path)["status"] == "success"


def test_all_same_cluster_fills_workers_and_claims_once(tmp_path):
    count, workers = 300, 8
    items = [SimpleNamespace(number=n, title="task", body="acceptance") for n in range(1, 65)]
    save_plan(tmp_path, {"clusters": [{"issues": list(range(1, 65)), "first_issue": 1}]}, items)
    conn = queue(tmp_path, [(f"issue:{n}", 1) for n in range(1, count + 1)])
    conn.close()
    barrier = threading.Barrier(workers)

    def worker(index):
        connection = vigil._connect(db_path=tmp_path / ".openagents" / "vigil-queue.db")
        claimed = []
        try:
            first = True
            while result := claim(connection, tmp_path, NOW):
                claimed.append(result[0]["subject"])
                assert result[0]["attempts"] == 1
                if first:
                    barrier.wait(timeout=10)  # all eight slots fill even in one cluster
                    first = False
                finish(connection, result)
            return claimed
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        claimed = [s for result in pool.map(worker, range(workers)) for s in result]
    assert len(claimed) == len(set(claimed)) == count


def test_config_inherits_coordination_into_fleet(tmp_path):
    config = agent_config._build_config(data={"coordination": "soft"}, base_dir=tmp_path)
    assert config.coordination == config.repos[0].coordination == "soft"
    fleet = vigil._repo_as_config(
        repo=config.repos[0], agents=config.agents, release=config.release
    )
    assert fleet.coordination == "soft"
    assert agent_config.default_config().coordination == "dependencies"


def test_incremental_discovery_starts_with_preferred_diverse_work(tmp_path):
    save_plan(tmp_path, PLAN, issues())
    subjects = ["issue:2", "issue:1", "issue:3"]
    assert preflight.discovery_order(work_dir=tmp_path, subjects=subjects) == [
        "issue:1",
        "issue:3",
        "issue:2",
    ]


def test_off_intake_does_not_call_any_planner(tmp_path, monkeypatch):
    config = replace(agent_config.default_config(), coordination="off")
    monkeypatch.setattr(vigil.github, "ensure_label", lambda **kw: None)
    monkeypatch.setattr(vigil.github, "list_issues", lambda **kw: issues())
    monkeypatch.setattr(vigil, "_order_edges", lambda **kw: pytest.fail("hard curator called"))
    monkeypatch.setattr(preflight, "refresh", lambda **kw: pytest.fail("soft planner called"))
    vigil._intake(backend=object(), work_dir=tmp_path, config=config, agent_id="test", now=NOW)


def test_preflight_skips_locked_preferred_issue_without_incrementing_attempts(tmp_path):
    save_plan(tmp_path, PLAN, issues())
    conn = queue(tmp_path, [("issue:1", 1), ("issue:2", 1)])
    held = vigil._try_lock(path=vigil._lock_path(work_dir=tmp_path, subject="issue:1"))
    try:
        result = claim(conn, tmp_path, NOW)
        assert result[0]["subject"] == "issue:2"
        assert (
            conn.execute("SELECT attempts FROM work_queue WHERE subject='issue:1'").fetchone()[0]
            == 0
        )
        finish(conn, result)
    finally:
        vigil._close_quietly(fd=held)
        conn.close()
