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

from collections.abc import Callable

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
# issue #48：服务端合并冲突后被本地索引自愈消解（重渲 OVERVIEW + push），区别于人工 conflict。
RESULT_HEALED = "healed"
# Spec-0028/T3：indexheal 不适用的真冲突被 coding agent 语义解冲突消解（解 + 自测 + push），
# 区别于 RESULT_HEALED（确定性、仅 OVERVIEW）与 RESULT_CONFLICT（回落人工）。
RESULT_RESOLVED = "resolved"
# Spec-0033/T2：冲突回落时该 PR 已打 needs-human（人已介入、#89 读侧在管其评论对话）——扇出**跳过**
# 留言（不机械重发罐头淹没人的追问），区别于 RESULT_CONFLICT（真首发、留一条带诊断的签名评论）。
RESULT_CONFLICT_SUPPRESSED = "conflict-suppressed"


def rebase_open_prs(
    *,
    merged_pr_number: int | None = None,
    rebase: bool = False,
    agent_id: str,
    heal: Callable[..., bool] | None = None,
    resolve: Callable[..., bool] | None = None,
    diagnose: Callable[..., str] | None = None,
) -> list[dict]:
    """RFC-0009 T2：对每个 open PR（排除 merged_pr_number）执行 github.update_branch。

    merged_pr_number：刚合并的 PR 编号——合并后它已不在 open 列表，但合并瞬间存在竞态，
    故再显式排除一次兜底；None 表示不排除、同步全部 open PR（手动入口缺省）。
    rebase：True 用 rebase、False（默认）用 merge 方式同步（决策 2）。
    agent_id：RFC-0011 T5 新增必填——冲突留言据此盖本实例签名，用于评论溯源/审计
    （RFC-0019：poll 不再读评论做签名过滤，自动流转由 reviewer 闸驱动）。
    保持无状态：rebase 不读 state，agent_id 由 messages/CLI 透传（理念 10）。

    Spec-0028/T3：冲突处理改为**分层降级** heal → resolve → 人工留言：
    - heal（issue #48，确定性、仅 OVERVIEW）命中 → RESULT_HEALED。
    - 否则 resolve（本组，coding agent 语义解真冲突）命中 → RESULT_RESOLVED。
    - 两层都没命中（或未注入）才 post_signed_comment + RESULT_CONFLICT。
    resolve=None（如手动 sync-prs，不在人手动命令里偷烧 token）即跳过该层，行为同今天。

    Spec-0033/T2：冲突回落分支（heal/resolve 都没命中）再分两路，以堵住唯一还在「机械重发罐头」
    的通道——
    - **重发收敛**：先 github.has_label(pr, BLOCKED_LABEL)。已 needs-human（人已介入、#89 读侧在管
      其评论对话）→ 跳过留言、记 RESULT_CONFLICT_SUPPRESSED、续下一个——不再贴第二/三句同样的罐头
      淹没人的追问（issue #92 的 A：评论只出不进 / 机械重发）。
    - **首发带诊断**：未打标签 → 留言正文取 diagnose(pr_number)（带冲突文件清单 + 关键 hunk 摘要）；
      diagnose is None（如手动 sync-prs 不注入诊断器）或其返回兜底文案时，正文即静态 CONFLICT_COMMENT。
    保持无状态：rebase 不持有 work_dir，诊断能力由 messages/CLI 透传 diagnose（与 heal/resolve 同构）。

    返回事件列表，每项 {"pr_number": int, "result": str}，result ∈ {RESULT_UPDATED, RESULT_UP_TO_DATE,
    RESULT_HEALED, RESULT_RESOLVED, RESULT_CONFLICT, RESULT_CONFLICT_SUPPRESSED}（供日志/测试断言）。
    冲突时留言（或抑制）并继续后续，不中断整轮扇出（决策 4，错误隔离）。
    """
    events: list[dict] = []
    for pr in github.list_open_prs():
        if merged_pr_number is not None and pr.number == merged_pr_number:
            continue
        try:
            updated = github.update_branch(pr_number=pr.number, rebase=rebase)
        except github.GithubError:
            # issue #48：服务端合并冲突——先试本地索引自愈（仅 OVERVIEW 冲突即重渲消解 + push）。
            # heal 安全降级：返回 True=已自愈、False/未注入=进入下一层（resolve）（决策 4）。
            if heal is not None and heal(pr_number=pr.number):
                events.append({"pr_number": pr.number, "result": RESULT_HEALED})
                continue
            # Spec-0028/T3：indexheal 不适用的真冲突——派 coding agent 语义解决（解 + 自测 + push）。
            # resolve 安全降级：返回 True=已解决、False/未注入=回落到下面的人工留言路径。
            if resolve is not None and resolve(pr_number=pr.number):
                events.append({"pr_number": pr.number, "result": RESULT_RESOLVED})
                continue
            # Spec-0033/T2：重发收敛——已 needs-human 的 PR（人已介入、#89 读侧在管）跳过留言，
            # 不机械重发同一句罐头淹没人的追问；把对话权交回 blocked 读侧闭环。
            if github.has_label(pr_number=pr.number, name=github.BLOCKED_LABEL):
                events.append({"pr_number": pr.number, "result": RESULT_CONFLICT_SUPPRESSED})
                continue
            # Spec-0033/T2：首发带诊断——有诊断器则取带冲突文件清单 + 关键 hunk 摘要的正文，
            # diagnose 缺省（手动 sync-prs）或返回兜底文案时退回静态 CONFLICT_COMMENT。
            body = diagnose(pr_number=pr.number) if diagnose is not None else CONFLICT_COMMENT
            # RFC-0011 T5：走 identity.post_signed_comment 给留言盖本实例签名，用于评论溯源/审计
            # （RFC-0019：poll 不读评论，自动流转由 reviewer 闸驱动，无自循环；#89 读侧按签名滤掉它）。
            identity.post_signed_comment(pr_number=pr.number, body=body, agent_id=agent_id)
            events.append({"pr_number": pr.number, "result": RESULT_CONFLICT})
            continue
        result = RESULT_UPDATED if updated else RESULT_UP_TO_DATE
        events.append({"pr_number": pr.number, "result": result})
    return events
