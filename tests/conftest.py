"""# Spec-0065/T2: 测试套的**离网硬闸**——哪个测试真的 shell 出去调了 `gh`，当场炸。

为什么必须有这道闸：`gh` 的桩全在各测试自己手里（monkeypatch 高层的 `openagents.utils.github.*`）。
生产代码哪天在某条路径上**多读一次** GitHub（本轮 `_park_needs_human` 的幂等去重就是如此：为了不重贴
同一段理由，它先读回评论流），漏打桩的老测试**不会失败**——开发机上的 `gh` 是登录着的，它会安安静静
去读真仓库的真 issue，绿得毫无破绽；一直到没有 `GH_TOKEN` 的 CI 上才炸。本地绿、CI 红，且本地那把绿
是**假的**（测试在读线上数据）。

闸放在 `subprocess.run` 这个真实边界上：`argv[0] == "gh"` 一律抛，其余（git 等）原样放行。自己打桩
`subprocess.run` 的测试（如 test_github.py 测 `_run_gh` 的重试）在 fixture 之后 setattr，天然覆盖本闸。
"""

import subprocess

import pytest

_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _no_real_gh(monkeypatch):
    """任何测试都不许真的调 `gh`：要么打桩 `github.*`，要么这条路径本就不该碰 GitHub。"""

    def _guard(argv, *args, **kwargs):
        if isinstance(argv, list | tuple) and argv and argv[0] == "gh":
            command = " ".join(str(arg) for arg in argv)
            raise AssertionError(
                f"测试真的调了 GitHub（离网硬闸拦下）：{command}\n"
                "→ 生产代码在这条路径上读/写了 GitHub，而这个测试没给它打桩。"
                "请 monkeypatch 对应的 openagents.utils.github.* 函数。"
            )
        return _REAL_RUN(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _guard)
