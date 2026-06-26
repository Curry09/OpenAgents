"""Spec-0025/T1: 代码盘点助手 backfill.inventory / slug_for 的单元测试。

纯函数、只读文件系统——用 tmp_path 造存量代码样例，覆盖单文件 / 目录两种形态、
公开符号抽取、docstring 抽取、坏文件降级，以及路径不存在 / 空目录抛错。
"""

import pytest

from openagents.backfill import BackfillError, inventory, slug_for


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# inventory：单文件形态
# --------------------------------------------------------------------------- #


def test_inventory_single_file_returns_one_module(tmp_path):
    mod = tmp_path / "release.py"
    _write(
        mod,
        '"""模块说明：发版逻辑。"""\n\n\ndef release():\n    pass\n\n\nclass Releaser:\n    pass\n',
    )

    inv = inventory(path=mod)

    assert inv.single_file is True
    assert len(inv.modules) == 1
    m = inv.modules[0]
    assert m.path == "release.py"
    assert m.docstring == "模块说明：发版逻辑。"
    # 顶层公开 def / class 都进符号；保序。
    assert m.symbols == ("release", "Releaser")


def test_inventory_single_non_py_file_raises(tmp_path):
    f = tmp_path / "README.md"
    _write(f, "# not python")
    with pytest.raises(BackfillError):
        inventory(path=f)


# --------------------------------------------------------------------------- #
# inventory：目录形态
# --------------------------------------------------------------------------- #


def test_inventory_directory_collects_py_files_sorted(tmp_path):
    pkg = tmp_path / "pkg"
    _write(pkg / "a.py", '"""a 模块。"""\n\n\ndef alpha():\n    pass\n')
    _write(pkg / "sub" / "b.py", "class Beta:\n    pass\n")
    # 非 .py 文件不计入。
    _write(pkg / "notes.txt", "ignore me")

    inv = inventory(path=pkg)

    assert inv.single_file is False
    paths = [m.path for m in inv.modules]
    # 递归收集且按相对路径字典序。
    assert paths == ["a.py", "sub/b.py"]
    assert inv.modules[0].symbols == ("alpha",)
    assert inv.modules[1].symbols == ("Beta",)
    assert inv.modules[1].docstring is None


def test_inventory_excludes_private_and_dunder_symbols(tmp_path):
    mod = tmp_path / "m.py"
    _write(
        mod,
        "def public():\n    pass\n\n\ndef _private():\n    pass\n\n\nasync def afetch():\n    pass\n",
    )

    inv = inventory(path=mod)

    assert inv.modules[0].symbols == ("public", "afetch")


def test_inventory_bad_syntax_file_degrades_not_raises(tmp_path):
    pkg = tmp_path / "pkg"
    _write(pkg / "good.py", "def ok():\n    pass\n")
    _write(pkg / "broken.py", "def (((:\n")  # 语法错误

    inv = inventory(path=pkg)

    broken = next(m for m in inv.modules if m.path == "broken.py")
    assert broken.symbols == ()
    assert broken.docstring is None
    good = next(m for m in inv.modules if m.path == "good.py")
    assert good.symbols == ("ok",)


# --------------------------------------------------------------------------- #
# inventory：错误路径
# --------------------------------------------------------------------------- #


def test_inventory_missing_path_raises(tmp_path):
    with pytest.raises(BackfillError):
        inventory(path=tmp_path / "does-not-exist")


def test_inventory_empty_dir_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(BackfillError):
        inventory(path=empty)


def test_inventory_dir_without_py_raises(tmp_path):
    d = tmp_path / "docs"
    _write(d / "a.md", "# md only")
    with pytest.raises(BackfillError):
        inventory(path=d)


# --------------------------------------------------------------------------- #
# render：范围摘要
# --------------------------------------------------------------------------- #


def test_render_summarizes_files_and_symbols(tmp_path):
    mod = tmp_path / "release.py"
    _write(mod, '"""发版逻辑。"""\n\n\ndef release():\n    pass\n')

    text = inventory(path=mod).render()

    assert "单文件" in text
    assert "release.py" in text
    assert "release" in text
    assert "发版逻辑" in text


# --------------------------------------------------------------------------- #
# slug_for
# --------------------------------------------------------------------------- #


def test_slug_for_single_file_strips_py_suffix(tmp_path):
    assert slug_for(path=tmp_path / "release.py") == "release"


def test_slug_for_directory_uses_dir_name(tmp_path):
    assert slug_for(path=tmp_path / "backends") == "backends"


def test_slug_for_normalizes_separators():
    from pathlib import Path

    assert slug_for(path=Path("My Module.py")) == "my-module"
