"""# Spec-0060/T1: utils.github —— 新栈的 gh 读 + 机器评论写稳定 import 面。

薄再导出现有 `github.py` 的 PR/issue 读原语与机器评论写原语，给新栈（runtime.context 组装
占位符、runtime.gates 判 PR 存在性、agents.deliver 报告）一个稳定 import 面，**不复制** 870 行
github.py（奥卡姆，理念 1），**不改动其任何一行**。

- **读**：`get_issue` / `find_pr_by_branch` / `list_comments` / `list_issue_comments` /
  `is_open` / `pr_head_branch`（PR 存在性探针）+ 数据类型 `Issue` / `PR` / `Comment` + `GithubError`。
- **机器评论写**：`post_comment`（PR 评论）/ `issue_comment`（issue 评论）。带 agent 署名、
  防自触发的**签名**评论写由 `identity.post_signed_comment` 承载（见 recipes 层按需引用），
  本模块只透传 github.py 的原始机器评论写原语。

所有名字均为对 github.py 同名原语的直接再导出，行为等价——新栈只依赖本稳定面，后续批次真把
github.py 搬进 utils/ 时下游 import 不必改。
"""

from __future__ import annotations

# Spec-0060/T1: 直接再导出 github.py 原语（读 + 机器评论写 + 类型），不复制、不改 github.py。
from openagents.github import (
    PR,
    Comment,
    GithubError,
    Issue,
    find_pr_by_branch,
    get_issue,
    is_open,
    issue_comment,
    list_comments,
    list_issue_comments,
    post_comment,
    pr_head_branch,
)

__all__ = [
    "Comment",
    "GithubError",
    "Issue",
    "PR",
    "find_pr_by_branch",
    "get_issue",
    "is_open",
    "issue_comment",
    "list_comments",
    "list_issue_comments",
    "post_comment",
    "pr_head_branch",
]
