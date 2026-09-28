"""RFC-0001 T2 + RFC-0003: Claude Code 后端适配器。

以子进程非交互（headless/print）方式调用 Claude Code CLI，在给定工作目录
按任务描述改代码，再通过 `git status --porcelain` 判定是否产生改动，
返回满足 `AgentBackend` 协议的 `AgentResult`（见 base.py，决策 2）。

RFC-0003 决策 6：求解过程**实时透传**。`claude -p` 默认 `--output-format=text`
会把输出整段缓冲到结束才吐（运行数分钟零反馈）；故改用
`--output-format stream-json --verbose`，用 `Popen` 逐行读取 NDJSON 事件流，
把助手文本与工具动作（如 `Edit foo.py`）即时格式化打印，并从 `result` 事件
取最终文本作为 PR 摘要。
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

# RFC-0001 T2: claude 可执行名做成模块级常量，便于测试 mock / 替换。
CLAUDE_BIN = "claude"

# Spec-0030/T1: 权限模式的环境变量旋钮与缺省值。
# 缺省 acceptEdits——headless 模式下必须显式放行编辑，否则 claude 不会落盘改动
# （端到端验证发现：缺此参数 run 永远返回 changed=False，见 RFC-0001 T2）。
# 与既有 OPENAGENTS_REVIEWERS 同款最小 env 旋钮（reviewer.py）：不引入配置文件、缺省取默认，
# 让 envcheck 报告里「export OPENAGENTS_PERMISSION_MODE=bypassPermissions」真正可操作
# （把 browser MCP 在 headless 下放行，见 Spec-0030 Reference-level (B)）。
PERMISSION_MODE_ENV = "OPENAGENTS_PERMISSION_MODE"
_DEFAULT_PERMISSION_MODE = "acceptEdits"


def effective_permission_mode() -> str:
    """Spec-0030/T1: 派 claude 时实际使用的权限模式（单一真相源）。

    读环境变量 ``OPENAGENTS_PERMISSION_MODE``，未设或为空白则回退缺省 ``acceptEdits``
    （默认行为不变，非侵入）。envcheck 体检经此访问器读模式，保证「报告里告知的模式」
    永远等于「派单实际用的模式」（否则告知会撒谎，见 Spec-0030 (A)）。
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


# Spec-0046/T1: claude -p 流式读的 idle（停顿）看门狗旋钮，镜像上面的 effective_permission_mode 最小 env 范式。
# 静默只说明没有新输出，不证明挂死；每行输出刷新 idle，但不延长公共总时长预算。
IDLE_TIMEOUT_ENV = "OPENAGENTS_CLAUDE_IDLE_TIMEOUT"
_DEFAULT_IDLE_TIMEOUT = 300.0

# Spec-0046/T1: terminate→kill 之间的宽限秒数（SIGTERM 后等这么久仍不退 → SIGKILL）。
_TERMINATE_GRACE_SECONDS = 5.0
# Spec-0046/T1: 看门狗轮询间隔上限；实际 poll 取「活跃阈值」与它的较小者，避免小阈值下轮询过疏而错过触发点。
_WATCHDOG_POLL_CAP = 5.0


def _effective_timeout(*, env_name, default):
    """Spec-0046/T1: 读某个「秒数」env、float 解析——非法/空白落缺省，``<=0`` 视为关闭（返回 ``0.0``）。

    与 effective_permission_mode 同源同理：单一真相源访问器、不引入配置文件、缺省取安全值。缺省本身恒 ``>0``，
    故空白/非法回退缺省即仍启用；只有显式设成 ``0``/负数才关闭对应看门狗（默认行为不变、非侵入）。
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
    """Spec-0046/T1: idle 停顿超时秒数（单一真相源）；``<=0`` 关闭 idle 看门狗。"""
    return _effective_timeout(env_name=IDLE_TIMEOUT_ENV, default=_DEFAULT_IDLE_TIMEOUT)


def _watchdog_poll_interval(*, idle, max_wall):
    """Spec-0046/T1: 看门狗轮询间隔——取活跃阈值与 ``_WATCHDOG_POLL_CAP`` 的较小者；两者皆关闭 → ``None``。

    返回 ``None`` 表示 idle 与墙钟都关了 → 压根不起看门狗线程（此时读路径与本 spec 之前逐字节一致）。
    """
    candidates = [v for v in (idle, max_wall) if v > 0]
    if not candidates:
        return None
    return min(min(candidates), _WATCHDOG_POLL_CAP)


def _terminate_then_kill(*, proc):
    """Spec-0046/T1: 终止 Claude 及其整个进程组。

    杀掉子进程会关闭其 stdout 管道 → 主循环的 ``for raw in proc.stdout:`` 随即结束迭代（这是唤醒阻塞读的
    唯一手段，故读路径零改动）。Claude 会再启动 shell/MCP 子进程；只调用 ``terminate()`` 会把这些子进程
    留成孤儿，所以 backend 在启动时创建独立 session，并在这里先杀整个 process group，再用句柄作兜底。
    尽力而为：各步吞异常，绝不把看门狗守护线程带崩（守夜第一要务是活着进下一轮）。
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


