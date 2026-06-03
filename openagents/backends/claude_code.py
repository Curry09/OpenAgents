"""RFC-0001 T2 + RFC-0003: Claude Code 后端适配器。

以子进程非交互（headless/print）方式调用 Claude Code CLI，在给定工作目录
按任务描述改代码，再通过 `git status --porcelain` 判定是否产生改动，
返回满足 `AgentBackend` 协议的 `AgentResult`（见 base.py，决策 2）。

RFC-0003 决策 6：求解过程**实时透传**——用 `Popen` 边读边把 claude 输出转发到
本进程 stdout（不再 `capture_output` 整段吞掉），同时留存全文供 PR 摘要使用，
解决「solve 运行数分钟却零反馈」的观感问题。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from openagents.backends.base import AgentResult

# RFC-0001 T2: claude 可执行名做成模块级常量，便于测试 mock / 替换。
CLAUDE_BIN = "claude"

# RFC-0001 T2: headless 模式下必须显式放行编辑，否则 claude 不会落盘改动
# （端到端验证发现：缺此参数 run 永远返回 changed=False）。
_PERMISSION_MODE = "acceptEdits"

# 摘要截断长度，避免把超长 CLI 输出整段塞进 PR 正文。
_SUMMARY_MAX_LEN = 2000


def _build_prompt(*, task, context):
    """RFC-0001 T2: 把 task 与 context 拼成喂给 claude 的单条 prompt。"""
    return f"任务：\n{task}\n\n上下文：\n{context}"


def _summarize(*, stdout, changed):
    """RFC-0001 T2: 从 CLI stdout 生成简短摘要（供 PR 正文/评论使用）。"""
    text = stdout.strip()
    if not text:
        return "无改动。" if not changed else "已产生改动（CLI 无输出）。"
    return text[:_SUMMARY_MAX_LEN]


class ClaudeCodeBackend:
    """RFC-0001 T2: Claude Code coding agent 适配器，满足 AgentBackend 协议。"""

    name = "claude-code"

    def run(self, *, work_dir: Path, task: str, context: str) -> AgentResult:
        """RFC-0001 T2 + RFC-0003: 在 work_dir 内驱动 Claude Code 改代码并报告结果。

        以 `claude -p "<prompt>"` 非交互模式运行（cwd=work_dir），输出实时透传到终端；
        调用后用 `git -C <work_dir> status --porcelain` 判定是否有改动；CLI 返回非零
        则抛出 RuntimeError。
        """
        work_dir_str = str(work_dir)
        prompt = _build_prompt(task=task, context=context)

        stdout_text = self._run_claude_streaming(work_dir=work_dir, prompt=prompt)

        status = subprocess.run(
            ["git", "-C", work_dir_str, "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        changed = bool(status.stdout.strip())

        return AgentResult(
            changed=changed,
            summary=_summarize(stdout=stdout_text, changed=changed),
        )

    def _run_claude_streaming(self, *, work_dir: Path, prompt: str) -> str:
        """RFC-0003 决策 6: 以 Popen 实时转发 claude 输出，同时累积全文返回。

        stderr 合并进 stdout 一并透传；非零退出码抛 RuntimeError（含已收集的输出）。
        """
        proc = subprocess.Popen(
            [CLAUDE_BIN, "-p", prompt, "--permission-mode", _PERMISSION_MODE],
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        captured: list[str] = []
        for line in proc.stdout:  # 边读边转发，给运行中的 solve 实时反馈
            sys.stdout.write(line)
            sys.stdout.flush()
            captured.append(line)
        returncode = proc.wait()

        output = "".join(captured)
        if returncode != 0:
            raise RuntimeError(f"Claude Code CLI 调用失败（返回码 {returncode}）：{output.strip()}")
        return output
