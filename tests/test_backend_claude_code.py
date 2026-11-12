"""RFC-0001 T2 + RFC-0003: Module test for ClaudeCodeBackend adapter.

All sub-processes are all side effects mock, unreal calls to external processes:
- CLI goes subprocess.Popen, output to stream-json event stream (RFC-0003 Decision 6);
- Let’s go. - subprocess.run.
"""

import io
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest

from openagents.backends import claude_code
from openagents.backends.base import AgentBackend, AgentResult
from openagents.backends.claude_code import (
    _GUARDRAIL,
    CLAUDE_BIN,
    IDLE_TIMEOUT_ENV,
    MAX_WALL_ENV,
    PERMISSION_MODE_ENV,
    ClaudeCodeBackend,
    _build_prompt,
    effective_idle_timeout,
    effective_max_wall,
    effective_permission_mode,
)
from openagents.utils import proc


def _assistant_text(text):
    """Construct an asistant text event (stream-json row)."""
    return json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    )


def _assistant_tool(name, **inp):
    """Construct an asistant tool to call an event."""
    block = {"type": "tool_use", "name": name, "input": inp}
    return json.dumps({"type": "assistant", "message": {"content": [block]}})


def _assistant_usage(**usage):
    """Construct anasist event with intermediate wheel usage; Spec-0079 to prove that it will not be accumulated over time."""
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "model": "intermediate-model",
                "usage": usage,
                "content": [{"type": "text", "text": "working"}],
            },
        }
    )


def _system_init(model):
    return json.dumps({"type": "system", "subtype": "init", "model": model})


def _result(text, *, usage=None, model_usage=None):
    """Constructs the final result event (summarized source)."""
    event = {"type": "result", "subtype": "success", "result": text, "is_error": False}
    if usage is not None:
        event["usage"] = usage
    if model_usage is not None:
        event["modelUsage"] = model_usage
    return json.dumps(event)


class _FakePopen:
    """Simulates subprocess.Popen:stdout as an iterative line sequence, wait() returns the exit code."""

    def __init__(self, *, lines, returncode, pass_fds=()):
        self.stdout = iter(lines)
        self.stdin = _RecordingStdin()
        self._returncode = returncode
        # Spec-0065/T2: True Popen Yes. pid Backend proc_utils.publish(pid=proc.pid) Self-reported self-claimed barrel.
        self.pid = 4242
        # Spec-0065/T2: True Popen gave `pass_fds` to the sub-process to inherit.
        # The fake Popen must take it as it is, otherwise the only survival chain, "lock the work process" is not visible in the test.
        self.pass_fds = pass_fds

    def wait(self):
        return self._returncode


