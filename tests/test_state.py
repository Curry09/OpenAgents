"""RFC-0001 T4: State 本地 JSON 持久化（决策 4）的单元测试。

用 tmp_path 真实读写临时 .openagents/state.json（验证真实读写行为）；
覆盖：record_run 登记、状态机 update_status、comment 游标读写、all_runs、
文件不存在时容错为空。
"""

import json

from openagents.github import PR
from openagents.state import STATUS_RFC_REVIEW, RunRecord, State


def _new_state(tmp_path):
    """构造一个指向临时 state 文件的 State。"""
    return State(path=tmp_path / ".openagents" / "state.json")


def test_all_runs_empty_when_file_missing(tmp_path):
    state = _new_state(tmp_path)
    assert state.all_runs() == []


def test_get_cursor_none_when_file_missing(tmp_path):
    state = _new_state(tmp_path)
    assert state.get_cursor(pr_number=42) is None


def test_record_run_creates_record_with_pr_open_status(tmp_path):
    state = _new_state(tmp_path)
    pr = PR(number=7, url="https://github.com/acme/widget/pull/7")

    state.record_run(issue_number=3, branch="openagents/issue-3", pr=pr)

    runs = state.all_runs()
    assert len(runs) == 1
    record = runs[0]
    assert isinstance(record, RunRecord)
    assert record.issue_number == 3
    assert record.branch == "openagents/issue-3"
    assert record.pr_number == 7
    assert record.pr_url == "https://github.com/acme/widget/pull/7"
    assert record.status == "pr-open"


def test_record_run_persists_to_disk(tmp_path):
    state = _new_state(tmp_path)
    pr = PR(number=7, url="https://github.com/acme/widget/pull/7")
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=pr)

    # 用一个全新的 State 实例从同一文件读，验证真实落盘。
    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    runs = reloaded.all_runs()
    assert len(runs) == 1
    assert runs[0].issue_number == 3
    assert runs[0].pr_number == 7


def test_record_run_writes_valid_json_file(tmp_path):
    state = _new_state(tmp_path)
    pr = PR(number=1, url="https://github.com/acme/widget/pull/1")
    state.record_run(issue_number=9, branch="openagents/issue-9", pr=pr)

    raw = json.loads((tmp_path / ".openagents" / "state.json").read_text())
    assert isinstance(raw, dict)


def test_update_status_transitions_record(tmp_path):
    state = _new_state(tmp_path)
    pr = PR(number=7, url="https://github.com/acme/widget/pull/7")
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=pr)

    state.update_status(issue_number=3, status="iterating")
    assert state.all_runs()[0].status == "iterating"

    state.update_status(issue_number=3, status="done")
    assert state.all_runs()[0].status == "done"


def test_update_status_persists(tmp_path):
    state = _new_state(tmp_path)
    pr = PR(number=7, url="https://github.com/acme/widget/pull/7")
    state.record_run(issue_number=3, branch="openagents/issue-3", pr=pr)
    state.update_status(issue_number=3, status="done")

    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.all_runs()[0].status == "done"


# RFC-0005 决策 6：游标存 comment 的 created_at（ISO 8601 字符串），原样读回不强转。
def test_set_and_get_cursor(tmp_path):
    state = _new_state(tmp_path)
    state.set_cursor(pr_number=7, comment_id="2026-06-04T02:00:00Z")
    assert state.get_cursor(pr_number=7) == "2026-06-04T02:00:00Z"


def test_cursor_persists(tmp_path):
    state = _new_state(tmp_path)
    state.set_cursor(pr_number=7, comment_id="2026-06-04T02:00:00Z")

    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.get_cursor(pr_number=7) == "2026-06-04T02:00:00Z"


def test_set_cursor_overwrites(tmp_path):
    state = _new_state(tmp_path)
    state.set_cursor(pr_number=7, comment_id="2026-06-04T01:00:00Z")
    state.set_cursor(pr_number=7, comment_id="2026-06-04T02:00:00Z")
    assert state.get_cursor(pr_number=7) == "2026-06-04T02:00:00Z"


def test_begin_run_records_solving_without_pr(tmp_path):
    # RFC-0003 决策 8：进入 solve 即记 solving、PR 待开（pr_number=0 / url 空）。
    state = _new_state(tmp_path)

    state.begin_run(issue_number=3, branch="openagents/issue-3")

    runs = state.all_runs()
    assert len(runs) == 1
    assert runs[0].status == "solving"
    assert runs[0].pr_number == 0
    assert runs[0].pr_url == ""


def test_record_run_replaces_begin_run_for_same_issue(tmp_path):
    # solving 记录在开 PR 后被 pr-open 覆盖（按 issue 去重），不残留两条。
    state = _new_state(tmp_path)
    state.begin_run(issue_number=3, branch="openagents/issue-3")
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )

    runs = state.all_runs()
    assert len(runs) == 1
    assert runs[0].status == "pr-open"
    assert runs[0].pr_number == 5


def test_find_by_issue_returns_record_or_none(tmp_path):
    # RFC-0003 决策 7：solve 按 issue 反查以分流 fresh / resume。
    state = _new_state(tmp_path)
    assert state.find_by_issue(issue_number=3) is None

    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )
    found = state.find_by_issue(issue_number=3)
    assert found is not None
    assert found.issue_number == 3
    assert found.pr_number == 5
    assert state.find_by_issue(issue_number=99) is None


def test_update_status_to_rfc_review(tmp_path):
    # RFC-0005：新增 rfc-review 状态（draft PR 承载 RFC、待评审）可落盘读回。
    state = _new_state(tmp_path)
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )

    state.update_status(issue_number=3, status=STATUS_RFC_REVIEW)

    assert state.all_runs()[0].status == STATUS_RFC_REVIEW
    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.all_runs()[0].status == "rfc-review"


def test_record_run_multiple_runs(tmp_path):
    state = _new_state(tmp_path)
    state.record_run(
        issue_number=1,
        branch="openagents/issue-1",
        pr=PR(number=10, url="https://github.com/acme/widget/pull/10"),
    )
    state.record_run(
        issue_number=2,
        branch="openagents/issue-2",
        pr=PR(number=11, url="https://github.com/acme/widget/pull/11"),
    )
    runs = state.all_runs()
    assert {r.issue_number for r in runs} == {1, 2}
