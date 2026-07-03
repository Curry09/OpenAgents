"""spec render 单元测试 —— markdown 单文件形态（2026-06-24）。

覆盖：四块标题齐全、看板行数 = 当前版 Task 数、跨组 relates-to 虚线边、当前版节点按 status
着色、文件冲突报告、幂等（两次 render 字节级一致）、空仓库不报错。history 机制已退役，
演化图退化为各 Task 单版本节点。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import E2EPlan, Group, Metadata, RelatesTo, Task
from openagents.spec.render import render, write_overview


def _group(*, root: Path, number: str, slug: str, issue: int, tasks: list[Task]) -> Path:
    group = Group(
        number=number,
        metadata=Metadata(title=f"{slug} feature", issue=issue, slug=slug, summary=f"{slug} 人话"),
        tasks=tasks,
    )
    path = model.group_path(specs_root=root, number=number, slug=slug)
    model.dump_group(group=group, path=path)
    return path


def _task(**overrides: object) -> Task:
    base: dict[str, object] = dict(id="T1", title="t", status="pending", priority="P1")
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


def test_four_blocks_present(tmp_path: Path) -> None:
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "## 全局看板" in text
    assert "## 跨 feature 关系图" in text
    assert "## 文件冲突报告" in text
    assert "## 各 feature 详情" in text


def test_tldr_block_shows_group_summary(tmp_path: Path) -> None:
    """Spec-0015/T4：OVERVIEW 顶部 TL;DR 逐 feature 展示 summary。"""
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "## TL;DR" in text
    assert "alpha 人话" in text


def test_board_row_count_equals_task_count(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["a.py"]), _task(id="T2", files=["b.py"])],
    )
    text = render(specs_root=tmp_path)
    rows = [ln for ln in text.splitlines() if ln.startswith("| 0001 |")]
    assert len(rows) == 2


def test_idempotent(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", files=["a.py"]), _task(id="T2", depends_on=["T1"], files=["b.py"])],
    )
    assert render(specs_root=tmp_path) == render(specs_root=tmp_path)


def test_cross_group_relates_to_dashed_edge(tmp_path: Path) -> None:
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[
            _task(id="T1", files=["a.py"], relates_to=[RelatesTo(ref="0002/T1", type="extends")])
        ],
    )
    _group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["b.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "-.extends.->" in text


def test_evolution_graph_colors_current_status(tmp_path: Path) -> None:
    """history 退役后，演化图呈现各 Task 当前单版本节点并按 status 着色。"""
    _group(
        root=tmp_path,
        number="0001",
        slug="alpha",
        issue=1,
        tasks=[_task(id="T1", status="done", files=["a.py"])],
    )
    text = render(specs_root=tmp_path)
    assert "v_T1_1" in text
    assert "classDef st_done" in text


def test_file_conflict_reported(tmp_path: Path) -> None:
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["x.py"])]
    )
    _group(
        root=tmp_path, number="0002", slug="beta", issue=2, tasks=[_task(id="T1", files=["x.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "x.py" in text.split("## 文件冲突报告")[1].split("## 各 feature")[0]


def test_empty_root_does_not_error(tmp_path: Path) -> None:
    text = render(specs_root=tmp_path)
    assert "## 全局看板" in text
    assert "无跨组文件冲突" in text


def test_e2e_plan_rendered_in_tldr(tmp_path: Path) -> None:
    """Spec-0040/T1：声明 e2e 粗规划的组，OVERVIEW 的 TL;DR 显示意图 + 验收行为。"""
    group = Group(
        number="0001",
        metadata=Metadata(
            title="alpha feature",
            issue=1,
            slug="alpha",
            summary="alpha 人话",
            e2e=E2EPlan(
                form="cli",
                intent="init 无 origin 必须显式失败",
                acceptance=["非零退出 + 提示", "补 origin 再跑成功"],
            ),
        ),
        tasks=[_task(id="T1", files=["a.py"])],
    )
    path = model.group_path(specs_root=tmp_path, number="0001", slug="alpha")
    model.dump_group(group=group, path=path)
    text = render(specs_root=tmp_path)
    assert "e2e 粗规划（cli）" in text
    assert "init 无 origin 必须显式失败" in text
    assert "非零退出 + 提示" in text
    assert "补 origin 再跑成功" in text


def test_no_e2e_plan_omits_block(tmp_path: Path) -> None:
    """未声明 e2e 的组：OVERVIEW 不出现 e2e 粗规划行（零回归）。"""
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    text = render(specs_root=tmp_path)
    assert "e2e 粗规划" not in text


def test_write_overview_writes_file(tmp_path: Path) -> None:
    _group(
        root=tmp_path, number="0001", slug="alpha", issue=1, tasks=[_task(id="T1", files=["a.py"])]
    )
    path = write_overview(specs_root=tmp_path)
    assert path == tmp_path / "OVERVIEW.md"
    assert path.read_text(encoding="utf-8") == render(specs_root=tmp_path)
