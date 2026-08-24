"""RFC-0001 T2 + RFC-0003: ClaudeCodeBackend 适配器的单元测试。

所有子进程副作用一律 mock，不真实调用外部进程：
- claude CLI 走 subprocess.Popen，输出为 stream-json 事件流（RFC-0003 决策 6）；
- git status 走 subprocess.run。
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

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
    """构造一条 assistant 文本事件（stream-json 行）。"""
    return json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    )


def _assistant_tool(name, **inp):
    """构造一条 assistant 工具调用事件。"""
    block = {"type": "tool_use", "name": name, "input": inp}
    return json.dumps({"type": "assistant", "message": {"content": [block]}})


def _result(text):
    """构造最终 result 事件（摘要来源）。"""
    return json.dumps({"type": "result", "subtype": "success", "result": text, "is_error": False})


class _FakePopen:
    """模拟 subprocess.Popen：stdout 为可迭代行序列，wait() 返回退出码。"""

    def __init__(self, *, lines, returncode, pass_fds=()):
        self.stdout = iter(lines)
        self._returncode = returncode
        # Spec-0065/T2: 真 Popen 有 pid，后端要 proc_utils.publish(pid=proc.pid) 自报给认领桶。
        self.pid = 4242
        # Spec-0065/T2: 真 Popen 把 `pass_fds` 交给子进程继承（守夜传的是它那把 flock 存活证明）——
        # 假 Popen 必须原样收下它，否则「锁跟着干活的进程走」这条唯一的存活证明链在测试里根本不可见。
        self.pass_fds = pass_fds

    def wait(self):
        return self._returncode


class _FakeCompleted:
    """模拟 subprocess.run 的返回对象（用于 git status）。"""

    def __init__(self, *, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _patch(monkeypatch, *, claude_lines, claude_returncode, git_porcelain):
    """打桩 Popen(claude 事件流) 与 run(git)，记录调用以便断言。"""
    popen_calls = []
    run_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return _FakePopen(
            lines=[line + "\n" for line in claude_lines],
            returncode=claude_returncode,
            pass_fds=kwargs.get("pass_fds", ()),
        )

    def fake_run(cmd, **kwargs):
        run_calls.append((cmd, kwargs))
        return _FakeCompleted(returncode=0, stdout=git_porcelain)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    return popen_calls, run_calls


# RFC-0016: 后端 prompt 全局硬约束——禁止 agent 改动 Claude Code 自身配置（`.claude/`）。


def test_prompt_starts_with_guardrail():
    # RFC-0016: 约束前置——_build_prompt 输出以 _GUARDRAIL 开头。
    prompt = _build_prompt(task="改 foo", context="issue 正文")
    assert prompt.startswith(_GUARDRAIL)


def test_prompt_contains_claude_config_guardrail():
    # RFC-0016: 约束语义——明确禁止改 Claude Code 自身配置、不写 `.claude/`。
    prompt = _build_prompt(task="t", context="c")
    assert ".claude/" in prompt
    assert "禁止修改 Claude Code 自身" in prompt


def test_guardrail_does_not_drop_task_and_context():
    # RFC-0016 回归保护：前置约束后，原有 task/context 仍完整出现（不破坏 RFC-0001 契约）。
    prompt = _build_prompt(task="修复 bug", context="历史 comment")
    assert "修复 bug" in prompt
    assert "历史 comment" in prompt


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

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="改 foo", context="issue 正文")

    assert isinstance(result, AgentResult)
    assert result.changed is True
    assert "done editing foo" in result.summary


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
    # RFC-0003 决策 6：助手文本与工具动作实时打印到 stdout。
    _patch(
        monkeypatch,
        claude_lines=[
            _assistant_text("开始改代码"),
            _assistant_tool("Edit", file_path="openagents/github.py"),
            _result("完成"),
        ],
        claude_returncode=0,
        git_porcelain=" M a.py\n",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    out = capsys.readouterr().out
    assert "开始改代码" in out
    assert "🔧 Edit" in out
    assert "openagents/github.py" in out


def test_invokes_claude_stream_json_in_work_dir(monkeypatch, tmp_path):
    popen_calls, _ = _patch(
        monkeypatch,
        claude_lines=[_result("ok")],
        claude_returncode=0,
        git_porcelain="",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="修复 bug", context="历史 comment")

    assert len(popen_calls) == 1
    cmd, kwargs = popen_calls[0]
    assert cmd[:2] == [CLAUDE_BIN, "-p"]
    prompt = cmd[2]
    assert "修复 bug" in prompt
    assert "历史 comment" in prompt
    assert "--permission-mode" in cmd and "acceptEdits" in cmd
    # RFC-0003：实时事件流参数。
    assert "--output-format" in cmd and "stream-json" in cmd and "--verbose" in cmd
    assert kwargs["cwd"] == tmp_path


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
        claude_lines=[_result("boom: 出错了")],
        claude_returncode=2,
        git_porcelain="",
    )

    with pytest.raises(RuntimeError) as exc:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "boom" in str(exc.value)


def test_non_json_line_passthrough_and_used_as_error_detail(monkeypatch, tmp_path):
    # 异常：claude 直接吐非 JSON（如启动失败）→ 原样透传，并作为错误详情。
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
# Spec-0065/T2：存活证明跟着干活的进程走——调用线程登记的 fd 必须进 `Popen(pass_fds=…)`
# --------------------------------------------------------------------------- #


def test_popen_hands_the_calling_thread_registered_fd_to_the_child(monkeypatch, tmp_path):
    """Spec-0065/T2：调用线程 `proc.hold_fd(fd=…)` 登记过的 fd，必须原样出现在 `Popen(pass_fds=…)` 里。

    这是守夜「零双跑」证明的**承重构件**：守夜给认领的 subject 持一把 flock，把那个 fd 传给 agent 子进程
    继承 → 锁的语义从「守夜进程还活着」变成「守夜进程**或**它起的 agent 还有一个活着」。守夜被
    SIGKILL / OOM / `docker stop` 打死时，claude 子进程是被**孤儿化**而不是被杀（它要到下次写 stdout 才发现
    父亲没了——足够它把一次 `git push` 做完）；此刻若锁随守夜进程一起被内核收走，重启后的 `_reclaim_dead`
    就会抢到锁、判「持有者已死」、把行打回 queued → 另一个 worker 领走同一个 subject → **双跑**。

    整条链只在这一行 `pass_fds=` 上成立，而它在这里之外**没有任何测试覆盖**（删掉它，全仓依旧全绿）。
    未登记的调用方 → 空元组 → 行为与本 spec 之前完全一致（见 `test_invokes_claude_stream_json_in_work_dir`）。
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
    assert kwargs["pass_fds"] == (fd,), "登记的存活证明 fd 必须传给 agent 子进程继承"
    # 自报的那个句柄**就是**收下这个 fd 的那个进程：认领桶（超时杀树用）与存活证明落在同一个 Popen 上。
    assert list(bucket) == [4242]
    assert bucket[4242].pass_fds == (fd,)


