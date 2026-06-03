"""RFC-0001 T2: Claude Code 后端适配器。

以子进程非交互（headless/print）方式调用 Claude Code CLI，在给定工作目录
按任务描述改代码，再通过 `git status --porcelain` 判定是否产生改动，
返回满足 `AgentBackend` 协议的 `AgentResult`（见 base.py，决策 2）。
"""

from __future__ import annotations

import subprocess
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
        """RFC-0001 T2: 在 work_dir 内驱动 Claude Code 改代码并报告结果。

        以 `claude -p "<prompt>"` 非交互模式运行（cwd=work_dir）；调用后用
        `git -C <work_dir> status --porcelain` 判定是否有改动；CLI 返回非零
        则抛出 RuntimeError。
        """
        work_dir_str = str(work_dir)
        prompt = _build_prompt(task=task, context=context)

        completed = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--permission-mode", _PERMISSION_MODE],
            cwd=work_dir,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Claude Code CLI 调用失败（返回码 {completed.returncode}）："
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )

        status = subprocess.run(
            ["git", "-C", work_dir_str, "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        changed = bool(status.stdout.strip())

        return AgentResult(
            changed=changed,
            summary=_summarize(stdout=completed.stdout, changed=changed),
        )