# RFC-0003 决策 6: 实时事件流格式（stream-json 需配 --verbose 才输出完整事件）。
_STREAM_ARGS = ["--output-format", "stream-json", "--verbose"]

# 摘要截断长度，避免把超长 CLI 输出整段塞进 PR 正文。
_SUMMARY_MAX_LEN = 2000

# 工具动作里用于提取「一句话提示」的常见入参键（按优先级）。
_TOOL_HINT_KEYS = ("file_path", "path", "command", "pattern", "url", "query")

# RFC-0016: 后端 prompt 全局硬约束——禁止 agent 改动 Claude Code 自身配置（`.claude/`）。
# 前置到每条 prompt 开头，从源头避免无人值守循环走向 `.claude/` 写入而撞上权限门卡死。
_GUARDRAIL = (
    "【全局硬约束】禁止修改 Claude Code 自身的任何配置。"
    "不得写入或改动 `.claude/` 目录下的任何内容（包括 skills、hooks、settings、commands 等）。"
    "如果遇到看似需要写入 `.claude/`（例如把某个 skill 写进 `.claude/skills/`）的任务，"
    "必须跳过该步骤并在输出中说明原因，绝不尝试写入——这是不可违反的边界。"
)


def _build_prompt(*, task, context):
    """RFC-0001 T2: 把 task 与 context 拼成喂给 claude 的单条 prompt。

    RFC-0016: 前置 `_GUARDRAIL` 全局硬约束，使「不可改 `.claude/`」出现在每条
    prompt 的开头（所有原子操作的唯一收敛点），对所有调用方透明生效。
    """
    return f"{_GUARDRAIL}\n\n任务：\n{task}\n\n上下文：\n{context}"


def _summarize(*, stdout, changed):
    """RFC-0001 T2: 从最终结果文本生成简短摘要（供 PR 正文/评论使用）。"""
    text = stdout.strip()
    if not text:
        return "无改动。" if not changed else "已产生改动（CLI 无输出）。"
    return text[:_SUMMARY_MAX_LEN]


