"""Spec-0091: local scheduling load, no forge writes or developer/model calls.

Run: python tools/preflight_stress.py --output /tmp/preflight-stress.json
Optionally --historical /path/to/preflight-roi-20260911/plans to replay existing API plans.
"""

import argparse
import ast
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openagents.recipes import vigil  # noqa: E402
from openagents.runtime import preflight  # noqa: E402


def measure(*, count, workers, soft, baseline):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        db = root / ".openagents" / "vigil-queue.db"
        vigil._init_db(db_path=db)
        conn = vigil._connect(db_path=db)
        now = datetime.now(UTC)
        for n in range(1, count + 1):
            vigil._enqueue(conn=conn, subject=f"issue:{n}", priority=1, now=now)
        conn.close()
        if soft:
            covered = min(count, preflight.MAX_ISSUES)
            plan = {
                "clusters": [{"issues": list(range(1, covered + 1)), "first_issue": 1}],
                "suggested_order": [{"issue": 1, "after": 2}, {"issue": 2, "after": 1}],
            }
            preflight.write(
                work_dir=root,
                data={
                    "version": 1,
                    "plan": plan,
                    "fingerprints": {str(n): "snapshot" for n in range(1, covered + 1)},
                },
            )
        barrier = threading.Barrier(workers)
        claim_fn = baseline if baseline is not None and not soft else vigil._claim_next

        def consume(index):
            connection = vigil._connect(db_path=db)
            seen, latency = [], []
            first = True
            try:
                while True:
                    start = time.perf_counter()
                    result = claim_fn(
                        conn=connection, work_dir=root, worker_id=f"worker-{index}", now=now
                    )
                    latency.append((time.perf_counter() - start) * 1000)
                    if result is None:
                        break
                    row, fd = result
                    assert row["attempts"] == 1
                    seen.append(row["subject"])
                    if first:
                        barrier.wait(timeout=30)
                        first = False
                    vigil._mark_done(conn=connection, task_id=row["id"], fd=fd)
                return seen, latency
            finally:
                connection.close()

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(consume, range(workers)))
        elapsed = time.perf_counter() - start
        seen = [s for subjects, _ in results for s in subjects]
        timings = sorted(t for _, times in results for t in times)
        assert len(seen) == len(set(seen)) == count
        return {
            "issues": count,
            "workers": workers,
            "soft": soft,
            "elapsed_seconds": round(elapsed, 4),
            "claims_per_second": round(count / elapsed),
            "claim_median_ms": round(statistics.median(timings), 3),
            "claim_p95_ms": round(timings[int(len(timings) * 0.95)], 3),
            "claim_max_ms": round(max(timings), 3),
            "duplicates": len(seen) - len(set(seen)),
            "missing": count - len(set(seen)),
            "all_workers_filled": all(subjects for subjects, _ in results),
        }


def replay(*, folder):
    original = json.loads((folder / "raw-plan.json").read_text())
    snapshot = json.loads((folder / "input.json").read_text())
    items = [
        SimpleNamespace(number=i["number"], title=i["title"], body=i["handoff"])
        for i in snapshot["issues"]
    ]
    known = {i.number for i in items}
    plan = preflight.sanitize(payload=original, known=known)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        preflight.write(
            work_dir=root,
            data={
                "version": 1,
                "plan": plan,
                "fingerprints": {str(i.number): preflight.fingerprint(issue=i) for i in items},
            },
        )
        db = root / ".openagents" / "vigil-queue.db"
        vigil._init_db(db_path=db)
        conn = vigil._connect(db_path=db)
        now = datetime.now(UTC)
        for i in items:
            vigil._enqueue(conn=conn, subject=f"issue:{i.number}", priority=1, now=now)
        initial = [
            vigil._claim_next(conn=conn, work_dir=root, worker_id=str(n), now=now) for n in range(8)
        ]
        assert all(initial)
        subjects = [row["subject"] for row, _ in initial]
        assert len(set(subjects)) == 8
        for row, fd in initial:
            vigil._mark_done(conn=conn, task_id=row["id"], fd=fd)
        completed = list(subjects)
        while result := vigil._claim_next(conn=conn, work_dir=root, worker_id="drain", now=now):
            row, fd = result
            completed.append(row["subject"])
            vigil._mark_done(conn=conn, task_id=row["id"], fd=fd)
        assert set(completed) == {f"issue:{n}" for n in known}
        conn.close()
        return {
            "round": folder.name,
            "issues": len(items),
            "first_eight": subjects,
            "all_issues_claimed": True,
            "plan_entries": {k: len(v) for k, v in plan.items()},
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--historical", type=Path)
    parser.add_argument(
        "--baseline-revision", help="Compare the original claim function at a git revision"
    )
    args = parser.parse_args()
    baseline = None
    if args.baseline_revision:
        source = subprocess.check_output(
            ["git", "show", f"{args.baseline_revision}:openagents/recipes/vigil.py"], text=True
        )
        node = next(
            n
            for n in ast.parse(source).body
            if isinstance(n, ast.FunctionDef) and n.name == "_claim_next"
        )
        namespace = dict(vars(vigil))
        exec(compile(ast.Module(body=[node], type_ignores=[]), "baseline-vigil", "exec"), namespace)
        baseline = namespace["_claim_next"]
    results = []
    for count, workers in [(30, 8), (300, 8), (3000, 8), (3000, 32)]:
        for soft in [False, True]:
            result = measure(count=count, workers=workers, soft=soft, baseline=baseline)
            results.append(result)
            print(json.dumps(result), flush=True)
    historical = (
        [replay(folder=args.historical / f"round-{n}") for n in [1, 2]] if args.historical else []
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "baseline_revision": args.baseline_revision,
                "stress": results,
                "historical": historical,
            },
            indent=2,
        )
    )