class _RecordingStdin(io.StringIO):
    def __init__(self):
        super().__init__()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class _FakeCompleted:
    """Simulates the return object for subprocess.run (for git status)."""

    def __init__(self, *, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class _Calls(list):
    """List-shaped call log that also exposes constructed fake processes."""


def _patch(monkeypatch, *, claude_lines, claude_returncode, git_porcelain):
    """Poopen (claude event stream) and run (git) recorded calls for assertions."""
    popen_calls = _Calls()
    popen_instances = []
    run_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        instance = _FakePopen(
            lines=[line + "\n" for line in claude_lines],
            returncode=claude_returncode,
            pass_fds=kwargs.get("pass_fds", ()),
        )
        popen_instances.append(instance)
        return instance

    def fake_run(cmd, **kwargs):
        run_calls.append((cmd, kwargs))
        return _FakeCompleted(returncode=0, stdout=git_porcelain)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    popen_calls.instances = popen_instances
    return popen_calls, run_calls


# RFC-0016: Backend prompt global hard-bar - forbids agent to change Claude Code's own configuration (`.claude/`).


def test_prompt_starts_with_guardrail():
    # RFC-0016: Contain pre-enactment - _build_prompt output starts with _GUARDRAIL.
    prompt = _build_prompt(task="Change, foo.", context="- Yes, sir.")
    assert prompt.startswith(_GUARDRAIL)


def test_prompt_contains_claude_config_guardrail():
    # RFC-0016: Compression syntax - explicitly prohibits changing Claude Code 's own configuration without writing `.claude/`.
    prompt = _build_prompt(task="t", context="c")
    assert ".claude/" in prompt
    assert "do not modify Claude Code configuration" in prompt


def test_guardrail_does_not_drop_task_and_context():
    # RFC-0016 Return Protection: The original task/context appears after pre-bargaining (without breaching the RFC-0001 contract).
    prompt = _build_prompt(task="Fix bug", context="History")
    assert "Fix bug" in prompt
    assert "History" in prompt


def test_backend_satisfies_protocol():
    assert isinstance(ClaudeCodeBackend(), AgentBackend)


def test_name_is_claude_code():
    assert ClaudeCodeBackend().name == "claude-code"


def test_summary_comes_from_result_event(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=[_assistant_text("working"), _result("done editing foo")],
        claude_returncode=0,
        git_porcelain=" M foo.py\n",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="Change, foo.", context="- Yes, sir.")

    assert isinstance(result, AgentResult)
    assert result.changed is True
    assert "done editing foo" in result.summary


def test_stream_and_result_redact_configured_secrets(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GITEA_TOKEN", "top-secret-token")
    _patch(
        monkeypatch,
        claude_lines=[
            _assistant_tool("Bash", command="curl -u bot:top-secret-token http://gitea"),
            _assistant_text("using top-secret-token"),
            _result('{"verdict":"PASS","reason":"top-secret-token removed"}'),
        ],
        claude_returncode=0,
        git_porcelain="",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "top-secret-token" not in capsys.readouterr().out
    assert "top-secret-token" not in result.summary
    assert "${GITEA_TOKEN}" in result.summary


def test_token_usage_comes_from_final_aggregate_result_only(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=[
            _system_init("configured-model"),
            _assistant_usage(
                input_tokens=999,
                output_tokens=999,
                cache_creation_input_tokens=999,
                cache_read_input_tokens=999,
            ),
            _result(
                "done",
                usage={
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "cache_creation_input_tokens": 3,
                    "cache_read_input_tokens": 20,
                    "server_tool_use": {"web_search_requests": 0},
                },
                model_usage={"user-api-model": {"inputTokens": 10, "outputTokens": 4}},
            ),
        ],
        claude_returncode=0,
        git_porcelain="",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert result.usage is not None
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 4
    assert result.usage.cache_creation_input_tokens == 3
    assert result.usage.cache_read_input_tokens == 20
    assert result.usage.total_tokens == 37
    assert result.usage.total_source == "derived-components"
    assert result.usage.model == "user-api-model"


def test_token_usage_uses_init_model_when_model_usage_is_absent(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=[
            _system_init("nex-agi/deepseek-v3.1-nex-1"),
            _result("done", usage={"input_tokens": 7, "output_tokens": 2}),
        ],
        claude_returncode=0,
        git_porcelain="",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert result.usage is not None
    assert result.usage.model == "nex-agi/deepseek-v3.1-nex-1"
    assert result.usage.total_tokens == 9


def test_token_usage_preserves_explicit_total_and_multiple_models(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=[
            _result(
                "done",
                usage={"input_tokens": 7, "output_tokens": 2, "total_tokens": 11},
                model_usage={"model-b": {}, "model-a": {}},
            )
        ],
        claude_returncode=0,
        git_porcelain="",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert result.usage is not None
    assert result.usage.total_tokens == 11
    assert result.usage.total_source == "reported"
    assert result.usage.model == "model-a,model-b"


def test_reasoning_only_usage_does_not_invent_zero_total(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=[_result("done", usage={"reasoning_tokens": 5})],
        claude_returncode=0,
        git_porcelain="",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert result.usage is not None
    assert result.usage.reasoning_tokens == 5
    assert result.usage.total_tokens is None
    assert result.usage.total_source is None


@pytest.mark.parametrize(
    "usage",
    [None, {}, {"input_tokens": -1}, {"output_tokens": True}, {"input_tokens": "12"}],
)
def test_missing_or_malformed_result_usage_is_unavailable(monkeypatch, tmp_path, usage):
    _patch(
        monkeypatch,
        claude_lines=[_result("done", usage=usage)],
        claude_returncode=0,
        git_porcelain="",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert result.usage is None


def test_long_result_is_only_truncated_for_display(monkeypatch, tmp_path):
    raw = "analysis " * 400 + '{"verdict":"PASS"}'
    _patch(
        monkeypatch,
        claude_lines=[_result(raw)],
        claude_returncode=0,
        git_porcelain="",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert len(result.summary) == 2000
    assert result.protocol_output == raw


def test_changed_false_when_git_clean(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=[_result("nothing to do")],
        claude_returncode=0,
        git_porcelain="",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert result.changed is False


def test_streams_text_and_tool_events_to_stdout(monkeypatch, tmp_path, capsys):
    # RFC-0003 Decision 6: Assistant Text and Tool Action Print to stdout in real time.
    _patch(
        monkeypatch,
        claude_lines=[
            _assistant_text("Start changing the code."),
            _assistant_tool("Edit", file_path="openagents/github.py"),
            _result("Completed"),
        ],
        claude_returncode=0,
        git_porcelain=" M a.py\n",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    out = capsys.readouterr().out
    assert "Start changing the code." in out
    assert "🔧 Edit" in out
    assert "openagents/github.py" in out


def test_invokes_claude_stream_json_in_work_dir(monkeypatch, tmp_path):
    popen_calls, _ = _patch(
        monkeypatch,
        claude_lines=[_result("ok")],
        claude_returncode=0,
        git_porcelain="",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="Fix bug", context="History")

    assert len(popen_calls) == 1
    cmd, kwargs = popen_calls[0]
    assert cmd[:2] == [CLAUDE_BIN, "-p"]
    assert "Fix bug" not in cmd
    assert "History" not in cmd
    assert kwargs["stdin"] == subprocess.PIPE
    assert "--permission-mode" in cmd and "acceptEdits" in cmd
    # RFC-0003: real-time event flow parameters.
    assert "--output-format" in cmd and "stream-json" in cmd and "--verbose" in cmd
    assert kwargs["cwd"] == tmp_path


def test_advisory_disables_tools_and_bounds_output_without_changing_developer(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("CLAUDE_CODE_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", raising=False)
    popen_calls, _ = _patch(
        monkeypatch, claude_lines=[_result("ok")], claude_returncode=0, git_porcelain=""
    )
    developer = ClaudeCodeBackend()
    developer.for_advisory().run(work_dir=tmp_path, task="plan", context="issues")
    developer.run(work_dir=tmp_path, task="implement", context="original issue")
    command, kwargs = popen_calls[0]
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--max-turns") + 1] == "1"
    assert "--strict-mcp-config" in command
    assert kwargs["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "8192"
    assert "--tools" not in popen_calls[1][0]
    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in popen_calls[1][1]["env"]
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" not in popen_calls[1][1]["env"]


def test_prompt_is_written_once_to_stdin_and_never_argv(monkeypatch, tmp_path):
    sentinel = "SENSITIVE-LONG-PROMPT-" * 10000
    popen_calls, _ = _patch(
        monkeypatch,
        claude_lines=[_result("ok")],
        claude_returncode=0,
        git_porcelain="",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="task", context=sentinel)

    cmd, _ = popen_calls[0]
    assert all(sentinel not in arg for arg in cmd)
    written = popen_calls.instances[0].stdin.getvalue()
    assert written == _build_prompt(task="task", context=sentinel)
    assert written.count(sentinel) == 1
    assert popen_calls.instances[0].stdin.close_calls == 1


def test_git_status_runs_against_work_dir(monkeypatch, tmp_path):
    _, run_calls = _patch(
        monkeypatch,
        claude_lines=[_result("ok")],
        claude_returncode=0,
        git_porcelain="",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    git_calls = [c for c in run_calls if c[0][0] == "git"]
    assert len(git_calls) == 1
    cmd, _ = git_calls[0]
    assert cmd == ["git", "-C", str(tmp_path), "status", "--porcelain"]


def test_raises_when_claude_fails(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=[_result("boom")],
        claude_returncode=2,
        git_porcelain="",
    )

    with pytest.raises(RuntimeError) as exc:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "boom" in str(exc.value)


def test_non_json_line_passthrough_and_used_as_error_detail(monkeypatch, tmp_path):
    # Altitude: claude spits directly on not JSON (e.g. failure to start) as it is passed and as error details.
    _patch(
        monkeypatch,
        claude_lines=["fatal: not authenticated"],
        claude_returncode=1,
        git_porcelain="",
    )

    with pytest.raises(RuntimeError) as exc:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "not authenticated" in str(exc.value)


def test_accepts_path_work_dir(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=[_result("ok")],
        claude_returncode=0,
        git_porcelain=" M a\n",
    )

    result = ClaudeCodeBackend().run(work_dir=Path(tmp_path), task="t", context="c")
    assert result.changed is True


# --------------------------------------------------------------------------- #
# Spec-0065/T2: Survivor certificate following the process of working - fd calling thread registration must go to `Popen(pass_fds=…)`
# --------------------------------------------------------------------------- #


def test_popen_hands_the_calling_thread_registered_fd_to_the_child(monkeypatch, tmp_path):
    """Spec-0065/T2: The fd registered with the `proc.hold_fd(fd=…)` has to be in `Popen(pass_fds=…)` as it is.

    This is a **replacement of the Night’s Watch **: the watch for the claim subproject holds a lock, passes the fd to agent subprocess
    The semantic of succession, locking, has been transformed from ”the Vigil is alive” to ”the Vigil** or ”the Vigil**” or ”agent” where it starts.
    When SIGKILL / OOM / `docker stop` was killed, the claude subprocess was orphaned** and not killed (it was not until next time it was written stdout that it discovered that the claude process was being killed)
    Father is gone -- enough to finish `git push` once; if locked up with the Vigil, taken by the kernel, then re-started `_reclaim_dead`
    The first time you get a new one, you get a lock, you get a ”possesser dead” and you hit the line back, and another worker takes the same subject ** running.**

    The whole chain is only set up on this line `pass_fds=`, and it has no test coverage** outside of here** (delete it, the whole warehouse remains green).
    The unregistered caller  →  space meta group behaves exactly the same as before this spec (see `test_invokes_claude_stream_json_in_work_dir`).
    """
    popen_calls, _ = _patch(
        monkeypatch,
        claude_lines=[_result("ok")],
        claude_returncode=0,
        git_porcelain="",
    )
    me = threading.get_ident()
    fd = os.open(str(tmp_path / "issue-5.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    proc.track()
    proc.hold_fd(fd=fd)
    try:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")
        bucket = proc.untrack(thread_id=me)
    finally:
        proc.release_fds(thread_id=me)
        os.close(fd)

    _, kwargs = popen_calls[0]
    assert kwargs["pass_fds"] == (fd,), (
        "Registered survival certificate fd must be passed to agent subprocess succession"
    )
    # The self-reported ** is the process ** of taking this fd: the recognition that the barrel (overtime killing the tree) and the survival certificate fell on the same Popen.
    assert list(bucket) == [4242]
    assert bucket[4242].pass_fds == (fd,)


# --------------------------------------------------------------------------- #
# Spec-0030/T1: Allows the minimum power mode env switches (default acceptEdits unchanged/ recapable by env)
# --------------------------------------------------------------------------- #


def test_effective_permission_mode_defaults_accept_edits(monkeypatch):
    # OPENAGENTS_PERMISSION_MODE Zulu returned default acceptEdits (the default is unchanged).
    monkeypatch.delenv(PERMISSION_MODE_ENV, raising=False)
    assert effective_permission_mode() == "acceptEdits"


def test_effective_permission_mode_blank_falls_back(monkeypatch):
    # The blank value is considered as unset and still returns to default (avoids empty string to spell the command line).
    monkeypatch.setenv(PERMISSION_MODE_ENV, "   ")
    assert effective_permission_mode() == "acceptEdits"


def test_effective_permission_mode_override(monkeypatch):
    # Sets the bypassPermissions Query accessor returns the value.
    monkeypatch.setenv(PERMISSION_MODE_ENV, "bypassPermissions")
    assert effective_permission_mode() == "bypassPermissions"


def test_command_line_uses_default_permission_mode(monkeypatch, tmp_path):
    # Default state:claude Command line remains valid --permission-mode acceptEdits(Default remains unchanged).
    monkeypatch.delenv(PERMISSION_MODE_ENV, raising=False)
    popen_calls, _ = _patch(
        monkeypatch,
        claude_lines=[_result("ok")],
        claude_returncode=0,
        git_porcelain="",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    cmd, _ = popen_calls[0]
    idx = cmd.index("--permission-mode")
    assert cmd[idx + 1] == "acceptEdits"


def test_command_line_honors_permission_mode_override(monkeypatch, tmp_path):
    # Overwrite: env set as bypassPermissions  →  and the command line becomes --permission-mode bypassPermissions.
    monkeypatch.setenv(PERMISSION_MODE_ENV, "bypassPermissions")
    popen_calls, _ = _patch(
        monkeypatch,
        claude_lines=[_result("ok")],
        claude_returncode=0,
        git_porcelain="",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    cmd, _ = popen_calls[0]
    idx = cmd.index("--permission-mode")
    assert cmd[idx + 1] == "bypassPermissions"


@pytest.mark.parametrize("advisory", [False, True])
def test_subagents_are_locked_to_main_model_even_with_stale_override(
    monkeypatch, tmp_path, advisory
):
    monkeypatch.setenv("ANTHROPIC_MODEL", "openai/gpt-6-luna")
    monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "anthropic/claude-sonnet-5")
    monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "0")
    popen_calls, _ = _patch(
        monkeypatch, claude_lines=[_result("ok")], claude_returncode=0, git_porcelain=""
    )

    ClaudeCodeBackend(advisory=advisory).run(work_dir=tmp_path, task="t", context="c")

    child_env = popen_calls[0][1]["env"]
    assert child_env["ANTHROPIC_MODEL"] == "openai/gpt-6-luna"
    assert child_env["CLAUDE_CODE_SUBAGENT_MODEL"] == "openai/gpt-6-luna"
    assert child_env["CLAUDE_CODE_SUBAGENT_MODEL_FORCE"] == "1"


def test_subagent_lock_inherits_main_when_no_explicit_model(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "anthropic/claude-sonnet-5")
    popen_calls, _ = _patch(
        monkeypatch, claude_lines=[_result("ok")], claude_returncode=0, git_porcelain=""
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    child_env = popen_calls[0][1]["env"]
    assert child_env["CLAUDE_CODE_SUBAGENT_MODEL_FORCE"] == "1"
    assert "CLAUDE_CODE_SUBAGENT_MODEL" not in child_env


def test_terminate_escalates_after_leader_exits_but_group_survives(monkeypatch):
    """Kill an orphaned Claude child after the leader exits cleanly."""
    events = []

    class _Leader:
        pid = 4242

        def wait(self, timeout=None):
            events.append(("wait", timeout))

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")

    monkeypatch.setattr(claude_code.os, "getpgid", lambda pid: 4242)

    def killpg(pgid, sig):
        events.append(("killpg", pgid, sig))
        if sig == signal.SIGTERM:
            return
        return None

    monkeypatch.setattr(claude_code.os, "killpg", killpg)
    signal_zero = []

    def kill(pid, sig):
        signal_zero.append((pid, sig))
        if sig == 0:
            return None

    monkeypatch.setattr(claude_code.os, "kill", kill)
    monkeypatch.setattr(claude_code.subprocess, "Popen", _Leader)

    claude_code._terminate_then_kill(proc=_Leader())

    assert ("killpg", 4242, signal.SIGTERM) in events
    assert ("killpg", 4242, signal.SIGKILL) in events
    assert signal_zero == []


def test_terminate_uses_captured_group_after_leader_was_reaped(monkeypatch):
    """Do not rediscover PGID from a leader that another thread already reaped."""
    events = []

    class _ReapedLeader:
        pid = 4242

        def wait(self, timeout=None):
            events.append(("wait", timeout))

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")

    leader = _ReapedLeader()
    proc.remember_process_group(handle=leader, pgid=4242)
    monkeypatch.setattr(
        claude_code.os,
        "getpgid",
        lambda pid: (_ for _ in ()).throw(ProcessLookupError(pid)),
    )

    def killpg(pgid, sig):
        events.append(("killpg", pgid, sig))

    monkeypatch.setattr(claude_code.os, "killpg", killpg)

    claude_code._terminate_then_kill(proc=leader)

    assert ("killpg", 4242, signal.SIGTERM) in events
    assert ("killpg", 4242, signal.SIGKILL) in events


# --------------------------------------------------------------------------- #
# Spec-0046/T2: claude-p fluent idle (stopping) watchdog - silent/pathic trigger, zero health flow back, access solver
#
# Full-time Popen, untouched real claude: `stdout` is a controlled rhythm sequence generator with threading.Event
# Blocking the simulation reading hang, terminate()/kill() remove the blocking and  →  end it in an iterative manner (repeated "killing process pipe shut-off  → for exit").
# Thresholds are minimal (0.1s/0.2s) to trigger certainty, subseconds, not real.
# --------------------------------------------------------------------------- #


class _WatchdogPopen:
    """Spec-0046/T2 Controllable rhythm fake Popen——The silence over the watchdog./Sick/Health in three currents.

    - `silence_after=True`: Blocking on `threading.Event` after the prelude line, simulated ”read and hang” (still dead);
      terminate()** does not** unblock (simulate SIGTERM ignored by the card-killing process) only kill() ends with Event  →  an iterative end.
    - `infinite=True`: Cirque `lines` (`per_line_sleep` per line) to simulate the pathological flow ”A line of garbage never ends per tick”;
      Killed after position, exits in the next round (repeated pipe shut).
    - All of them: after spitting out `lines`, it’s natural end - Health flow.
    """

    def __init__(
        self, *, lines, returncode, silence_after=False, infinite=False, per_line_sleep=0.0
    ):
        self._lines = list(lines)
        self._returncode = returncode
        self._silence_after = silence_after
        self._infinite = infinite
        self._per_line_sleep = per_line_sleep
        self._unblock = threading.Event()
        self.pid = 4242
        self.pass_fds = ()
        self.terminated = False
        self.killed = False
        self.stdout = self._iter()
        self.stdin = io.StringIO()

    def _iter(self):
        while True:
            for ln in self._lines:
                if self._per_line_sleep:
                    time.sleep(self._per_line_sleep)
                if self.killed:  # Kill() turn off the pipe, poach, stop throwing up.
                    return
                yield ln
            if self._infinite and self._lines:
                continue
            break
        if self._silence_after:
            self._unblock.wait()  # Block simulation "read-and- hang" until (kill) set Event

    def terminate(self):
        # Simulation of a dead-end process ignores SIGTERM: only call, not unblock (pushing watchdogs to kill).
        self.terminated = True

    def kill(self):
        self.killed = True
        self._unblock.set()

    def wait(self, timeout=None):
        # With timeout and not kill throw TimeoutExpired (inside the grace limit), engraved the Popen syntax.
        if timeout is not None and not self.killed:
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
        return self._returncode


def _patch_popen(monkeypatch, *, fake, git_porcelain):
    """Spec-0046/T2: Put subprocess.Popen The post is part of a process of returning to the plagiarization process.git status Fake. run。Back popen Call the record."""
    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        fake.pass_fds = kwargs.get("pass_fds", ())
        return fake

    def fake_run(cmd, **kwargs):
        return _FakeCompleted(returncode=0, stdout=git_porcelain)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    return popen_calls


def test_idle_timeout_terminates_then_kills_and_raises(monkeypatch, tmp_path):
    # 1 Silently and silently after idle terminate, bill was transferred for reasons documented no output.
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "0.1")
    monkeypatch.setenv(MAX_WALL_ENV, "0")  # Just test, idle, close the wall.
    fake = _WatchdogPopen(
        lines=[_assistant_text("thinking...") + "\n"], returncode=0, silence_after=True
    )
    _patch_popen(monkeypatch, fake=fake, git_porcelain="")

    with pytest.raises(RuntimeError) as exc:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "produced no output" in str(exc.value)
    assert "Budget depletion" not in str(exc.value)
    assert "Hang on." not in str(exc.value)
    assert fake.terminated is True, "Watchdog trigger first"
    assert fake.killed is True, "SIGTERM within the limit unrepeated should be upgraded to kill()"


def test_max_wall_timeout_on_pathological_stream_raises(monkeypatch, tmp_path):
    # 2 The continued outlet still consumes the total budget and the output cannot be renewed.
    monkeypatch.setenv(
        IDLE_TIMEOUT_ENV, "0"
    )  # idle: There's always a "new line" in the pathological flow, and idle's been deceived.
    monkeypatch.setenv(MAX_WALL_ENV, "0.2")
    fake = _WatchdogPopen(
        lines=[_assistant_text("Garbage.") + "\n"],
        returncode=0,
        infinite=True,
        per_line_sleep=0.03,
    )
    _patch_popen(monkeypatch, fake=fake, git_porcelain="")

    with pytest.raises(RuntimeError) as exc:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "wall-clock budget" in str(exc.value)
    assert "produced no output" not in str(exc.value)
    assert "Hang on." not in str(exc.value)
    assert fake.killed is True


def test_zero_regression_healthy_stream_watchdog_never_fires(monkeypatch, tmp_path, capsys):
    # A healthy stream is read normally, with its result and change state preserved.
    lines = [
        _assistant_text("Start changing the code.") + "\n",
        _assistant_tool("Edit", file_path="a.py") + "\n",
        _result("Completed") + "\n",
    ]

    # (A) Watchdogs enabled (default threshold 300 s/3600s, never triggered by health rapids).
    monkeypatch.delenv(IDLE_TIMEOUT_ENV, raising=False)
    monkeypatch.delenv(MAX_WALL_ENV, raising=False)
    fake_on = _WatchdogPopen(lines=list(lines), returncode=0)
    _patch_popen(monkeypatch, fake=fake_on, git_porcelain=" M a.py\n")
    res_on = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")
    out_on = capsys.readouterr().out

    # (B) The door dog is all off (env=0  →  cannot reach the thread and is equal to the path read before Ben spec).
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "0")
    monkeypatch.setenv(MAX_WALL_ENV, "0")
    fake_off = _WatchdogPopen(lines=list(lines), returncode=0)
    _patch_popen(monkeypatch, fake=fake_off, git_porcelain=" M a.py\n")
    res_off = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")
    out_off = capsys.readouterr().out

    assert out_on == out_off, "The stdout of the healthy flow must be byte-like."
    assert res_on.summary == res_off.summary == "Completed"
    assert res_on.changed is res_off.changed is True
    assert fake_on.terminated is False and fake_on.killed is False, (
        "The health-care dogs never intervene."
    )


def test_effective_idle_timeout_defaults_to_300(monkeypatch):
    # Accessor: No default 300s (wider than no kill for normal long mission).
    monkeypatch.delenv(IDLE_TIMEOUT_ENV, raising=False)
    assert effective_idle_timeout() == 300.0


def test_effective_max_wall_defaults_to_3600(monkeypatch):
    # 4 Accessor: No default 3600s (mostly greater than idle).
    monkeypatch.delenv(MAX_WALL_ENV, raising=False)
    assert effective_max_wall() == 3600.0


@pytest.mark.parametrize("raw", ["", " ", "invalid", "nan", "inf", "-inf"])
def test_invalid_max_wall_falls_back_to_finite_budget(monkeypatch, raw):
    """Spec-0046: malformed budgets must not disable the guard or overflow thread.join."""
    monkeypatch.setenv(MAX_WALL_ENV, raw)
    assert effective_max_wall() == 3600.0


def test_effective_idle_timeout_blank_or_invalid_falls_back(monkeypatch):
    # Accessors: Empty/illegal values are defaulted (no bad values are used as thresholds).
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "   ")
    assert effective_idle_timeout() == 300.0
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "not-a-number")
    assert effective_idle_timeout() == 300.0


def test_effective_idle_timeout_zero_or_negative_disables(monkeypatch):
    # 4 Accessor: <=0 is considered to be closing the door dog (return 0.0).
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "0")
    assert effective_idle_timeout() == 0.0
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "-5")
    assert effective_idle_timeout() == 0.0


def test_effective_timeouts_honor_override(monkeypatch):
    # 4 Accessor: Legitimate overwrite  →  returns the value.
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "42")
    monkeypatch.setenv(MAX_WALL_ENV, "1234.5")
    assert effective_idle_timeout() == 42.0
    assert effective_max_wall() == 1234.5
