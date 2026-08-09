"""# Spec-0074/T2: Gitea driver 单测——假 HTTP 层（monkeypatch gitea._http）覆盖公共面请求形状与语义映射。

不触网络：全部经 `_FakeHttp` 回放 canned 响应并记录请求（method/path/body/query），逐条断言
Spec-0074 正文映射表（checks→combined status、mergeable bool 三态收敛、WIP 前缀、dependencies、
update 422、merge 幂等、标签名→id、瞬时 5xx 退避重试）。
"""

from __future__ import annotations

import pytest

from openagents.utils import gitea
from openagents.utils.github import GithubError


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    gitea.configure(settings={"base_url": "http://gitea.local", "owner": "own", "repo": "rep"})
    monkeypatch.setenv("GITEA_TOKEN", "tkn")
    gitea._label_ids.clear()
    yield
    gitea._label_ids.clear()


class _FakeHttp:
    """按序回放响应并记录每次请求（driver 的唯一传输缝）。"""

    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)

    def __call__(self, *, method, path, body, query):
        self.calls.append({"method": method, "path": path, "body": body, "query": query})
        status, data, text = self._responses.pop(0)
        return gitea._HttpResult(status=status, data=data, text=text)


def _install(monkeypatch, *responses):
    fake = _FakeHttp(responses)
    monkeypatch.setattr(gitea, "_http", fake)
    return fake


# --------------------------------------------------------------------------------------------------
# configure / 预检。
# --------------------------------------------------------------------------------------------------


def test_configure_requires_connection_keys():
    with pytest.raises(GithubError, match="缺少连接设置"):
        gitea.configure(settings={"base_url": "http://x"})


def test_token_missing_fails_loud(monkeypatch):
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    with pytest.raises(GithubError, match="GITEA_TOKEN"):
        gitea._token()


def test_ensure_prerequisites_probes_repo_and_labels(monkeypatch):
    existing = [
        {"id": index, "name": name} for index, name in enumerate(gitea.PROCESS_LABELS, start=1)
    ]
    fake = _install(
        monkeypatch,
        (200, {"full_name": "own/rep"}, ""),  # GET repos/own/rep
        (200, existing, ""),  # 首个 ensure 完整预读；其余全部命中缓存，零 POST
    )
    gitea.ensure_prerequisites()
    assert fake.calls[0] == {"method": "GET", "path": "repos/own/rep", "body": None, "query": None}
    assert [call["method"] for call in fake.calls] == ["GET", "GET"]


# --------------------------------------------------------------------------------------------------
# 标签：名→id、幂等。
# --------------------------------------------------------------------------------------------------


def test_ensure_label_creates_with_hash_color(monkeypatch):
    fake = _install(
        monkeypatch,
        (200, [], ""),  # POST 前完整预读，确实不存在
        (201, {"id": 7, "name": "ready"}, ""),
    )
    gitea.ensure_label(name="ready")
    assert [call["method"] for call in fake.calls] == ["GET", "POST"]
    assert fake.calls[1]["body"] == {"name": "ready", "color": "#ededed", "description": ""}
    assert gitea._label_ids["ready"] == 7


def test_ensure_label_existing_name_never_posts(monkeypatch):
    fake = _install(monkeypatch, (200, [{"id": 3, "name": "ready"}], ""))
    gitea.ensure_label(name="ready")
    assert gitea._label_ids["ready"] == 3
    assert [call["method"] for call in fake.calls] == ["GET"]


def test_ensure_label_creation_race_refreshes_cache(monkeypatch):
    fake = _install(
        monkeypatch,
        (200, [], ""),  # 预读时尚不存在
        (409, None, "already exists"),
        (200, [{"id": 3, "name": "ready"}], ""),  # 回退 GET labels
    )
    gitea.ensure_label(name="ready")
    assert gitea._label_ids["ready"] == 3
    assert [call["method"] for call in fake.calls] == ["GET", "POST", "GET"]


def test_ensure_label_reads_all_pages_before_creating(monkeypatch):
    monkeypatch.setattr(gitea, "_LIST_LIMIT", 2)
    fake = _install(
        monkeypatch,
        (200, [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], ""),
        (200, [{"id": 3, "name": "ready"}], ""),
    )
    gitea.ensure_label(name="ready")
    assert [call["query"]["page"] for call in fake.calls] == [1, 2]
    assert all(call["method"] == "GET" for call in fake.calls)


