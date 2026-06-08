"""RFC-0013 T1: e2e 模块（脚本实跑 + 结果评论渲染）的单元测试。

覆盖 run_e2e_script 四分支（passed / failed / 超时 / skipped）与 render_result
四种 outcome 渲染，全程不抛错。脚本用真实 bash 跑（退出码可控），无需 mock subprocess。
"""

from pathlib import Path

from openagents import e2e
from openagents.e2e import E2EResult, render_result, run_e2e_script


def _write_script(tmp_path: Path, *, name: str, body: str) -> str:
    """在 tmp_path 下落一个脚本，返回相对路径（worktree=tmp_path 时即 script_path）。"""
    script = tmp_path / name
    script.write_text(body, encoding="utf-8")
    return name


def test_run_exit_zero_is_passed(tmp_path):
    rel = _write_script(tmp_path, name="ok.sh", body="echo hello\nexit 0\n")
    result = run_e2e_script(worktree=tmp_path, script_path=rel, timeout_seconds=30, tail_lines=40)
    assert result.outcome == "passed"
    assert result.exit_code == 0
    assert result.timed_out is False
    assert "hello" in result.log_tail
    assert result.script_path == rel


def test_run_nonzero_is_failed_with_exit_code(tmp_path):
    rel = _write_script(tmp_path, name="bad.sh", body="echo boom >&2\nexit 3\n")
    result = run_e2e_script(worktree=tmp_path, script_path=rel, timeout_seconds=30, tail_lines=40)
    assert result.outcome == "failed"
    assert result.exit_code == 3
    assert result.timed_out is False
    # stderr 也被合并进日志末尾。
    assert "boom" in result.log_tail


def test_run_timeout_is_failed_and_timed_out(tmp_path):
    rel = _write_script(tmp_path, name="slow.sh", body="sleep 5\n")
    result = run_e2e_script(worktree=tmp_path, script_path=rel, timeout_seconds=1, tail_lines=40)
    assert result.outcome == "failed"
    assert result.timed_out is True
    assert result.exit_code is None


def test_run_missing_script_path_none_is_skipped(tmp_path):
    result = run_e2e_script(worktree=tmp_path, script_path=None, timeout_seconds=30, tail_lines=40)
    assert result.outcome == "skipped"
    assert result.exit_code is None
    assert result.script_path is None
    assert result.log_tail  # 降级提示非空


def test_run_nonexistent_file_is_skipped_without_subprocess(tmp_path):
    result = run_e2e_script(
        worktree=tmp_path, script_path="scripts/nope.sh", timeout_seconds=30, tail_lines=40
    )
    assert result.outcome == "skipped"
    assert result.exit_code is None
    # 文件不存在仍保留请求的 script_path 以便评论指明。
    assert result.script_path == "scripts/nope.sh"


def test_run_directory_is_skipped(tmp_path):
    (tmp_path / "scripts").mkdir()
    result = run_e2e_script(
        worktree=tmp_path, script_path="scripts", timeout_seconds=30, tail_lines=40
    )
    assert result.outcome == "skipped"


def test_run_tail_truncates_to_last_n_lines(tmp_path):
    rel = _write_script(tmp_path, name="many.sh", body="for i in $(seq 1 100); do echo L$i; done\n")
    result = run_e2e_script(worktree=tmp_path, script_path=rel, timeout_seconds=30, tail_lines=5)
    tail_lines = result.log_tail.splitlines()
    assert len(tail_lines) == 5
    assert tail_lines[-1] == "L100"
    assert tail_lines[0] == "L96"
    assert "L95" not in result.log_tail


def test_render_passed_shows_check_and_exit_code(tmp_path):
    result = E2EResult(
        outcome="passed",
        exit_code=0,
        script_path="scripts/x.sh",
        log_tail="all green",
        timed_out=False,
    )
    md = render_result(result=result, tail_lines=40)
    assert "## 端到端测试结果" in md
    assert "`bash scripts/x.sh`" in md
    assert "✅ 通过（退出码 0）" in md
    assert "all green" in md
    assert "最后 40 行" in md


def test_render_failed_shows_cross_and_exit_code():
    result = E2EResult(
        outcome="failed", exit_code=1, script_path="scripts/x.sh", log_tail="trace", timed_out=False
    )
    md = render_result(result=result, tail_lines=40)
    assert "❌ 失败（退出码 1）" in md


def test_render_timeout_shows_timeout_line():
    result = E2EResult(
        outcome="failed", exit_code=None, script_path="scripts/x.sh", log_tail="", timed_out=True
    )
    md = render_result(result=result, tail_lines=40)
    assert "❌ 超时" in md
    assert str(e2e.DEFAULT_TIMEOUT_SECONDS) in md


def test_render_skipped_shows_warning_and_rfc_pointer():
    result = E2EResult(
        outcome="skipped", exit_code=None, script_path=None, log_tail="见 RFC", timed_out=False
    )
    md = render_result(result=result, tail_lines=40)
    assert "⚠️ 跳过" in md
    assert "- 脚本：见 RFC「集成测试」段" in md


def test_module_defaults():
    assert e2e.DEFAULT_TIMEOUT_SECONDS == 600
    assert e2e.DEFAULT_TAIL_LINES == 40
