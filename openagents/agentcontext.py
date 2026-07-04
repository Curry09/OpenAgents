"""Spec-0050/T1：统一 agent 上下文构造——build_agent_context。

OpenAgents 每次派 coding agent（精炼 spec / 实现 / 迭代 / 评审）时喂给它的 `context` 今天既
不统一也不完整：PR 号有的入口写进 prompt、有的不写；所有 agent 都看不到**本 PR 的对话历史**
（历轮评审裁决、作者历轮回复、人类评论）。本模块抽出唯一构造入口 `build_agent_context`，同时
负责两件事：① 保证 PR 号进入上下文；② 拉取本 PR 对话历史，按作者身份 + 轮次渲染、去噪、截断后
拼进 `context`，让每个 agent 都能看到「这个 PR 之前发生过什么」（issue #129 缺口一/缺口二）。

解耦定位（CLAUDE.md 理念 10）：本模块只依赖 `github` 读原语（list_comments）+ `identity` 解析
原语（parse_agent_id），**不碰 git / state / 编排**——便于 hermetic 单测（打桩 github.list_comments
即可）。分类去噪用到的机器标记（认领便签 / 裁决抬头 / 作者 refine 说明）以本地常量匹配，不 import
reviewer / orchestrator（避免耦合 + 循环 import）；这些常量的规范来源在注释里标注，其同步由 T4
集成测试（用 reviewer.render_decision / orchestrator._REFINE_COMMENT 造真实评论）兜底防漂移。
"""

from __future__ import annotations

import re

from openagents import github, identity

# 历史块长度上限：超出则「保留最近若干条 + 头部标注省略」压缩，控制塞进 prompt 的长度
# （与 claude_code._SUMMARY_MAX_LEN 同源的「别让上下文无限膨胀」思路）。多轮 PR 上历史会累积，
# 最近的澄清 / 共识最相关，故按时序保留尾部。取值待集成测试标定（Spec-0050 Unresolved questions）。
_HISTORY_MAX_CHARS = 4000

# 分类去噪用的机器评论标记（规范来源在别处，此处以本地常量匹配以保持解耦）：
# - 认领便签标记：identity._CLAIM_MARKER（Spec-0049/T2）——派单去重便签，纯噪声，过滤。
# - 评审闸裁决抬头：reviewer._DECISION_HEADER（Spec-0047/T1）——历轮裁决，保留。
# - 作者 refine 说明前缀：orchestrator._REFINE_COMMENT（RFC-0005 决策 6）——作者历轮回复，保留。
_CLAIM_MARKER = "<!-- openagents:claim -->"
_DECISION_HEADER = "## 评审闸裁决"
_REFINE_MARKER = "🤖 已根据评审意见更新 spec"

# 隐藏 HTML 注释（签名 <!-- openagents:agent=… --> / 认领标记 / 其它埋点）——渲染历史前整段剥除，
# 避免签名噪声污染上下文。GitHub 本就不渲染 HTML 注释，剥掉不丢人类可读信息。
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def build_agent_context(*, pr_number: int, extra_detail: str) -> str:
    """Spec-0050/T1：构造一段统一的 agent `context`——PR 号 + 本 PR 对话历史 + 本轮反馈。

    结构固定为三块（各自缺省时优雅降级，不产空标题块）：
      ① 一行「本 PR 是 #N」把 PR 号带进上下文；
      ② 「## 本 PR 对话历史（供背景参考）」——按 created_at 升序、每条标注作者 + 第几轮 + 时间，
         含历轮评审闸裁决 / 作者 refine 说明 / 人类评论（去噪 + 截断，见 `_render_history`）；
      ③ 「## 本轮具体反馈」——调用方原本要传的 extra_detail（reviewer 本轮意见 / 单条人类评论 /
         CI 日志……）。

    唯一副作用是读 `github.list_comments`（受 RFC-0010 瞬时重试兜底）。硬失败时 fail-open：历史降级
    为空、只留 PR 号 + 本轮反馈——一次评论读失败不应打断核心的 refine/implement/iterate/review 流程
    （呼应本仓库对只读增强的 fail-open 取舍，见 orchestrator._post_review_decision 去重降级）。
    """
    try:
        comments = github.list_comments(pr_number=pr_number)
    except github.GithubError:
        comments = []
    history = _render_history(comments=comments)

    parts = [f"本 PR 是 #{pr_number}。"]
    if history:
        parts.append(f"## 本 PR 对话历史（供背景参考）\n{history}")
    detail = (extra_detail or "").strip()
    if detail:
        parts.append(f"## 本轮具体反馈\n{detail}")
    return "\n\n".join(parts)


