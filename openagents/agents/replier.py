"""# Spec-0061/T2: agents.replier —— 回应 PR 上的人类评论 → 结构化回复（零逻辑）。

吸收旧 orchestrator `_HUMAN_UNBLOCK_TASK`（人在挂起 PR 上追问 → agent 继续改代码并**直接回应**
那条评论）的判断部分，降为 prompt 字符串。「这条人类评论想要什么、该怎么回、要不要动代码」是
**需要判断**的操作，故下放 agent 出结构化裁决；recipes.poll_comments 只负责拉新评论、把 agent
自述的 `reply` 盖签名回帖、按 `resolved` 决定是否推进状态，自己零业务判断。

回复经**签名**回帖（recipe 用 utils.identity.post_signed_comment）——盖上本 agent 签名后，回复
不会被下一轮 poll 当成新的人类评论，避免自触发死循环（旧 identity/conflict 的 reply-tool 纪律）。
"""

from string import Template

PROMPT = Template(
    """你是评论回应 agent。有人在 PR #$pr_number（工作分支 $branch）上回复了一条评论，请回应它：
1) 读懂这条评论想要什么（追问？要求改动？反对某处实现？）；
2) 若需要改代码就改（改完按交付协议 commit + push，让改动落到 PR head），若只是答疑则不必动代码；
3) 直接、具体地回应这条评论——回答追问 / 说明你改了什么 / 若仍有阻塞就诚实说清卡在哪，别打太极。

判定 resolved：你认为这条评论的诉求已被本轮回应/改动**充分解决** → true；仍需人进一步拍板/提供
信息 → false（reply 里写清还缺什么）。

最后只输出一行 JSON：{"reply": "<回给这条评论的正文>", "resolved": true 或 false}

这条评论的正文：
$comment_body
"""
)

OUTPUT_SCHEMA = {"reply": str, "resolved": bool}
