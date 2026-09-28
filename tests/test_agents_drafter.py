"""Spec-0062/T1: agents.drafter 提示词层单测——只含 PROMPT（Template）+ OUTPUT_SCHEMA、零逻辑。

drafter 单 agent 承 RFC 生命周期五种起草判断（draft/backfill/refine/implement/iterate），用同一
Template 骨架 + `$mode` 占位符分化。此处断言其契约（PROMPT 是 Template、schema 键→类型正确、五 mode
占位符可延后 substitute），并做「模块零 def / 零 subprocess」的静态锚点（与 test_agents_prompts.py
的 glob 用例互为冗余，锁死判断在 agent、逻辑不在 Python）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from string import Template

from openagents.agents import drafter


def test_drafter_exposes_prompt_and_schema():
    assert isinstance(drafter.PROMPT, Template)
    assert drafter.OUTPUT_SCHEMA == {"delivered": bool, "head_sha": str, "summary": str}


def test_drafter_prompt_substitutes_for_every_mode():
    # 五 mode 复用同一占位符集（mode/target/branch/detail）——每个 mode 都能填齐、不抛。
    for mode in ("draft", "backfill", "refine", "implement", "iterate"):
        task = drafter.PROMPT.substitute(
            mode=mode, target="issue #145「t」", branch="openagents/issue-145"
        )
        assert mode in task
        assert "openagents/issue-145" in task
        assert "下方“上下文”区" in task


def test_drafter_module_has_no_logic():
    # 零逻辑静态锚点：模块顶层只允许 import + PROMPT/OUTPUT_SCHEMA/__all__ 赋值，禁止任何函数/类定义。
    path = Path(drafter.__file__)
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        assert not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)), (
            f"drafter 含逻辑定义 {type(node).__name__}（agent 应零逻辑）"
        )
    # 禁 subprocess（更强的「无 IO」锚点；prompt 里出现 git/gh 字样是文案、非调用）。
    assert "import subprocess" not in src
    assert "subprocess." not in src
