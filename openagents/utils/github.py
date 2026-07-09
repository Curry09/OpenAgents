"""# Spec-0060/T1 + Spec-0061/T1: utils.github —— 新栈的 gh 读写完整稳定 import 面。

薄再导出现有 `github.py` 的**全部**公共原语（读 / 写 / 机器评论 / 标签 / CI / 数据类型 /
流程标签常量 / 异常），给新栈（runtime.context 组装占位符、runtime.gates 判 PR 存在性、
recipes.vigil 发现派单、recipes.poll_comments 拉评论、agents.deliver 报告）一个稳定 import 面，
**不复制** 870 行 github.py（奥卡姆，理念 1），**不改动其任何一行**。

Spec-0060/T1 只立起 solve_issue 竖切依赖的最小读面；Spec-0061/T1 把再导出面扩成 github.py 的
完整公共 API——批次二的 vigil/poll_comments/fleet 三条 recipe 需要 issue 列举、PR 列举、标签
增删、CI 状态、可合并性、更新分支等全套确定性原语，新栈从此不再直接 `import openagents.github`
（只依赖本稳定面），后续批次真把 github.py 搬进 utils/ 时下游 import 零改动。

所有名字均为对 github.py 同名原语的直接再导出，行为等价；本模块自身零逻辑（纯再导出）。
"""

from __future__ import annotations

# Spec-0061/T1: 直接再导出 github.py 的全部公共 API（读 + 写 + 类型 + 常量 + 异常），
# 不复制、不改 github.py。
from openagents.github import (
    APPROVAL_LABEL,
    BLOCKED_LABEL,
    DISCOVERY_LABEL,
    DISPATCH_LABEL,
    PR,
    PROCESS_LABELS,
    CheckStatus,
    Comment,
    GithubError,
    Issue,
    Mergeability,
    add_label,
    branch_ci_green,
    check_status,
    close_issue,
    code_fingerprint,
    create_issue,
    create_pr,
    create_repo,
    ensure_label,
    ensure_prerequisites,
    find_pr_by_branch,
    get_issue,
    has_label,
    is_closed,
    is_draft,
    is_merged,
    is_open,
    issue_add_label,
    issue_comment,
    issue_remove_label,
    list_comments,
    list_issue_comments,
    list_issues,
    list_open_prs,
    mark_ready,
    merge_pr,
    mergeability,
    post_comment,
    pr_head_branch,
    remove_label,
    update_branch,
)

__all__ = [
    # 流程标签常量（单一真源）。
    "APPROVAL_LABEL",
    "BLOCKED_LABEL",
    "DISCOVERY_LABEL",
    "DISPATCH_LABEL",
    "PROCESS_LABELS",
    # 数据类型。
    "PR",
    "CheckStatus",
    "Comment",
    "Issue",
    "Mergeability",
    # 异常。
    "GithubError",
    # 标签 / CI / 可合并性。
    "add_label",
    "branch_ci_green",
    "check_status",
    "code_fingerprint",
    "ensure_label",
    "ensure_prerequisites",
    "has_label",
    "mergeability",
    "remove_label",
    "update_branch",
    # issue 读写。
    "create_issue",
    "get_issue",
    "list_issues",
    "list_issue_comments",
    "issue_add_label",
    "issue_comment",
    "issue_remove_label",
    "close_issue",
    # PR 读写。
    "create_pr",
    "create_repo",
    "find_pr_by_branch",
    "is_closed",
    "is_draft",
    "is_merged",
    "is_open",
    "list_comments",
    "list_open_prs",
    "mark_ready",
    "merge_pr",
    "post_comment",
    "pr_head_branch",
]
