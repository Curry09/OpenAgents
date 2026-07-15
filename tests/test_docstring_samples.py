# Spec-0059/T3: 三处样例落地的断言测试——engine 模块 docstring + run_vigil 函数 docstring 合规。

"""Assert the two sample files carry PEP-257-aligned docstrings after Spec-0059/T3.

样例证明 T1 规则在真实文件上可落地：`runtime.engine` 模块 docstring 去掉 `\"\"\"#` 写法、spec-id 上移
为文件顶部 `#` 注释、补 `Exports:`；`recipes.vigil.run_vigil` 函数 docstring 补 `Args:` 与 `Raises:`。

Exports:
    无导出对象（pytest 用例模块）。
"""

from __future__ import annotations

from pathlib import Path

from openagents.recipes import vigil
from openagents.runtime import engine


def test_engine_module_docstring_is_clean():
    doc = engine.__doc__
    assert doc is not None
    # 首字符非 `#`：spec-id 已上移为文件顶部 `#` 注释、不再污染 __doc__/help()。
    assert doc.lstrip()[0] != "#", "engine 模块 docstring 首行不应以 # 开头"
    # 列出导出对象（PEP 257「list the classes, exceptions and functions exported」）。
    assert "Exports:" in doc


def test_engine_spec_id_moved_to_top_comment():
    src = Path(engine.__file__).read_text(encoding="utf-8")
    # spec-id 落在文件顶部的 `#` 注释行（对齐 argparse `# Author:` 惯例）。
    assert "# Spec-0060/T2" in src.splitlines()[0]
    # 模块 docstring 不再有 `"""#` 序列（`#` 在三引号里是字面文本会进 __doc__）。
    assert '"""#' not in src


def test_run_vigil_docstring_has_args_and_raises():
    doc = vigil.run_vigil.__doc__
    assert doc is not None
    assert "Args:" in doc
    assert "Raises:" in doc