# --------------------------------------------------------------------------- #
# Spec-0030/T1：权限模式最小 env 开关（默认 acceptEdits 不变 / 可经 env 覆写）
# --------------------------------------------------------------------------- #


def test_effective_permission_mode_defaults_accept_edits(monkeypatch):
    # 未设 OPENAGENTS_PERMISSION_MODE → 回退缺省 acceptEdits（默认行为不变）。
    monkeypatch.delenv(PERMISSION_MODE_ENV, raising=False)
    assert effective_permission_mode() == "acceptEdits"


def test_effective_permission_mode_blank_falls_back(monkeypatch):
    # 空白值视同未设 → 仍回退缺省（避免拿空串去拼命令行）。
    monkeypatch.setenv(PERMISSION_MODE_ENV, "   ")
    assert effective_permission_mode() == "acceptEdits"


def test_effective_permission_mode_override(monkeypatch):
    # 设为 bypassPermissions → 访问器随之返回该值。
    monkeypatch.setenv(PERMISSION_MODE_ENV, "bypassPermissions")
    assert effective_permission_mode() == "bypassPermissions"


def test_command_line_uses_default_permission_mode(monkeypatch, tmp_path):
    # 默认态：claude 命令行仍为 --permission-mode acceptEdits（默认不变）。
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
    # 覆写态：env 设为 bypassPermissions → 命令行随之变为 --permission-mode bypassPermissions。
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