def _render_history(*, comments: list[github.Comment]) -> str:
    """Spec-0050/T1：把 PR 评论列表分类去噪 → 按时序渲染 → 截断，返回历史块正文（纯函数）。

    保留三类（正是要让 agent 看见的历史）：评审闸裁决、作者 refine 说明、一切人类评论；
    过滤认领便签与其它纯噪声机器评论。每条剥掉隐藏 HTML 注释签名后渲染成
    `【第 k 轮 · <author> · <created_at>】\\n<正文>`，历史为空返回空串。
    """
    kept = [comment for comment in comments if _should_keep(comment=comment)]
    kept.sort(key=lambda comment: comment.created_at)
    entries: list[str] = []
    for index, comment in enumerate(kept, start=1):
        body = _strip_signatures(text=comment.body).strip()
        author = comment.author or "（未知作者）"
        stamp = comment.created_at or "（无时间）"
        entries.append(f"【第 {index} 轮 · {author} · {stamp}】\n{body}")
    return _truncate(entries=entries)


def _should_keep(*, comment: github.Comment) -> bool:
    """Spec-0050/T1：判定一条评论是否进历史（保留裁决 / 作者回复 / 人类评论，滤认领便签+机器噪声）。

    认领便签（含 `_CLAIM_MARKER`）无论是否署名一律过滤——它是派单去重噪声。无 OpenAgents 签名的
    即人类评论，保留。带签名的机器评论仅当是评审闸裁决或作者 refine 说明才保留，其余（指路牌 /
    对齐评论 / 解冲突回贴等）作纯噪声过滤。
    """
    body = comment.body
    if _CLAIM_MARKER in body:
        return False
    if identity.parse_agent_id(body=body) is None:
        return True
    return _DECISION_HEADER in body or _REFINE_MARKER in body


def _strip_signatures(*, text: str) -> str:
    """Spec-0050/T1：剥掉正文里的隐藏 HTML 注释（签名 / 认领标记 / 埋点），返回可读正文（纯函数）。"""
    return _HTML_COMMENT_RE.sub("", text)


def _truncate(*, entries: list[str]) -> str:
    """Spec-0050/T1：历史条目按 `\\n\\n` 拼接；超 `_HISTORY_MAX_CHARS` 时保留最近若干条 + 标注省略。

    从最新一条起向前累加，直到再加一条会超上限即停；至少保留最新一条（哪怕它单条就超上限——
    最近的反馈最相关）。截断时头部标注「（更早的 N 条历史已省略）」，让 agent 知道有更早历史被裁掉。
    """
    if not entries:
        return ""
    full = "\n\n".join(entries)
    if len(full) <= _HISTORY_MAX_CHARS:
        return full
    kept: list[str] = []
    total = 0
    for entry in reversed(entries):
        added = len(entry) + (2 if kept else 0)  # 2 = 段间 "\n\n"
        if kept and total + added > _HISTORY_MAX_CHARS:
            break
        kept.append(entry)
        total += added
    kept.reverse()
    omitted = len(entries) - len(kept)
    body = "\n\n".join(kept)
    return f"（更早的 {omitted} 条历史已省略）\n\n{body}" if omitted else body
