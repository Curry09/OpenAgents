"""# Spec-0061/T1: utils.identity —— 本实例身份 + 评论签名的稳定 import 面。

身份解析（env>state>生成落盘）、评论签名/验签、新人类评论探测、认领便签读写都是确定性机制
（不含业务判断），归 utils。recipes.poll_comments 靠 `new_human_comments` 拉未签名人类评论、
靠 `post_signed_comment` 盖签名回复（防下一轮把自己的回复当新人类评论、自触发死循环）；
recipes.vigil 靠 `latest_claim` 判认领归属。薄再导出现有 `identity.py`，不复制、不改动。

注：identity 读写侧依赖旧 `State`（resolve_agent_id/new_human_comments）；新栈接线时由 CLI 注入
现成 State（与旧路径同源，身份跨进程一致），本模块只透传原语、不改其依赖。
"""

from __future__ import annotations

# Spec-0061/T1: 再导出身份 + 签名原语（不改 identity.py）。
from openagents.identity import (
    AGENT_ID_ENV,
    build_claim_note,
    latest_claim,
    new_human_comments,
    parse_agent_id,
    post_signed_comment,
    resolve_agent_id,
    sign,
)

__all__ = [
    "AGENT_ID_ENV",
    "build_claim_note",
    "latest_claim",
    "new_human_comments",
    "parse_agent_id",
    "post_signed_comment",
    "resolve_agent_id",
    "sign",
]
