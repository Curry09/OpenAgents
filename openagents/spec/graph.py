"""spec graph：从代码生成「对代码的唯一映射」（现状架构视图）。

2026-06-24 spec-markdown-form 需求①：代码本身是唯一真源。用标准库 `ast` 扫项目内 `.py`，
按 import 连边（文件 = 节点，import = 有向边，只连项目内文件、忽略标准库/第三方），再叠加
**注释规范**——每个 `.py` 的**文件级 docstring**（本文件负责什么）、每个包 `__init__.py` 的
**模块级 docstring**（本子系统整体做什么）。三者合起来即可还原整个架构。

刻意保持最轻（理念 1 奥卡姆）：不引入 PageRank / tree-sitter / 图库 / Neo4j（那些是给
「运行时把上下文挤进 prompt 预算」用的，静态文档不需要）。
"""

from __future__ import annotations

import ast
from pathlib import Path

# 生成物文件名（CI drift-check 对象）。
ARCHITECTURE_FILENAME = "ARCHITECTURE.md"

_HEADING = "# 架构现状（ARCHITECTURE）"


def iter_py_files(*, package_root: Path) -> list[Path]:
    """package_root 下全部 .py（排序，跳过 __pycache__）。"""
    return sorted(path for path in package_root.rglob("*.py") if "__pycache__" not in path.parts)


def module_name(*, path: Path, top_parent: Path) -> str:
    """文件路径 → 点分模块名（相对 top_parent），__init__ 归到所在包。"""
    parts = list(path.relative_to(top_parent).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def build_graph(*, package_root: Path) -> tuple[dict[str, Path], list[tuple[str, str]]]:
    """构图：返回 (模块名→文件路径, 边列表[(src_module, dst_module)])。

    只连「项目内文件之间」的 import；指向标准库/第三方/不存在模块的忽略。
    """
    top_parent = package_root.parent
    nodes: dict[str, Path] = {}
    for path in iter_py_files(package_root=package_root):
        nodes[module_name(path=path, top_parent=top_parent)] = path

    edges: set[tuple[str, str]] = set()
    for src_module, path in nodes.items():
        for target in _imported_modules(path=path, src_module=src_module):
            dst = _resolve_to_node(target=target, nodes=nodes)
            if dst is not None and dst != src_module:
                edges.add((src_module, dst))
    return nodes, sorted(edges)


def missing_docstrings(*, package_root: Path) -> list[str]:
    """返回缺 docstring 的文件路径（文件级 + 包级 __init__）。注释规范的硬校验。"""
    missing: list[str] = []
    for path in iter_py_files(package_root=package_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        if not (ast.get_docstring(tree) or "").strip():
            missing.append(str(path))
    return missing


def render_architecture(*, package_root: Path) -> str:
    """渲染 ARCHITECTURE.md 全文（纯函数、幂等）：子系统 → 组件 → import 关系图。"""
    nodes, edges = build_graph(package_root=package_root)
    top_parent = package_root.parent

    blocks = [
        _HEADING,
        f"> 本文件由 `spec graph` 自动生成，请勿手工编辑。源 = `{package_root}/` 的代码与 docstring。",
        _render_subsystems(package_root=package_root, top_parent=top_parent),
        _render_relation_graph(nodes=nodes, edges=edges),
    ]
    return "\n\n".join(blocks).rstrip("\n") + "\n"


def write_architecture(*, specs_root: Path, package_root: Path) -> Path:
    """render + 落盘 specs_root/ARCHITECTURE.md，返回路径。"""
    path = specs_root / ARCHITECTURE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_architecture(package_root=package_root), encoding="utf-8")
    return path


def _render_subsystems(*, package_root: Path, top_parent: Path) -> str:
    """每个包（含 __init__）= 一个子系统段：模块级 docstring + 各文件的文件级 docstring。"""
    lines = ["## 子系统与组件"]
    # 包目录（含 __init__.py），按路径排序。
    packages = sorted({path.parent for path in iter_py_files(package_root=package_root)})
    for pkg_dir in packages:
        pkg_name = module_name(path=pkg_dir / "__init__.py", top_parent=top_parent) or "(root)"
        init_path = pkg_dir / "__init__.py"
        pkg_doc = _first_line(path=init_path) if init_path.is_file() else ""
        lines.append("")
        lines.append(f"### {pkg_name}")
        lines.append("")
        lines.append(f"_{pkg_doc or '（缺模块级 docstring）'}_")
        lines.append("")
        lines.append("| 组件 | 职责（文件级 docstring 首行） |")
        lines.append("|----|----|")
        files = sorted(
            path
            for path in package_root.rglob("*.py")
            if path.parent == pkg_dir and "__pycache__" not in path.parts
        )
        for path in files:
            doc = _first_line(path=path) or "（缺文件级 docstring）"
            lines.append(f"| `{path.name}` | {_cell(doc)} |")
    return "\n".join(lines)


def _render_relation_graph(*, nodes: dict[str, Path], edges: list[tuple[str, str]]) -> str:
    """import 关系图（Mermaid）：节点 = 模块短名，边 = import。"""
    lines = ["## 依赖关系图（import）", "", "```mermaid", "graph LR"]
    for module in sorted(nodes):
        lines.append(f'    {_node(module)}["{_short(module)}"]')
    for src, dst in edges:
        lines.append(f"    {_node(src)} --> {_node(dst)}")
    lines.append("```")
    return "\n".join(lines)


def _imported_modules(*, path: Path, src_module: str) -> list[str]:
    """解析文件里的 import 目标模块名（含相对 import 解析为绝对）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_from(module=node.module, level=node.level, src_module=src_module)
            if base is None:
                continue
            # from base import X → 候选 base.X（子模块）与 base 本身。
            for alias in node.names:
                targets.append(f"{base}.{alias.name}" if base else alias.name)
            if base:
                targets.append(base)
    return targets


def _absolute_from(*, module: str | None, level: int, src_module: str) -> str | None:
    """把 `from . / .. import` 的相对模块解析为绝对点分名。"""
    if level == 0:
        return module
    parts = src_module.split(".")
    # level=1 指当前包；level=2 指上一层。src_module 已是去掉 __init__ 的模块名。
    base = parts[: len(parts) - level + 1] if len(parts) >= level else []
    if module:
        base = [*base, *module.split(".")]
    return ".".join(base) if base else None


def _resolve_to_node(*, target: str, nodes: dict[str, Path]) -> str | None:
    """把 import 目标解析到已知节点：精确命中，或回退到其最长已知前缀（包）。"""
    if target in nodes:
        return target
    parts = target.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:cut])
        if candidate in nodes:
            return candidate
    return None


def _first_line(*, path: Path) -> str:
    """文件的 docstring 首行（去空白）；无则空串。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return ""
    doc = (ast.get_docstring(tree) or "").strip()
    return doc.split("\n", 1)[0].strip() if doc else ""


def _node(module: str) -> str:
    """模块名 → 合法 Mermaid 节点名。"""
    return "n" + "".join(ch if ch.isalnum() else "_" for ch in module)


def _short(module: str) -> str:
    """节点 label：取末两段，省略冗长前缀。"""
    return ".".join(module.split(".")[-2:])


def _cell(text: str) -> str:
    """表格单元：压单行、转义竖线。"""
    return text.replace("\n", " ").replace("|", "\\|")
