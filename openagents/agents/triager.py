"""# Spec-0061/T2: agents.triager —— issue 分诊：对齐 + 冲突自检 → 结构化裁决（零逻辑）。

吸收旧 `align.restate`（把粗糙 issue 复述成 想做/边界/不做 三段）+ `issuecheck.check`（issue
内部「修复方向冲突」自检，issue #111 的五类冲突）的判断部分，降为 prompt 字符串。这两件事都是
**需要判断**的操作（issue 讲清楚了吗？改的方向自相矛盾吗？），故下放 agent 出结构化裁决；
recipes.vigil 只看 `actionable` 决定派单（True→solve_issue / False→记录机器可解释的拒绝），
自己零业务判断。

分诊纪律沿用 issuecheck 的 **fail-open**（宁可漏判、不可滥拦）：拿不准就判 actionable=True 放行——
过度拦截一个健康 issue 比漏判一个更糟（漏判的人还能在 PR 评审兜住，滥拦却直接冻住正常流转）。
与 reviewer 的 fail-closed 相反：这里是「进场闸」宽、那里是「出场闸」严。
"""

from string import Template

PROMPT = Template(
    """你是 issue 分诊 agent。判断 issue #$issue_number 是否可以直接派单开始解决，做两件事：
1) 对齐复述：用大白话把这个 issue 复述成「想做什么 / 边界在哪 / 明确不做什么」，确认你理解了需求；
2) 冲突自检：检查 issue 标题+正文里有没有会**直接影响修复方向**的内部矛盾（issue #111 五类）——
   ① 标题主张的修法 ≠ 正文主张的修法；② 根因分析 ≠ 建议的修法；③ 两个互斥修法都写了却没拍板选哪个；
   ④「问题是 A，但修的是 B」；⑤ 已知有取舍却没说明是否接受。

判定纪律（**fail-open，宁可漏判、不可滥拦**）：只有当上述矛盾确实存在、且会让实现 agent 起草时
跑偏方向，才判不可派单（actionable=false，reason 写清矛盾点 + 候选修法，供人对齐）；一切别的情况
——包括你拿不准、issue 只是略粗糙但方向明确——都判可派单（actionable=true）。别吹毛求疵、别因为
「不够详细」就拦，细节由实现 agent 读 spec 时补。

最后只输出一行 JSON：{"actionable": true 或 false, "reason": "<复述 + 判定理由；不可派单时写清矛盾点与候选修法>"}

issue 标题与正文由运行时在下方“上下文”区提供，只读取一次。
"""
)

OUTPUT_SCHEMA = {"actionable": bool, "reason": str}
