"""# Spec-0060/T4: agents.implementer —— 按 RFC 实现 / 按反馈迭代的提示词（零逻辑）。

文案从旧 orchestrator._IMPLEMENT_TASK / _ITERATE_TASK 内联串降为 prompt 字符串；取证判断纪律
（三分类 + 反测试顶替 + 诚实报阻塞）内联为 prompt 文本。$feedback 为空表示首轮实现、非空表示按
reviewer 反馈迭代（同一模块两用，靠占位符区分，recipe 零业务判断）。
"""

from string import Template

PROMPT = Template(
    """你是实现 agent。issue #$issue_number 的 spec 已获批准，对应 PR #$pr_number。请阅读 docs/specs/ 下对应 spec 组，按其 Task 实现代码并自测（ruff + pytest），代码注释引用对应 `# Spec-NNNN/Tn`。

若下方有「评审反馈」，说明这是一轮迭代：请针对反馈逐条修改；反馈为空则为首轮实现。

取证判断纪律：你改的行为若是产品对外行为，验证就要真 app 跑出来的证据，自检分三类——① UI 直接看得到→截下可视化结果存进 tracked 证据目录；② UI 看不到但改产品对外行为→真 app 触发它、提交真实运行日志文本 + 触发上下文为证；③ 纯内部实现细节（重构等）→ 用相称的自动化测试即可。纪律：自动化测试/后端日志替代不了真 app 证据；不许拿「LLM 慢/flaky/投入产出比差」当跳过借口；真跑不起来就诚实报「因 X 未验证」的阻塞项，绝不假称已验证。

收尾前先确认本分支能与最新 `origin/main` 干净合并：取最新 main 并入/变基，若有冲突就地解决（OVERVIEW.md 这类生成式索引直接 `spec render` 重渲、其余语义解决）。完成后自负交付（commit + push），最后只输出一行 JSON：
{"summary": "<你本轮实现/迭代了什么的一句话概述>"}

评审反馈：
$feedback
"""
)

OUTPUT_SCHEMA = {"summary": str}
