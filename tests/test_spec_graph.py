"""spec graph 测试：import 图构建（含相对 import 解析）、docstring 校验、渲染幂等。

2026-06-24 spec-markdown-form 需求①：ARCHITECTURE.md 是「对代码的唯一映射」，
import 边不能漏。这里重点锁住相对 import（`from . import x`）在普通模块/包 __init__
两种来源下的解析正确性（_absolute_from 曾 off-by-one，漏掉普通模块的相对 import 边）。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import graph


def _make_pkg(root: Path) -> Path:
    """搭一个最小包 pkg/{__init__,a,b,sub/__init__,sub/c}.py 用于构图。"""
    pkg = root / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""pkg 顶层。"""\nfrom . import a\n', encoding="utf-8")
    # 普通模块用相对 import 引同包邻居：from . import b -> pkg.b。
    (pkg / "a.py").write_text('"""a 模块。"""\nfrom . import b\n', encoding="utf-8")
    (pkg / "b.py").write_text('"""b 模块。"""\n', encoding="utf-8")
    (pkg / "sub" / "__init__.py").write_text('"""sub 子包。"""\n', encoding="utf-8")
    # 子包模块用 `from .. import b` 上跳一层引 pkg.b。
    (pkg / "sub" / "c.py").write_text('"""c 模块。"""\nfrom .. import b\n', encoding="utf-8")
    return pkg


def test_relative_import_from_regular_module_resolves_to_sibling(tmp_path: Path) -> None:
    """普通模块 pkg.a 的 `from . import b` 必须连到 pkg.b（不能漏边）。"""
    pkg = _make_pkg(tmp_path)
    _nodes, edges = graph.build_graph(package_root=pkg)
    assert ("pkg.a", "pkg.b") in edges


def test_relative_import_dotdot_from_subpackage(tmp_path: Path) -> None:
    """子包模块 pkg.sub.c 的 `from .. import b` 必须连到 pkg.b。"""
    pkg = _make_pkg(tmp_path)
    _nodes, edges = graph.build_graph(package_root=pkg)
    assert ("pkg.sub.c", "pkg.b") in edges


def test_package_init_relative_import_resolves_to_self_package(tmp_path: Path) -> None:
    """包 __init__ 的 `from . import a` 以包自身为基准 → pkg.a。"""
    pkg = _make_pkg(tmp_path)
    _nodes, edges = graph.build_graph(package_root=pkg)
    assert ("pkg", "pkg.a") in edges


def test_absolute_from_levels() -> None:
    """直接验证 _absolute_from 在 level 0/1/2 下的解析。"""
    assert graph._absolute_from(module="x", level=0, src_package="pkg") == "x"
    # level=1 以所在包自身为基准。
    assert graph._absolute_from(module="b", level=1, src_package="pkg") == "pkg.b"
    # level=2 上跳一层。
    assert graph._absolute_from(module="b", level=2, src_package="pkg.sub") == "pkg.b"


def test_missing_docstrings_flags_files_without_docstring(tmp_path: Path) -> None:
    """缺文件级 docstring 的 .py 会被 missing_docstrings 列出。"""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""pkg。"""\n', encoding="utf-8")
    (pkg / "ok.py").write_text('"""有 docstring。"""\n', encoding="utf-8")
    (pkg / "bad.py").write_text("x = 1\n", encoding="utf-8")
    missing = graph.missing_docstrings(package_root=pkg)
    assert str(pkg / "bad.py") in missing
    assert str(pkg / "ok.py") not in missing


def test_render_architecture_is_deterministic(tmp_path: Path) -> None:
    """render_architecture 纯函数、幂等：两次渲染字节级一致。"""
    pkg = _make_pkg(tmp_path)
    assert graph.render_architecture(package_root=pkg) == graph.render_architecture(
        package_root=pkg
    )
