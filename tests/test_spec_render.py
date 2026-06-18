"""Spec-0014/T3: spec render 单元测试。

覆盖：四块标题齐全、看板行数 = 当前版 Task 数、跨组 relates-to 虚线边、
演化图 v1→v2 边与 abandoned 节点着色、幂等（两次 render 字节级一致）、空仓库不报错。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import RelatesTo, Task
from openagents.spec.render import _BOARD_HEADING, _TLDR_HEADING, render, write_overview


def _write_group(
    *,
    root: Path,
    number: str,
    slug: str,
    issue: int,
    tasks: list[Task],
    summary: str = "人话 TL;DR",
) -> Path:
    # Spec-0015/T4：写组级 summary，供 TL;DR 顶部区块渲染。
    group_dir = root / f"{number}-{slug}"
    (group_dir / "tasks").mkdir(parents=True)
    (group_dir / "metadata.yaml").write_text(
        f'title: {slug} feature\nissue: {issue}\nslug: {slug}\nsummary: "{summary}"\n',
        encoding="utf-8",
    )
    for task in tasks:
        model.dump_task(task=task, path=group_dir / "tasks" / f"{task.id}.yaml")
    return group_dir


def _task(**overrides: object) -> Task:
    base: dict[str, object] = dict(id="T1", title="t", status="pending", priority="P1")
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


def test_four_blocks_present(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "## 全局看板" in text
    assert "## 跨 feature 关系图" in text
    assert "## 文件冲突报告" in text
    assert "## 各 feature 详情" in text


def test_board_row_count_equals_task_count(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["a.py"]), _task(id="T2", files=["b.py"])],
    )
    text = render(specs_root=tmp_path)
    # 看板数据行（| 0001 | 开头）应等于当前版 Task 数。
    rows = [ln for ln in text.splitlines() if ln.startswith("| 0001 |")]
    assert len(rows) == 2


def test_idempotent(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(id="T1", files=["a.py"]),
            _task(id="T2", depends_on=["T1"], files=["b.py"]),
        ],
    )
    assert render(specs_root=tmp_path) == render(specs_root=tmp_path)


def test_cross_group_relates_to_dashed_edge(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(
                id="T1",
                files=["a.py"],
                relates_to=[RelatesTo(ref="0002/T1", type="extends")],
            )
        ],
    )
    _write_group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["b.py"])]
    )
    text = render(specs_root=tmp_path)
    # 虚线边带 type 标注。
    assert "-.extends.->" in text


def test_evolution_graph_versions_and_abandoned_color(tmp_path: Path) -> None:
    group_dir = _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", version=2, files=["a.py"])],
    )
    (group_dir / "history").mkdir()
    # T1 历史 v1；另一个被废弃的 task T9（仅在历史，末态 abandoned）。
    model.dump_history(
        versions=[_task(id="T1", status="done", version=1)],
        path=group_dir / "history" / "T1.yaml",
    )
    model.dump_history(
        versions=[_task(id="T9", status="abandoned", version=1)],
        path=group_dir / "history" / "T9.yaml",
    )
    text = render(specs_root=tmp_path)
    # T1 的 v1→v2 redefined 边。
    assert "redefined" in text
    assert "v_T1_1" in text and "v_T1_2" in text
    # abandoned 节点参与着色。
    assert "classDef st_abandoned" in text
    assert "v_T9_1" in text


def test_file_conflict_reported(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["x.py"])]
    )
    _write_group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["x.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "x.py" in text.split("## 文件冲突报告")[1].split("## 各 feature")[0]


def test_tldr_block_before_board(tmp_path: Path) -> None:
    """Spec-0015/T4：TL;DR 区块存在且位于全局看板之前。"""
    _write_group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    text = render(specs_root=tmp_path)
    assert _TLDR_HEADING in text
    assert text.index(_TLDR_HEADING) < text.index(_BOARD_HEADING)


def test_tldr_contains_each_feature_summary(tmp_path: Path) -> None:
    """Spec-0015/T4：每个 feature 的 summary 文本出现在 TL;DR 区块内。"""
    _write_group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["a.py"])],
        summary="阿尔法在干这个",
    )
    _write_group(
        root=tmp_path,
        number="0002",
        slug="beta",
        issue=2,
        tasks=[_task(id="T1", files=["b.py"])],
        summary="贝塔在干那个",
    )
    text = render(specs_root=tmp_path)
    tldr_block = text.split(_TLDR_HEADING)[1].split(_BOARD_HEADING)[0]
    assert "阿尔法在干这个" in tldr_block
    assert "贝塔在干那个" in tldr_block


def test_empty_root_does_not_error(tmp_path: Path) -> None:
    text = render(specs_root=tmp_path)
    assert "## 全局看板" in text
    assert "无跨组文件冲突" in text
    # Spec-0015/T4：空仓库仍含 TL;DR 标题骨架。
    assert _TLDR_HEADING in text


def test_write_overview_writes_file(tmp_path: Path) -> None:
    _write_group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    path = write_overview(specs_root=tmp_path)
    assert path == tmp_path / "OVERVIEW.md"
    assert path.read_text(encoding="utf-8") == render(specs_root=tmp_path)
