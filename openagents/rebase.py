"""RFC-0009 T2: 合并后自动同步其余 open PR 的扇出模块。

一个 PR 合并进 main 后，其余 open PR 仍停留在旧 base，与 main 产生差异/潜在冲突。
`rebase_open_prs` 列出所有 open PR、排除刚合并的那个、逐个 `github.update_branch`
（默认把最新 main 以合并提交并入，触发各 PR 的 CI 重跑）；遇冲突（GithubError）时在
该 PR 留言提示人工 rebase 并继续下一个——单个 PR 失败不拖垮整轮扇出（错误隔离，
沿用 RFC-0004 决策 8 的风格）。

解耦设计（CLAUDE.md 理念 10）：以模块函数方式调用 github.*，不持有状态；既被
messages.poll 的合并分支自动驱动（决策 1），也被 `openagents sync-prs` 手动入口复用
（决策 6）。测试里 monkeypatch github.list_open_prs / update_branch / post_comment 即可
保持 hermetic（不触达真实 gh）。
"""

from __future__ import annotations

from openagents import github, identity

# RFC-0009 决策 4：冲突时贴给 PR 的提示文案——以模块常量定义，便于测试断言与统一维护。
CONFLICT_COMMENT = (
    "🤖 OpenAgents 在 main 更新后尝试自动同步本 PR 分支，但存在无法自动解决的冲突，"
    "请手动 rebase / 解决冲突后重新 push。"
)

# 同步结果分类（决策 4/5）：供日志与测试断言。
RESULT_UPDATED = "updated"
RESULT_UP_TO_DATE = "up-to-date"
RESULT_CONFLICT = "conflict"


def rebase_open_prs(
    *, merged_pr_number: int | None = None, rebase: bool = False, agent_id: str
) -> list[dict]:
    """RFC-0009 T2：对每个 open PR（排除 merged_pr_number）执行 github.update_branch。

    merged_pr_number：刚合并的 PR 编号——合并后它已不在 open 列表，但合并瞬间存在竞态，
    故再显式排除一次兜底；None 表示不排除、同步全部 open PR（手动入口缺省）。
    rebase：True 用 rebase、False（默认）用 merge 方式同步（决策 2）。
    agent_id：RFC-0011 T5 新增必填——冲突留言据此盖本实例签名，使下一轮 poll 据签名
    剔除这条自评论（保持无状态：rebase 不读 state，agent_id 由 messages/CLI 透传，理念 10）。

    返回事件列表，每项 {"pr_number": int, "result": str}，
    result ∈ {RESULT_UPDATED, RESULT_UP_TO_DATE, RESULT_CONFLICT}（供日志/测试断言）。
    冲突时留言并继续后续，不中断整轮扇出（决策 4，错误隔离）。
    """
    events: list[dict] = []
    for pr in github.list_open_prs():
        if merged_pr_number is not None and pr.number == merged_pr_number:
            continue
        try:
            updated = github.update_branch(pr_number=pr.number, rebase=rebase)
        except github.GithubError:
            # 决策 4：无法自动并入（冲突等）→ 留言提示人工处理，记 conflict 后继续下一个。
            # RFC-0011 T5：走 identity.post_signed_comment 盖签名，避免自评论触发自循环。
            identity.post_signed_comment(
                pr_number=pr.number, body=CONFLICT_COMMENT, agent_id=agent_id
            )
            events.append({"pr_number": pr.number, "result": RESULT_CONFLICT})
            continue
        result = RESULT_UPDATED if updated else RESULT_UP_TO_DATE
        events.append({"pr_number": pr.number, "result": result})
    return events