def test_issue_add_label_resolves_id(monkeypatch):
    gitea._label_ids["ready"] = 5
    fake = _install(monkeypatch, (200, [], ""))
    gitea.issue_add_label(number=9, name="ready")
    assert fake.calls[0]["method"] == "POST"
    assert fake.calls[0]["path"] == "repos/own/rep/issues/9/labels"
    assert fake.calls[0]["body"] == {"labels": [5]}


def test_issue_remove_label_unknown_label_is_noop(monkeypatch):
    fake = _install(monkeypatch, (200, [], ""))  # 仅 refresh 的 GET
    gitea.issue_remove_label(number=9, name="ghost")
    assert [call["method"] for call in fake.calls] == ["GET"]  # 无 DELETE


def test_issue_remove_label_404_is_noop(monkeypatch):
    gitea._label_ids["ready"] = 5
    _install(monkeypatch, (404, None, "not found"))
    gitea.issue_remove_label(number=9, name="ready")  # 不抛


# --------------------------------------------------------------------------------------------------
# issue 读写。
# --------------------------------------------------------------------------------------------------


def test_get_issue_parses_labels(monkeypatch):
    _install(
        monkeypatch,
        (200, {"number": 3, "title": "t", "body": "b", "labels": [{"name": "ready"}]}, ""),
    )
    issue = gitea.get_issue(number=3)
    assert issue.number == 3 and issue.labels == ("ready",)


def test_list_issues_uses_server_search_and_revalidates_response(monkeypatch):
    """# Spec-0074/T2: 标签过滤交 search API；若服务端混回脏数据，响应复核仍 fail-closed。"""
    fake = _install(
        monkeypatch,
        (200, [{"id": 11, "name": "openagents"}], ""),
        (
            200,
            [
                {
                    "number": 1,
                    "title": "wanted",
                    "body": "",
                    "labels": [{"name": "openagents"}],
                    "repository": {"full_name": "own/rep"},
                },
                {
                    "number": 2,
                    "title": "must-not-leak",
                    "body": "",
                    "labels": [{"name": "needs-triage"}],
                    "repository": {"full_name": "own/rep"},
                },
                {
                    "number": 3,
                    "title": "pr",
                    "body": "",
                    "labels": [{"name": "openagents"}],
                    "pull_request": {"merged": False},
                    "repository": {"full_name": "own/rep"},
                },
                {
                    "number": 4,
                    "title": "other-repo",
                    "body": "",
                    "labels": [{"name": "openagents"}],
                    "repository": {"full_name": "own/another"},
                },
            ],
            "",
        ),
    )
    issues = gitea.list_issues(labels=["openagents"])
    assert [issue.number for issue in issues] == [1]
    assert fake.calls[1]["path"] == "repos/issues/search"
    assert fake.calls[1]["query"] == {
        "owner": "own",
        "state": "open",
        "type": "issues",
        "labels": "openagents",
        "limit": gitea._LIST_LIMIT,
        "page": 1,
    }


def test_list_issues_multiple_labels_are_one_server_side_or_query(monkeypatch):
    fake = _install(
        monkeypatch,
        (200, [{"id": 11, "name": "openagents"}, {"id": 12, "name": "ready"}], ""),
        (
            200,
            [
                {
                    "number": 1,
                    "title": "a",
                    "body": "",
                    "labels": [{"name": "openagents"}],
                    "repository": {"full_name": "own/rep"},
                },
                {
                    "number": 2,
                    "title": "b",
                    "body": "",
                    "labels": [{"name": "ready"}],
                    "repository": {"full_name": "own/rep"},
                },
            ],
            "",
        ),
    )
    assert [issue.number for issue in gitea.list_issues(labels=["openagents", "ready"])] == [1, 2]
    assert fake.calls[1]["query"]["labels"] == "openagents,ready"
    assert len(fake.calls) == 2


def test_list_issues_unknown_label_is_zero_match_not_unfiltered(monkeypatch):
    """未知标签必须是「零匹配」——绝不能把 labels 参数省掉退化成全量发现（vigil 会吃进所有 issue）。"""
    fake = _install(
        monkeypatch,
        (200, [{"id": 3, "name": "other"}], ""),
    )
    assert gitea.list_issues(labels=["ghost"]) == []
    assert [call["path"] for call in fake.calls] == ["repos/own/rep/labels"]


