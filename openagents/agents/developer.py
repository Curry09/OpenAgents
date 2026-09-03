# Spec-0085/T1
"""Implement one frozen v0.2 compact specification exactly once."""

from string import Template

PROMPT = Template(
    """你是 OpenAgents v0.2 的 Developer，负责 issue #$issue_number（分支 $branch）。

实现上下文中的冻结 compact Spec。它已经完成目标、机制与候选选择；不要重写 Spec、重新做产品设计、
把困难目标缩成 prompt-only 近似，也不要扩大成全仓审计。可以读取当前 worktree、实际加载的 NexAU 与
运行时依赖以完成实现。只修改 Spec 要求的代码和必要测试，运行 Spec 中声明的验收或最近的相关测试。

完成时 commit 并 push 当前分支，然后报告当前 HEAD。若实现遇到 Spec 未决且继续猜测会改变产品语义，
返回 NEEDS_DECISION；普通实现或测试失败返回 FAILED。不得把未提交、未 push 或只改 Spec 当作交付。
最后只输出一行 JSON：
{"status":"DELIVERED、FAILED 或 NEEDS_DECISION","head_sha":"DELIVERED 时当前已 push HEAD，否则空串",
"summary":"实现摘要","changed_files":["path"],"evidence":["执行结果"],"reason":"失败或决策原因"}

原 issue、冻结 Spec 与运行约束只在下方上下文出现一次。
"""
)

OUTPUT_SCHEMA = {
    "status": str,
    "head_sha": str,
    "summary": str,
    "changed_files": list,
    "evidence": list,
    "reason": str,
}

__all__ = ["PROMPT", "OUTPUT_SCHEMA"]
