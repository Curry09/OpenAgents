# Spec-0086/T1
"""Run a real interactive acceptance test in a disposable repository copy.

The acceptance agent is still useful for interpreting an interaction, but it must not
invent the interaction itself.  This module owns the mechanical part: copy the
candidate at its already-delivered ``HEAD`` into an external directory, feed the
configured user messages to a harness, collect its transcript, and classify process
termination.  Nothing in this module can modify the candidate worktree.

Configuration is intentionally small and environment based so the same runner works
inside an isolated v0.2 container and in tests:

``OPENAGENTS_USER_TEST_COMMAND``
    Shell-like command (parsed with :func:`shlex.split`) for the interactive harness.
``OPENAGENTS_USER_TEST_TRANSCRIPT``
    JSON file containing a list of strings or event objects.  An object is sent as-is;
    a string is sent as ``{"message": <string>}``.
``OPENAGENTS_USER_TEST_TIMEOUT``
    Wall-clock limit in seconds (default 900).
``OPENAGENTS_USER_TEST_ARTIFACT_DIR``
    Optional external directory for immutable artifacts.

The result is deliberately JSON serialisable.  A timeout, crash, or setup failure is
never a successful user test and therefore cannot be used to produce an Acceptance
PASS.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UserTestEvent:
    """One JSON-line message sent to the interactive harness."""

    payload: str | Mapping[str, Any]
    wait_seconds: float = 0.0

    def json_payload(self) -> dict[str, Any]:
        if isinstance(self.payload, str):
            return {"message": self.payload}
        return dict(self.payload)


@dataclass(frozen=True)
class UserTestPlan:
    """Command and transcript for one end-to-end user interaction."""

    command: tuple[str, ...]
    events: tuple[UserTestEvent, ...]
    timeout_seconds: float = 900.0
    close_stdin: bool = True


@dataclass(frozen=True)
class UserTestResult:
    """Auditable result of :func:`run_user_test`."""

    status: str
    exit_code: int | None = None
    artifact_dir: str = ""
    transcript_path: str = ""
    stdout_path: str = ""
    stderr_path: str = ""
    status_path: str = ""
    diff_path: str = ""
    workspace_changed: bool = False
    frames: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    tool_events: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_user_test_plan(env: Mapping[str, str] | None = None) -> UserTestPlan | None:
    """Load a configured plan, returning ``None`` when user testing is not configured."""

    values = os.environ if env is None else env
    raw_command = str(values.get("OPENAGENTS_USER_TEST_COMMAND", "")).strip()
    if not raw_command:
        return None
    try:
        command = tuple(shlex.split(raw_command))
    except ValueError as exc:
        raise ValueError(f"OPENAGENTS_USER_TEST_COMMAND 无法解析：{exc}") from exc
    if not command:
        raise ValueError("OPENAGENTS_USER_TEST_COMMAND 不能为空")

    transcript_name = str(values.get("OPENAGENTS_USER_TEST_TRANSCRIPT", "")).strip()
    if not transcript_name:
        raise ValueError("配置用户测试命令时必须同时提供 OPENAGENTS_USER_TEST_TRANSCRIPT")
    transcript_path = Path(transcript_name)
    try:
        raw_events = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取用户测试 transcript {transcript_path}: {exc}") from exc
    if not isinstance(raw_events, list) or not raw_events:
        raise ValueError("用户测试 transcript 必须是非空 JSON 数组")
    events: list[UserTestEvent] = []
    for index, item in enumerate(raw_events):
        wait_seconds = 0.0
        payload: str | Mapping[str, Any]
        if isinstance(item, str):
            payload = item
        elif isinstance(item, dict):
            item_copy = dict(item)
            raw_wait = item_copy.pop("wait_seconds", 0.0)
            if not isinstance(raw_wait, (int, float)) or raw_wait < 0:
                raise ValueError(f"transcript 第 {index + 1} 项 wait_seconds 无效")
            wait_seconds = float(raw_wait)
            payload = item_copy
        else:
            raise ValueError(f"transcript 第 {index + 1} 项必须是字符串或对象")
        events.append(UserTestEvent(payload=payload, wait_seconds=wait_seconds))

    raw_timeout = str(values.get("OPENAGENTS_USER_TEST_TIMEOUT", "900")).strip()
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as exc:
        raise ValueError(f"OPENAGENTS_USER_TEST_TIMEOUT 无效：{raw_timeout!r}") from exc
    if timeout_seconds <= 0:
        raise ValueError("OPENAGENTS_USER_TEST_TIMEOUT 必须大于 0")
    close_stdin = str(values.get("OPENAGENTS_USER_TEST_CLOSE_STDIN", "1")).strip().lower()
    return UserTestPlan(
        command=command,
        events=tuple(events),
        timeout_seconds=timeout_seconds,
        close_stdin=close_stdin not in {"0", "false", "no"},
    )


def run_user_test(
    *,
    candidate: Path,
    plan: UserTestPlan,
    artifact_dir: Path | None = None,
) -> UserTestResult:
    """Execute ``plan`` against a copy of ``candidate`` and persist all observations.

    The returned ``status`` is one of ``completed``, ``timed_out``, ``crashed`` or
    ``setup_failed``.  The candidate is only inspected through git and is never used as
    the subprocess working directory.
    """

    candidate = Path(candidate).resolve()
    root: Path | None = None
    try:
        if artifact_dir is None:
            root = Path(tempfile.mkdtemp(prefix="openagents-user-test-"))
        else:
            requested_root = Path(artifact_dir).resolve()
            try:
                requested_root.relative_to(candidate)
            except ValueError:
                pass
            else:
                raise ValueError("artifact_dir 不得位于 candidate worktree 内")
            root = requested_root
            root.mkdir(parents=True, exist_ok=True)
            # Each invocation gets a unique child, avoiding accidental overwrite of a
            # previous audit record while keeping the configured parent discoverable.
            root = root / f"run-{time.time_ns()}"
            root.mkdir(parents=True, exist_ok=False)
        repo = root / "repo"
        _copy_repository(candidate=candidate, destination=repo)
    except Exception as exc:
        if root is None:
            root = Path(tempfile.mkdtemp(prefix="openagents-user-test-error-"))
        return _setup_failure(root=root, error=f"repository setup failed: {type(exc).__name__}: {exc}")

    transcript_path = root / "input.jsonl"
    stdout_path = root / "stdout.log"
    stderr_path = root / "stderr.log"
    status_path = root / "status.json"
    diff_path = root / "workspace.diff"
    transcript_lines = [json.dumps(event.json_payload(), ensure_ascii=False, sort_keys=True) for event in plan.events]
    transcript_path.write_text("\n".join(transcript_lines) + "\n", encoding="utf-8")

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    try:
        process = subprocess.Popen(
            list(plan.command),
            cwd=repo,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=(os.name != "nt"),
            env=_harness_environment(root=root, repo=repo),
        )
    except Exception as exc:
        return _setup_failure(
            root=root,
            error=f"harness start failed: {type(exc).__name__}: {exc}",
        )

    def _drain(stream: Any, target: list[str]) -> None:
        try:
            for line in iter(stream.readline, ""):
                target.append(line)
        finally:
            stream.close()

    out_thread = threading.Thread(target=_drain, args=(process.stdout, stdout_lines), daemon=True)
    err_thread = threading.Thread(target=_drain, args=(process.stderr, stderr_lines), daemon=True)
    out_thread.start()
    err_thread.start()
    status = "completed"
    error = ""
    try:
        assert process.stdin is not None
        for event in plan.events:
            process.stdin.write(json.dumps(event.json_payload(), ensure_ascii=False) + "\n")
            process.stdin.flush()
            if event.wait_seconds:
                time.sleep(event.wait_seconds)
        if plan.close_stdin:
            process.stdin.close()
            process.stdin = None
        try:
            process.wait(timeout=plan.timeout_seconds)
        except subprocess.TimeoutExpired:
            status = "timed_out"
            error = f"harness exceeded {plan.timeout_seconds:g}s timeout"
            _terminate_process(process)
    except (BrokenPipeError, OSError) as exc:
        status = "crashed"
        error = f"harness input failed: {type(exc).__name__}: {exc}"
        _terminate_process(process)
    finally:
        if process.poll() is None:
            _terminate_process(process)
        out_thread.join(timeout=2)
        err_thread.join(timeout=2)

    exit_code = process.returncode
    if status == "completed" and exit_code != 0:
        status = "crashed"
        error = f"harness exited with code {exit_code}"
    stdout_path.write_text("".join(stdout_lines), encoding="utf-8")
    stderr_path.write_text("".join(stderr_lines), encoding="utf-8")
    changed, diff = _workspace_observation(repo=repo)
    diff_path.write_text(diff, encoding="utf-8")
    frames, tool_events = _parse_frames(stdout_lines)
    payload = {
        "status": status,
        "exit_code": exit_code,
        "workspace_changed": changed,
        "error": error,
        "command": list(plan.command),
        "timeout_seconds": plan.timeout_seconds,
        "repo": str(repo),
        "artifact_dir": str(root),
        "transcript_path": str(transcript_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "diff_path": str(diff_path),
        "tool_events": tool_events,
    }
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return UserTestResult(
        status=status,
        exit_code=exit_code,
        artifact_dir=str(root),
        transcript_path=str(transcript_path),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        status_path=str(status_path),
        diff_path=str(diff_path),
        workspace_changed=changed,
        frames=tuple(frames),
        tool_events=tuple(tool_events),
        error=error,
    )


def _copy_repository(*, candidate: Path, destination: Path) -> None:
    """Copy a worktree without depending on its ``.git`` indirection."""

    result = subprocess.run(
        ["git", "clone", "--local", "--no-hardlinks", str(candidate), str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=candidate,
        capture_output=True,
        check=False,
    )
    if archive.returncode != 0:
        detail = (archive.stderr or b"").decode(errors="replace").strip()
        raise RuntimeError(detail or result.stderr.strip() or "git clone failed")
    with tarfile.open(fileobj=BytesIO(archive.stdout), mode="r:") as tar:
        tar.extractall(destination)
    subprocess.run(["git", "init", "--quiet"], cwd=destination, check=True)
    subprocess.run(["git", "config", "user.name", "OpenAgents user test"], cwd=destination, check=True)
    subprocess.run(["git", "config", "user.email", "user-test@example.invalid"], cwd=destination, check=True)
    subprocess.run(["git", "add", "-A"], cwd=destination, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "user-test baseline"], cwd=destination, check=True)


def _harness_environment(*, root: Path, repo: Path) -> dict[str, str]:
    env = dict(os.environ)
    # The copied repository is the product under test.  The stock harness uses
    # ``SANDBOX_WORK_DIR`` as the project root for shell tools; forcing it to the
    # copy prevents a caller's inherited value from escaping the disposable run.
    env.update(
        {
            "OPENAGENTS_USER_TEST_REPO": str(repo),
            "OPENAGENTS_USER_TEST_ARTIFACT_DIR": str(root),
            "SANDBOX_WORK_DIR": str(repo),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(root / "pycache"),
            "XDG_CACHE_HOME": str(root / "cache"),
        }
    )
    return env


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _workspace_observation(*, repo: Path) -> tuple[bool, str]:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=False
    ).stdout
    diff = subprocess.run(
        ["git", "diff", "--binary"], cwd=repo, capture_output=True, text=True, check=False
    ).stdout
    if status:
        diff = f"# git status --porcelain\n{status}\n{diff}"
    return bool(status.strip() or diff.strip()), diff


def _parse_frames(lines: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    frames: list[dict[str, Any]] = []
    tools: list[str] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        frames.append(value)
        raw_tools = value.get("tool_events") or value.get("tools")
        if isinstance(raw_tools, list):
            tools.extend(str(item) for item in raw_tools)
        if isinstance(value.get("tool"), str):
            tools.append(value["tool"])
    return frames, tools


def _setup_failure(
    *,
    root: Path,
    error: str,
) -> UserTestResult:
    for name in ("input.jsonl", "stdout.log", "stderr.log", "workspace.diff"):
        path = root / name
        if not path.exists():
            path.write_text("", encoding="utf-8")
    status_path = root / "status.json"
    status_path.write_text(
        json.dumps({"status": "setup_failed", "error": error}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return UserTestResult(
        status="setup_failed",
        artifact_dir=str(root),
        transcript_path=str(root / "input.jsonl"),
        stdout_path=str(root / "stdout.log"),
        stderr_path=str(root / "stderr.log"),
        status_path=str(status_path),
        diff_path=str(root / "workspace.diff"),
        error=error,
    )


__all__ = [
    "UserTestEvent",
    "UserTestPlan",
    "UserTestResult",
    "load_user_test_plan",
    "run_user_test",
]
