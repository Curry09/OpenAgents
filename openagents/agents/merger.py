"""# Spec-0017/T3: agents.merger —— 落合并动作 → 结构化合并报告的提示词（零逻辑）。

合并**不可逆**，故「可不可以合」这条红线由确定性硬闸 `gates.assert_merge_allowed`（CI 全绿 +
`review-approved:<head sha7>`@head）在派本 agent **之前**把守——本 agent 只在闸放行后被派上来落
「合并」这一个几乎零判断的机械动作（跑一条 `gh pr merge`），换来的是架构一致性（生命周期动作全归
agent 层）+ 一个最后关头的 `needs-human` 一等出口（察觉硬闸没覆盖的异常时主动交人，绝不硬合）。
"""

from string import Template

PROMPT = Template(
    """你是合并 agent。PR #$pr_number 已通过确定性合并硬闸（CI 全绿 + review-approved 裁决绑当前 head），
「可不可以合」这条不可逆红线已由 harness 放行——你只需落最后一个动作：

`gh pr merge $pr_number --merge`

完成判据：`gh pr view $pr_number --json state` 的 state == "MERGED"。已经是 MERGED 则视作已完成（幂等 no-op）。

【一等出口 needs-human】若合并动作反复失败、或你察觉到硬闸没覆盖的异常（分支保护规则拦合、base 已变、
其它一切让你没把握直接合的情形）——**不要硬合、不要空转、不要假装合成功**：给该 PR 打上 `needs-human`
label、留一条说明理由的评论，然后正常收工把 merged 报 false。守夜会当场判终态、把理由交给人。

最后只输出一行 JSON：{"merged": true 或 false, "summary": "<合并情况一句话>"}
"""
)

OUTPUT_SCHEMA = {"merged": bool, "summary": str}
