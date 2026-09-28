"""Spec-0087: runner-authenticated gap reports, persisted before transmission."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import threading
import time
import uuid
from pathlib import Path

from openagents.runtime.invocation import redact_text
from openagents.utils import forge

MARKER = "auto-designer:observation-gap-v1"
FIELDS = ("question", "checked", "unknowns", "impact", "desired_capability", "verification")
_SWEEP_LOCK = threading.Lock()
_SWEEPS: dict[str, tuple[float, threading.Thread]] = {}


def outbox_root(*, work_dir: Path) -> Path:
    """Keep pending reports outside disposable source worktrees. Spec-0087/T1."""
    result = subprocess.run(
        ["git", "-C", str(work_dir), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise ValueError("observation outbox requires a repository")
    path = Path(result.stdout.strip())
    root = (path if path.is_absolute() else work_dir / path).resolve() / "observation-outbox"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def save(*, path: Path, value: dict) -> None:
    """Atomically persist a scoped report. Spec-0087/T1."""
    temp = path.with_name(f".{uuid.uuid4().hex}.tmp")
    with temp.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def flush(*, path: Path, row: dict) -> dict:
    """Retry a stable machine comment, including after ambiguous responses. Spec-0087/T1."""
    if row.get("state") == "sent":
        return row
    try:
        payload = row["payload"]
        identity = f"observation-request-id: {row['id']}"
        if not forge.observation_request_exists(number=payload["issue"], identity=identity):
            forge.issue_comment(
                number=payload["issue"],
                body=(
                    f"<!-- openagents:agent=observation-runner -->\n{identity}\n"
                    f"<!-- {MARKER} {json.dumps(payload, ensure_ascii=False, sort_keys=True)} -->"
                ),
            )
        row["state"] = "sent"
    except Exception as exc:
        row.update(state="pending", error=type(exc).__name__)
    save(path=path, value=row)
    return row


def retry_pending(*, work_dir: Path) -> None:
    """Retry the bounded durable queue when a delivery role next starts. Spec-0087/T1."""
    root = outbox_root(work_dir=work_dir)
    attempted = 0
    for path in sorted(root.glob("*.json")):
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            row = json.loads(path.read_text())
            if row.get("state") == "pending":
                flush(path=path, row=row)
                attempted += 1
                if attempted >= 10:
                    break


def collect_requests(*, scope: dict | None) -> None:
    """Validate only this invocation's explicit request file, never logs. Spec-0087/T1."""
    if scope is None:
        return
    path = Path(scope["request_path"])
    if not path.exists():
        return
    receipt = path.with_name("request-receipt.json")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 64_000:
                raise ValueError("unsafe observation request file")
            requests = json.loads(stream.read(64_001))
        if not isinstance(requests, list) or len(requests) > 3:
            raise ValueError("expected at most three observation requests")
        receipts = []
        root = outbox_root(work_dir=Path(scope["work_dir"]))
        for request in requests:
            if set(request) != {*FIELDS, "request_id", "scope", "session_ids", "related_issues"}:
                raise ValueError("invalid observation request fields")
            if any(
                not isinstance(request[k], str) or not 1 <= len(request[k].strip()) <= 2000
                for k in FIELDS
            ):
                raise ValueError("observation request requires concrete nonempty statements")
            if (
                request["scope"] not in {"harness", "framework"}
                or not isinstance(request["request_id"], str)
                or not 1 <= len(request["request_id"]) <= 128
                or not set(request["session_ids"]) <= set(scope["sessions"])
                or not set(request["related_issues"]) <= {scope["issue"]}
            ):
                raise ValueError("observation request outside invocation scope")
            key = hashlib.sha256(
                f"{scope['issue']}:{scope['role']}:{request['request_id']}".encode()
            ).hexdigest()
            payload = json.loads(
                redact_text(
                    json.dumps({"issue": scope["issue"], "role": scope["role"], "request": request})
                )
            )
            dest = root / f"{key}.json"
            with dest.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                row = {"id": key, "payload": payload, "state": "pending"}
                if dest.exists():
                    old = json.loads(dest.read_text())
                    if old["payload"] != payload:
                        raise ValueError("observation request_id conflict")
                    row = old
                save(path=dest, value=row)
                result = flush(path=dest, row=row)
                receipts.append({"id": key, "state": result["state"]})
        save(
            path=receipt,
            value={
                "requests": receipts,
                "note": "sent means delivered to framework, not admitted or implemented",
            },
        )
    except Exception as exc:
        # Diagnosis cannot change the original role's return status.
        try:
            save(path=receipt, value={"status": "failed", "error": type(exc).__name__})
        except OSError:
            pass


def sweep_async(*, work_dir: Path) -> None:
    """Retry an existing main-repository outbox without delaying scheduling. Spec-0087/T1."""
    # Vigil / v0.2 adapters are rooted at the main checkout; per-issue calls also retry explicitly.
    root = Path(work_dir) / ".git" / "observation-outbox"
    if not root.is_dir() or not any(root.glob("*.json")):
        return
    key = str(root.resolve())
    with _SWEEP_LOCK:
        previous = _SWEEPS.get(key)
        now = time.monotonic()
        if previous and (previous[1].is_alive() or now - previous[0] < 60):
            return

        def run():
            try:
                retry_pending(work_dir=Path(work_dir))
            except Exception:
                pass  # Durable files remain; a future tick retries without changing delivery state.

        worker = threading.Thread(target=run, daemon=True, name="observation-outbox")
        _SWEEPS[key] = (now, worker)
        worker.start()
