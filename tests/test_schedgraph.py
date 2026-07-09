"""Spec-0058/T3：DAG 渲图 schedgraph 的单元测试（hermetic，注入 run）。

覆盖：build_dot 产出含各节点 + 下游←上游有向边 + 波次分层的合法 DOT、closed 上游不入图；render 在
注入 run 成功（并真写出 png）时返回 dag.png；注入 run 抛 FileNotFoundError / 非 0 / 异常时降级写
dag.dot 返回其路径且不上抛（本机无 graphviz 常态路径）。
"""

import subprocess

from openagents.schedgraph import build_dot, render
from openagents.scheduler import DepEdge


def _edges():
    # #150 -> #137 -> #170：两跳链，波次 0/1/2。
    return [
        DepEdge(downstream=137, upstream=150, kind="file-conflict", reason="x"),
        DepEdge(downstream=170, upstream=137, kind="logical", reason="y"),
    ]


# --------------------------------------------------------------------------- #
# build_dot
# --------------------------------------------------------------------------- #


def test_build_dot_contains_nodes_edges_and_waves():
    dot = build_dot(edges=_edges(), open_issue_numbers={137, 150, 170})
    assert dot.startswith("digraph schedule {")
    # 各 issue 节点。
    assert '"#150"' in dot and '"#137"' in dot and '"#170"' in dot
    # 下游←上游有向边（上游 -> 下游）。
    assert '"#150" -> "#137"' in dot
    assert '"#137" -> "#170"' in dot
    # 波次分层：#150 wave 0、#137 wave 1、#170 wave 2。
    assert "#150\\n(wave 0)" in dot
    assert "#137\\n(wave 1)" in dot
    assert "#170\\n(wave 2)" in dot


def test_build_dot_excludes_closed_upstream():
    # 上游 #150 已 closed（不在 open 集）→ 那条边不入图，#150 节点不出现。
    dot = build_dot(edges=_edges(), open_issue_numbers={137, 170})
    assert '"#150"' not in dot
    assert '"#150" -> "#137"' not in dot
    # #137 -> #170 仍在。
    assert '"#137" -> "#170"' in dot


def test_build_dot_empty_edges_is_valid_empty_graph():
    dot = build_dot(edges=[], open_issue_numbers=set())
    assert dot.startswith("digraph schedule {")
    assert dot.rstrip().endswith("}")


# --------------------------------------------------------------------------- #
# render —— happy path（注入 run 真写出 png）
# --------------------------------------------------------------------------- #


def test_render_returns_png_when_dot_succeeds(tmp_path):
    def fake_run(*, args):
        # args = ["dot", "-Tpng", <dot>, "-o", <png>]；模拟 graphviz 真写出 png。
        png = args[args.index("-o") + 1]
        from pathlib import Path

        Path(png).write_bytes(b"\x89PNG fake")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    out = render(edges=_edges(), open_issue_numbers={137, 150, 170}, out_dir=tmp_path, run=fake_run)
    assert out.name == "dag.png"
    assert out.exists()
    # .dot 也一并写下（源文本产物）。
    assert (tmp_path / "dag.dot").exists()


# --------------------------------------------------------------------------- #
# render —— 安全降级
# --------------------------------------------------------------------------- #


def test_render_degrades_to_dot_when_dot_missing(tmp_path):
    def missing_run(*, args):
        raise FileNotFoundError("dot not found")

    out = render(
        edges=_edges(), open_issue_numbers={137, 150, 170}, out_dir=tmp_path, run=missing_run
    )
    assert out.name == "dag.dot"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert '"#150" -> "#137"' in text


def test_render_degrades_to_dot_on_nonzero(tmp_path):
    def failing_run(*, args):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="boom")

    out = render(
        edges=_edges(), open_issue_numbers={137, 150, 170}, out_dir=tmp_path, run=failing_run
    )
    assert out.name == "dag.dot"
    assert out.exists()


def test_render_degrades_to_dot_on_exception(tmp_path):
    def boom_run(*, args):
        raise RuntimeError("unexpected")

    out = render(edges=_edges(), open_issue_numbers={137, 150, 170}, out_dir=tmp_path, run=boom_run)
    assert out.name == "dag.dot"
    assert out.exists()
