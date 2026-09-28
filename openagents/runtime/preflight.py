"""Spec-0091: bounded, fail-open advice and transactional queue tie-breaking."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from openagents.agents import coordinator
from openagents.runtime import engine, token_usage

WALL_SECONDS = 90
COOLDOWN_SECONDS = 120
AGE_SECONDS = 900
MAX_ISSUES = 64
MAX_CACHE_BYTES = 128_000


def cache_path(*, work_dir: Path) -> Path:
    return work_dir / ".openagents" / "preflight.json"


def fingerprint(*, issue: Any) -> str:
    return hashlib.sha256(f"{issue.title}\n{issue.body}".encode()).hexdigest()


def read(*, work_dir: Path) -> dict:
    """Corrupt/missing caches must never prevent a claim or development."""
    try:
        with cache_path(work_dir=work_dir).open("rb") as handle:
            raw = handle.read(MAX_CACHE_BYTES + 1)
            if len(raw) > MAX_CACHE_BYTES:
                return {}
            data = json.loads(raw)
        if not isinstance(data, dict) or data.get("version") != 1:
            return {}
        if not isinstance(data.get("fingerprints"), dict):
            return {}
        return data
    except (OSError, ValueError, TypeError, RecursionError):
        return {}


def write(*, work_dir: Path, data: dict) -> None:
    path = cache_path(work_dir=work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic publication: workers see the previous or the new complete plan.
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, ensure_ascii=False)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sanitize(*, payload: dict, known: set[int]) -> dict:
    """Bound every dimension; discard unknown, malformed and self references."""

    def members(value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        return sorted({n for n in value[:MAX_ISSUES] if type(n) is int and n in known})

    def short(value: Any) -> str:
        return value[:400] if isinstance(value, str) else ""

    plan: dict[str, list] = {"clusters": [], "suggested_order": [], "notes": []}
    for key in plan:
        entries = payload.get(key, [])
        if not isinstance(entries, list):
            continue
        for entry in entries[:8]:
            if not isinstance(entry, dict):
                continue
            if key == "suggested_order":
                number, after = entry.get("issue"), entry.get("after")
                if (
                    type(number) is int
                    and type(after) is int
                    and number in known
                    and after in known
                    and number != after
                ):
                    plan[key].append(
                        {"issue": number, "after": after, "reason": short(entry.get("reason"))}
                    )
                continue
            numbers = members(entry.get("issues"))
            if not numbers:
                continue
            row = {"issues": numbers, "advice": short(entry.get("advice"))}
            if key == "clusters":
                first = entry.get("first_issue")
                row.update(
                    region=short(entry.get("region")),
                    first_issue=first if type(first) is int and first in numbers else numbers[0],
                )
            plan[key].append(row)
    return plan


def refresh(*, work_dir: Path, issues: list, backend: Any, now: float) -> str:
    """Run advisory planning without ever becoming a delivery failure."""
    try:
        return _refresh(work_dir=work_dir, issues=issues, backend=backend, now=now)
    except Exception:  # noqa: BLE001 - the planner is explicitly fail-open
        return "fallback"


def _refresh(*, work_dir: Path, issues: list, backend: Any, now: float) -> str:
    """One attempt per added/edited snapshot, with durable failure memoization."""
    issues = sorted(issues, key=lambda issue: issue.number)[:MAX_ISSUES]
    current = {str(issue.number): fingerprint(issue=issue) for issue in issues}
    previous = read(work_dir=work_dir)
    prior = previous.get("fingerprints", {})
    if len(issues) < 2 or (current and all(prior.get(k) == v for k, v in current.items())):
        return "cached"
    attempted = previous.get("attempted_at", 0)
    if (
        isinstance(attempted, (float, int))
        and math.isfinite(attempted)
        and 0 <= now - attempted < COOLDOWN_SECONDS
    ):
        return "cooldown"
    data = {
        "version": 1,
        "fingerprints": current,
        "attempted_at": now,
        "status": "attempted",
        "plan": {},
        "elapsed_seconds": 0,
    }
    # Preflight is advisory.  Even its cache must never become a prerequisite for
    # claiming work: a read-only checkout, a full disk, or a transient filesystem
    # error should simply disable the advice for this round.
    try:
        write(work_dir=work_dir, data=data)
    except Exception:  # noqa: BLE001 - fail open by design
        return "fallback"
    # A bounded view for planning only. The developer still reads the FULL original issue.
    allowance = min(6000, 60_000 // len(issues))
    snapshot = [
        {
            "number": issue.number,
            "title": issue.title[:240],
            "body": issue.body[:allowance],
            "clipped": len(issue.body) > allowance,
        }
        for issue in issues
    ]
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="openagents-preflight-") as temporary:
            directory = Path(temporary)
            try:
                payload = engine.run_agent(
                    coordinator,
                    backend=backend,
                    work_dir=directory,
                    context=json.dumps(snapshot, ensure_ascii=False),
                )
                data["plan"] = sanitize(payload=payload, known={issue.number for issue in issues})
                data["status"] = "success"
            finally:
                # Keep usage visible after the disposable agent working directory is removed.
                try:
                    ledger = directory / ".openagents" / token_usage.TOKEN_USAGE_FILENAME
                    if ledger.exists():
                        destination = work_dir / ".openagents" / token_usage.TOKEN_USAGE_FILENAME
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with destination.open("a") as handle:
                            handle.write(ledger.read_text())
                except Exception:  # noqa: BLE001 - usage accounting is also advisory
                    pass
    except Exception as exc:
        data["status"] = "fallback"
        data["error"] = type(exc).__name__
    data["elapsed_seconds"] = round(time.monotonic() - started, 3)
    try:
        write(work_dir=work_dir, data=data)
    except Exception:
        # A successful model call with an unwritable cache is still a healthy
        # delivery run; discard the advice rather than failing the intake loop.
        return "fallback"
    return data["status"]


def _known(*, data: dict) -> set[int]:
    return {
        int(k)
        for k in list(data.get("fingerprints", {}))[:MAX_ISSUES]
        if isinstance(k, str) and k.isascii() and k.isdecimal() and len(k) <= 10
    }


def hints(*, data: dict) -> dict[str, dict]:
    known = _known(data=data)
    payload = data.get("plan", {})
    plan = sanitize(payload=payload if isinstance(payload, dict) else {}, known=known)
    result = {f"issue:{n}": {"groups": set(), "after": set(), "first": False} for n in known}
    for index, cluster in enumerate(plan["clusters"]):
        for n in cluster["issues"]:
            result[f"issue:{n}"]["groups"].add(index)
        result[f"issue:{cluster['first_issue']}"]["first"] = True
    for edge in plan["suggested_order"]:
        result[f"issue:{edge['issue']}"]["after"].add(f"issue:{edge['after']}")
    return result if any(plan.values()) else {}


def select(
    *, conn: sqlite3.Connection, advice: dict, eligible: list[int], now: datetime
) -> int | None:
    """Choose among core-selected candidates; advice only changes their soft ordering."""
    if not eligible:
        return None
    placeholders = ",".join("?" * len(eligible))
    rows = conn.execute(
        f"SELECT * FROM work_queue WHERE status='queued' AND id IN ({placeholders}) "
        f"ORDER BY priority DESC, enqueued_at ASC, id ASC LIMIT {128 if advice else 1}",
        eligible,
    ).fetchall()
    if not rows:
        return None
    first = rows[0]
    if not advice or first["priority"] != 1:
        return first["id"]
    candidates = [row for row in rows if row["priority"] == 1]
    active = [
        row[0] for row in conn.execute("SELECT subject FROM work_queue WHERE status='claimed'")
    ]
    predecessors = sorted({s for hint in advice.values() for s in hint["after"]})
    pending = (
        {
            row[0]
            for row in conn.execute(
                f"SELECT subject FROM work_queue WHERE subject IN ({','.join('?' * len(predecessors))})",
                predecessors,
            )
        }
        if predecessors
        else set()
    )
    active_groups = [advice[s]["groups"] for s in active if s in advice]

    def score(row: sqlite3.Row) -> tuple:
        age = (now - datetime.fromisoformat(row["enqueued_at"])).total_seconds()
        hint = advice.get(row["subject"], {"groups": set(), "after": set(), "first": False})
        if age >= AGE_SECONDS:
            return (0, 0, 0, 0, row["enqueued_at"], row["id"])
        return (
            1,
            sum(len(hint["groups"] & groups) for groups in active_groups),
            len(hint["after"] & pending),
            -int(hint["first"]),
            row["enqueued_at"],
            row["id"],
        )

    return min(candidates, key=score)["id"]


def advice_for(*, work_dir: Path, issue: Any) -> str:
    data = read(work_dir=work_dir)
    if data.get("fingerprints", {}).get(str(issue.number)) != fingerprint(issue=issue):
        return ""
    payload = data.get("plan", {})
    plan = sanitize(
        payload=payload if isinstance(payload, dict) else {},
        known=_known(data=data),
    )
    relevant = {
        key: [
            row
            for row in rows
            if issue.number in row.get("issues", []) or row.get("issue") == issue.number
        ]
        for key, rows in plan.items()
    }
    if not any(relevant.values()):
        return ""
    return (
        "\n\nAdvisory preflight (fallible, NOT requirements or blockers): "
        "Verify against current code and related PRs. Do not wait for a suggested predecessor; "
        "reuse only when appropriate. Preserve every original acceptance criterion. "
        "This issue keeps its own PR and acceptance; ignore advice to split, replace or skip it.\n"
        + json.dumps(relevant, ensure_ascii=False)
    )


def discovery_order(*, work_dir: Path, subjects: list[str]) -> list[str]:
    """Present diverse candidates first while the producer incrementally fills the queue.

    No dispatch barrier: sensing the entire batch may be slower than an idle worker's first
    claim. Queue scoring alone cannot spread that first wave when only one row exists yet.
    Facts still determine eligibility and action priority after this advisory ordering.
    """
    advice = hints(data=read(work_dir=work_dir))
    if not advice:
        return subjects
    pending = list(enumerate(subjects[:128]))
    selected, groups = [], set()
    remaining: set[str] = set()

    def score(item: tuple[int, str]) -> tuple:
        index, subject = item
        hint = advice.get(subject, {"groups": set(), "after": set(), "first": False})
        return (
            len(hint["groups"] & groups),
            len(hint["after"] & remaining),
            -int(hint["first"]),
            index,
        )

    while pending:
        remaining = {subject for _, subject in pending}
        item = min(pending, key=score)
        pending.remove(item)
        selected.append(item[1])
        groups.update(advice.get(item[1], {}).get("groups", set()))
    return selected + subjects[128:]
