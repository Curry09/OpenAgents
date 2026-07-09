"""Spec-0032/T1：State 的 block_watermark 字段 + set_block_watermark 单元测试。

用 tmp_path 真实读写临时 .openagents/state.json（hermetic，不触网）；覆盖：
- 新字段缺省值使 RunRecord(**旧记录) 不报错（向后兼容缺键旧 state.json）；
- set_block_watermark 落盘 / 覆盖；
- 与 block_gate / merge_attempts 互不干扰（写一个不动另外两个）。
"""

import json

from openagents.state import RunRecord, State
from openagents.utils.github import PR


def _new_state(tmp_path):
    return State(path=tmp_path / ".openagents" / "state.json")


# --------------------------------------------------------------------------- #
# 新字段默认值 + 向后兼容
# --------------------------------------------------------------------------- #


def test_runrecord_block_watermark_defaults_empty():
    record = RunRecord(
        issue_number=3,
        branch="openagents/issue-3",
        pr_number=5,
        pr_url="u/pull/5",
        status="pr-open",
        summary="",
    )
    assert record.block_watermark == ""


def test_runrecord_accepts_legacy_record_without_watermark():
    # 缺 block_watermark 键的旧 state.json 记录 → RunRecord(**旧记录) 不报错。
    legacy = {
        "issue_number": 3,
        "branch": "openagents/issue-3",
        "pr_number": 5,
        "pr_url": "u/pull/5",
        "status": "blocked",
        "summary": "",
        "rounds": 1,
        "review_invalid": 0,
        "block_gate": "rfc",
        "merge_attempts": 0,
    }
    record = RunRecord(**legacy)
    assert record.block_watermark == ""


def test_all_runs_reads_legacy_state_file_without_watermark(tmp_path):
    path = tmp_path / ".openagents" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "issue_number": 3,
                        "branch": "openagents/issue-3",
                        "pr_number": 5,
                        "pr_url": "u/pull/5",
                        "status": "blocked",
                        "summary": "",
                    }
                ],
                "cursors": {},
            }
        ),
        encoding="utf-8",
    )
    runs = State(path=path).all_runs()
    assert len(runs) == 1
    assert runs[0].block_watermark == ""


# --------------------------------------------------------------------------- #
# set_block_watermark
# --------------------------------------------------------------------------- #


def test_set_block_watermark_persists(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    state.set_block_watermark(issue_number=3, watermark="2026-06-29T10:00:00Z")

    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.find_by_issue(issue_number=3).block_watermark == "2026-06-29T10:00:00Z"


def test_set_block_watermark_overwrites(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.set_block_watermark(issue_number=3, watermark="2026-06-29T10:00:00Z")

    state.set_block_watermark(issue_number=3, watermark="2026-06-29T11:00:00Z")

    assert state.find_by_issue(issue_number=3).block_watermark == "2026-06-29T11:00:00Z"


def test_set_block_watermark_independent_of_gate_and_attempts(tmp_path):
    # 写 watermark 不动 block_gate / merge_attempts（三者彼此独立）。
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.set_block_gate(issue_number=3, gate="merge")
    state.increment_merge_attempts(issue_number=3)

    state.set_block_watermark(issue_number=3, watermark="2026-06-29T10:00:00Z")

    record = state.find_by_issue(issue_number=3)
    assert record.block_watermark == "2026-06-29T10:00:00Z"
    assert record.block_gate == "merge"
    assert record.merge_attempts == 1
