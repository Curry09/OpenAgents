# RFC-0001, RFC-0003
"""Run Claude Code in the assigned worktree and stream its progress.

The backend invokes headless Claude Code with stream-json and verbose output,
reads events as they arrive, and extracts the result text. Git status provides
change evidence. A watchdog supervises idle time and total wall-clock time.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from openagents.backends.base import MAX_WALL_ENV as MAX_WALL_ENV
from openagents.backends.base import AgentResult, TokenUsage
from openagents.backends.base import effective_max_wall as effective_max_wall
from openagents.runtime.invocation import redact_text
from openagents.utils import proc as proc_utils
from openagents.utils import streams

# RFC-0001 T2: claude can be tested as a modular level constant to allow the mock/ replacement.
CLAUDE_BIN = "claude"

# Spec-0030/T1: The environment variable spin button and default values for permission mode.
# Default Edits-headless mode must be clearly released for editing, otherwise the message will not be set to change
# (end-to-end validation found: missing this parameter Run returns changed = False for good, see RFC-0001 T2).
# And the old one. OPENAGENTS_REVIEWERS Minimum paragraph env Rotate button (%1)reviewer.py）: Do not include profiles, default default defaults, and do not include profiles.
# Let the "export OPENAGENTS_PERMISSION_MODE =bypassPermissions" in the envcheck report be truly operational
# (Delegate the Browner MCP in headless, see Spec-0030 Reference-level (B)).
PERMISSION_MODE_ENV = "OPENAGENTS_PERMISSION_MODE"
_DEFAULT_PERMISSION_MODE = "acceptEdits"


def effective_permission_mode() -> str:
    """Spec-0030/T1: The permission model (single truth source) that is actually used when sending claude.

    Read Environment Variables ’`OPENAGENTS_PERMISSION_MODE`’, not created or blanked or retired ’`acceptEdits`’
    (Assault behaviour remains unchanged, non-intrusive). Envcheck examines the mode of reading from this access device, and ensures that ”the pattern of communication in the report”
    It’s always the ”Peer-Sate-Performance Model” (or else, the message would lie, see Spec-0030 (A)).
    """
    value = os.environ.get(PERMISSION_MODE_ENV, "").strip()
    return value or _DEFAULT_PERMISSION_MODE


def _claude_child_env(*, advisory: bool) -> dict[str, str]:
    """Lock every Claude Code subagent to this invocation's main model.

    A per-call ``Agent(model=sonnet)`` overrides Claude Code's normal subagent
    default.  FORCE makes that selection inherit the parent (CLI >= 2.1.257).
    Pinning SUBAGENT_MODEL to ANTHROPIC_MODEL also covers older supported CLIs.
    Never trust a caller's stale subagent override for this backend.
    """
    env = dict(os.environ)
    env["CLAUDE_CODE_SUBAGENT_MODEL_FORCE"] = "1"
    model = env.get("ANTHROPIC_MODEL", "").strip()
    if model:
        env["CLAUDE_CODE_SUBAGENT_MODEL"] = model
    else:
        env.pop("CLAUDE_CODE_SUBAGENT_MODEL", None)
    if advisory:
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "8192"
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


# Spec-0046/T1: claude -p It's a fluent reading. idle(suspend) Watch the dog's spin button, mirrors above. effective_permission_mode Min env Paradigm.
# Silence only means that there are no new outputs and no evidence of hanging; each line of output is refreshed idle, but does not extend the total public time budget.
IDLE_TIMEOUT_ENV = "OPENAGENTS_CLAUDE_IDLE_TIMEOUT"
_DEFAULT_IDLE_TIMEOUT = 300.0

# Spec-0046/T1: width seconds between metrine → kill (SIGTERM remains unchanged for so long).
_TERMINATE_GRACE_SECONDS = 5.0
# Spec-0046/T1: Maximum limit for door-dog Query; actual pollell takes the `active threshold' from its smaller, avoiding a small threshold that is overt and misss the trigger point.
_WATCHDOG_POLL_CAP = 5.0


def _effective_timeout(*, env_name, default):
    """Spec-0046/T1: Read a second number env、float Parsing——Illegal/The blogger says:’`<=0`’ Consider Closed (Return) ’`0.0`’）。

    Same as effective_permission_mode: Single truth source accesser, non-inclusion of configuration file, default security value. The default itself is constant ’`>0` ’,
    The blank/illegal retreat is therefore still active; only the visible ’`0` ’ / negative number will close the corresponding watchdog (the default behaviour remains unchanged, non-intrusive).
    """
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            value = default
    return value if value > 0 else 0.0


def effective_idle_timeout() -> float:
    """Spec-0046/T1: idle paused for extra hours (single truth source); ’`<=0` ’ ’Close idle door dog."""
    return _effective_timeout(env_name=IDLE_TIMEOUT_ENV, default=_DEFAULT_IDLE_TIMEOUT)


def _watchdog_poll_interval(*, idle, max_wall):
    """Spec-0046/T1: Watchdogs’ rounds of inquiry interval——Take active threshold and ’`_WATCHDOG_POLL_CAP`’ The smaller; both are closed. → ’`None`’。

    Returns ’`None` ’ means that idle and the wall clock are closed and cannot afford the watchdog thread (the reading path is consistent with the byte before this spec).
    """
    candidates = [v for v in (idle, max_wall) if v > 0]
    if not candidates:
        return None
    return min(min(candidates), _WATCHDOG_POLL_CAP)


def _terminate_then_kill(*, proc):
    """Spec-0046/T1: Termination of Claude and its entire process group.

    The kill child process closes its stdout pipe, and the main cycle of ’`for raw in proc.stdout:` ’ ends the trajectories.
    Only means, so the path is read with zero changes. Claude will start shell/MCP subprocesses again; only `terminate()` ’ will call on these subprocesses
    Staying orphans, so backend creates an independent session at startup, kills the whole procacy group here, then uses the handle to cover it.
    Do your best: each step is abnormal and never leads to a breakdown in the guard dog’s line (the first priority of the Vigil is to go into the next round alive).
    """
    pgid = proc_utils.process_group(handle=proc)
    try:
        if pgid is None and not isinstance(proc, subprocess.Popen):
            raise TypeError("non-Popen test double")
        if pgid is None:
            pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    graceful = False
    try:
        proc.wait(timeout=_TERMINATE_GRACE_SECONDS)
        graceful = True
    except Exception:
        graceful = False
    if not graceful:
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass
    elif pgid is not None:
        # The Claude leader can exit after SIGTERM while a shell/MCP child keeps
        # the pipe open.  ``wait()`` only proves the leader is gone; inspect the
        # session before escalating so an orphan cannot survive a timed stop.
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        except OSError:
            return
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass


# RFC-0003 Decision 6: Real-time Event Flow Format (sstream-json needs to be accompanied by --verbose to output the full event).
_STREAM_ARGS = ["--output-format", "stream-json", "--verbose"]

# Summary cut-off length to avoid plugging an overlong CLI output in the PR text.
_SUMMARY_MAX_LEN = 2000

# The common input key (by priority) used in a tool action to extract a " one sentence hint " .
_TOOL_HINT_KEYS = ("file_path", "path", "command", "pattern", "url", "query")

# RFC-0016: Backend prompt global hard-bar - forbids agent to change Claude Code's own configuration (`.claude/`).
# Prefix to start with each prompt, avoids the `.claude/` writing from the source and crashes the access doorcard to death.
_GUARDRAIL = (
    "Global constraint: do not modify Claude Code configuration. "
    "Do not write or change anything under `.claude/`, including skills, hooks, settings, or commands. "
    "If a task appears to require writing under `.claude/` (for example, adding a skill to `.claude/skills/`), "
    "skip that step and explain why in your output. Never attempt the write."
)


def _build_prompt(*, task, context):
    """RFC-0001 T2: Spell the task with constext as a single line of prompt for claude.

    RFC-0016: Pre-`_GUARDRAIL` global hard-barrel, so that ”`.claude/`” appears in every article
    The beginning of the prompt (the only condensation point for all atomic operations) is applied transparently to all callers.
    """
    return f"{_GUARDRAIL}\n\nTask:\n{task}\n\nContext:\n{context}"


def _summarize(*, stdout, changed):
    """RFC-0001 T2: Generates a short summary from the final result text (for PR body/comment)."""
    text = stdout.strip()
    if not text:
        return "No changes." if not changed else "Changes detected (no CLI output)."
    return text[:_SUMMARY_MAX_LEN]


def _parse_event(*, line):
    """RFC-0003 Decision 6: Resolve a line from stread-json to dict event; non-JSON returns None."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _format_tool_use(*, block):
    """RFC-0003 Decision 6: Format a tool_use block into a line of human readable progress."""
    name = block.get("name") or "tool"
    inp = block.get("input") or {}
    hint = ""
    for key in _TOOL_HINT_KEYS:
        if inp.get(key):
            hint = str(inp[key]).replace("\n", " ")
            break
    if len(hint) > 80:
        hint = hint[:77] + "..."
    rendered = f"🔧 {name}: {hint}".rstrip(": ").rstrip() if hint else f"🔧 {name}"
    return redact_text(rendered)


