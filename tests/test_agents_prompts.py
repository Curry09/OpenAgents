"""Spec-0060/T4: agents 提示词层单测——只含 PROMPT（Template）+ OUTPUT_SCHEMA（dict）、零逻辑。

对 5 个 agent 模块逐个断言契约；并做「源码无 def / 无 subprocess·gh·git 调用」的静态锚点
（与 e2e 脚本 grep 互为冗余，锁死「判断在 agent、逻辑不在 Python」）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from string import Template

import pytest

from openagents import agents
from openagents.agents import deliver, drafter, implementer, replier, reviewer, tester, triager

# Spec-0064/T6：planner 已合并进 drafter，改断言新栈实际 agent 集（drafter/triager/replier 补入）。
_MODULES = [drafter, implementer, reviewer, deliver, tester, triager, replier]
_AGENTS_DIR = Path(agents.__file__).parent


@pytest.mark.parametrize("module", _MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_module_exposes_prompt_and_schema(module):
    assert isinstance(module.PROMPT, Template)
    assert isinstance(module.OUTPUT_SCHEMA, dict)
    # OUTPUT_SCHEMA 是「键→Python 类型」映射。
    assert all(isinstance(v, type) for v in module.OUTPUT_SCHEMA.values())


def test_reviewer_schema_has_verdict_and_reason():
    assert reviewer.OUTPUT_SCHEMA == {"verdict": str, "reason": str}


def test_deliver_schema_reports_base_sha():
    # recipe 用 deliver 的 base_sha 喂 assert_head_advanced，必须在 schema 里。
    assert "base_sha" in deliver.OUTPUT_SCHEMA
    assert deliver.OUTPUT_SCHEMA["delivered"] is bool


@pytest.mark.parametrize(
    "path", sorted(p for p in _AGENTS_DIR.glob("*.py") if p.name != "__init__.py")
)
def test_prompt_module_has_no_logic(path):
    # 零逻辑静态锚点：模块顶层只允许 import + PROMPT/OUTPUT_SCHEMA 赋值，禁止任何函数/类定义。
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        assert not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)), (
            f"{path.name} 含逻辑定义 {type(node).__name__}（agent 应零逻辑）"
        )
    # 禁 import subprocess（更强的「无 IO」锚点；prompt 字符串里出现 git/gh 字样是文案、非调用）。
    src = path.read_text(encoding="utf-8")
    assert "import subprocess" not in src
    assert "subprocess." not in src


def test_prompt_placeholders_substitute():
    # Template 可被延后 substitute（占位符齐全即不抛），验证 prompt 字符串形态合法。
    reviewer.PROMPT.substitute(pr_number=1, issue_body="x")
    deliver.PROMPT.substitute(branch="openagents/issue-1", rebase_onto="main", pr_number=1)
    drafter.PROMPT.substitute(mode="draft", target="issue #1", branch="b", detail="d")
    implementer.PROMPT.substitute(issue_number=1, pr_number=1, feedback="")
    tester.PROMPT.substitute(pr_number=1, issue_body="x")
