"""RFC-0011 T2: 本地 agent 身份 + 评论签名。

把「区分自评论 vs 非自评论」的判定收口到一个去中心化的本地身份：每个 OpenAgents
实例持有一个稳定 `agent_id`，并给自己经 OpenAgents 发出的每条 PR 评论盖一个隐藏
HTML 注释签名 `<!-- openagents:agent=<agent_id> -->`。poll 据此剔除自己的回贴，
不再依赖「按 GitHub 账号过滤」（人机共用账号会误杀真人）或「推游标吃自评论」
（非原子、抗崩溃差），根治崩溃自循环 / 误跳真人 / 同秒撞车三个缺陷（决策 1）。

身份解析优先级（决策 2）：env OPENAGENTS_AGENT_ID > state 已存值 > 首次自动生成并落盘。
盖章逻辑收口在本模块（决策 4）：所有「agent 主动发评论」的调用方走 post_signed_comment，
github.post_comment 维持「对 gh pr comment 的薄封装、不含业务逻辑」的定位（理念 10：解耦）。
"""

from __future__ import annotations

import os
import re
import uuid

from openagents import github
from openagents.state import State

# RFC-0011 决策 2：显式命名实例的环境变量；多 agent 协同时给运维一个可读的命名入口。
AGENT_ID_ENV = "OPENAGENTS_AGENT_ID"

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

    poll 用它判定「这条评论是不是我自己发的」：parse_agent_id(body) == 我的 id 即剔除。
    """
    match = _SIGNATURE_RE.search(body)
    return match.group(1) if match else None


def post_signed_comment(*, pr_number: int, body: str, agent_id: str) -> None:
    """RFC-0011 决策 4：盖章后调用 github.post_comment——所有「agent 主动发评论」的唯一出口。

    收口盖章逻辑，使 github.post_comment 保持纯薄封装；下一轮 poll 即可据签名剔除本回贴。
    """
    github.post_comment(pr_number=pr_number, body=sign(body=body, agent_id=agent_id))
