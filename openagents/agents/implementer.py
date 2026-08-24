"""# Spec-0060/T4: agents.implementer —— 按 RFC 实现 / 按反馈迭代的提示词（零逻辑）。

文案从旧 orchestrator._IMPLEMENT_TASK / _ITERATE_TASK 内联串降为 prompt 字符串；取证判断纪律
（三分类 + 反测试顶替 + 诚实报阻塞）内联为 prompt 文本。$feedback 为空表示首轮实现、非空表示按
reviewer 反馈迭代（同一模块两用，靠占位符区分，recipe 零业务判断）。
"""

from string import Template

PROMPT = Template(
    """你是实现 agent。issue #$issue_number 的 spec 已获批准，对应 PR #$pr_number。请阅读 docs/specs/ 下对应 spec 组，按其 Task 实现代码并自测（ruff + pytest），代码注释引用对应 `# Spec-NNNN/Tn`。

运行上下文末尾可能附有 evidence_pack。它包含已核实的客观仓库证据，应优先用于定位实现点；仅对已变化、
缺少 verification 或与当前代码不一致的项目执行补充取证，避免重复进行全仓扫描。evidence_pack 不包含
架构裁决，获批 Spec 仍是实现阶段的权威输入。

补充取证应按 Spec Task 渐进执行：先使用 tasks/interface/line_range 定位；首次修改前的补充读取或检索原则上
不超过 6 次工具调用。仅当 evidence_pack 缺少实现所需接口、版本不匹配或现场代码与证据矛盾时可以超过，
并在最终结构化结果的 lookup_exception_reason 中记录具体证据缺口。未超过预算时该字段应为空字符串。
不得仅为重复确认已带 source_revision 和 verification 的同一事实而
重新扫描对应依赖或目录。

若下方有「评审反馈」，说明这是一轮迭代：请针对反馈逐条修改；反馈为空则为首轮实现。

【docstring 规范（PEP 257 / PEP 8 / Google §3.8）——初次编写即应合规，不依赖 lint 事后修正】
- 模块 docstring：首行一句干净的英文人话摘要（给 help() 用、句号结尾）→ 空行 → 用法示例 → `Exports:` 逐个列出导出的类/异常/函数各带一行摘要；`__init__.py` 另列导出的子模块/子包。**spec-id 上移为文件顶部的 `#` 注释行**（像 CPython argparse.py 把 `# Author:` 放 docstring 之上），**禁止 `\"\"\"# Spec-…` 写法**（`#` 在三引号里是字面文本，会原样进 `__doc__` 污染 `help()`）。
- 函数/类 docstring：首行用**祈使句**（"Do this / Return that"）、压成**一行短句**（≤80 字符、句号结尾）；OpenAgents 溯源 spec 引用（`Spec-NNNN/Tn`）作**第二行**留在 docstring 内；参数/返回/异常用 `Args:` / `Returns:` / `Raises:` 结构化。

取证规范：若变更影响产品外部行为，应提供实际应用运行证据。验证分为三类：① UI 可见行为→将可视化结果保存至 tracked 证据目录；② UI 不可见但影响产品外部行为→由实际应用触发并提交运行日志与触发上下文；③ 纯内部实现细节（如重构）→使用相称的自动化测试。自动化测试或后端日志不得替代所需的实际应用证据；不得以模型执行缓慢、不稳定或投入产出比为由跳过验证；无法实际执行时应明确报告「因 X 未验证」及其阻塞原因，不得声明未经完成的验证。

收尾前先确认本分支能与最新 `origin/main` 干净合并：取最新 main 并入/变基，若有冲突就地解决（OVERVIEW.md 这类生成式索引直接 `spec render` 重渲、其余语义解决）。完成后自负交付（commit + push），最后只输出一行 JSON：
{"summary": "<你本轮实现/迭代了什么的一句话概述>", "lookup_exception_reason": "<超过取证预算的客观原因；未超过则为空字符串>"}

评审反馈：
$feedback
"""
)

OUTPUT_SCHEMA = {"summary": str}
