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


@pytest.fixture(autouse=True)
def _isolate_forge_state():
    """# Spec-0074: 隔离 forge 分发层的模块级状态，杜绝测试间串台。

    `openagents.utils.forge` 是 PEP 562 `__getattr__` 委托模块（`vigil.github` 即它）。大量 vigil 测试用
    `monkeypatch.setattr(vigil_module.github, "get_issue", ...)` 打桩——而 `vigil_module.github` **就是
    forge 模块**：`monkeypatch` 判 `forge.get_issue` 存在（经 __getattr__ 委托到 github 解析成功）、存下那个
    真函数，teardown 时把它**作为真实属性写回 forge**。真实属性遮蔽 __getattr__，于是**下一个**测试里
    `forge.get_issue` 不再委托到（被打桩的）github driver、而是那枚泄漏的真函数 → 真的 shell 出去调 `gh`
    → 被离网硬闸拦下（本 PR 的 CI 红根因）。也重置 `_active`，免惰性发现结果跨测试缓存。

    每个测试前后：`reset()` 清 `_active` + 删掉一切**泄漏进 forge.__dict__ 的真属性**（import 时就有的
    合法名不动），保证 forge 恒是纯委托态。零业务侵入——不碰那几十处 `setattr(vigil_module.github, ...)`。
    """
    from openagents.utils import forge

    baseline = set(vars(forge))  # import 时的合法模块名（含 configure/reset/_active/常量…）
    forge.reset()
    yield
    for name in list(vars(forge)):
        if name not in baseline:
            delattr(forge, name)  # 测试泄漏进来的真属性——删掉，恢复纯 __getattr__ 委托
    forge.reset()


@pytest.fixture(autouse=True)
def _no_self_update(monkeypatch):
    """# Spec-0070/T1: 全局关掉自更新预检——既有测试导入/调用 `cli.main` 时预检整段 no-op，零回归、不触网。

    `openagents.cli.main()` 每次都在 `parse_args` 前跑一段自更新预检（`selfupdate.precheck`：git fetch →
    比对落后 → pull/uv install/execvp）。测试里绝不能真去 fetch 网络 / 重装 / execvp，故 autouse 置硬开关
    `OPENAGENTS_NO_SELF_UPDATE=1`，让 `precheck` 一进来就短路。测 selfupdate 本体的用例自己 delenv 覆盖它。
    """
    from openagents.utils import selfupdate

    monkeypatch.setenv(selfupdate.DISABLE_ENV, "1")
