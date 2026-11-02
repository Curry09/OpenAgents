# Spec-0076/T3
"""Review an admitted objective's implementation architecture before coding.

Exports:
    PROMPT: Architecture-review task template.
    OUTPUT_SCHEMA: Structured architecture verdict contract.
"""

from string import Template

# Spec-0093/T2: role-specific duties consume the engine-verified contract context.
PROMPT = Template(
    """你是实现前技术架构评审 agent。审查 issue #$issue_number 的候选 Spec（design digest=$design_digest）。

已核验执行合同是目标的使用前提：审查每个来源的输入可用性、预算和公开交付物是否仍可满足。non-goals 排除这些条件、无人任务依赖第二条目标消息或只证明符合旧 Spec，均须指出具体缺口。
需求目标已经准入：你不重新做产品发现或价值准入，也不编写实现。你要独立检查从目标到技术方案的转换：
1. objective_fidelity：是否保持目标，并把 issue 中的实现建议当候选而非约束；
2. intervention_fit：所选层是否真正拥有待改变行为，是否基于当前仓库证据比较了可行候选；
3. boundary_integrity：接口、并发、状态、进程生命周期、兼容与失败恢复中相关边界是否闭合；
4. verification_strength：验收是否观察行为结果，且有能推翻方案的 negative case；行为主张不能只靠
   grep、关键词或字段存在性证明。

候选 Spec 上下文末尾可能附有 evidence_pack。它是前序角色记录的客观仓库证据，仅用于证据定位，不构成
架构结论。应复核影响干预层、状态边界或失败恢复的关键事实；仅在证据缺失、陈旧或相互矛盾时执行渐进式
补充取证，避免重复进行全仓扫描。

任一维度不成立即 REWORK；缺少判断所需证据时也返回 REWORK，并在 reason/findings 点明缺口，禁止用猜测 PASS。
最后只输出一行 JSON：
{"verdict":"PASS 或 REWORK","objective_fidelity":"结论","intervention_fit":"结论",
 "boundary_integrity":"结论","verification_strength":"结论","reason":"可执行意见","findings":[]}

完整候选 Spec、issue 上下文与 evidence_pack 由运行时在下方“上下文”区提供；只读取一次，
不要把它重新复制到输出。
"""
)

OUTPUT_SCHEMA = {
    "verdict": str,
    "objective_fidelity": str,
    "intervention_fit": str,
    "boundary_integrity": str,
    "verification_strength": str,
    "reason": str,
    "findings": list,
}

__all__ = ["PROMPT", "OUTPUT_SCHEMA"]
