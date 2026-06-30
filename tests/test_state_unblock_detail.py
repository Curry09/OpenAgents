"""Spec-0036/T1：State 的 unblock_detail 字段 + set_unblock_detail 方法单元测试。

用 tmp_path 真实读写临时 .openagents/state.json（hermetic，不触网）；覆盖：
- 新字段缺省值使 RunRecord(**旧记录) 不报错（向后兼容缺该键的旧 state.json）；
- set_unblock_detail 落盘 / 清除（detail=""）；
- unblock_detail 与 block_gate / block_watermark 互不干扰（同住一条记录、各管各的）。
"""

import json

from openagents.github import PR
from openagents.state import RunRecord, State


def _new_state(tmp_path):
    """构造一个指向临时 state 文件的 State。"""
    return State(path=tmp_path / ".openagents" / "state.json")


# --------------------------------------------------------------------------- #
# 新字段默认值 + 向后兼容
# --------------------------------------------------------------------------- #


def test_runrecord_unblock_detail_defaults_empty():
    # 不传 unblock_detail 也能构造，默认值为 ""。
    record = RunRecord(
        issue_number=3,
        branch="openagents/issue-3",
        pr_number=5,
        pr_url="u/pull/5",
        status="blocked",
        summary="",
    )
    assert record.unblock_detail == ""


def test_runrecord_accepts_legacy_record_without_unblock_detail():
    # 模拟缺 unblock_detail 键的旧 state.json 记录 → RunRecord(**旧记录) 不报错。
    legacy = {
        "issue_number": 3,
        "branch": "openagents/issue-3",
        "pr_number": 5,
        "pr_url": "u/pull/5",
        "status": "blocked",
        "summary": "",
        "rounds": 1,
        "review_invalid": 0,
        "block_gate": "merge",
        "merge_attempts": 0,
        "block_watermark": "t1",
    }
    record = RunRecord(**legacy)
    assert record.unblock_detail == ""
    # 既有字段照常读出。
    assert record.block_gate == "merge"
    assert record.block_watermark == "t1"


def test_all_runs_reads_legacy_state_file(tmp_path):
    # 旧 state.json（runs 记录缺 unblock_detail 键）能被 all_runs 读出而不报错。
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
    state = State(path=path)
    runs = state.all_runs()
    assert len(runs) == 1
    assert runs[0].unblock_detail == ""


# --------------------------------------------------------------------------- #
# set_unblock_detail
# --------------------------------------------------------------------------- #


def test_set_unblock_detail_persists(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    state.set_unblock_detail(issue_number=3, detail="先解 OVERVIEW.md 再动 state.py")

    # 用全新 State 实例从同一文件读，验证真实落盘。
    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.find_by_issue(issue_number=3).unblock_detail == "先解 OVERVIEW.md 再动 state.py"


def test_set_unblock_detail_empty_clears(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.set_unblock_detail(issue_number=3, detail="人类指导")

    state.set_unblock_detail(issue_number=3, detail="")

    assert state.find_by_issue(issue_number=3).unblock_detail == ""


def test_set_unblock_detail_handles_legacy_record(tmp_path):
    # 旧记录缺 unblock_detail 键 → set 写入后能读出（缺键不阻碍写）。
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
    state = State(path=path)
    state.set_unblock_detail(issue_number=3, detail="人类指导")
    assert state.find_by_issue(issue_number=3).unblock_detail == "人类指导"


# --------------------------------------------------------------------------- #
# 与 block_gate / block_watermark 互不干扰
# --------------------------------------------------------------------------- #


def test_unblock_detail_independent_of_block_gate_and_watermark(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.set_block_gate(issue_number=3, gate="merge")
    state.set_block_watermark(issue_number=3, watermark="t1")

    state.set_unblock_detail(issue_number=3, detail="人类指导")

    record = state.find_by_issue(issue_number=3)
    assert record.unblock_detail == "人类指导"
    assert record.block_gate == "merge"  # 不受影响
    assert record.block_watermark == "t1"  # 不受影响

    # 清 unblock_detail 不影响 block_gate / block_watermark。
    state.set_unblock_detail(issue_number=3, detail="")
    record = state.find_by_issue(issue_number=3)
    assert record.unblock_detail == ""
    assert record.block_gate == "merge"
    assert record.block_watermark == "t1"
