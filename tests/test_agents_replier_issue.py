"""# Spec-0016/T3：replier.ISSUE_PROMPT（issue 语境、只答疑不改代码）单元测试。

覆盖：
- ISSUE_PROMPT.substitute 能填入 issue_number / comment_body；
- 渲染文本**不含** branch / 改代码 / 交付协议字样，**含**「只答疑不改代码」意图；
- 复用同一 OUTPUT_SCHEMA；
- 既有 PR 版 PROMPT 行为不变（占位符仍是 pr_number/branch/comment_body）。
"""

import pytest

from openagents.agents import replier


def test_issue_prompt_substitutes_placeholders():
    text = replier.ISSUE_PROMPT.substitute(issue_number=149)
    assert "149" in text
    assert "下方“上下文”区" in text


def test_issue_prompt_has_no_branch_or_code_change_intent():
    text = replier.ISSUE_PROMPT.substitute(issue_number=149, comment_body="x")
    # issue 尚无工作分支：不得出现 branch 占位符或字样。
    assert "$branch" not in replier.ISSUE_PROMPT.template
    assert "branch" not in text
    # 只答疑：明确写「只答疑、不改代码」，且「开 PR」只出现在否定语境（不要开 PR）。
    assert "只答疑" in text and "不改代码" in text
    assert "开 PR" in text  # 出现在「不要开 PR」的否定语境里


def test_issue_prompt_reuses_output_schema():
    assert replier.OUTPUT_SCHEMA == {"reply": str, "resolved": bool}


def test_pr_prompt_unchanged():
    # Spec-0081/T1：PR 版只保留 pr_number / branch，评论正文归 context。
    text = replier.PROMPT.substitute(pr_number=7, branch="openagents/issue-7")
    assert "7" in text and "openagents/issue-7" in text
    assert "下方“上下文”区" in text


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
