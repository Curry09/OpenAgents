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
from openagents.agents import (
    acceptance,
    deliver,
    developer,
    drafter,
    executor,
    implementer,
    replier,
    reviewer,
    spec_writer,
    tester,
    triager,
)

# Spec-0064/T6：planner 已合并进 drafter，改断言新栈实际 agent 集（drafter/triager/replier 补入）。
_MODULES = [
    drafter,
    spec_writer,
    executor,
    implementer,
    acceptance,
    reviewer,
    deliver,
    tester,
    triager,
    replier,
]
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
    executor.PROMPT.substitute(issue_number=1, pr_number=1)
    tester.PROMPT.substitute(pr_number=1, issue_body="x")
    spec_writer.PROMPT.substitute(issue_number=1, branch="b", mode="AUTHOR")
    acceptance.PROMPT.substitute(issue_number=1, pr_number=1)


def test_minimal_roles_keep_original_issue_as_authority():
    assert "原 issue" in spec_writer.PROMPT.template
    assert "语义守恒" in spec_writer.PROMPT.template
    assert "因果链" in spec_writer.PROMPT.template
    assert "PARTIAL" in spec_writer.PROMPT.template
    assert "不得仅因未来" in spec_writer.PROMPT.template
    assert "交给 Developer 实现、Acceptance" in spec_writer.PROMPT.template
    assert "head_sha" not in spec_writer.OUTPUT_SCHEMA
    assert "head_sha" not in developer.OUTPUT_SCHEMA
    assert "独立证伪" in spec_writer.PROMPT.template
    assert "PARTIAL" in acceptance.PROMPT.template
    assert acceptance.OUTPUT_SCHEMA == {"verdict": str, "reason": str, "evidence": list}
    assert "唯一可写 worktree" in spec_writer.PROMPT.template
    assert "NexAU 及其它运行时依赖全部向你开放\n只读检查" in spec_writer.PROMPT.template
    assert "不设文件数、行数或工具调用额度" in spec_writer.PROMPT.template
    assert "不得修改依赖" in spec_writer.PROMPT.template
    assert "delivery" in spec_writer.PROMPT.template
    assert "control_effect" in spec_writer.PROMPT.template
    assert "evidence_level" in spec_writer.PROMPT.template
    assert "候选的选择与\n拒绝必须使用同一证据强度" in spec_writer.PROMPT.template
    assert "prompt 文件存在或被配置引用还不证明可达" in spec_writer.PROMPT.template
    assert "不调用 `spec`" in spec_writer.PROMPT.template
    assert "docs/objectives/issue-$issue_number.md" in spec_writer.PROMPT.template
    assert "candidate_assessments" in spec_writer.OUTPUT_SCHEMA
    assert "intervention_candidates" not in spec_writer.OUTPUT_SCHEMA
    assert "Spec 的核心是解释为什么" in spec_writer.PROMPT.template
    assert "不是提前替 Developer 写实现" in spec_writer.PROMPT.template
    assert "不得规定新类名" in spec_writer.PROMPT.template
    assert "最高允许的方案粒度" in spec_writer.PROMPT.template
    assert "不得规定新增包装层" in spec_writer.PROMPT.template
    assert "留给 Developer 决定的技术选择" in spec_writer.PROMPT.template
    assert "具体技术设计归 Developer 自主决定" in spec_writer.PROMPT.template
    assert "核对并交付" in spec_writer.PROMPT.template
    assert "DELIVERY_REPAIR" in spec_writer.PROMPT.template
    assert "CONTRACT_REPAIR" in spec_writer.PROMPT.template
    assert "scope_coverage=FULL, evidence_level=HYPOTHESIS" in spec_writer.PROMPT.template
    assert "不得重新探索仓库" in spec_writer.PROMPT.template
    assert "不得把“文档已写完”当成任务完成" in spec_writer.PROMPT.template
    assert "只是 Curator 做并发\n冲突判断所需的预计协调面" in spec_writer.PROMPT.template
    assert "冻结的是原目标、决策理由、因果边界、不变量和独立验收" in developer.PROMPT.template
    assert "不要机械照抄" in developer.PROMPT.template
    assert "普通技术设计由你决定" in developer.PROMPT.template
    assert "source=original_replay" in acceptance.PROMPT.template
    assert "source=user_test" in acceptance.PROMPT.template
    assert "independent variant" in acceptance.PROMPT.template
    assert "任何一项 `passed=false` 时不得 PASS" in acceptance.PROMPT.template
    assert "候选 worktree 是不可变验收对象" in acceptance.PROMPT.template
    assert "/tmp/openagents-acceptance-$issue_number/" in acceptance.PROMPT.template
    assert "任何候选修改都会使整份裁决作废" in acceptance.PROMPT.template


def test_spec_writer_contract_does_not_embed_case_specific_answers():
    prompt = spec_writer.PROMPT.template
    leaked_phrases = (
        "首次 edit",
        "停止 X",
        "事后 marker",
        "prompt-only",
        "heartbeat",
        "tool wrapper",
    )
    assert all(phrase not in prompt for phrase in leaked_phrases)


def test_generate_only_executor_is_constrained_and_does_not_validate():
    assert "compact objective spec" in executor.PROMPT.template
    assert "不要运行 ruff" in executor.PROMPT.template
    assert "不得修改 forge 标签" in executor.PROMPT.template
    assert executor.OUTPUT_SCHEMA["head_sha"] is str