def test_list_issues_paginates_without_losing_matches(monkeypatch):
    monkeypatch.setattr(gitea, "_LIST_LIMIT", 2)
    fake = _install(
        monkeypatch,
        (200, [{"id": 11, "name": "openagents"}], ""),
        (
            200,
            [
                {
                    "number": 1,
                    "title": "a",
                    "body": "",
                    "labels": [{"name": "other"}],
                    "repository": {"full_name": "own/rep"},
                },
                {
                    "number": 2,
                    "title": "b",
                    "body": "",
                    "labels": [{"name": "openagents"}],
                    "repository": {"full_name": "own/rep"},
                },
            ],
            "",
        ),
        (
            200,
            [
                {
                    "number": 3,
                    "title": "c",
                    "body": "",
                    "labels": [{"name": "openagents"}],
                    "repository": {"full_name": "own/rep"},
                }
            ],
            "",
        ),
    )
    assert [issue.number for issue in gitea.list_issues(labels=["openagents"])] == [2, 3]
    assert [call["query"]["page"] for call in fake.calls[1:]] == [1, 2]


def test_list_issues_without_labels_uses_repository_endpoint(monkeypatch):
    fake = _install(
        monkeypatch,
        (200, [{"number": 1, "title": "a", "body": "", "labels": []}], ""),
    )
    assert [issue.number for issue in gitea.list_issues(labels=[])] == [1]
    assert fake.calls[0]["path"] == "repos/own/rep/issues"
    assert "labels" not in fake.calls[0]["query"]


def test_list_issues_label_containing_comma_falls_back_to_local_filter(monkeypatch):
    fake = _install(
        monkeypatch,
        (200, [{"id": 11, "name": "team,a"}], ""),
        (
            200,
            [{"number": 1, "title": "a", "body": "", "labels": [{"name": "team,a"}]}],
            "",
        ),
    )
    assert [issue.number for issue in gitea.list_issues(labels=["team,a"])] == [1]
    assert [call["path"] for call in fake.calls] == [
        "repos/own/rep/labels",
        "repos/own/rep/issues",
    ]


def test_create_issue_maps_label_names_to_ids(monkeypatch):
    gitea._label_ids.update({"openagents": 11})
    fake = _install(monkeypatch, (201, {"number": 8}, ""))
    issue = gitea.create_issue(title="t", body="b", labels=["openagents"])
    assert issue.number == 8
    assert fake.calls[0]["body"] == {"title": "t", "body": "b", "labels": [11]}


def test_close_issue_404_is_noop(monkeypatch):
    _install(monkeypatch, (404, None, "not found"))
    gitea.close_issue(number=9)  # 不抛


def test_comments_author_association_owner_only(monkeypatch):
    _install(
        monkeypatch,
        (
            200,
            [
                {
                    "id": 1,
                    "user": {"login": "own"},
                    "body": "yes",
                    "created_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": 2,
                    "user": {"login": "guest"},
                    "body": "hi",
                    "created_at": "2026-01-02T00:00:00Z",
                },
            ],
            "",
        ),
    )
    comments = gitea.list_issue_comments(number=3)
    # 语义降级：只把配置 owner 认作 OWNER，其余 fail-closed 留空。
    assert comments[0].author_association == "OWNER"
    assert comments[1].author_association == ""


def test_pr_comments_share_issue_endpoint(monkeypatch):
    fake = _install(monkeypatch, (201, {}, ""))
    gitea.post_comment(pr_number=12, body="hello")
    assert fake.calls[0]["path"] == "repos/own/rep/issues/12/comments"


# --------------------------------------------------------------------------------------------------
# 依赖边（blocked_by）。
# --------------------------------------------------------------------------------------------------


def test_list_blocked_by_parses_state(monkeypatch):
    _install(monkeypatch, (200, [{"number": 4, "state": "closed"}], ""))
    blockers = gitea.list_blocked_by(number=9)
    assert blockers == [gitea.Blocker(number=4, state="CLOSED")]


def test_list_blocked_by_404_means_no_deps(monkeypatch):
    _install(monkeypatch, (404, None, ""))
    assert gitea.list_blocked_by(number=9) == []


def test_add_blocked_by_posts_issue_meta(monkeypatch):
    # Spec-0074 实证修复：仓名字段的 JSON key 是 `repo` 不是 `name`（传 name 被吞空 → 404）。
    fake = _install(monkeypatch, (201, {}, ""))
    gitea.add_blocked_by(number=9, blocker_number=4)
    assert fake.calls[0]["body"] == {"index": 4, "owner": "own", "repo": "rep"}


def test_add_blocked_by_duplicate_is_noop(monkeypatch):
    _install(monkeypatch, (409, None, "duplicate"))
    gitea.add_blocked_by(number=9, blocker_number=4)  # 不抛


