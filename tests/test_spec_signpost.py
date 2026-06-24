"""spec 端到端指路牌（signpost）单元测试 —— markdown 单文件形态（2026-06-24）。

覆盖：从 Task tests 字段抽脚本、渲染指路牌（有/无脚本）、组文件不存在返回 None。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Group, Metadata, Task
from openagents.spec.signpost import script_path_for_group, signpost_for_group


def _group(*, root: Path, tests: str) -> Path:
    group = Group(
        number="0008",
        metadata=Metadata(title="demo", issue=8, slug="demo"),
        tasks=[Task(id="T1", title="t", status="done", priority="P1", tests=tests)],
    )
    path = model.group_path(specs_root=root, number="0008", slug="demo")
    model.dump_group(group=group, path=path)
    return path


def test_script_path_extracted_from_tests(tmp_path: Path) -> None:
    path = _group(root=tmp_path, tests="离线跑 `scripts/e2e-demo.sh`（ruff + pytest）。")
    assert script_path_for_group(group_path=path) == "scripts/e2e-demo.sh"


def test_script_path_none_when_no_script(tmp_path: Path) -> None:
    path = _group(root=tmp_path, tests="纯手动验证，无脚本。")
    assert script_path_for_group(group_path=path) is None


def test_signpost_with_script_gives_run_command(tmp_path: Path) -> None:
    path = _group(root=tmp_path, tests="`scripts/e2e-demo.sh`")
    body = signpost_for_group(group_path=path)
    assert "## 端到端验证" in body
    assert "`bash scripts/e2e-demo.sh`" in body
    assert "docs/specs/0008-demo.md" in body


def test_signpost_without_script_points_to_group(tmp_path: Path) -> None:
    path = _group(root=tmp_path, tests="")
    body = signpost_for_group(group_path=path)
    assert "Spec-0008" in body
    assert "bash" not in body  # 无脚本不给 run 命令


def test_signpost_none_when_group_missing(tmp_path: Path) -> None:
    assert signpost_for_group(group_path=tmp_path / "nope.md") is None
    assert script_path_for_group(group_path=tmp_path / "nope.md") is None
