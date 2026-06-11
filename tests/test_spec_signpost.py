"""issue #53: spec 端到端指路牌（signpost）单元测试。

覆盖：从 Task tests 字段抽脚本、渲染指路牌（有/无脚本）、组不存在返回 None。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Task
from openagents.spec.signpost import script_path_for_group, signpost_for_group


def _group(*, root: Path, tests: str) -> Path:
    group_dir = root / "0008-demo"
    (group_dir / "tasks").mkdir(parents=True)
    (group_dir / "metadata.yaml").write_text(
        "title: demo\nissue: 8\nslug: demo\n", encoding="utf-8"
    )
    model.dump_task(
        task=Task(id="T1", title="t", status="done", priority="P1", tests=tests),
        path=group_dir / "tasks" / "T1.yaml",
    )
    return group_dir


def test_script_path_extracted_from_tests(tmp_path: Path) -> None:
    group_dir = _group(root=tmp_path, tests="离线跑 `scripts/e2e-demo.sh`（ruff + pytest）。")
    assert script_path_for_group(group_dir=group_dir) == "scripts/e2e-demo.sh"


def test_script_path_none_when_no_script(tmp_path: Path) -> None:
    group_dir = _group(root=tmp_path, tests="纯手动验证，无脚本。")
    assert script_path_for_group(group_dir=group_dir) is None


def test_signpost_with_script_gives_run_command(tmp_path: Path) -> None:
    group_dir = _group(root=tmp_path, tests="`scripts/e2e-demo.sh`")
    body = signpost_for_group(group_dir=group_dir)
    assert "## 端到端验证" in body
    assert "`bash scripts/e2e-demo.sh`" in body
    assert "docs/specs/0008-demo" in body


def test_signpost_without_script_points_to_group(tmp_path: Path) -> None:
    group_dir = _group(root=tmp_path, tests="")
    body = signpost_for_group(group_dir=group_dir)
    assert "Spec-0008" in body
    assert "bash" not in body  # 无脚本不给 run 命令


def test_signpost_none_when_group_missing(tmp_path: Path) -> None:
    assert signpost_for_group(group_dir=tmp_path / "nope") is None
    assert script_path_for_group(group_dir=tmp_path / "nope") is None
