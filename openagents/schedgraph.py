"""Spec-0058/T3：跨 issue DAG 渲图（best-effort，注入 run + 安全降级）——标签真值 → DOT → graphviz PNG。

把标签真值（边集）渲成一张本地 DAG 拓扑图，一眼看清波次与并行面（未来前端排程面板的数据底座，
理念 8）。镜像 conflictdiag.py 的「注入 run + 全程安全降级」形态：

- build_dot：纯函数，由边集构 DOT（按拓扑分层标注 / 着色波次，closed 上游不入图）。
- render：写 `.dot` 文本后经注入 run 调 `dot -Tpng` 出 `dag.png` 返回其路径；`dot` 缺失
  （FileNotFoundError）/ 非 0 / 任何异常 → **吞异常、退回写 `dag.dot` 文本**并返回其路径，绝不上抛
  （本机实测无 graphviz，降级路径是常态而非边角，见 spec Reference-level「渲图」）。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from openagents.scheduler import DepEdge

# Spec-0058/T3：波次配色——按拓扑波次循环取色（波次多于色数时回绕，仅为可视区分、非语义）。
_WAVE_COLORS = (
    "#e8f0fe",
    "#e6f4ea",
    "#fef7e0",
    "#fce8e6",
    "#f3e8fd",
    "#e0f7fa",
)

# Spec-0058/T3：波次计算的迭代上限——防 agent 幻觉出的环导致最长路径松弛不收敛（build_dot 绝不失败）。
_MAX_WAVE_ITERS = 64

# Spec-0058/T3：产物文件名（单一来源，供 render 与调用方对齐）。
_PNG_NAME = "dag.png"
_DOT_NAME = "dag.dot"


def build_dot(*, edges: Iterable[DepEdge], open_issue_numbers: set[int]) -> str:
    """Spec-0058/T3：由边集构 DOT（按波次分层着色，closed 上游 / 下游不入图）；纯函数、不失败。

    只保留两端都在 open 集内的边（closed 的上游 / 下游已满足或已完成，不入图，见 spec 满足判定）。
    节点 = 保留边的两端并集；每个节点标注其波次（拓扑最长路径层，无上游者波 0），按波次着色。
    有向边渲成 `"#<上游>" -> "#<下游>"`（上游先做、指向下游）并标注 kind。无任何边 → 空图占位。
    """
    kept = [
        edge
        for edge in edges
        if edge.upstream in open_issue_numbers and edge.downstream in open_issue_numbers
    ]
    nodes = _nodes(edges=kept)
    waves = _waves(nodes=nodes, edges=kept)

    lines = ["digraph schedule {", "  rankdir=LR;", "  node [shape=box, style=filled];"]
    for node in sorted(nodes):
        wave = waves.get(node, 0)
        color = _WAVE_COLORS[wave % len(_WAVE_COLORS)]
        lines.append(f'  "#{node}" [label="#{node}\\n(wave {wave})", fillcolor="{color}"];')
    for edge in kept:
        lines.append(f'  "#{edge.upstream}" -> "#{edge.downstream}" [label="{edge.kind}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render(
    *,
    edges: Iterable[DepEdge],
    open_issue_numbers: set[int],
    out_dir: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> Path:
    """Spec-0058/T3：写 `.dot` 后经注入 run 调 `dot -Tpng` 出 dag.png；失败降级写 dag.dot，绝不上抛。

    run 签名 `run(*, args: list[str]) -> CompletedProcess`（args 含 "dot" 前缀，与 conflictdiag 注入
    风格一致）。流程：写 dag.dot 文本 → 调 `dot -Tpng dag.dot -o dag.png` → returncode 0 且 png 存在
    则返回 dag.png 路径；`dot` 缺失（FileNotFoundError）/ 非 0 / 任何异常 → 吞掉、退回 dag.dot 路径
    （本机无 graphviz 为常态路径）。out_dir 不存在则创建（唯一副作用是写产物文件，绝不抛给上层）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dot_path = out_dir / _DOT_NAME
    png_path = out_dir / _PNG_NAME
    dot_text = build_dot(edges=edges, open_issue_numbers=open_issue_numbers)
    dot_path.write_text(dot_text, encoding="utf-8")
    try:
        proc = run(args=["dot", "-Tpng", str(dot_path), "-o", str(png_path)])
    except Exception:  # noqa: BLE001 — 安全降级：dot 缺失 / 任何异常都退回 .dot，绝不上抛
        return dot_path
    if getattr(proc, "returncode", 1) == 0 and png_path.exists():
        return png_path
    # 非 0 退出 / png 未生成 → 降级为 .dot 文本产物（已写好）。
    return dot_path


def _nodes(*, edges: list[DepEdge]) -> set[int]:
    """保留边两端并集即图中节点集。"""
    nodes: set[int] = set()
    for edge in edges:
        nodes.add(edge.upstream)
        nodes.add(edge.downstream)
    return nodes


def _waves(*, nodes: set[int], edges: list[DepEdge]) -> dict[int, int]:
    """Spec-0058/T3：拓扑最长路径层（波次）——无上游者波 0，其余 = max(上游波)+1；有环时有界松弛止损。

    松弛式最长路径：反复用「下游波 ≥ 上游波 + 1」更新，直到不再变化或达 _MAX_WAVE_ITERS（防环不收敛，
    build_dot 绝不失败）。上游→下游邻接由保留边给出。
    """
    wave = {node: 0 for node in nodes}
    for _ in range(_MAX_WAVE_ITERS):
        changed = False
        for edge in edges:
            candidate = wave.get(edge.upstream, 0) + 1
            if candidate > wave.get(edge.downstream, 0):
                wave[edge.downstream] = candidate
                changed = True
        if not changed:
            break
    return wave
