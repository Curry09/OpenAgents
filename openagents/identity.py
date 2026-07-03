"""RFC-0011 T2: 本地 agent 身份 + 评论签名。

每个 OpenAgents 实例持有一个稳定 `agent_id`，并给自己经 OpenAgents 发出的每条 PR 评论盖一个
隐藏 HTML 注释签名 `<!-- openagents:agent=<agent_id> -->`。

RFC-0019 现状对账：RFC-0011 原设计的「读侧」——poll 读 PR 评论 → 按签名剔除自评论 → 触发
`refine_rfc`/`iterate`——已被 RFC-0012 的 reviewer 闸取代且从未在 `messages.poll` 落地
（poll 不读 PR 评论）。因此本模块的活跃职责收敛为**写侧**：盖章（`sign` / `post_signed_comment`）
服务于评论**溯源/审计**，并为未来若复活读侧保留零成本接口。`parse_agent_id` 是 `sign` 的
验证逆函数，由测试断言盖章往返、并作为公开 API。

Spec-0032（issue #89）**定向复活读侧**于一个安全子集：`new_human_comments` 调
github.list_comments 读评论，用 `parse_agent_id` 滤掉一切带 OpenAgents 签名的机器评论、只留
「block 之后的无签名人类评论」，专供 messages 的 blocked 解挂判定（自动流转主路径仍由 reviewer
闸驱动，不读评论）。两道硬约束（仅新评论 + 仅人类签名）精确化解 RFC-0019 的自循环顾虑。

身份解析优先级（决策 2）：env OPENAGENTS_AGENT_ID > state 已存值 > 首次自动生成并落盘。
盖章逻辑收口在本模块（决策 4）：所有「agent 主动发评论」的调用方走 post_signed_comment，
github.post_comment 维持「对 gh pr comment 的薄封装、不含业务逻辑」的定位（理念 10：解耦）。
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime

from openagents import github
from openagents.state import State

# RFC-0011 决策 2：显式命名实例的环境变量；多 agent 协同时给运维一个可读的命名入口。
AGENT_ID_ENV = "OPENAGENTS_AGENT_ID"

# Spec-0049/T2：认领便签标记——与既有 agent 签名**并存**的第二段隐藏标记，把「认领便签」从
# 其它署名机器评论（precheck 对齐评论、reviewer 裁决回贴等同样带 <!-- openagents:agent=… -->
# 签名）里区分出来。GitHub 不渲染 HTML 注释，对人类零干扰；gh raw body 里可被 `in` 子串命中。
# 只需「在不在」判定（不带可变字段），故用常量 + 子串匹配，不引入正则（奥卡姆，理念 1）。
_CLAIM_MARKER = "<!-- openagents:claim -->"

# RFC-0011 决策 3：agent_id 字符集限制为 [A-Za-z0-9_-]，使签名正则稳健、不被正文意外撞匹配。
_AGENT_ID_CHARS = "A-Za-z0-9_-"

# 隐藏签名标记模板：GitHub Markdown 不渲染 HTML 注释，对人类读者零干扰，
# 但 gh pr view --json comments 返回的原始 body 里可被下方正则解析出来。
_SIGNATURE_TEMPLATE = "<!-- openagents:agent={agent_id} -->"

# 解析签名用的正则：只认严格匹配字符集的 agent_id，正文里的普通文字不会被误判。
_SIGNATURE_RE = re.compile(rf"<!-- openagents:agent=([{_AGENT_ID_CHARS}]+) -->")


def resolve_agent_id(*, state: State) -> str:
    """RFC-0011 决策 2：解析本实例 agent_id（env > state > 自动生成并落盘）。

    - env OPENAGENTS_AGENT_ID 非空白：直接用，不写 state（不污染落盘值，env 是临时覆盖）。
    - 否则 state 已有值：复用，保证跨进程/重启稳定。
    - 都没有：uuid4 生成短串，立即 state.set_agent_id 落盘，使后续进程拿到同一 id。

    返回非空、字符集受限（[A-Za-z0-9_-]）的稳定 id。
    """
    env_value = os.environ.get(AGENT_ID_ENV)
    if env_value and env_value.strip():
        return env_value.strip()

    existing = state.get_agent_id()
    if existing:
        return existing

    # uuid4 的十六进制短串：无外部依赖（理念 1），天然落在受限字符集内。
    generated = uuid.uuid4().hex[:12]
    state.set_agent_id(agent_id=generated)
    return generated


def sign(*, body: str, agent_id: str) -> str:
    """RFC-0011 决策 3：在 body 末尾追加隐藏签名标记，返回带签名的新正文（纯函数）。"""
    return f"{body}\n\n{_SIGNATURE_TEMPLATE.format(agent_id=agent_id)}"


def parse_agent_id(*, body: str) -> str | None:
    """RFC-0011：从 body 中解析签名里的 agent_id；无签名返回 None（纯函数）。

    RFC-0019：`sign` 的验证逆函数。当前无生产 poll 调用它过滤评论（评论驱动读侧已退役，
    poll 不读 PR 评论，自动流转由 reviewer 闸驱动）；保留作为公开 API + 测试盖章往返的断言对象，
    并为未来若复活读侧留接口。
    """
    match = _SIGNATURE_RE.search(body)
    return match.group(1) if match else None


def new_human_comments(*, pr_number: int, since: str) -> list[github.Comment]:
    """Spec-0032/T4：读侧复活——返回 PR 上「block 之后的新人类评论」，按时间升序。

    调 github.list_comments 取全量评论，保留同时满足两条硬约束的：
    - created_at 严格大于 `since`（挂起水位线 block_watermark）——历史评论、上次解挂前的评论
      都被滤掉；since="" 时任何非空 created_at 都算新（任意人类评论即可触发）。
    - parse_agent_id(body) is None（无 OpenAgents 隐藏签名）——一切带签名的机器评论（本实例刚
      贴的挂起评论、reviewer 回贴、refine/iterate/解冲突回贴）全被滤掉。

    两道约束叠加 → agent 永远读不到自己的评论自触发，精确还原 RFC-0011 读侧的安全子集、定向
    解除 RFC-0019「不读评论」限制（自动流转主路径仍由 reviewer 闸驱动，本函数只服务 blocked 解挂）。
    """
    fresh = [
        comment
        for comment in github.list_comments(pr_number=pr_number)
        if comment.created_at > since and parse_agent_id(body=comment.body) is None
    ]
    return sorted(fresh, key=lambda comment: comment.created_at)


def build_claim_note(*, agent_id: str) -> str:
    """Spec-0049/T2：构造一条**署名认领便签**正文——claim 标记 + agent 签名，供贴到 issue。

    认领 = 幂等 add 固定标签 + 追加这条便签（归属凭证 + 刷新新鲜度的新 created_at）。便签同时带
    两段隐藏标记：`_CLAIM_MARKER`（区分「这是认领便签」）与 `sign` 追加的 agent 签名（记「是谁
    认领」）。正文给人一行可读说明，隐藏标记只在 gh raw body 可见。与 latest_claim 互为逆：
    latest_claim(build_claim_note(agent_id=x)) 还原出 owner==x（测试断言往返保真）。
    """
    body = f"🤖 openagents 认领本 issue、起草中（派单去重便签）。\n\n{_CLAIM_MARKER}"
    return sign(body=body, agent_id=agent_id)


def latest_claim(*, comments: list[github.Comment]) -> tuple[str, float] | None:
    """Spec-0049/T2：从 issue 评论列表解析**最近一条认领便签**的 (owner_agent_id, age_seconds)。

    纯函数（唯一的「现在」来自 datetime.now，用于算年龄）：
    - 只认同时满足两条的评论：含 `_CLAIM_MARKER`（是认领便签，滤掉 precheck 对齐评论 / reviewer
      裁决回贴 / 无签名人类评论）**且** parse_agent_id 能取出 owner（有归属）。
    - 在这些认领便签里按 created_at（ISO 8601，字典序即时序）取**最新一条**，返回其 owner 与
      「now - created_at」秒龄。无任何有效认领便签 → None。

    归属 + 新鲜度一次读出：调用方（vigil 发现段判归属闸 / orchestrator 二次确认退让）据此判
    「是不是我的」「过没过期」。created_at 空/不可解析时保守判 age=0.0（未过期，宁可占坑多留一轮
    也不误判过期回收活后端）——与发现段「取不到证据保守判未过期」同源。
    """
    notes = [
        (comment, owner)
        for comment in comments
        if _CLAIM_MARKER in comment.body
        and (owner := parse_agent_id(body=comment.body)) is not None
    ]
    if not notes:
        return None
    comment, owner = max(notes, key=lambda pair: pair[0].created_at)
    return owner, _claim_age_seconds(created_at=comment.created_at)


def _claim_age_seconds(*, created_at: str) -> float:
    """Spec-0049/T2：认领便签 created_at（ISO 8601）距今秒数；空/不可解析保守判 0.0（未过期）。"""
    if not created_at:
        return 0.0
    try:
        stamped = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (datetime.now(UTC) - stamped).total_seconds()


def post_signed_comment(*, pr_number: int, body: str, agent_id: str) -> None:
    """RFC-0011 决策 4：盖章后调用 github.post_comment——所有「agent 主动发评论」的唯一出口。

    收口盖章逻辑，使 github.post_comment 保持纯薄封装。RFC-0019：签名服务于评论溯源/审计
    （poll 不再读评论做过滤，自动流转由 reviewer 闸驱动）。
    """
    github.post_comment(pr_number=pr_number, body=sign(body=body, agent_id=agent_id))
