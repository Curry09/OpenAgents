"""# Spec-0070/T1: 自更新预检 hermetic 测试——注入 fake run/execvp，全程不触真实 git/uv/网络/shell。

覆盖 issue #146 全部验收：DISABLE/DONE 守卫短路、无 source.json 短路、落后+安全走完整闭环（pull --ff-only
→ uv tool install --force → execvp 置 DONE=1）、不安全（分支不符/工作区脏）与 fetch 失败一律 fail-open 打印
提示且不 exec、detect_source_repo 源仓库内落盘/目标项目内不落盘、OPENAGENTS_HOME 覆盖 home 路径。
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

from openagents.utils import selfupdate

_REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------------------------------
# 测试替身：可注入的 run / execvp。
# --------------------------------------------------------------------------------------------------


def _cp(argv, *, rc: int = 0, out: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), rc, out, "")


class _Recorder:
    """记录每次子进程调用；按注入的 handler(argv) 返回 CompletedProcess（或抛异常模拟超时/OSError）。"""

    def __init__(self, handler):
        self._handler = handler
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return self._handler(list(argv))

    def ran(self, *tokens: str) -> bool:
        """是否有某次调用同时含全部 tokens。"""
        return any(all(tok in call for tok in tokens) for call in self.calls)


class _ExecvpRecorder:
    """记录 execvp 调用；不真的替换进程（返回 None，使 precheck 正常收尾便于断言）。"""

    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, file, args):
        self.calls.append((file, list(args)))
        return None


def _boom(*args, **kwargs):  # 任何调用即失败——用于断言「这条路径根本不该起子进程」。
    raise AssertionError(f"不该被调用：{args} {kwargs}")


def _happy_handler(argv):
    """落后 + 安全的完整闭环：fetch OK / 落后 3 / 当前分支 main / 干净 / pull OK / uv install OK。"""
    if "--show-toplevel" in argv:
        return _cp(argv, rc=1)  # detect 找不到源仓库（本例已预置 source.json）
    if "fetch" in argv:
        return _cp(argv, rc=0)
    if "rev-list" in argv:
        return _cp(argv, rc=0, out="3")
    if "--abbrev-ref" in argv:
        return _cp(argv, rc=0, out="main")
    if "--porcelain" in argv:
        return _cp(argv, rc=0, out="")
    if "--ff-only" in argv:
        return _cp(argv, rc=0)
    if argv[:1] == ["uv"]:
        return _cp(argv, rc=0)
    return _cp(argv, rc=0)


def _seed(environ: dict, *, repo_path: Path, branch: str = "main") -> None:
    selfupdate.save_source_config(
        config=selfupdate.SourceConfig(repo_path=str(repo_path), branch=branch), environ=environ
    )


# --------------------------------------------------------------------------------------------------
# home_dir / source.json 读写。
# --------------------------------------------------------------------------------------------------


def test_home_dir_defaults_to_dot_openagents():
    assert selfupdate.home_dir(environ={}) == Path.home() / ".openagents"


def test_home_dir_honors_openagents_home(tmp_path):
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    assert selfupdate.home_dir(environ=environ) == tmp_path
    assert selfupdate.source_config_path(environ=environ) == tmp_path / "source.json"


def test_save_and_load_source_config_roundtrip(tmp_path):
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=tmp_path / "src", branch="main")
    loaded = selfupdate.load_source_config(environ=environ)
    assert loaded == selfupdate.SourceConfig(
        repo_path=str(tmp_path / "src"), remote="origin", branch="main"
    )


def test_load_source_config_missing_returns_none(tmp_path):
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    assert selfupdate.load_source_config(environ=environ) is None


def test_load_source_config_bad_json_returns_none(tmp_path):
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    path = selfupdate.source_config_path(environ=environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert selfupdate.load_source_config(environ=environ) is None


# --------------------------------------------------------------------------------------------------
# detect_source_repo：源仓库内落盘 / 目标项目内不落盘。
# --------------------------------------------------------------------------------------------------


def test_detect_source_repo_saves_when_inside_source(tmp_path):
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    run = _Recorder(lambda argv: _cp(argv, rc=0, out=str(_REPO_ROOT)))
    found = selfupdate.detect_source_repo(cwd=_REPO_ROOT, run=run, environ=environ)
    assert found == _REPO_ROOT
    assert selfupdate.load_source_config(environ=environ) == selfupdate.SourceConfig(
        repo_path=str(_REPO_ROOT), remote="origin", branch="main"
    )


def test_detect_source_repo_none_in_target_project(tmp_path):
    # toplevel 是一个普通目录（无 openagents/cli.py）→ 不认作源仓库、不落盘。
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    run = _Recorder(lambda argv: _cp(argv, rc=0, out=str(tmp_path)))
    assert selfupdate.detect_source_repo(cwd=tmp_path, run=run, environ=environ) is None
    assert selfupdate.load_source_config(environ=environ) is None


def test_detect_source_repo_none_when_not_git(tmp_path):
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    run = _Recorder(lambda argv: _cp(argv, rc=128))  # git rev-parse 非零 = 非 git 仓库
    assert selfupdate.detect_source_repo(cwd=tmp_path, run=run, environ=environ) is None


# --------------------------------------------------------------------------------------------------
# precheck：守卫短路。
# --------------------------------------------------------------------------------------------------


def test_precheck_noop_when_disabled(tmp_path):
    environ = {selfupdate.DISABLE_ENV: "1", selfupdate.HOME_ENV: str(tmp_path)}
    selfupdate.precheck(argv=["openagents", "vigil"], environ=environ, run=_boom, execvp=_boom)


def test_precheck_noop_when_done(tmp_path):
    environ = {selfupdate.DONE_ENV: "1", selfupdate.HOME_ENV: str(tmp_path)}
    selfupdate.precheck(argv=["openagents", "vigil"], environ=environ, run=_boom, execvp=_boom)


def test_precheck_noop_without_source_config(tmp_path):
    # 无 source.json 且 detect 找不到源仓库 → 不 fetch、不 exec（静默）。
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    run = _Recorder(lambda argv: _cp(argv, rc=1))  # show-toplevel 非零 → detect None
    execvp = _ExecvpRecorder()
    selfupdate.precheck(argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp)
    assert not execvp.calls
    assert not run.ran("fetch")


# --------------------------------------------------------------------------------------------------
# precheck：落后 + 安全 → 完整闭环 pull --ff-only / uv install --force / execvp（置 DONE=1）。
# --------------------------------------------------------------------------------------------------


def test_precheck_full_update_loop_when_behind_and_safe(tmp_path):
    src = tmp_path / "src"
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=src, branch="main")
    run = _Recorder(_happy_handler)
    execvp = _ExecvpRecorder()

    selfupdate.precheck(
        argv=["openagents", "vigil", "--once"], environ=environ, run=run, execvp=execvp
    )

    assert run.ran("fetch", "origin", "main")
    assert run.ran("pull", "--ff-only", "origin", "main")
    assert run.ran("uv", "tool", "install", "--force")
    assert execvp.calls == [("openagents", ["openagents", "vigil", "--once"])]
    # 重执行守卫：重执行前必置 DONE=1，使被替换的子进程一进来即短路（防无限循环）。
    assert environ[selfupdate.DONE_ENV] == "1"


def test_precheck_noop_when_up_to_date(tmp_path):
    src = tmp_path / "src"
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=src, branch="main")

    def handler(argv):
        if "--show-toplevel" in argv:
            return _cp(argv, rc=1)
        if "fetch" in argv:
            return _cp(argv, rc=0)
        if "rev-list" in argv:
            return _cp(argv, rc=0, out="0")  # 不落后
        return _boom(argv)  # 已最新 → 不该再走到安全闸/pull/exec

    run = _Recorder(handler)
    execvp = _ExecvpRecorder()
    selfupdate.precheck(argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp)
    assert not execvp.calls
    assert not run.ran("pull")


# --------------------------------------------------------------------------------------------------
# precheck：不可安全更新 / fetch 失败 → fail-open 提示 + 不 exec + 不动工作区。
# --------------------------------------------------------------------------------------------------


def test_precheck_fail_open_when_branch_mismatch(tmp_path):
    src = tmp_path / "src"
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=src, branch="main")

    def handler(argv):
        if "--show-toplevel" in argv:
            return _cp(argv, rc=1)
        if "fetch" in argv:
            return _cp(argv, rc=0)
        if "rev-list" in argv:
            return _cp(argv, rc=0, out="2")
        if "--abbrev-ref" in argv:
            return _cp(argv, rc=0, out="feature-x")  # 当前在 feature 分支 → 不安全
        return _boom(argv)  # 绝不 pull / status 之后就该止步

    run = _Recorder(handler)
    execvp = _ExecvpRecorder()
    stderr = io.StringIO()
    selfupdate.precheck(
        argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp, stderr=stderr
    )
    assert not execvp.calls
    assert not run.ran("pull")
    assert "手动更新" in stderr.getvalue()


def test_precheck_fail_open_when_dirty_worktree(tmp_path):
    src = tmp_path / "src"
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=src, branch="main")

    def handler(argv):
        if "--show-toplevel" in argv:
            return _cp(argv, rc=1)
        if "fetch" in argv:
            return _cp(argv, rc=0)
        if "rev-list" in argv:
            return _cp(argv, rc=0, out="1")
        if "--abbrev-ref" in argv:
            return _cp(argv, rc=0, out="main")
        if "--porcelain" in argv:
            return _cp(argv, rc=0, out=" M openagents/cli.py")  # 脏工作区 → 不安全
        return _boom(argv)

    run = _Recorder(handler)
    execvp = _ExecvpRecorder()
    stderr = io.StringIO()
    selfupdate.precheck(
        argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp, stderr=stderr
    )
    assert not execvp.calls
    assert not run.ran("pull")
    assert "手动更新" in stderr.getvalue()


def test_precheck_fail_open_when_fetch_fails(tmp_path):
    src = tmp_path / "src"
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=src, branch="main")

    def handler(argv):
        if "--show-toplevel" in argv:
            return _cp(argv, rc=1)
        if "fetch" in argv:
            return _cp(argv, rc=1)  # fetch 失败 → 立即 fail-open，不再比对
        return _boom(argv)

    run = _Recorder(handler)
    execvp = _ExecvpRecorder()
    stderr = io.StringIO()
    selfupdate.precheck(
        argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp, stderr=stderr
    )
    assert not execvp.calls
    assert not run.ran("rev-list")
    assert stderr.getvalue()  # 打了软提示


def test_precheck_fail_open_when_fetch_times_out(tmp_path):
    src = tmp_path / "src"
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=src, branch="main")

    def handler(argv):
        if "--show-toplevel" in argv:
            return _cp(argv, rc=1)
        if "fetch" in argv:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=30)  # 半开 socket 挂死
        return _boom(argv)

    run = _Recorder(handler)
    execvp = _ExecvpRecorder()
    stderr = io.StringIO()
    selfupdate.precheck(
        argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp, stderr=stderr
    )
    assert not execvp.calls
    assert stderr.getvalue()


def test_precheck_never_raises_on_unexpected_error(tmp_path):
    # 任何意料外异常都必须被最外层兜住（fail-open 铁律），precheck 对调用方永不抛。
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=tmp_path / "src", branch="main")

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    stderr = io.StringIO()
    selfupdate.precheck(
        argv=["openagents", "vigil"], environ=environ, run=explode, execvp=_boom, stderr=stderr
    )
    assert stderr.getvalue()


# --------------------------------------------------------------------------------------------------
# cli.main() 接线：parse_args 前调 precheck；打桩为 no-op 时正常行为不变。
# --------------------------------------------------------------------------------------------------


def test_cli_main_calls_precheck_before_parse(monkeypatch):
    from openagents import cli

    monkeypatch.delenv(selfupdate.DISABLE_ENV, raising=False)
    order: list[str] = []

    def fake_precheck(*, argv):
        order.append("precheck")

    real_parse = cli.build_parser().__class__.parse_args

    def spy_parse(self, *args, **kwargs):
        order.append("parse")
        return real_parse(self, *args, **kwargs)

    monkeypatch.setattr(selfupdate, "precheck", fake_precheck)
    monkeypatch.setattr(cli.argparse.ArgumentParser, "parse_args", spy_parse)

    rc = cli.main([])
    assert rc == 2  # 无命令仍返回 2（正常行为逐字不变）
    assert order[0] == "precheck" and "parse" in order
