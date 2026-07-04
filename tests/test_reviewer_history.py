"""Spec-0050/T2：reviewer.review 的 history 注入 + 落盘产物为准 rubric 单元测试。

打桩 AgentBackend（记录每次 run 的 context），覆盖：
- review(history=…) 把历史送进每个 reviewer 的 backend.run context（n=1 与 n>1）；
- history 缺省 "" 时 context 逐字节为 ""（既有行为零回归）；
- UNPARSED 重跑分支也带 history；
- 两个评审任务模板均含「落盘产物为准、评论仅供参考」rubric。
"""

from openagents import reviewer
from openagents.backends.base import AgentResult


class _CtxBackend:
    """记录每次 run 的 context/task 的伪后端，按序返回预设 summary。"""

    name = "ctx"

    def __init__(self, *, summaries):
        self._summaries = list(summaries)
        self._index = 0
        self.contexts = []
        self.tasks = []

    def run(self, *, work_dir, task, context):
        self.contexts.append(context)
        self.tasks.append(task)
        summary = self._summaries[self._index % len(self._summaries)]
        self._index += 1
        return AgentResult(changed=False, summary=summary)


def test_history_is_injected_into_reviewer_context(tmp_path):
    backend = _CtxBackend(summaries=["VERDICT: PASS"])
    reviewer.review(
        backend=backend,
        work_dir=tmp_path,
        kind="code",
        pr_number=5,
        n=1,
        history="本 PR 是 #5。历轮裁决：REWORK。",
    )
    assert backend.contexts == ["本 PR 是 #5。历轮裁决：REWORK。"]


def test_history_injected_across_all_parallel_reviewers(tmp_path):
    backend = _CtxBackend(summaries=["VERDICT: PASS"])
    reviewer.review(
        backend=backend, work_dir=tmp_path, kind="rfc", pr_number=7, n=3, history="HIST"
    )
    # 三个并发 reviewer 各收到同一份历史。
    assert backend.contexts == ["HIST", "HIST", "HIST"]


def test_history_defaults_to_empty_string_zero_regression(tmp_path):
    backend = _CtxBackend(summaries=["VERDICT: PASS"])
    reviewer.review(backend=backend, work_dir=tmp_path, kind="code", pr_number=5, n=1)
    assert backend.contexts == [""]


def test_unparsed_retry_also_carries_history(tmp_path):
    # 首轮无法解析裁决 → 单次重跑；重跑同样带 history（不回落 ""）。
    backend = _CtxBackend(summaries=["无裁决的乱码", "VERDICT: PASS"])
    reviewer.review(
        backend=backend, work_dir=tmp_path, kind="code", pr_number=5, n=1, history="HIST"
    )
    # 首轮 + 重跑各一次，两次都带 HIST。
    assert backend.contexts == ["HIST", "HIST"]


def test_both_templates_contain_landed_artifact_primacy_rubric():
    for template in (reviewer._RFC_REVIEW_TASK, reviewer._CODE_REVIEW_TASK):
        assert "落盘产物为准" in template
        assert "评论仅供参考" in template
        assert "不构成放行理由" in template
        # 明确点出历史仅供背景。
        assert "对话历史" in template
