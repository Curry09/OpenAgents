"""RFC-0013: 实跑端到端脚本并把「合否 + 日志末尾」渲染成 PR 评论（纯旁路模块）。

RFC-0008 给 PR 正文加了「端到端验证」指路牌（指针），本模块是其自然延伸：在
`implement` 转正前实际执行本分支 RFC 的 e2e 脚本，给出确定性「合否」成果
（CLAUDE.md 理念 8：以成果为中心，模型替人做端到端测试）。

只懂 subprocess + 文本处理的纯模块——不感知 git / GitHub / RFC 文档语义 / orchestrator
（理念 10 解耦）。对外暴露（见 RFC-0013 接口契约）：
- `E2EResult`：实跑结果的结构化载体。
- `run_e2e_script`：在 worktree 内 `bash <script>` 跑离线段、截退出码与日志末尾，绝不抛错。
- `render_result`：把结果渲染成「## 端到端测试结果」评论 Markdown，纯函数。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# RFC-0013 决策 3：实跑离线段（ruff + pytest，全程 mock）的超时上限，保护 implement 不被拖死。
DEFAULT_TIMEOUT_SECONDS = 600
# RFC-0013 决策 7：结果评论默认截取的日志末尾行数（ruff/pytest 失败摘要天然落在末尾）。
DEFAULT_TAIL_LINES = 40

# RFC-0013 决策 1：四种 outcome——脚本跑通 / 跑挂 / 无脚本可跑。
_OUTCOME_PASSED = "passed"
_OUTCOME_FAILED = "failed"
_OUTCOME_SKIPPED = "skipped"

# 跳过（无脚本可跑）时的降级提示，指回 RFC 集成测试段供人工验证。
_SKIPPED_LOG = "本分支 RFC 未声明 e2e 脚本（或脚本尚未落地），见 RFC「集成测试」段手动验证。"


@dataclass(frozen=True)
class E2EResult:
    """RFC-0013：实跑结果的结构化载体。

    脚本缺失 / 非常规文件 / 超时 / 非零退出 各映射成此结构，run_e2e_script 绝不抛错。
    """

    outcome: str  # "passed" | "failed" | "skipped"
    exit_code: int | None  # 子进程退出码；skipped / 超时未取到时为 None
    script_path: str | None  # 实跑的脚本相对路径；无脚本时为 None
    log_tail: str  # 合并 stdout+stderr 的末尾若干行；skipped 时为降级提示文本
    timed_out: bool  # 是否因超时被终止（outcome 随之为 "failed"）


def run_e2e_script(
    *, worktree: Path, script_path: str | None, timeout_seconds: int, tail_lines: int
) -> E2EResult:
    """RFC-0013 决策 1/3：在 worktree 内 `bash <script_path>` 实跑离线段，捕获结果。

    绝不抛错（决策 6，旁路尽力而为）：
    - script_path 为 None / 文件不存在 / 非常规文件 → outcome="skipped"，不起子进程，
      log_tail 给降级提示。
    - 退出码 0 → "passed"；非零 → "failed"；超时 → "failed" 且 timed_out=True。
    """
    # 1. 无脚本可跑：不起子进程，降级为 skipped。
    if script_path is None:
        return _skipped(script_path=None)
    script_file = worktree / script_path
    if not script_file.is_file():
        return _skipped(script_path=script_path)

    # 2. 默认环境跑脚本离线段（不设 OPENAGENTS_E2E_REAL，决策 3），合并 stdout+stderr。
    try:
        proc = subprocess.run(
            ["bash", str(script_file)],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        # 超时：映射为 failed + timed_out，截取超时前已产出的输出末尾。
        tail = _tail(text=_combine(stdout=expired.stdout, stderr=expired.stderr), lines=tail_lines)
        return E2EResult(
            outcome=_OUTCOME_FAILED,
            exit_code=None,
            script_path=script_path,
            log_tail=tail,
            timed_out=True,
        )

    # 3. 退出码 0 → passed，否则 failed；日志取合并输出末尾 tail_lines 行。
    outcome = _OUTCOME_PASSED if proc.returncode == 0 else _OUTCOME_FAILED
    tail = _tail(text=_combine(stdout=proc.stdout, stderr=proc.stderr), lines=tail_lines)
    return E2EResult(
        outcome=outcome,
        exit_code=proc.returncode,
        script_path=script_path,
        log_tail=tail,
        timed_out=False,
    )


def render_result(*, result: E2EResult, tail_lines: int) -> str:
    """RFC-0013 决策 4/7：渲染「## 端到端测试结果」评论 Markdown（纯函数，只读 result）。

    脚本行 + 合否行（✅/❌/⚠️ + 退出码/超时）+ 日志末尾代码块；四种情形各自降级，不抛错。
    """
    lines = ["## 端到端测试结果"]

    # 1. 脚本行：有脚本给可直接执行的命令，无脚本指回 RFC 集成测试段。
    if result.script_path:
        lines.append(f"- 脚本：`bash {result.script_path}`")
    else:
        lines.append("- 脚本：见 RFC「集成测试」段")

    # 2. 合否行：按 outcome / timed_out 降级（超时单列、退出码随附）。
    lines.append(f"- 结果：{_outcome_line(result=result)}")

    # 3. 日志末尾代码块：始终给出（skipped 时为降级提示）。
    lines.append(f"- 日志末尾（最后 {tail_lines} 行）：")
    lines.append("```")
    lines.append(result.log_tail)
    lines.append("```")
    return "\n".join(lines)


def _outcome_line(*, result: E2EResult) -> str:
    """渲染「结果」行文本：✅ 通过 / ❌ 失败或超时 / ⚠️ 跳过。"""
    if result.outcome == _OUTCOME_PASSED:
        return f"✅ 通过（退出码 {result.exit_code}）"
    if result.outcome == _OUTCOME_SKIPPED:
        return "⚠️ 跳过：本分支 RFC 未声明 e2e 脚本（或脚本尚未落地），见 RFC「集成测试」段手动验证"
    if result.timed_out:
        return f"❌ 超时（>{DEFAULT_TIMEOUT_SECONDS}s）"
    return f"❌ 失败（退出码 {result.exit_code}）"


def _skipped(*, script_path: str | None) -> E2EResult:
    """无脚本可跑时的降级结果（不起子进程）。"""
    return E2EResult(
        outcome=_OUTCOME_SKIPPED,
        exit_code=None,
        script_path=script_path,
        log_tail=_SKIPPED_LOG,
        timed_out=False,
    )


def _combine(*, stdout: str | None, stderr: str | None) -> str:
    """合并子进程 stdout + stderr（任一为 None 视作空串）。"""
    return f"{stdout or ''}{stderr or ''}"


def _tail(*, text: str, lines: int) -> str:
    """截取文本末尾 lines 行；行数 ≤ 0 或文本为空时返回空串。"""
    if lines <= 0 or not text:
        return ""
    return "\n".join(text.splitlines()[-lines:])