def _parse_event(*, line):
    """RFC-0003 决策 6: 把一行 stream-json 解析为 dict 事件；非 JSON 返回 None。"""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _format_tool_use(*, block):
    """RFC-0003 决策 6: 把一个 tool_use 块格式化成一行人类可读进度。"""
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
    """RFC-0003 决策 6: 从一条事件提取要打印的人类可读行（assistant 文本 + 工具动作）。"""
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
    """RFC-0001 T2: Claude Code coding agent 适配器，满足 AgentBackend 协议。"""

    name = "claude-code"

    def __init__(self, *, advisory: bool = False) -> None:
        self._advisory = advisory

    def for_advisory(self) -> ClaudeCodeBackend:
        """Spec-0091: a separate, tool-free instance; never mutate developer settings."""
        return ClaudeCodeBackend(advisory=True)

    def run(self, *, work_dir: Path, task: str, context: str) -> AgentResult:
        """RFC-0001 T2 + RFC-0003: 在 work_dir 内驱动 Claude Code 改代码并报告结果。

        以 `claude -p ... --output-format stream-json --verbose` 运行（cwd=work_dir），
        事件实时透传到终端；调用后用 `git -C <work_dir> status --porcelain` 判定改动；
        CLI 返回非零则抛 RuntimeError。
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
        """RFC-0003 决策 6: 逐行解析 stream-json 事件、实时打印进度，返回最终结果文本。

        stderr 合并进 stdout；从 `result` 事件取 `result` 文本作摘要；非零退出抛
        RuntimeError（带已知错误详情）。

        Spec-0046/T1: 阻塞式逐行读外挂一道 idle（停顿）看门狗守护线程——主循环每来一行只多刷一次
        `last_activity`（monotonic）戳；看门狗轮询若发现「连续静默超 idle」或「总时长超 max_wall」，就
        terminate()→kill() 子进程，管道随之关闭、主循环退出，收尾抛**既有的** `RuntimeError`（带无输出/预算
        耗尽详情），交上游 per-issue/per-round try/except 隔离（这轮这个 agent 失败 → 跳过、下轮重试）。
        新输出只刷新静默计时，不证明有效进展，也不延长总时长预算；已有流式读取路径保持不变。
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
            # Spec-0065/T2: 把调用方登记的 fd 传给子进程继承（守夜传的是它那把 flock 存活证明）。
            # 于是「谁在干活谁持锁」——守夜进程被 SIGKILL 后，还在跑的 agent 孤儿仍持着锁，回收方抢不到、
            # 那行就不会被打回队列重领（双跑的最后一个入口）。非守夜的调用方没登记 → 空元组 → 行为不变。
            pass_fds=proc_utils.inherited_fds(),
        )
        # Capture the session group before any watchdog/reaper can observe a dead leader.
        try:
            proc_utils.remember_process_group(handle=proc, pgid=os.getpgid(proc.pid))
        except OSError:
            pass
        # Spec-0065/T2: 自报 PID + Popen 句柄给认领桶——守夜的 `_act` 硬超时据此**精确**杀掉这次调用起的
        # 进程树；句柄用于验明正身（PID 被 reap 后可能已被复用，裸 PID 杀过去就是杀无辜者，见 utils.proc）。
        proc_utils.publish(pid=proc.pid, handle=proc)

        # Spec-0081/T1: prompt 是可能超过 Linux 单参数上限的大载荷，只经 stdin 传一次；argv
        # 只留控制参数。独立 writer 让主线程立即消费 stream-json，避免 stdin/stdout 管道互相背压。
        stdin_errors: list[Exception] = []

        def _write_prompt() -> None:
            try:
                if proc.stdin is None:
                    raise RuntimeError("Claude Code CLI stdin pipe 未建立")
                proc.stdin.write(prompt)
                proc.stdin.close()
            except Exception as exc:  # noqa: BLE001 - 跨线程带回主调用边界统一报告
                stdin_errors.append(exc)

        stdin_writer = threading.Thread(target=_write_prompt, daemon=True)
        stdin_writer.start()

        # Spec-0046/T1: 起 idle 看门狗。last_activity 用单元素 list 做可变共享戳（monotonic，不受系统时间回拨
        # 影响）；watchdog_reason 记录「长时间无输出」或「时间预算耗尽」，收尾据此抛 RuntimeError。
        idle = effective_idle_timeout()
        max_wall = effective_max_wall()
        poll = _watchdog_poll_interval(idle=idle, max_wall=max_wall)
        start = time.monotonic()
        last_activity = [start]
        stop_event = threading.Event()
        watchdog_reason: list[str] = []

        def _watch():
            # Spec-0046/T1: 守护线程——不介入读，只轮询「上次进展戳」与墙钟；触发即杀子进程唤醒阻塞读。
            while not stop_event.wait(poll):
                now = time.monotonic()
                if idle > 0 and now - last_activity[0] > idle:
                    watchdog_reason.append(f"长时间无输出（连续 {idle:g}s 无新输出）")
                    _terminate_then_kill(proc=proc)
                    return
                if max_wall > 0 and now - start > max_wall:
                    watchdog_reason.append(f"时间预算耗尽（单次调用总时长超 {max_wall:g}s）")
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
                # Spec-0046/T1: 每来一行只多做这一件事——刷新「上次进展」戳（含随后被 continue 的空行，
                # 空行也是进展）。事件解析/打印/result 提取全部原样，健康流输出路径不经过看门狗（零回归）。
                last_activity[0] = time.monotonic()
                line = redact_text(raw.rstrip("\n"))
                if not line.strip():
                    continue
                event = _parse_event(line=line)
                if event is None:
                    # 异常：非 JSON 行（如启动错误）——原样透传并留作兜底详情。
                    # Spec-0073/T1: print 换成 streams.emit——照旧打 stdout（行为不变）+ 追加当前线程绑定
                    # subject 的 ring buffer，供 daemon 的大窗 SSE 分流呈现。
                    streams.emit(line=line)
                    raw_tail.append(line)
                    continue
                for human in _lines_for_event(event=event):
                    # Spec-0073/T1: 同上——事件文本落当前线程绑定 subject 的 buffer。
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
            # Spec-0046/T1: 无论正常读完还是看门狗杀掉，都停表并回收看门狗线程（daemon，join 立即返回）。
            stop_event.set()
            if watchdog is not None:
                watchdog.join()
            stdin_writer.join(timeout=_TERMINATE_GRACE_SECONDS)

        if watchdog_reason:
            # Spec-0046/T1: 复用既有 RuntimeError（不新增异常类型）——上游 try/except Exception 零改动接住。
            raise RuntimeError(
                f"Claude Code CLI 调用{watchdog_reason[0]}——已终止子进程"
                f"（idle={idle:.0f}s, max_wall={max_wall:.0f}s）"
            )
        if returncode != 0:
            detail = result_text.strip() or "\n".join(raw_tail).strip()
            raise RuntimeError(f"Claude Code CLI 调用失败（返回码 {returncode}）：{detail}")
        if stdin_errors:
            raise RuntimeError(f"Claude Code CLI prompt 写入 stdin 失败：{stdin_errors[0]}")
        return result_text or "\n".join(raw_tail), tuple(tool_events), result_usage