def test_add_blocked_by_feature_unavailable_404_is_noop(monkeypatch):
    # Spec-0074 实证修复：依赖边是建议性特性（deps_done 机械复核兜底），404 与 list_blocked_by
    # 对称降级为 no-op——绝不能让可选特性失败把票挂死到 needs-human。
    _install(monkeypatch, (404, None, "not found"))
    gitea.add_blocked_by(number=9, blocker_number=4)  # 不抛


# --------------------------------------------------------------------------------------------------
# PR：draft/WIP、状态归一、mergeable 收敛、按分支查找。
# --------------------------------------------------------------------------------------------------


def test_create_pr_draft_uses_wip_prefix(monkeypatch):
    fake = _install(monkeypatch, (201, {"number": 5, "html_url": "u"}, ""))
    pr = gitea.create_pr(branch="b", title="t", body="", draft=True)
    assert pr.number == 5
    assert fake.calls[0]["body"]["title"] == "WIP: t"


def test_pr_for_branch_filters_by_head_ref(monkeypatch):
    fake = _install(
        monkeypatch,
        (
            200,
            [
                {"number": 1, "html_url": "u1", "head": {"ref": "other"}},
                {"number": 2, "html_url": "u2", "head": {"ref": "mine"}},
            ],
            "",
        ),
    )
    pr = gitea.pr_for_branch(branch="mine")
    assert pr is not None and pr.number == 2
    assert fake.calls[0]["query"]["state"] == "all"  # 不限状态——终止条件要能看见已合并 PR


def test_pr_snapshot_merged_and_mergeable_mapping(monkeypatch):
    _install(
        monkeypatch,
        (
            200,
            {
                "number": 5,
                "state": "closed",
                "merged": True,
                "title": "t",
                "head": {"sha": "abc"},
                "labels": [{"name": "x"}],
                "mergeable": False,
                "updated_at": "2026-01-01T00:00:00Z",
            },
            "",
        ),
    )
    snap = gitea.pr_snapshot(pr_number=5)
    assert snap.state == "MERGED"  # merged 布尔归一到三态互斥
    assert snap.mergeable == "CONFLICTING" and snap.merge_state_status == "DIRTY"
    assert snap.head_sha == "abc" and snap.labels == ("x",)


def test_pr_snapshot_missing_mergeable_is_unknown(monkeypatch):
    _install(
        monkeypatch,
        (
            200,
            {"number": 5, "state": "open", "title": "WIP: t", "head": {"sha": "a"}, "labels": []},
            "",
        ),
    )
    snap = gitea.pr_snapshot(pr_number=5)
    assert snap.mergeable == "UNKNOWN" and snap.merge_state_status == "UNKNOWN"
    assert snap.is_draft is True  # WIP 标题前缀即 draft


def test_mark_ready_strips_wip_prefix(monkeypatch):
    fake = _install(
        monkeypatch,
        (200, {"number": 5, "title": "WIP: t", "head": {}}, ""),
        (200, {}, ""),
    )
    gitea.mark_ready(pr_number=5)
    assert fake.calls[1]["method"] == "PATCH"
    assert fake.calls[1]["body"] == {"title": "t"}


def test_mark_ready_noop_when_not_draft(monkeypatch):
    fake = _install(monkeypatch, (200, {"number": 5, "title": "t", "head": {}}, ""))
    gitea.mark_ready(pr_number=5)
    assert len(fake.calls) == 1  # 只 GET，无 PATCH


def test_update_branch_already_up_to_date_returns_false(monkeypatch):
    _install(monkeypatch, (422, None, "nothing to do"))
    assert gitea.update_branch(pr_number=5) is False


def test_update_branch_rebase_style(monkeypatch):
    fake = _install(monkeypatch, (200, None, ""))
    assert gitea.update_branch(pr_number=5, rebase=True) is True
    assert fake.calls[0]["query"] == {"style": "rebase"}


def test_merge_pr_posts_do_method(monkeypatch):
    fake = _install(monkeypatch, (200, {}, ""))
    gitea.merge_pr(pr_number=5)
    assert fake.calls[0]["path"] == "repos/own/rep/pulls/5/merge"
    assert fake.calls[0]["body"] == {"Do": "merge"}


def test_merge_pr_already_merged_is_idempotent(monkeypatch):
    _install(
        monkeypatch,
        (405, None, "already merged"),
        (200, {"number": 5, "state": "closed", "merged": True, "title": "t"}, ""),  # is_merged 复读
    )
    gitea.merge_pr(pr_number=5)  # 不抛


