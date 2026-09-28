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

若本轮要改 Python 源码，docstring 须合规（PEP 257 / PEP 8 / Google §3.8）：
- 模块 docstring：首行一句干净的英文人话摘要（句号结尾）→ 空行 → 用法示例 → `Exports:` 列出导出的类/异常/函数各带一行摘要；`__init__.py` 另列子模块/子包。**spec-id 上移为文件顶部的 `#` 注释行**（像 argparse.py 的 `# Author:`），**禁止 `\"\"\"# Spec-…` 写法**（`#` 会原样进 `__doc__` 污染 `help()`）。
- 函数/类 docstring：首行用**祈使句**、一行短句（≤80 字符、句号结尾）；spec 引用（`Spec-NNNN/Tn`）作**第二行**留 docstring 内；参数/返回/异常用 `Args:` / `Returns:` / `Raises:` 结构化。

判定 resolved：你认为这条评论的诉求已被本轮回应/改动**充分解决** → true；仍需人进一步拍板/提供
信息 → false（reply 里写清还缺什么）。

最后只输出一行 JSON：{"reply": "<回给这条评论的正文>", "resolved": true 或 false}

待回复评论由运行时在下方“上下文”区提供，只读取一次。
"""
)

# Spec-0016/T3: issue 页评论回复的提示词——issue #149「只要回复、不要解决」。
# 与 PR 版 PROMPT 刻意分家：**无** $branch（issue 尚无工作分支）、**无**「若需要改代码就改」分支
# （改代码/开 PR 是 solve 分支的事，issue reply 只答疑、不触发交付协议），故这里绝不诱导 agent 动代码。
# 复用同一 OUTPUT_SCHEMA（resolved 表这条评论诉求是否已被本轮答复充分解决）。PR 版 PROMPT 零改动。
ISSUE_PROMPT = Template(
    """你是 issue 评论回应 agent。有人在 issue #$issue_number 上追加了一条评论，请回应它：
1) 读懂这条评论想要什么（追问？补充需求？纠偏？）；
2) **只答疑、不改代码**——issue 尚在对齐阶段，你的职责是把这条评论回应清楚（回答追问 / 澄清你的理解 /
   确认收到并复述你打算怎么做），**不要**动任何代码、**不要**开 PR（那是后续 solve 阶段的事）；
3) 直接、具体地回应这条评论，别打太极；答不了 / 需求超出你能定的，就诚实说清卡在哪。

判定 resolved：你认为这条评论的诉求已被本轮回应**充分解决** → true；仍需人进一步拍板/提供信息 →
false（reply 里写清还缺什么）。

最后只输出一行 JSON：{"reply": "<回给这条评论的正文>", "resolved": true 或 false}

待回复评论由运行时在下方“上下文”区提供，只读取一次。
"""
)

OUTPUT_SCHEMA = {"reply": str, "resolved": bool}
