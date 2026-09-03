from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from openagents.runtime.user_test import (
    UserTestEvent,
    UserTestPlan,
    _harness_environment,
    run_user_test,
)


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "candidate"
    repo.mkdir()
    (repo / "entry.py").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "candidate"], cwd=repo, check=True)
    return repo


def _harness(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "harness.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_user_test_runs_against_external_copy_and_records_observations(tmp_path):
    candidate = _git_repo(tmp_path)
    harness = _harness(
        tmp_path,
        """
import json
from pathlib import Path
for line in __import__('sys').stdin:
    event = json.loads(line)
    Path('observed.txt').write_text(event['message'], encoding='utf-8')
    print(json.dumps({'reply': 'ok', 'tool': 'write_file'}), flush=True)
""",
    )
    result = run_user_test(
        candidate=candidate,
        plan=UserTestPlan(
            command=(sys.executable, str(harness)),
            events=(UserTestEvent("hello"),),
            timeout_seconds=5,
        ),
        artifact_dir=tmp_path / "artifacts",
    )

    assert result.status == "completed"
    assert result.exit_code == 0
    assert result.workspace_changed is True
    assert result.tool_events == ("write_file",)
    assert Path(result.transcript_path).read_text(encoding="utf-8").strip() == '{"message": "hello"}'
    assert "observed.txt" not in subprocess.run(
        ["git", "status", "--porcelain"], cwd=candidate, capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(Path(result.status_path).read_text(encoding="utf-8"))["status"] == "completed"


def test_user_test_timeout_is_terminal_and_process_is_stopped(tmp_path):
    candidate = _git_repo(tmp_path)
    harness = _harness(
        tmp_path,
        """
import time
for _ in __import__('sys').stdin:
    time.sleep(30)
""",
    )
    result = run_user_test(
        candidate=candidate,
        plan=UserTestPlan(
            command=(sys.executable, str(harness)),
            events=(UserTestEvent("hang"),),
            timeout_seconds=0.1,
        ),
    )

    assert result.status == "timed_out"
    assert result.exit_code is not None
    assert "timeout" in result.error


def test_user_test_nonzero_exit_is_crashed(tmp_path):
    candidate = _git_repo(tmp_path)
    harness = _harness(tmp_path, "raise SystemExit(3)\n")
    result = run_user_test(
        candidate=candidate,
        plan=UserTestPlan(command=(sys.executable, str(harness)), events=(UserTestEvent("x"),)),
    )

    assert result.status == "crashed"
    assert result.exit_code == 3


def test_user_test_environment_always_points_sandbox_root_at_disposable_copy(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("SANDBOX_WORK_DIR", "/tmp/unrelated-worktree")

    env = _harness_environment(root=tmp_path / "artifact", repo=tmp_path / "artifact" / "repo")

    assert env["SANDBOX_WORK_DIR"] == str(tmp_path / "artifact" / "repo")
