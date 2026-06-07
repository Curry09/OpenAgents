"""RFC-0001 T4: State 本地 JSON 持久化（决策 4）的单元测试。

用 tmp_path 真实读写临时 .openagents/state.json（验证真实读写行为）；
覆盖：record_run 登记、状态机 update_status、comment 游标读写、all_runs、
文件不存在时容错为空。
"""

import json

from openagents.github import PR
from openagents.state import STATUS_PR_OPEN, STATUS_RFC_REVIEW, RunRecord, State


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


def test_record_run_with_rfc_review_status_writes_once(tmp_path):
    # RFC-0007 T1：record_run(status=rfc-review) 一次落盘即得 rfc-review + 非零 pr_number，
    # 无需随后再 update_status（消除瞬态 pr-open 窗口）。
    state = _new_state(tmp_path)
    pr = PR(number=5, url="https://github.com/acme/widget/pull/5")

    state.record_run(issue_number=3, branch="openagents/issue-3", pr=pr, status=STATUS_RFC_REVIEW)

    runs = state.all_runs()
    assert len(runs) == 1
    assert runs[0].status == STATUS_RFC_REVIEW
    assert runs[0].pr_number == 5
    # 真实落盘可读回。
    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.all_runs()[0].status == "rfc-review"


def test_record_run_defaults_to_pr_open(tmp_path):
    # RFC-0007 T1：不传 status 时默认仍落 pr-open（既有调用方/夹具不回归）。
    state = _new_state(tmp_path)
    pr = PR(number=7, url="https://github.com/acme/widget/pull/7")

    state.record_run(issue_number=3, branch="openagents/issue-3", pr=pr)

    assert state.all_runs()[0].status == STATUS_PR_OPEN


# --------------------------------------------------------------------------- #
# RFC-0011 T1：agent_id 持久化
# --------------------------------------------------------------------------- #


def test_get_agent_id_none_when_unset(tmp_path):
    # RFC-0011 T1：未设过 agent_id 时 get 返回 None。
    state = _new_state(tmp_path)
    assert state.get_agent_id() is None


def test_set_and_get_agent_id(tmp_path):
    # RFC-0011 T1：set 后 get 取回同值。
    state = _new_state(tmp_path)
    state.set_agent_id(agent_id="abc123")
    assert state.get_agent_id() == "abc123"


def test_agent_id_persists_to_disk(tmp_path):
    # RFC-0011 T1：真实落盘，跨 State 实例（即跨进程）读回一致。
    state = _new_state(tmp_path)
    state.set_agent_id(agent_id="abc123")

    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.get_agent_id() == "abc123"


def test_set_agent_id_overwrites(tmp_path):
    # RFC-0011 T1：后写覆盖前值。
    state = _new_state(tmp_path)
    state.set_agent_id(agent_id="first")
    state.set_agent_id(agent_id="second")
    assert state.get_agent_id() == "second"


def test_set_agent_id_preserves_runs_and_cursors(tmp_path):
    # RFC-0011 T1 验收：写 agent_id 不破坏既有 runs / cursors。
    state = _new_state(tmp_path)
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )
    state.set_cursor(pr_number=5, comment_id="2026-06-04T02:00:00Z")

    state.set_agent_id(agent_id="abc123")

    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.get_agent_id() == "abc123"
    assert len(reloaded.all_runs()) == 1
    assert reloaded.all_runs()[0].pr_number == 5
    assert reloaded.get_cursor(pr_number=5) == "2026-06-04T02:00:00Z"


def test_record_run_preserves_existing_agent_id(tmp_path):
    # RFC-0011 T1：先落 agent_id，再写 run，agent_id 不被 _load/_save 丢掉。
    state = _new_state(tmp_path)
    state.set_agent_id(agent_id="abc123")
    state.record_run(
        issue_number=3,
        branch="openagents/issue-3",
        pr=PR(number=5, url="https://github.com/acme/widget/pull/5"),
    )

    reloaded = State(path=tmp_path / ".openagents" / "state.json")
    assert reloaded.get_agent_id() == "abc123"
    assert len(reloaded.all_runs()) == 1


def test_get_agent_id_none_when_file_missing(tmp_path):
    # RFC-0011 T1：文件缺失容错为 None（与 cursors/runs 同风格）。
    state = _new_state(tmp_path)
    assert state.get_agent_id() is None


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
