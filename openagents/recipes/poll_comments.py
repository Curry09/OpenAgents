"""# Spec-0061/T3: recipes.poll_comments —— 守候段：回应 PR 上的新人类评论（纯控制流，零业务判断）。

新栈的「消息机制」竖切：逐轮列 open PR，对每个 PR 拉「上次游标之后的**新人类评论**」，派 replier
agent 出结构化回复，据裁决路由——盖签名回帖，按 `resolved` 决定推进游标。整条循环**只**做三件事：
调 engine 派 agent、按 agent 的结构化裁决分支、调确定性 utils（评论拉取/签名回帖/游标持久化）；
自己不判「这条评论想要什么/该怎么回」（那是 replier 的活），也不直接碰 gh/git（那是 utils 的活）。

去重靠两道确定性机制，避免自触发死循环与重复回复：
  ① 只取**无 OpenAgents 签名**的人类评论（`utils.identity.new_human_comments` 按签名滤掉一切机器
     评论，含 replier 自己盖签名的回帖）——回复不会被下一轮当成新的人类评论；
  ② 只取 created_at **严于上次游标**的评论（`RuntimeState` 按 pr_number 存的 comment 游标）——
     处理过的评论不重复回。回帖走 `utils.identity.post_signed_comment` 盖本实例签名（配合①闭环）。

与旧 `messages.poll` 的 964 行阶段状态机（mergeability/CI/e2e/review/merge 全套闸）**不同**：新栈把
「一个 issue 的完整求解」收进同步 `solve_issue` 竖切，poll_comments 只承担「人在已开 PR 上追问 →
agent 回应」这一件事，职责单一（理念 1 奥卡姆 + 理念 10 解耦）。深度「据评论改代码」需 PR worktree，
留后续批次（见 spec Unresolved）；本批 replier 在传入的 work_dir 内运行，回应/答疑闭环即可跑通。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from openagents.agents import replier
from openagents.runtime import context, engine
from openagents.runtime.state import RuntimeState
from openagents.utils import github, identity


def poll_comments(
    *,
    backend: Any,
    state: RuntimeState,
    agent_id: str,
    work_dir: Path,
) -> list[dict]:
    """扫所有 open PR，对每个 PR 的新人类评论派 replier 回应，返回本轮事件列表。

    每个事件形如 `{"pr_number": int, "reason": "replied" | "resolved"}`（resolved=replier 判诉求
    已充分解决，否则 replied=已回应但仍需人跟进），便于日志与测试断言。单 PR 处理失败（gh/agent
    异常）只记一条 error 事件并 continue，绝不让异常掀翻整轮（错误隔离，对齐旧 messages.poll）。
    """
    events: list[dict] = []
    for pr in github.list_open_prs():
        try:
            event = _process_pr(
                pr_number=pr.number,
                backend=backend,
                state=state,
                agent_id=agent_id,
                work_dir=Path(work_dir),
            )
        except Exception as error:  # noqa: BLE001 —— 错误隔离：单 PR 失败不拖垮整轮
            events.append({"pr_number": pr.number, "reason": "error", "error": str(error)})
            continue
        if event is not None:
            events.append(event)
    return events


def _process_pr(
    *,
    pr_number: int,
    backend: Any,
    state: RuntimeState,
    agent_id: str,
    work_dir: Path,
) -> dict | None:
    """处理单个 PR：拉游标后的新人类评论 → 无则跳过 → 有则派 replier 回应最新一条 → 推进游标。

    只回应**最新一条**新人类评论（`new_human_comments` 已按 created_at 升序，取末条）：多条积压时
    回应最新的即代表当前诉求，游标一次推进到它、其余历史评论随游标跨过（不逐条刷屏回复）。回帖盖
    签名后写游标——顺序上先回帖再记游标，回帖失败则游标不动、下轮重试（宁可重回一次也不漏回）。
    """
    since = state.get_cursor(pr_number=pr_number) or ""
    news = identity.new_human_comments(pr_number=pr_number, since=since)
    if not news:
        return None
    latest = news[-1]
    branch = github.pr_head_branch(pr_number=pr_number)

    verdict = engine.run_agent(
        replier,
        backend=backend,
        **context.for_reply(work_dir=work_dir, pr_number=pr_number, branch=branch, comment=latest),
    )
    identity.post_signed_comment(pr_number=pr_number, body=verdict["reply"], agent_id=agent_id)
    # 游标推进到刚回应的评论 created_at（new_human_comments 的水位线语义）：下轮只取更新的评论。
    state.set_cursor(pr_number=pr_number, comment_id=latest.created_at)

    reason = "resolved" if verdict["resolved"] else "replied"
    _log(message=f"↩ PR #{pr_number}：已回应人类评论（{reason}）")
    return {"pr_number": pr_number, "reason": reason}


def _log(*, message: str) -> None:
    """守候进度打到 stderr，保证无人值守时仍有可观测轨迹（与 recipes.vigil 同通道）。"""
    print(message, file=sys.stderr, flush=True)
