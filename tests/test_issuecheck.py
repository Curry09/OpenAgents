"""Spec-0043/T2: issue 自洽性判读模块 issuecheck 的单元测试。

打桩 backend（不触达真实 LLM），覆盖：check 调注入 backend 判读 #106 样本、按标记回解析成
ConflictVerdict；fail-open（『冲突：否』/ 空 / 格式跑偏 / 有『是』无冲突点 → has_conflict=False）；
build_alignment_comment 含冲突点 + 候选修法 + needs-human 摘标签指引、不含 PR 失败文案；
模块不做任何 IO（不 import github/argparse）。
"""

from pathlib import Path

from openagents import issuecheck
from openagents.backends.base import AgentResult
from openagents.issuecheck import (
    ConflictVerdict,
    IssueDraft,
    build_alignment_comment,
    check,
)

# issue #106 的真实标题/正文（本 spec 的一等回归样例）。
_106_TITLE = "已 PASS 的 PR 被反复重审：评审结论应按 commit sha 缓存，避免同码 PASS/REWORK 震荡"
_106_BODY = "hold-merge 后已 PASS 的 PR 仍被反复重审，应冻结成 needs-human，避免继续重跑 reviewer"

# backend 判读 #106 后按标记格式返回「冲突：是」+ 两条冲突点 + 两条候选修法。
_CONFLICT_SUMMARY = (
    "冲突：是\n"
    "冲突点：标题主张按 commit sha 缓存评审结论；正文主张 hold-merge 后把已 PASS 的 PR 冻结成 needs-human。\n"
    "冲突点：两者语义不同——一个保留 PR 在活跃轮询里复用缓存，一个把 PR 移出活跃轮询等人合并。\n"
    "候选修法：按 commit sha 缓存评审结论\n"
    "候选修法：hold-merge 冻结 PR\n"
)


class _StubBackend:
    """记录调用与入参的伪 backend，按预设文本回判读结果（不触达真实 LLM）。"""

    name = "stub"

    def __init__(self, *, summary):
        self.calls = []
        self._summary = summary

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        return AgentResult(changed=False, summary=self._summary)


# --------------------------------------------------------------------------- #
# check —— 命中冲突
# --------------------------------------------------------------------------- #


def test_check_detects_conflict_on_106_sample():
    backend = _StubBackend(summary=_CONFLICT_SUMMARY)

    verdict = check(draft=IssueDraft(title=_106_TITLE, body=_106_BODY), backend=backend)

    assert isinstance(verdict, ConflictVerdict)
    assert verdict.has_conflict is True
    assert len(verdict.conflicts) == 2
    # 两个不同的修法方向被解析出来供人取舍。
    assert verdict.candidate_fixes == (
        "按 commit sha 缓存评审结论",
        "hold-merge 冻结 PR",
    )


def test_check_calls_backend_once_with_title_and_body_in_context():
    backend = _StubBackend(summary=_CONFLICT_SUMMARY)

    check(draft=IssueDraft(title="T", body="B"), backend=backend)

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert isinstance(call["work_dir"], Path)
    assert "T" in call["context"] and "B" in call["context"]


# --------------------------------------------------------------------------- #
# check —— fail-open（放行）
# --------------------------------------------------------------------------- #


def test_check_passes_when_no_conflict():
    verdict = check(draft=IssueDraft(title="t", body="b"), backend=_StubBackend(summary="冲突：否"))
    assert verdict.has_conflict is False
    assert verdict.conflicts == ()
    assert verdict.candidate_fixes == ()


def test_check_fail_open_on_empty_summary():
    verdict = check(draft=IssueDraft(title="t", body="b"), backend=_StubBackend(summary=""))
    assert verdict.has_conflict is False


def test_check_fail_open_on_garbled_summary():
    # 格式跑偏、无稳定标记 → 无法解析出明确冲突信号 → 放行。
    garbled = "这个 issue 看起来还行吧，我觉得没啥大问题，就先这样"
    verdict = check(draft=IssueDraft(title="t", body="b"), backend=_StubBackend(summary=garbled))
    assert verdict.has_conflict is False


def test_check_fail_open_when_conflict_yes_but_no_points():
    # 写了『冲突：是』却没列出任何冲突点 → 视为格式跑偏，fail-open 放行（不空拦）。
    verdict = check(
        draft=IssueDraft(title="t", body="b"), backend=_StubBackend(summary="冲突：是\n")
    )
    assert verdict.has_conflict is False


# --------------------------------------------------------------------------- #
# build_alignment_comment
# --------------------------------------------------------------------------- #


def test_build_alignment_comment_lists_points_and_fixes_and_guidance():
    verdict = ConflictVerdict(
        has_conflict=True,
        conflicts=("标题=sha 缓存 vs 正文=hold-merge 冻结",),
        candidate_fixes=("按 commit sha 缓存评审结论", "hold-merge 冻结 PR"),
    )

    body = build_alignment_comment(verdict=verdict)

    # 含冲突点、候选修法取舍、needs-human 摘标签指引。
    assert "标题=sha 缓存 vs 正文=hold-merge 冻结" in body
    assert "按 commit sha 缓存评审结论" in body and "hold-merge 冻结 PR" in body
    assert "候选修法" in body
    assert "needs-human" in body and "对齐" in body
    # 绝不含 PR 级失败/求救文案。
    assert "卡住了" not in body
    assert "🤖" not in body


def test_build_alignment_comment_omits_fixes_section_when_empty():
    verdict = ConflictVerdict(has_conflict=True, conflicts=("只有一个冲突点，无清晰候选",))
    body = build_alignment_comment(verdict=verdict)
    assert "只有一个冲突点，无清晰候选" in body
    # 候选修法为空 → 不渲染该段标题。
    assert "候选修法" not in body
    assert "needs-human" in body


# --------------------------------------------------------------------------- #
# 解耦：模块不做任何 IO
# --------------------------------------------------------------------------- #


def test_module_does_no_io():
    # 用 AST 检查真实的 import / 调用（而非文本子串——docstring 里会提到这些词），确保纯逻辑无 IO。
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(issuecheck))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)

    assert "argparse" not in imported
    assert not any(name.endswith("github") or name == "github" for name in imported)
    assert "print" not in called and "input" not in called
