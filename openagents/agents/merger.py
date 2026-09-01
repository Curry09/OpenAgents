"""# Spec-0017/T3: agents.merger —— 落合并动作 → 结构化合并报告的提示词（零逻辑）。

合并**不可逆**，故「可不可以合」这条红线由确定性硬闸 `gates.assert_merge_allowed`（CI 全绿 +
`review-approved:<head sha7>`@head）在派本 agent **之前**把守——本 agent 只在闸放行后被派上来落
「合并」这一个几乎零判断的机械动作（跑一条平台命令），换来的是架构一致性（生命周期动作全归
agent 层）。察觉硬闸没覆盖的异常时必须明确报告未合并，由统一机器失败路径收口。

Spec-0074/T1：平台命令参数化——原 GitHub CLI 合并/查看硬编码改 `$merge_command` /
`$verify_command` 占位符，由 stages.merge 经当前 forge driver 的 merge_command_text /
merge_verify_command_text 注入（GitHub 侧仍是原 gh 命令，行为零变化；Gitea 侧是
`openagents merge-pr --pr N`，token 处理留在 driver 内、凭证不进提示词）。
"""

from string import Template

PROMPT = Template(
    """你是合并 agent。PR #$pr_number 已通过确定性合并硬闸（CI 全绿 + review-approved 裁决绑当前 head），
「可不可以合」这条不可逆红线已由 harness 放行——你只需落最后一个动作：

`$merge_command`

完成判据：跑 `$verify_command`，输出含 "MERGED" 即已合并。已经是 MERGED 则视作已完成（幂等 no-op）。

若合并动作失败、或你察觉到硬闸没覆盖的异常（分支保护规则拦合、base 已变等），不要硬合、空转、假装成功，
也不要自行修改 forge 标签。最后输出 `{"merged": false, "summary": "具体阻塞原因与已核实事实"}`。
正常完成时输出 `{"merged": true, "summary": "<合并情况一句话>"}`。
"""
)

OUTPUT_SCHEMA = {"merged": bool, "summary": str}
