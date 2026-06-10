"""Spec-0014/T6: migrate-rfc-to-spec 单元测试。

用真实 RFC 跑迁移，断言：产出通过 spec validate、Task 数 = 子任务表行数、
implemented→done、blocked→pending、version=1 且 history 初始为空；
全部真实 RFC 迁移后 validate 全绿（仅 warning）且 render 幂等。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from openagents.spec import model
from openagents.spec.render import render
from openagents.spec.validate import validate

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RFCS_DIR = _REPO_ROOT / "docs" / "rfcs"


def _load_migrate():
    path = _REPO_ROOT / "scripts" / "migrate-rfc-to-spec.py"
    spec = importlib.util.spec_from_file_location("migrate_rfc_to_spec", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _count_table_rows(*, rfc_path: Path) -> int:
    """数 RFC 子任务表的数据行（| T<n> | 开头）。"""
    count = 0
    for line in rfc_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped[1:].lstrip().startswith("T"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) >= 5 and cells[0][1:2].isdigit():
                count += 1
    return count


def test_migrate_single_rfc_passes_validate(tmp_path: Path) -> None:
    mod = _load_migrate()
    rfc = _RFCS_DIR / "0008-pr-e2e-signpost.md"
    group_dir = mod.migrate_rfc(rfc_path=rfc, specs_root=tmp_path)

    # Task 数 = 子任务表行数。
    group = model.load_group(group_dir=group_dir)
    assert len(group.tasks) == _count_table_rows(rfc_path=rfc)

    # 该 RFC 全部 implemented → done。
    assert all(task.status == "done" for task in group.tasks)
    # version=1，history 初始为空。
    assert all(task.version == 1 for task in group.tasks)
    assert group.history == {}
    # origin.md 写入、metadata 正确。
    assert (group_dir / "origin.md").is_file()
    assert group.metadata.slug == "pr-e2e-signpost"

    # 单组 validate 通过。
    assert validate(specs_root=tmp_path).ok is True


def test_status_and_dependency_mapping(tmp_path: Path) -> None:
    """构造一份含 blocked 状态与 RFC 级依赖的迷你 RFC，断言映射。"""
    mod = _load_migrate()
    rfc = tmp_path / "0099-demo.md"
    rfc.write_text(
        "# RFC-0099: demo\n"
        "- **优先级**: P2\n"
        "- **标签**: `cli`, `dx`\n"
        "- **负责人**: openagents (agent: issue-77)\n\n"
        "## 实现计划\n\n"
        "| ID | 标题 | 依赖 | 涉及文件 | 状态 |\n"
        "|----|----|----|----|----|\n"
        "| T1 | 基础 | RFC-0001 | `a.py` | implemented |\n"
        "| T2 | 后续 | T1 | `b.py` | blocked |\n",
        encoding="utf-8",
    )
    specs_root = tmp_path / "specs"
    group_dir = mod.migrate_rfc(rfc_path=rfc, specs_root=specs_root)
    group = model.load_group(group_dir=group_dir)

    by_id = {t.id: t for t in group.tasks}
    assert by_id["T1"].status == "done"
    assert by_id["T2"].status == "pending"  # blocked → pending
    # RFC-0001 整 RFC 级依赖被丢弃；T1 的 depends-on 为空。
    assert by_id["T1"].depends_on == []
    assert by_id["T2"].depends_on == ["T1"]
    # 头部元数据。
    assert by_id["T1"].priority == "P2"
    assert by_id["T1"].tags == ["cli", "dx"]
    assert group.metadata.issue == 77


def test_intra_group_files_disjoint_after_migration(tmp_path: Path) -> None:
    """历史 RFC 中多子任务共用文件，迁移后同组 files 不重叠（首个占用）。"""
    mod = _load_migrate()
    # 0003 的 T1/T2/T3 都列了 orchestrator.py。
    group_dir = mod.migrate_rfc(
        rfc_path=_RFCS_DIR / "0003-issue-worktree-isolation.md", specs_root=tmp_path
    )
    group = model.load_group(group_dir=group_dir)
    all_files = [f for task in group.tasks for f in task.files]
    assert len(all_files) == len(set(all_files))  # 无重复
    assert validate(specs_root=tmp_path).ok is True


def test_migrate_all_real_rfcs_validate_and_idempotent(tmp_path: Path) -> None:
    mod = _load_migrate()
    mod.migrate_all(rfcs_dir=_RFCS_DIR, specs_root=tmp_path)

    # 全部真实 RFC 迁移后 validate 无 error（仅跨组文件 warning）。
    report = validate(specs_root=tmp_path)
    assert report.ok is True
    assert all(i.level == "warning" for i in report.issues)

    # render 幂等（两次字节级一致）。
    assert render(specs_root=tmp_path) == render(specs_root=tmp_path)
