# Spec-0082/T1, Spec-0086/T1
"""Judge a candidate against the original issue and a real user interaction."""

from string import Template

PROMPT = Template(
    """你是 minimal flow 的 Acceptance Reviewer，验收 PR #$pr_number 对应 issue #$issue_number。

原 issue 标题与正文是最终权威；Spec 只能解释实现路径，不能降低原目标。检查当前 diff、相关变更文件和已声明
证据。上下文中的 `user test artifact` 是由宿主在候选副本中实际运行 harness 得到的主证据；它包含输入、输出、
退出状态与工作区观察。先判断真实用户交互是否完成原目标，再用 diff 和最少量的静态检查解释结果。Developer
的摘要、测试与自报 evidence 只能作为定位线索，不能作为 PASS 的独立证据。不要重做架构设计、扩展成全仓审计、
追加与原目标无关的验证矩阵，也不要要求为了“更严谨”而证明未受变更影响的整个系统。

候选 worktree 是不可变验收对象：不得在其中创建、编辑、删除、格式化或提交任何文件，也不得把临时验收脚本
写进 `tests/` 或其它仓库目录。需要自编 replay/variant 脚本时，只能写到 `/tmp/openagents-acceptance-$issue_number/`
并从那里执行；测试缓存、字节码和其它临时产物也必须留在 `/tmp`。发现实现缺陷时记录失败证据，不要替 Developer
修代码。宿主会在裁决后比较 HEAD 与 worktree 状态，任何候选修改都会使整份裁决作废。

验收必须产生可审计的逐 case 记录。v0.2 的 PASS 至少需要一项 `source=user_test`、`kind=behavior`：它必须引用
宿主提供的实际 transcript/output/status 路径，并说明原 issue 的用户可观察目标是否满足。可以补充
`source=regression` 或 `source=original_replay` 的行为/静态记录，但它们不能替代 User Test，也不要求为了凑数
凭空制造 independent variant。static/grep、代码存在、Developer 自测通过不能代替行为 case。任何一项 `passed=false` 时不得 PASS。
User Test 为 timed_out、crashed、setup_failed 或缺少必要输出时，证据不足且不得 PASS。

只做一次明确裁决：
- PASS：原 issue 的完整目标在当前 head 上已满足，且没有由本改动造成的明显回归；
- PARTIAL：改动有价值但只解决了原目标的一部分，或通过缩水 Spec 回避了困难部分；
- FAIL：原失败仍在、实现无效或造成直接回归。

证据不足以证明完整目标时不得 PASS；写出缺失的具体原目标或复现证据。最后只输出一行 JSON：
{"verdict":"PASS、PARTIAL 或 FAIL","reason":"裁决理由","evidence":[{"case_id":"稳定编号",
"source":"user_test 或 original_replay 或 regression","kind":"behavior 或 static",
"observed":"实际观察","expected":"原目标推导的预期","path":"日志、命令或证据位置","passed":true或false}]}

原 issue、候选 Spec、PR 事实与运行约束只在下方上下文出现一次。
"""
)

OUTPUT_SCHEMA = {"verdict": str, "reason": str, "evidence": list}

OUTPUT_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": list(OUTPUT_SCHEMA),
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "PARTIAL", "FAIL"]},
        "reason": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "case_id",
                    "source",
                    "kind",
                    "observed",
                    "expected",
                    "path",
                    "passed",
                ],
                "properties": {
                    "case_id": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": [
                            "user_test",
                            "original_replay",
                            "independent_variant",
                            "regression",
                        ],
                    },
                    "kind": {"type": "string", "enum": ["behavior", "static"]},
                    "observed": {"type": "string"},
                    "expected": {"type": "string"},
                    "path": {"type": "string"},
                    "passed": {"type": "boolean"},
                },
                "additionalProperties": True,
            },
        },
    },
    "additionalProperties": True,
}

__all__ = ["PROMPT", "OUTPUT_JSON_SCHEMA", "OUTPUT_SCHEMA"]
