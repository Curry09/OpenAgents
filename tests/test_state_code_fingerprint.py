"""Spec-0053/T1：State 的 code_passed_fingerprint 字段 + set_code_fingerprint 方法单元测试。

用 tmp_path 真实读写临时 .openagents/state.json（hermetic，不触网）；覆盖：
- 新字段缺省值使 RunRecord(**旧记录) 不报错（向后兼容缺该键的旧 state.json）；
- set_code_fingerprint 落盘 / 清除（fingerprint=""，对称留用）；
- code_passed_fingerprint 与 block_* / merge_attempts / closed_at 互不干扰
  （同住一条记录、各管各的）。
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


def test_runrecord_code_fingerprint_defaults_empty():
    # 不传 code_passed_fingerprint 也能构造，默认值为 ""。
    record = RunRecord(
        issue_number=3,
        branch="openagents/issue-3",
        pr_number=5,
        pr_url="u/pull/5",
        status="pr-open",
        summary="",
    )
    assert record.code_passed_fingerprint == ""


def test_runrecord_accepts_legacy_record_without_fingerprint():
    # 模拟缺 code_passed_fingerprint 键的旧 state.json 记录 → RunRecord(**旧记录) 不报错。
    legacy = {
        "issue_number": 3,
        "branch": "openagents/issue-3",
        "pr_number": 5,
        "pr_url": "u/pull/5",
        "status": "pr-open",
        "summary": "",
        "rounds": 1,
        "review_invalid": 0,
        "block_gate": "merge",
        "merge_attempts": 0,
        "block_watermark": "t1",
        "unblock_detail": "d",
        "closed_at": "",
    }
    record = RunRecord(**legacy)
    assert record.code_passed_fingerprint == ""
    # 既有字段照常读出。
    assert record.block_gate == "merge"
    assert record.unblock_detail == "d"


def test_all_runs_reads_legacy_state_file(tmp_path):
    # 旧 state.json（runs 记录缺 code_passed_fingerprint 键）能被 all_runs 读出而不报错。
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
    runs = state.all_runs()
    assert len(runs) == 1
    assert runs[0].code_passed_fingerprint == ""


# --------------------------------------------------------------------------- #
# set_code_fingerprint
# --------------------------------------------------------------------------- #


def test_set_code_fingerprint_persists_and_reloads(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))

    state.set_code_fingerprint(issue_number=3, fingerprint="abc123")

    # 用全新 State 实例从同一文件读，验证真实落盘、重载读回一致。
    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.find_by_issue(issue_number=3).code_passed_fingerprint == "abc123"


def test_set_code_fingerprint_empty_clears(tmp_path):
    # fingerprint="" 表示清除（对称留用）。
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.set_code_fingerprint(issue_number=3, fingerprint="abc123")

    state.set_code_fingerprint(issue_number=3, fingerprint="")

    assert state.find_by_issue(issue_number=3).code_passed_fingerprint == ""


def test_set_code_fingerprint_handles_legacy_record(tmp_path):
    # 旧记录缺 code_passed_fingerprint 键 → set 写入后能读出（缺键不阻碍写）。
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
    state.set_code_fingerprint(issue_number=3, fingerprint="abc123")
    assert state.find_by_issue(issue_number=3).code_passed_fingerprint == "abc123"


# --------------------------------------------------------------------------- #
# 与 block_gate / block_watermark / unblock_detail / merge_attempts / closed_at 互不干扰
# --------------------------------------------------------------------------- #


def test_code_fingerprint_independent_of_other_fields(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=PR(number=5, url="u/pull/5"))
    state.set_block_gate(issue_number=3, gate="merge")
    state.set_block_watermark(issue_number=3, watermark="t1")
    state.set_unblock_detail(issue_number=3, detail="人类指导")
    state.increment_merge_attempts(issue_number=3)
    state.set_closed_at(issue_number=3, when="2026-07-02T06:22:00+00:00")

    state.set_code_fingerprint(issue_number=3, fingerprint="abc123")

    record = state.find_by_issue(issue_number=3)
    assert record.code_passed_fingerprint == "abc123"
    assert record.block_gate == "merge"  # 不受影响
    assert record.block_watermark == "t1"  # 不受影响
    assert record.unblock_detail == "人类指导"  # 不受影响
    assert record.merge_attempts == 1  # 不受影响
    assert record.closed_at == "2026-07-02T06:22:00+00:00"  # 不受影响

    # 清 code_passed_fingerprint 不影响其余字段。
    state.set_code_fingerprint(issue_number=3, fingerprint="")
    record = state.find_by_issue(issue_number=3)
    assert record.code_passed_fingerprint == ""
    assert record.block_gate == "merge"
    assert record.closed_at == "2026-07-02T06:22:00+00:00"
