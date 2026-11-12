"""Spec graph test: Import image construction (including relative Import resolution), validation of docstring, rendering, etc.

2026-06-24 spec-markdown-form Requirements ①：ARCHITECTURE.md The only image of the code is ”the only image of the code” and it is the only image of the code that is the only one that can be shown in the world.
The import side cannot be missed. The focus is on the relative import (`from . import x`) in the normal module/package __init__
The resolution corrects the two sources (_absolute_from once off-by-one, missing the relative import side of the normal module).
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import graph


def _make_pkg(root: Path) -> Path:
    """A minimum package of pkg/ {__init__,a,b,sub/__init__,sub/c}.py is used for the drawing."""
    pkg = root / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""Example package."""\nfrom . import a\n', encoding="utf-8")
    # The normal module uses a relative import to draw the package of neighbours: from. import b->pkg.b.
    (pkg / "a.py").write_text('"""Module a."""\nfrom . import b\n', encoding="utf-8")
    (pkg / "b.py").write_text('"""Module b."""\n', encoding="utf-8")
    (pkg / "sub" / "__init__.py").write_text('"""Example subpackage."""\n', encoding="utf-8")
    # The subpackage module jumps `from .. import b` on a layer of pkg.b.
    (pkg / "sub" / "c.py").write_text('"""Module c."""\nfrom .. import b\n', encoding="utf-8")
    return pkg


def test_relative_import_from_regular_module_resolves_to_sibling(tmp_path: Path) -> None:
    """`from . import b` of the normal module pkg.a must be connected to pkg.b (cannot be missed)."""
    pkg = _make_pkg(tmp_path)
    _nodes, edges = graph.build_graph(package_root=pkg)
    assert ("pkg.a", "pkg.b") in edges


def test_relative_import_dotdot_from_subpackage(tmp_path: Path) -> None:
    """The `from .. import b` of the subpackage module pkg.sub.c must be connected to pkg.b."""
    pkg = _make_pkg(tmp_path)
    _nodes, edges = graph.build_graph(package_root=pkg)
    assert ("pkg.sub.c", "pkg.b") in edges


def test_package_init_relative_import_resolves_to_self_package(tmp_path: Path) -> None:
    """`from . import a` for __init__ packages uses its own pkg.a as the basis."""
    pkg = _make_pkg(tmp_path)
    _nodes, edges = graph.build_graph(package_root=pkg)
    assert ("pkg", "pkg.a") in edges


def test_absolute_from_levels() -> None:
    """Verify directly the resolution of _absolute_from under level 0 /1/2."""
    assert graph._absolute_from(module="x", level=0, src_package="pkg") == "x"
    # The list =1 is based on the package itself.
    assert graph._absolute_from(module="b", level=1, src_package="pkg") == "pkg.b"
    # Love = 2 jumps up.
    assert graph._absolute_from(module="b", level=2, src_package="pkg.sub") == "pkg.b"


def test_missing_docstrings_flags_files_without_docstring(tmp_path: Path) -> None:
    """The .py of missing file level docstring will be listed by missing_docstrings."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""pkg。"""\n', encoding="utf-8")
    (pkg / "ok.py").write_text('"""Documented module."""\n', encoding="utf-8")
    (pkg / "bad.py").write_text("x = 1\n", encoding="utf-8")
    missing = graph.missing_docstrings(package_root=pkg)
    assert str(pkg / "bad.py") in missing
    assert str(pkg / "ok.py") not in missing


def test_render_architecture_is_deterministic(tmp_path: Path) -> None:
    """render_architecture Pure function, Zirconium, etc.: Two retrospect bytes."""
    pkg = _make_pkg(tmp_path)
    assert graph.render_architecture(package_root=pkg) == graph.render_architecture(
        package_root=pkg
    )
