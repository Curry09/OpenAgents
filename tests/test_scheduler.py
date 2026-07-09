"""Spec-0058/T1：跨 issue 调度判边模块 scheduler 的单元测试。

打桩 backend（不触达真实 LLM），覆盖：schedule 调注入 backend 判边、按标记回解析成 DepEdge
（file-conflict / logical 两 kind、方向 / 理由齐）；fail-open（空 / 格式跑偏 / 未知 kind / 自环 /
越界号 → 该边丢弃、全丢即空边集）；parse_owned_files 对真实 spec markdown 解出 tasks[].files 并集、
对无 frontmatter 容错空集；模块不做任何 IO（不 import github / argparse、不 print / input）。
"""

from pathlib import Path

from openagents import scheduler
from openagents.backends.base import AgentResult
from openagents.scheduler import (
    DepEdge,
    IssueContext,
    ScheduleVerdict,
    parse_owned_files,
    schedule,
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


def _issues():
    # #137 与 #150 的 owned_files 有交集（messages.py），#160 独立。
    return [
        IssueContext(
            number=150,
            title="调度",
            body="补跨 issue 顺序",
            owned_files=frozenset({"openagents/messages.py"}),
        ),
        IssueContext(
            number=137,
            title="并行执行器",
            body="复用 #150 的 sched-ready 接口",
            owned_files=frozenset({"openagents/messages.py"}),
        ),
        IssueContext(
            number=160, title="独立小改", body="改个文案", owned_files=frozenset({"docs/README.md"})
        ),
    ]


# --------------------------------------------------------------------------- #
# schedule —— 判边命中
# --------------------------------------------------------------------------- #


def test_schedule_parses_file_conflict_edge():
    summary = (
        "边：137 <- 150\n类型：file-conflict\n理由：两者都改 openagents/messages.py，应先合 #150\n"
    )
    verdict = schedule(issues=_issues(), backend=_StubBackend(summary=summary))

    assert isinstance(verdict, ScheduleVerdict)
    assert verdict.edges == (
        DepEdge(
            downstream=137,
            upstream=150,
            kind="file-conflict",
            reason="两者都改 openagents/messages.py，应先合 #150",
        ),
    )


def test_schedule_parses_logical_edge_from_body_claim():
    summary = "边：#137 <- #150\n类型：logical\n理由：#137 要复用 #150 的 sched-ready 接口\n"
    verdict = schedule(issues=_issues(), backend=_StubBackend(summary=summary))

    assert len(verdict.edges) == 1
    edge = verdict.edges[0]
    assert edge.kind == "logical"
    assert edge.downstream == 137 and edge.upstream == 150


def test_schedule_calls_backend_once_with_issue_context():
    backend = _StubBackend(summary="")
    schedule(issues=_issues(), backend=backend)

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert isinstance(call["work_dir"], Path)
    # 编号 / owned_files 都进上下文，供 agent 判文件冲突序。
    assert "150" in call["context"] and "137" in call["context"]
    assert "openagents/messages.py" in call["context"]


def test_schedule_parses_multiple_edges():
    summary = (
        "边：137 <- 150\n类型：file-conflict\n理由：文件冲突\n"
        "边：160 <- 150\n类型：logical\n理由：需先落底座\n"
    )
    verdict = schedule(issues=_issues(), backend=_StubBackend(summary=summary))
    assert len(verdict.edges) == 2


def test_schedule_dedupes_repeated_edges():
    summary = (
        "边：137 <- 150\n类型：file-conflict\n理由：文件冲突\n"
        "边：137 <- 150\n类型：file-conflict\n理由：重复\n"
    )
    verdict = schedule(issues=_issues(), backend=_StubBackend(summary=summary))
    assert len(verdict.edges) == 1


# --------------------------------------------------------------------------- #
# schedule —— fail-open（不乱连）
# --------------------------------------------------------------------------- #


def test_schedule_fail_open_on_empty_summary():
    verdict = schedule(issues=_issues(), backend=_StubBackend(summary=""))
    assert verdict.edges == ()


def test_schedule_fail_open_on_garbled_summary():
    garbled = "我觉得这几个 issue 都能并行吧，没啥依赖"
    verdict = schedule(issues=_issues(), backend=_StubBackend(summary=garbled))
    assert verdict.edges == ()


def test_schedule_drops_edge_with_unknown_kind():
    summary = "边：137 <- 150\n类型：unknown-kind\n理由：xx\n"
    verdict = schedule(issues=_issues(), backend=_StubBackend(summary=summary))
    assert verdict.edges == ()


def test_schedule_drops_self_loop():
    summary = "边：150 <- 150\n类型：logical\n理由：自环\n"
    verdict = schedule(issues=_issues(), backend=_StubBackend(summary=summary))
    assert verdict.edges == ()


def test_schedule_drops_out_of_range_number():
    # #999 不在本批 issue 里（agent 幻觉），丢弃。
    summary = "边：137 <- 999\n类型：logical\n理由：幻觉上游\n"
    verdict = schedule(issues=_issues(), backend=_StubBackend(summary=summary))
    assert verdict.edges == ()


def test_schedule_empty_issues_short_circuits():
    backend = _StubBackend(summary="边：1 <- 2\n类型：logical\n理由：x\n")
    verdict = schedule(issues=[], backend=backend)
    assert verdict.edges == ()
    # 无 issue 直接短路，不调 backend。
    assert backend.calls == []


# --------------------------------------------------------------------------- #
# parse_owned_files
# --------------------------------------------------------------------------- #


_SPEC_MD = """---
number: "0058"
title: 跨 issue 调度
issue: 150
slug: issue-scheduler
summary: xxx
tasks:
  - id: T1
    files:
      - openagents/scheduler.py
      - tests/test_scheduler.py
  - id: T2
    files:
      - openagents/schedlabels.py
---

# 正文
"""


def test_parse_owned_files_collects_union():
    files = parse_owned_files(spec_markdown=_SPEC_MD)
    assert files == frozenset(
        {
            "openagents/scheduler.py",
            "tests/test_scheduler.py",
            "openagents/schedlabels.py",
        }
    )


def test_parse_owned_files_no_frontmatter_returns_empty():
    assert parse_owned_files(spec_markdown="# 只有正文，无 frontmatter") == frozenset()


def test_parse_owned_files_malformed_yaml_returns_empty():
    bad = "---\n: : : not yaml :\n---\n正文"
    assert parse_owned_files(spec_markdown=bad) == frozenset()


def test_parse_owned_files_no_tasks_returns_empty():
    md = '---\nnumber: "0001"\nissue: 1\n---\n正文'
    assert parse_owned_files(spec_markdown=md) == frozenset()


# --------------------------------------------------------------------------- #
# 解耦：模块不做任何 IO
# --------------------------------------------------------------------------- #


def test_module_does_no_io():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(scheduler))
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
