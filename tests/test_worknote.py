"""Spec-0050/T3: worknote（agent「本轮做了什么」回执渲染）单元测试。

worknote 是纯字符串模块（仿 blocknote/replynote），只吃基元 str、无副作用、不含签名、不做 IO。
覆盖：三个 render_* 各带稳定抬头；reason ci/review/e2e 中文化；summary 空回落占位不报错；
纯函数确定性；无外部 import 副作用（不反向 import orchestrator）。
"""

from openagents import worknote


def test_render_implement_header_and_summary():
    body = worknote.render_implement(summary="实现了 T1/T2 两个纯函数")
    assert body.startswith("## 实现自述")
    assert "实现了 T1/T2 两个纯函数" in body


def test_render_iterate_reasons_localized():
    ci = worknote.render_iterate(reason="ci", summary="补了单测")
    review = worknote.render_iterate(reason="review", summary="改了命名")
    e2e = worknote.render_iterate(reason="e2e", summary="修了 runbook 判定点")
    assert ci.startswith("## 迭代自述（CI 反馈）")
    assert review.startswith("## 迭代自述（代码评审反馈）")
    assert e2e.startswith("## 迭代自述（证据闸反馈）")
    # 三种 reason 抬头各异 → messages 去重天然分桶、互不抑制。
    assert len({ci.splitlines()[0], review.splitlines()[0], e2e.splitlines()[0]}) == 3
    assert "补了单测" in ci


def test_render_iterate_unknown_reason_falls_back_to_literal():
    body = worknote.render_iterate(reason="mystery", summary="x")
    assert body.startswith("## 迭代自述（mystery）")


def test_render_runbook_header_form_and_path():
    body = worknote.render_runbook(form="cli", runbook_path="docs/e2e-results/12/runbook.md")
    assert body.startswith("## 说明书定稿")
    assert "cli" in body
    assert "docs/e2e-results/12/runbook.md" in body


def test_empty_summary_falls_back_to_placeholder():
    # summary='' 回落占位、不报错，保证结构齐全。
    assert "（无摘要）" in worknote.render_implement(summary="")
    assert "（无摘要）" in worknote.render_iterate(reason="ci", summary="   ")


def test_render_runbook_empty_values_placeholder():
    body = worknote.render_runbook(form="", runbook_path="")
    assert "（未声明）" in body
    assert "（未知路径）" in body


def test_render_functions_are_deterministic():
    assert worknote.render_implement(summary="a") == worknote.render_implement(summary="a")
    assert worknote.render_iterate(reason="ci", summary="a") == worknote.render_iterate(
        reason="ci", summary="a"
    )


def test_worknote_does_not_import_orchestrator():
    """worknote 不反向 import orchestrator/github/identity（保持展示模块解耦，理念 10）。

    只查**import 语句行**（而非正文/docstring 里的字样），避免注释提到模块名就误判。
    """
    import openagents.worknote as mod

    with open(mod.__file__, encoding="utf-8") as fh:
        import_lines = [line for line in fh if line.startswith(("import ", "from "))]
    for line in import_lines:
        for forbidden in ("orchestrator", "identity", "github", "openagents"):
            assert forbidden not in line, f"worknote 不应 import {forbidden}：{line!r}"
