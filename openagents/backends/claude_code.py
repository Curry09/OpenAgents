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
import subprocess
from pathlib import Path

from openagents.backends.base import AgentResult

# RFC-0001 T2: claude 可执行名做成模块级常量，便于测试 mock / 替换。
CLAUDE_BIN = "claude"

# RFC-0001 T2: headless 模式下必须显式放行编辑，否则 claude 不会落盘改动
# （端到端验证发现：缺此参数 run 永远返回 changed=False）。
_PERMISSION_MODE = "acceptEdits"

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
    return f"🔧 {name}: {hint}".rstrip(": ").rstrip() if hint else f"🔧 {name}"


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


class ClaudeCodeBackend:
    """RFC-0001 T2: Claude Code coding agent 适配器，满足 AgentBackend 协议。"""

    name = "claude-code"

    def run(self, *, work_dir: Path, task: str, context: str) -> AgentResult:
        """RFC-0001 T2 + RFC-0003: 在 work_dir 内驱动 Claude Code 改代码并报告结果。

        以 `claude -p ... --output-format stream-json --verbose` 运行（cwd=work_dir），
        事件实时透传到终端；调用后用 `git -C <work_dir> status --porcelain` 判定改动；
        CLI 返回非零则抛 RuntimeError。
        """
        work_dir_str = str(work_dir)
        prompt = _build_prompt(task=task, context=context)

        result_text = self._run_claude_streaming(work_dir=work_dir, prompt=prompt)

        status = subprocess.run(
            ["git", "-C", work_dir_str, "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        changed = bool(status.stdout.strip())

        return AgentResult(
            changed=changed,
            summary=_summarize(stdout=result_text, changed=changed),
        )

    def _run_claude_streaming(self, *, work_dir: Path, prompt: str) -> str:
        """RFC-0003 决策 6: 逐行解析 stream-json 事件、实时打印进度，返回最终结果文本。

        stderr 合并进 stdout；从 `result` 事件取 `result` 文本作摘要；非零退出抛
        RuntimeError（带已知错误详情）。
        """
        proc = subprocess.Popen(
            [CLAUDE_BIN, "-p", prompt, "--permission-mode", _PERMISSION_MODE, *_STREAM_ARGS],
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        result_text = ""
        raw_tail: list[str] = []
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            event = _parse_event(line=line)
            if event is None:
                # 异常：非 JSON 行（如启动错误）——原样透传并留作兜底详情。
                print(line, flush=True)
                raw_tail.append(line)
                continue
            for human in _lines_for_event(event=event):
                print(human, flush=True)
            if event.get("type") == "result":
                result_text = str(event.get("result") or "")
        returncode = proc.wait()

        if returncode != 0:
            detail = result_text.strip() or "\n".join(raw_tail).strip()
            raise RuntimeError(f"Claude Code CLI 调用失败（返回码 {returncode}）：{detail}")
        return result_text or "\n".join(raw_tail)
