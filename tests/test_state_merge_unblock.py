"""Spec-0031/T1：State 的 block_gate / merge_attempts 字段 + 计数/重置方法单元测试。

用 tmp_path 真实读写临时 .openagents/state.json（hermetic，不触网）；覆盖：
- 新字段缺省值使 RunRecord(**旧记录) 不报错（向后兼容）；
- set_block_gate 落盘 / 清除（gate=""）；
- increment_merge_attempts 镜像 increment_rounds（含旧记录缺键兜底）；
- reset_rounds 同点把 merge_attempts 一并归零，但**不动 block_gate**。
"""

import json

from openagents.state import RunRecord, State
from openagents.utils.github import PR


def _new_state(tmp_path):
    """构造一个指向临时 state 文件的 State。"""
    return State(path=tmp_path / ".openagents" / "state.json")


# --------------------------------------------------------------------------- #
# 新字段默认值 + 向后兼容
# --------------------------------------------------------------------------- #


def test_runrecord_new_fields_default():
    # 不传新字段也能构造，且默认值为 ""/0。
    record = RunRecord(
        issue_number=3,
        branch="openagents/issue-3",
        pr_number=5,
        pr_url="u/pull/5",
        status="pr-open",
        summary="",
    )
    assert record.block_gate == ""
    assert record.merge_attempts == 0


def test_runrecord_accepts_legacy_record_without_new_keys():
    # 模拟缺 block_gate / merge_attempts 键的旧 state.json 记录 → RunRecord(**旧记录) 不报错。
    legacy = {
        "issue_number": 3,
        "branch": "openagents/issue-3",
        "pr_number": 5,
        "pr_url": "u/pull/5",
        "status": "pr-open",
        "summary": "",
        "rounds": 1,
        "review_invalid": 0,
    }
    record = RunRecord(**legacy)
    assert record.block_gate == ""
    assert record.merge_attempts == 0


def test_all_runs_reads_legacy_state_file(tmp_path):
    # 旧 state.json（runs 记录缺新键）能被 all_runs 读出而不报错。
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
    assert runs[0].block_gate == ""
    assert runs[0].merge_attempts == 0


# --------------------------------------------------------------------------- #
# set_block_gate
# --------------------------------------------------------------------------- #


def test_set_block_gate_persists(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    state.set_block_gate(issue_number=3, gate="merge")

    # 用全新 State 实例从同一文件读，验证真实落盘。
    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.find_by_issue(issue_number=3).block_gate == "merge"


def test_set_block_gate_empty_clears(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.set_block_gate(issue_number=3, gate="merge")

    state.set_block_gate(issue_number=3, gate="")

    assert state.find_by_issue(issue_number=3).block_gate == ""


# --------------------------------------------------------------------------- #
# increment_merge_attempts
# --------------------------------------------------------------------------- #


def test_increment_merge_attempts_returns_new_value(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    assert state.increment_merge_attempts(issue_number=3) == 1
    assert state.increment_merge_attempts(issue_number=3) == 2
    assert state.find_by_issue(issue_number=3).merge_attempts == 2


def test_increment_merge_attempts_handles_legacy_record(tmp_path):
    # 旧记录缺 merge_attempts 键 → get(...,0) 兜底，首次递增得 1。
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
                        "status": "pr-open",
                        "summary": "",
                    }
                ],
                "cursors": {},
            }
        ),
        encoding="utf-8",
    )
    state = State(path=path)
    assert state.increment_merge_attempts(issue_number=3) == 1


# --------------------------------------------------------------------------- #
# reset_rounds 与 block_gate / merge_attempts 的关系
# --------------------------------------------------------------------------- #


def test_reset_rounds_zeroes_merge_attempts(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.increment_merge_attempts(issue_number=3)
    state.increment_merge_attempts(issue_number=3)

    state.reset_rounds(issue_number=3)

    assert state.find_by_issue(issue_number=3).merge_attempts == 0


def test_reset_rounds_does_not_clear_block_gate(tmp_path):
    # 关键不变式：reset_rounds 不动 block_gate——解挂 merge 闸 arm 时要保留 "merge" 作标记。
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.set_block_gate(issue_number=3, gate="merge")
    state.increment_merge_attempts(issue_number=3)

    state.reset_rounds(issue_number=3)

    record = state.find_by_issue(issue_number=3)
    assert record.merge_attempts == 0  # 预算清零
    assert record.block_gate == "merge"  # armed 标记保留
