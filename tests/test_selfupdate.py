"""# Spec-0070/T1: Update hermetic test - inject fake run/execvp, untouched for the real git/uv/ network/ shell.

Cover issue #146 All accepted: DISABLE/DONE guard short circuit, no source.json short circuit, backward+ safe walk full closed loop (pull --ff-only)
uv tool install --force  →  execvp for DONE=1, unsafe (segment mismatch/steal area) and fetch always print-open
Not to mention no. exec、detect_source_repo Disc within source repository/No landings within target items,OPENAGENTS_HOME Overwrite home Path.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

from openagents.utils import selfupdate

_REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------------------------------
# Test double: injectable run/execvp.
# --------------------------------------------------------------------------------------------------


def _cp(argv, *, rc: int = 0, out: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), rc, out, "")


class _Recorder:
    """Records each call of the sub-process; press the injection handler (argv) returns CompletedProces (or ejects simulations of timeout/OSError)."""

    def __init__(self, handler):
        self._handler = handler
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return self._handler(list(argv))

    def ran(self, *tokens: str) -> bool:
        """Is there a call that includes all tokens."""
        return any(all(tok in call for tok in tokens) for call in self.calls)


class _ExecvpRecorder:
    """Record execvp call; invalid replacement process (returning to None, allowing for normal closing of precheck to make a claim)."""

    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, file, args):
        self.calls.append((file, list(args)))
        return None


def _boom(
    *args, **kwargs
):  # Any call is a failure - to assert that "this path should never have been the starting process."
    raise AssertionError(f"Should not be called:{args} {kwargs}")


def _happy_handler(argv):
    """Backward + Safe Full Closed: Fetch OK / Back 3 / Current branchmain / clean / full OK / uv install OK."""
    if "--show-toplevel" in argv:
        return _cp(
            argv, rc=1
        )  # Could not find source repository (this example presets source.json)
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
# home_dir / source.json reads and writes.
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
# detect_source_repo: Drop a plate in the source repository / target item without a drop.
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
    # Toplevel is a common directory (no openagents/cli.py) that does not recognize as a source repository and does not leave a disk.
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    run = _Recorder(lambda argv: _cp(argv, rc=0, out=str(tmp_path)))
    assert selfupdate.detect_source_repo(cwd=tmp_path, run=run, environ=environ) is None
    assert selfupdate.load_source_config(environ=environ) is None


def test_detect_source_repo_none_when_not_git(tmp_path):
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    run = _Recorder(lambda argv: _cp(argv, rc=128))  # gint rev-parse non-zero = non-guit repository
    assert selfupdate.detect_source_repo(cwd=tmp_path, run=run, environ=environ) is None


# --------------------------------------------------------------------------------------------------
# Precheck: Guard short roads.
# --------------------------------------------------------------------------------------------------


def test_precheck_noop_when_disabled(tmp_path):
    environ = {selfupdate.DISABLE_ENV: "1", selfupdate.HOME_ENV: str(tmp_path)}
    selfupdate.precheck(argv=["openagents", "vigil"], environ=environ, run=_boom, execvp=_boom)


def test_precheck_noop_when_done(tmp_path):
    environ = {selfupdate.DONE_ENV: "1", selfupdate.HOME_ENV: str(tmp_path)}
    selfupdate.precheck(argv=["openagents", "vigil"], environ=environ, run=_boom, execvp=_boom)


def test_precheck_noop_without_source_config(tmp_path):
    # No source.json and no source repository found in detec
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    run = _Recorder(lambda argv: _cp(argv, rc=1))  # Show-toplevel non-zero
    execvp = _ExecvpRecorder()
    selfupdate.precheck(argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp)
    assert not execvp.calls
    assert not run.ran("fetch")


# --------------------------------------------------------------------------------------------------
# Precheck: Backward + Safe --ff-only / uv install --force / execvp (DONE = 1).
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
    # Re-energizing the guards: DONE = 1 must be placed before re-execution, and short circuits (infinite loops) are made available as soon as the subprocess(s) replaced is brought in.
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
            return _cp(argv, rc=0, out="0")  # Not behind.
        return _boom(argv)  # Updated → We shouldn't have gone to the gate./pull/exec

    run = _Recorder(handler)
    execvp = _ExecvpRecorder()
    selfupdate.precheck(argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp)
    assert not execvp.calls
    assert not run.ran("pull")


# --------------------------------------------------------------------------------------------------
# Precheck: Could not safely update / setch failed  → fail-open hint + no exec + no workspace.
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
            return _cp(argv, rc=0, out="feature-x")  # Currently at the feature branch.
        return _boom(argv)  # Never pull / status

    run = _Recorder(handler)
    execvp = _ExecvpRecorder()
    stderr = io.StringIO()
    selfupdate.precheck(
        argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp, stderr=stderr
    )
    assert not execvp.calls
    assert not run.ran("pull")
    assert "Update manually" in stderr.getvalue()


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
            return _cp(argv, rc=0, out=" M openagents/cli.py")  # - Dirty workspace. - No, it's not.
        return _boom(argv)

    run = _Recorder(handler)
    execvp = _ExecvpRecorder()
    stderr = io.StringIO()
    selfupdate.precheck(
        argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp, stderr=stderr
    )
    assert not execvp.calls
    assert not run.ran("pull")
    assert "Update manually" in stderr.getvalue()


def test_precheck_fail_open_when_fetch_fails(tmp_path):
    src = tmp_path / "src"
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=src, branch="main")

    def handler(argv):
        if "--show-toplevel" in argv:
            return _cp(argv, rc=1)
        if "fetch" in argv:
            return _cp(
                argv, rc=1
            )  # Fetch failed . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .        .   . .           .          . . .   .       . . . . .  .
        return _boom(argv)

    run = _Recorder(handler)
    execvp = _ExecvpRecorder()
    stderr = io.StringIO()
    selfupdate.precheck(
        argv=["openagents", "vigil"], environ=environ, run=run, execvp=execvp, stderr=stderr
    )
    assert not execvp.calls
    assert not run.ran("rev-list")
    assert stderr.getvalue()  # Sneaked it.


def test_precheck_fail_open_when_fetch_times_out(tmp_path):
    src = tmp_path / "src"
    environ = {selfupdate.HOME_ENV: str(tmp_path)}
    _seed(environ, repo_path=src, branch="main")

    def handler(argv):
        if "--show-toplevel" in argv:
            return _cp(argv, rc=1)
        if "fetch" in argv:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=30)  # Half-open socket, hang up.
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
    # Any unexpected anomaly must be covered by the outermost, precheck against the caller.
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
# cli.main() wiring: parse_args precheck; normal behaviour remains unchanged when no-op is used as a stake.
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
    assert rc == 2  # Return without order 2 (normal conduct remains unchanged)
    assert order[0] == "precheck" and "parse" in order