def test_merge_pr_blocked_and_not_merged_raises(monkeypatch):
    _install(
        monkeypatch,
        (405, None, "blocked"),
        (200, {"number": 5, "state": "open", "merged": False, "title": "t"}, ""),
    )
    with pytest.raises(GithubError):
        gitea.merge_pr(pr_number=5)


# --------------------------------------------------------------------------------------------------
# CI：combined status 归类 / 计数 / 分支绿判。
# --------------------------------------------------------------------------------------------------

_PULL_HEAD = (200, {"number": 5, "state": "open", "title": "t", "head": {"sha": "abc"}}, "")


def test_check_status_failure_collects_logs(monkeypatch):
    _install(
        monkeypatch,
        _PULL_HEAD,
        (
            200,
            {
                "state": "failure",
                "statuses": [
                    {"context": "ci/test", "status": "failure", "target_url": "http://log"},
                    {"context": "ci/lint", "status": "success", "target_url": ""},
                ],
            },
            "",
        ),
    )
    status = gitea.check_status(pr_number=5)
    assert status.state == "fail"
    assert status.failed_logs == ["ci/test [FAILURE] http://log"]


def test_check_snapshot_zero_statuses_counts_zero(monkeypatch):
    _install(monkeypatch, _PULL_HEAD, (200, {"state": "", "statuses": []}, ""))
    snap = gitea.check_snapshot(pr_number=5)
    # 零 status 如实计 0——「没有 check」≠「绿」，判「等 CI」的责任在守夜调用方。
    assert snap.count == 0 and snap.state == "pass" and snap.latest_started_at == ""


def test_check_snapshot_counts_and_latest(monkeypatch):
    _install(
        monkeypatch,
        _PULL_HEAD,
        (
            200,
            {
                "state": "pending",
                "statuses": [
                    {"context": "a", "status": "pending", "created_at": "2026-01-01T00:00:00Z"},
                    {"context": "b", "status": "success", "created_at": "2026-01-02T00:00:00Z"},
                ],
            },
            "",
        ),
    )
    snap = gitea.check_snapshot(pr_number=5)
    assert snap.count == 2 and snap.state == "pending"
    assert snap.latest_started_at == "2026-01-02T00:00:00Z"


def test_branch_ci_green_zero_statuses_true(monkeypatch):
    _install(monkeypatch, (200, {"state": "", "statuses": []}, ""))
    assert gitea.branch_ci_green(branch="main") is True


def test_branch_ci_green_pending_false(monkeypatch):
    _install(monkeypatch, (200, {"state": "pending", "statuses": [{"status": "pending"}]}, ""))
    assert gitea.branch_ci_green(branch="main") is False


# --------------------------------------------------------------------------------------------------
# diff 指纹 / 重试 / 命令文本。
# --------------------------------------------------------------------------------------------------


def test_code_fingerprint_hashes_and_strips(monkeypatch):
    diff = (
        "diff --git a/src.py b/src.py\n+code\n"
        "diff --git a/docs/e2e-results/x b/docs/e2e-results/x\n+evidence\n"
    )
    _install(monkeypatch, (200, None, diff))
    fingerprint = gitea.code_fingerprint(pr_number=5)
    assert fingerprint  # 非空
    _install(monkeypatch, (200, None, "diff --git a/src.py b/src.py\n+code\n"))
    assert gitea.code_fingerprint(pr_number=5) == fingerprint  # 证据文件块不改指纹


def test_code_fingerprint_error_fail_open(monkeypatch):
    _install(monkeypatch, (500, None, "boom"))
    assert gitea.code_fingerprint(pr_number=5) == ""


def test_transient_5xx_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(gitea.time, "sleep", lambda seconds: None)
    _install(
        monkeypatch,
        (502, None, "bad gateway"),
        (200, {"number": 3, "title": "t", "body": "", "labels": []}, ""),
    )
    assert gitea.get_issue(number=3).number == 3


def test_network_error_retries_then_gives_up(monkeypatch):
    monkeypatch.setattr(gitea.time, "sleep", lambda seconds: None)

    def _always_timeout(*, method, path, body, query):
        raise TimeoutError("connect refused")

    monkeypatch.setattr(gitea, "_http", _always_timeout)
    with pytest.raises(GithubError, match="connect refused"):
        gitea.get_issue(number=3)


def test_merge_command_text_is_platform_neutral_cli():
    assert gitea.merge_command_text(pr_number=7) == "openagents merge-pr --pr 7"
    assert gitea.merge_verify_command_text(pr_number=7) == "openagents merge-pr --pr 7"
