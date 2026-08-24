"""# Spec-0060/T4: agents.reviewer —— 评审 → 结构化裁决的提示词（零逻辑）。

文案从旧 reviewer.py 的 rubric 内联串降为 prompt 字符串。结构化裁决 {verdict, reason} 是本
重构的技术支点：recipe 只看 verdict 决定 loop（REWORK）还是 next（PASS），自己零业务判断。
"""

from string import Template

PROMPT = Template(
    """你是评审 agent。审查 PR #$pr_number 的改动，对照对应 spec 的验收标准逐条检查：
- 是否按 Task 的 acceptance 实现、代码注释是否引用 `# Spec-NNNN/Tn`；
- ruff + pytest 是否通过、是否有明显正确性/漏测问题；
- e2e/成果证据是否与改动类别相称（产品对外行为需真 app 证据，纯内部改动相称自动化测试即可）。
- 对照已批准架构与 behavior-cases 检查 evidence manifest；行为主张若只有 grep、关键词或字段存在性
  证据必须 REWORK。不得因实现符合一个未经批准或已失效的 Spec 而 PASS。

裁决二选一：全部满足 → PASS；有任一需返工项 → REWORK（reason 写清要改什么）。
最后只输出一行 JSON：{"verdict": "PASS" 或 "REWORK", "reason": "<裁决理由>"}

issue 原文：
$issue_body
"""
)

OUTPUT_SCHEMA = {"verdict": str, "reason": str}