def _lines_for_event(*, event):
    """RFC-0003 Decision 6: Extract a human readable line (assistant text + tool action) from an event."""
    if event.get("type") != "assistant":
        return []
    content = (event.get("message") or {}).get("content") or []
    lines: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = (block.get("text") or "").strip()
            if text:
                lines.append(text)
        elif block.get("type") == "tool_use":
            lines.append(_format_tool_use(block=block))
    return lines


def _tool_names_for_event(*, event) -> list[str]:
    """Extract ordered tool names without retaining tool inputs or command text."""
    if event.get("type") != "assistant":
        return []
    content = (event.get("message") or {}).get("content") or []
    return [
        str(block.get("name") or "tool")
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


def _usage_count(value: object) -> int | None:
    """Accept only provider-reported non-negative integers (bool is not an integer here)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _token_usage_for_result_event(
    *, event: dict, fallback_model: str | None = None
) -> TokenUsage | None:
    """Normalize Claude Code's final aggregate ``result.usage`` event.

    Claude Code also emits ``assistant.message.usage`` for intermediate turns.  The final result
    usage is already aggregated across the CLI invocation, so consuming both would double count.
    """
    if event.get("type") != "result":
        return None
    raw_usage = event.get("usage")
    if not isinstance(raw_usage, dict):
        return None

    input_tokens = _usage_count(raw_usage.get("input_tokens"))
    output_tokens = _usage_count(raw_usage.get("output_tokens"))
    cache_read = _usage_count(raw_usage.get("cache_read_input_tokens"))
    cache_creation = _usage_count(raw_usage.get("cache_creation_input_tokens"))
    reasoning = _usage_count(raw_usage.get("reasoning_tokens"))
    total = _usage_count(raw_usage.get("total_tokens"))
    if all(
        value is None
        for value in (input_tokens, output_tokens, cache_read, cache_creation, reasoning, total)
    ):
        return None

    total_source = "reported" if total is not None else None
    total_components = (input_tokens, cache_read, cache_creation, output_tokens)
    if total is None and any(value is not None for value in total_components):
        # Claude Code 2.1.12 exposes mutually exclusive Anthropic-style input/cache/output
        # components on the aggregate result event.  Reasoning, if a future version adds it,
        # remains a subcomponent of output and is therefore not added again.
        total = sum(value for value in total_components if value is not None)
        total_source = "derived-components"

    model_usage = event.get("modelUsage")
    models = sorted(str(model) for model in model_usage) if isinstance(model_usage, dict) else []
    model = ",".join(models) if models else fallback_model
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
        reasoning_tokens=reasoning,
        total_tokens=total,
        model=model,
        total_source=total_source,
    )


class ClaudeCodeBackend:
    """RFC-0001 T2: Claude Code working ant adapter, meet the AgentBackend protocol."""

    name = "claude-code"

    def __init__(self, *, advisory: bool = False) -> None:
        self._advisory = advisory

    def for_advisory(self) -> ClaudeCodeBackend:
        """Spec-0091: a separate, tool-free instance; never mutate developer settings."""
        return ClaudeCodeBackend(advisory=True)

    def run(self, *, work_dir: Path, task: str, context: str) -> AgentResult:
        """RFC-0001 T2+RFC-0003: Driver Claude Code within work_dir to change the code and report the results.

        Runs as `claude -p ... --output-format stream-json --verbose` (cwd=work_dir).
        Event is passed through terminal in real time; on call, the change is determined by `git -C <work_dir> status --porcelain`;
        CLI returns non-zero-dot overruntimeError.
        """
        work_dir_str = str(work_dir)
        prompt = _build_prompt(task=task, context=context)
        result_text, tool_events, usage = self._run_claude_streaming(
            work_dir=work_dir, prompt=prompt
        )

        status = subprocess.run(
            ["git", "-C", work_dir_str, "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        changed = bool(status.stdout.strip())

        return AgentResult(
            changed=changed,
            summary=_summarize(stdout=result_text, changed=changed),
            raw_output=result_text,
            tool_events=tool_events,
            usage=usage,
        )

    def _run_claude_streaming(
        self, *, work_dir: Path, prompt: str
    ) -> tuple[str, tuple[str, ...], TokenUsage | None]:
        """RFC-0003 Decision 6: Parse the stream-json event, print progress in real time, and return the final result text.

        Stderr merge into stdout; extract `result` text from `result` event for summary; non-zero exit throw
        RuntimeError (with known error details).

        Spec-0046/T1: Blocked line-by-line idle (stop) door-dog-protective thread - main cycle only brushes once more each line
        `last_activity` (monotonic) jab; if a door-dog turns to find ”silent silence idle” or ”total time over max_wall”, then
        terminate() → kill() subprocesses with pipe shut, main cycle exited, end-screwed** `RuntimeError` (with no output/budget)
        Exhausted details) and submitted to upstream per-issue/per-round try/except quarantine (this round of agent failed to skip, retrace).
        The new output will only be updated to the silent clock, will not prove effective progress and will not extend the total time-consuming budget; the current reading path remains unchanged.
        """
        proc = subprocess.Popen(
            [
                CLAUDE_BIN,
                "-p",
                "--permission-mode",
                effective_permission_mode(),
                *_STREAM_ARGS,
                *(
                    [
                        "--tools",
                        "",
                        "--max-turns",
                        "1",
                        "--strict-mcp-config",
                        "--disable-slash-commands",
                        "--setting-sources",
                        "",
                    ]
                    if self._advisory
                    else []
                ),
            ],
            cwd=work_dir,
            env=_claude_child_env(advisory=self._advisory),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
            # Spec-0065/T2: Pass the fd registered by the caller to the child process to inherit (it's the flock survival certificate).
            # So, "Who works and who holds the lock" -- the watch is still running after SIGKILL, and the orphan is still holding the lock, and the recycler can't take it.
            # The line will not be pushed back to the queue re-lead (the last entry for double running). The non-night watch caller is not registered  →  empty element group  →  behavior is unchanged.
            pass_fds=proc_utils.inherited_fds(),
        )
        # Capture the session group before any watchdog/reaper can observe a dead leader.
        try:
            proc_utils.remember_process_group(handle=proc, pgid=os.getpgid(proc.pid))
        except OSError:
            pass
        # Spec-0065/T2: Self-reported PID + Popen handles the recognized collar - Vigil `_act` is hard-tempered ** precisely killed ** from this call
        # Process tree; handles for the identification of body (PID may have been reused after recap, nud PID kills the innocent, see utils.proc).
        proc_utils.publish(pid=proc.pid, handle=proc)

        # Spec-0081/T1: prompt is a large payload that may exceed the limit of Linux single parameter, transmitted only once by stdin; argv
        # Only the control parameters are left. Independent Writer allows the main route to consume stream-json immediately, avoiding stdin/stdout pipes backsliding.
        stdin_errors: list[Exception] = []

        def _write_prompt() -> None:
            try:
                if proc.stdin is None:
                    raise RuntimeError("Claude Code CLI stdin pipe was not established")
                proc.stdin.write(prompt)
                proc.stdin.close()
            except Exception as exc:  # noqa: BLE001 - Cross-line to call the main line.
                stdin_errors.append(exc)

        stdin_writer = threading.Thread(target=_write_prompt, daemon=True)
        stdin_writer.start()

        # Spec-0046/T1: Up idle watchdog. last_activity uses the mutated list to make a variable share stamp (monotonic, not called back by system time)
        # Impact; watchdog_reason records "no output for long time" or "time budget run out" and ends with RuntimeError.
        idle = effective_idle_timeout()
        max_wall = effective_max_wall()
        poll = _watchdog_poll_interval(idle=idle, max_wall=max_wall)
        start = time.monotonic()
        last_activity = [start]
        stop_event = threading.Event()
        watchdog_reason: list[str] = []

        def _watch():
            # Spec-0046/T1: Guardian thread - without interrogating, only "last progress" and "wall clocks" are asked; triggers the killing process wakes up and blockes reading.
            while not stop_event.wait(poll):
                now = time.monotonic()
                if idle > 0 and now - last_activity[0] > idle:
                    watchdog_reason.append(f"produced no output for {idle:g}s")
                    _terminate_then_kill(proc=proc)
                    return
                if max_wall > 0 and now - start > max_wall:
                    watchdog_reason.append(f"exceeded its {max_wall:g}s wall-clock budget")
                    _terminate_then_kill(proc=proc)
                    return

        watchdog = None
        if poll is not None:
            watchdog = threading.Thread(target=_watch, daemon=True)
            watchdog.start()

        result_text = ""
        result_usage = None
        init_model = None
        tool_events: list[str] = []
        raw_tail: list[str] = []
        try:
            for raw in proc.stdout:
                # Spec-0046/T1: This is only one thing that happens in every line - to refresh the last progress stamp (including the subsequent empty line by continue) and to re-enact the "last progress" stamp.
                # The empty line is progress./Print/result The whole of the health flow is extracted without going through the door dog (no behavior change).
                last_activity[0] = time.monotonic()
                line = redact_text(raw.rstrip("\n"))
                if not line.strip():
                    continue
                event = _parse_event(line=line)
                if event is None:
                    # Altitude: Non-JSON lines (e.g., startup errors) - originals are circulated and left as background details.
                    # Spec-0073/T1: print for streams.emit - always hit stdout (behaviour unchanged)+ Add the current thread binding
                    # The subproject's ring buffer, for the daemon's big window SSE diversion.
                    streams.emit(line=line)
                    raw_tail.append(line)
                    continue
                for human in _lines_for_event(event=event):
                    # Spec-0073/T1: Idem - Event text is bound by the current line to the subject's buffer.
                    streams.emit(line=human)
                tool_events.extend(_tool_names_for_event(event=event))
                if (
                    event.get("type") == "system"
                    and event.get("subtype") == "init"
                    and isinstance(event.get("model"), str)
                ):
                    init_model = event["model"]
                if event.get("type") == "result":
                    result_text = redact_text(str(event.get("result") or ""))
                    result_usage = _token_usage_for_result_event(
                        event=event,
                        fallback_model=init_model,
                    )
            returncode = proc.wait()
        finally:
            # Spec-0046/T1: Stop the watch and recycle the door dog thread (daemon,join immediately returns) whether it is read properly or the watchdog is killed.
            stop_event.set()
            if watchdog is not None:
                watchdog.join()
            stdin_writer.join(timeout=_TERMINATE_GRACE_SECONDS)

        if watchdog_reason:
            # Spec-0046/T1: Re-use existing RunteError (no new abnormal type) - Upstream try/except Exchange ZEMPTION Zero Changes.
            raise RuntimeError(
                f"Claude Code CLI {watchdog_reason[0]}; subprocess terminated"
                f"（idle={idle:.0f}s, max_wall={max_wall:.0f}s）"
            )
        if returncode != 0:
            detail = result_text.strip() or "\n".join(raw_tail).strip()
            raise RuntimeError(f"Claude Code CLI failed (exit code {returncode}): {detail}")
        if stdin_errors:
            raise RuntimeError(
                f"Failed to write the Claude Code prompt to stdin: {stdin_errors[0]}"
            )
        return result_text or "\n".join(raw_tail), tuple(tool_events), result_usage