# --------------------------------------------------------------------------- #
# Spec-0046/T2：claude -p 流式读的 idle（停顿）看门狗——真静默/病态流触发、健康流零回归、访问器解析
#
# 全程假 Popen，不触真实 claude：`stdout` 是可控节奏行序列生成器，「长时间静默」用 threading.Event
# 阻塞模拟读挂住，terminate()/kill() 置该 Event 解除阻塞 → 迭代结束（复刻「杀进程→管道关→for 退出」）。
# 阈值走极小值（0.1s / 0.2s）使触发确定性、亚秒级，不真等。
# --------------------------------------------------------------------------- #


class _WatchdogPopen:
    """Spec-0046/T2：可控节奏的假 Popen——覆盖看门狗的静默/病态/健康三种流形态。

    - `silence_after=True`：吐完 prelude 行后在 `threading.Event` 上阻塞，模拟「读挂住」（真僵死）；
      terminate() **不**解除阻塞（模拟 SIGTERM 被卡死进程忽略），只有 kill() 置 Event → 迭代结束。
    - `infinite=True`：循环吐 `lines`（每行前 `per_line_sleep`），模拟「每 tick 吐一行垃圾永不结束」的病态流；
      killed 置位后下一轮退出（复刻管道关闭）。
    - 皆为 False：吐完 `lines` 自然结束——健康连续流。
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

    def _iter(self):
        while True:
            for ln in self._lines:
                if self._per_line_sleep:
                    time.sleep(self._per_line_sleep)
                if self.killed:  # kill() 关闭管道 → 停止吐行
                    return
                yield ln
            if self._infinite and self._lines:
                continue
            break
        if self._silence_after:
            self._unblock.wait()  # 阻塞模拟「读挂住」，直到 kill() 置 Event

    def terminate(self):
        # 模拟真僵死进程忽略 SIGTERM：只记调用、不解除阻塞（逼看门狗走到 kill）。
        self.terminated = True

    def kill(self):
        self.killed = True
        self._unblock.set()

    def wait(self, timeout=None):
        # 带 timeout 且尚未 kill → 抛 TimeoutExpired（terminate 宽限内没退），复刻真 Popen 语义。
        if timeout is not None and not self.killed:
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
        return self._returncode


def _patch_popen(monkeypatch, *, fake, git_porcelain):
    """Spec-0046/T2：把 subprocess.Popen 打桩成返回给定假进程，git status 走假 run。返回 popen 调用记录。"""
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
    # ① idle 触发：吐一行后长时间静默 → 连续静默超 idle → terminate 后 kill 被调 + 抛 RuntimeError 含「停顿超时」。
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "0.1")
    monkeypatch.setenv(MAX_WALL_ENV, "0")  # 只测 idle，关墙钟兜底
    fake = _WatchdogPopen(
        lines=[_assistant_text("thinking...") + "\n"], returncode=0, silence_after=True
    )
    _patch_popen(monkeypatch, fake=fake, git_porcelain="")

    with pytest.raises(RuntimeError) as exc:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "停顿超时" in str(exc.value)
    assert fake.terminated is True, "看门狗触发时应先 terminate()"
    assert fake.killed is True, "SIGTERM 宽限内未退 → 应升级到 kill()"


def test_max_wall_timeout_on_pathological_stream_raises(monkeypatch, tmp_path):
    # ② 墙钟触发：每 tick 吐一行（idle 骗得过）但总时长超绝对上限 → 抛 RuntimeError 含「墙钟超时」。
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "0")  # 关 idle：病态流一直有「新行」，idle 判据被骗过
    monkeypatch.setenv(MAX_WALL_ENV, "0.2")
    fake = _WatchdogPopen(
        lines=[_assistant_text("垃圾") + "\n"],
        returncode=0,
        infinite=True,
        per_line_sleep=0.03,
    )
    _patch_popen(monkeypatch, fake=fake, git_porcelain="")

    with pytest.raises(RuntimeError) as exc:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "墙钟超时" in str(exc.value)
    assert fake.killed is True


def test_zero_regression_healthy_stream_watchdog_never_fires(monkeypatch, tmp_path, capsys):
    # ③ 零回归：连续正常流 → 看门狗从不介入读、从不杀；输出/摘要/changed 与「看门狗全关」逐字节一致。
    lines = [
        _assistant_text("开始改代码") + "\n",
        _assistant_tool("Edit", file_path="a.py") + "\n",
        _result("完成") + "\n",
    ]

    # (A) 看门狗启用（默认阈值 300s/3600s，健康快流下永不触发）。
    monkeypatch.delenv(IDLE_TIMEOUT_ENV, raising=False)
    monkeypatch.delenv(MAX_WALL_ENV, raising=False)
    fake_on = _WatchdogPopen(lines=list(lines), returncode=0)
    _patch_popen(monkeypatch, fake=fake_on, git_porcelain=" M a.py\n")
    res_on = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")
    out_on = capsys.readouterr().out

    # (B) 看门狗全关（env=0 → 压根不起线程，等价于本 spec 之前的读路径）。
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "0")
    monkeypatch.setenv(MAX_WALL_ENV, "0")
    fake_off = _WatchdogPopen(lines=list(lines), returncode=0)
    _patch_popen(monkeypatch, fake=fake_off, git_porcelain=" M a.py\n")
    res_off = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")
    out_off = capsys.readouterr().out

    assert out_on == out_off, "看门狗启用与否，健康流的 stdout 必须逐字节一致"
    assert res_on.summary == res_off.summary == "完成"
    assert res_on.changed is res_off.changed is True
    assert fake_on.terminated is False and fake_on.killed is False, "健康流看门狗从不介入"


def test_effective_idle_timeout_defaults_to_300(monkeypatch):
    # ④ 访问器：未设 → 缺省 300s（宽到不误杀正常长任务）。
    monkeypatch.delenv(IDLE_TIMEOUT_ENV, raising=False)
    assert effective_idle_timeout() == 300.0


def test_effective_max_wall_defaults_to_3600(monkeypatch):
    # ④ 访问器：未设 → 缺省 3600s（远大于 idle）。
    monkeypatch.delenv(MAX_WALL_ENV, raising=False)
    assert effective_max_wall() == 3600.0


def test_effective_idle_timeout_blank_or_invalid_falls_back(monkeypatch):
    # ④ 访问器：空白/非法值落缺省（不拿坏值去当阈值）。
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "   ")
    assert effective_idle_timeout() == 300.0
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "not-a-number")
    assert effective_idle_timeout() == 300.0


def test_effective_idle_timeout_zero_or_negative_disables(monkeypatch):
    # ④ 访问器：<=0 视为关闭该看门狗（返回 0.0）。
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "0")
    assert effective_idle_timeout() == 0.0
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "-5")
    assert effective_idle_timeout() == 0.0


def test_effective_timeouts_honor_override(monkeypatch):
    # ④ 访问器：合法覆写 → 随之返回该值。
    monkeypatch.setenv(IDLE_TIMEOUT_ENV, "42")
    monkeypatch.setenv(MAX_WALL_ENV, "1234.5")
    assert effective_idle_timeout() == 42.0
    assert effective_max_wall() == 1234.5
