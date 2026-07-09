"""# Spec-0060/T4: agents.planner —— 起草/精炼 RFC 的提示词（零逻辑）。

文案从旧 orchestrator._DRAFT_RFC_TASK 内联串降为 prompt 字符串；交付协议随之内联（deliver
agent 亦有独立提示词，此处保留起草侧的自负交付约束，使 planner 独立可用）。
"""

from string import Template

PROMPT = Template(
    """你是起草 agent。为 issue #$issue_number 起草一份 spec，遵循 spec-driven-development skill 的 Phase 2（rust-RFC 形态，总览先行）：
1) 用 `spec new <slug> --issue $issue_number --title ... --summary "<一句话 TL;DR>"` 建组（已铺好 9 段脚手架）；
2) 先写组级 rust-RFC 9 段总览：Summary / Motivation（现状+为什么，背景就地复述，单 spec 自包含）/ Guide-level / Reference-level（技术方案 + DAG + 文件分配 + e2e 脚本路径）/ Drawbacks / Rationale and alternatives（≥1 备选）/ Prior art / Unresolved questions / Future possibilities；
3) 再用 `spec add-task` 逐个加工作分解行（必填 --files 互斥 + --acceptance，含依赖、范围）；
4) 必须在组 frontmatter 声明 e2e: 测法块（intent=一句话验什么 + method=一段 prose 测法步骤）；每个 spec 都要声明；
5) 最后 `spec validate` + `spec render` + `spec graph`。只产出 spec（docs/specs/ 下），不写实现代码。

完成后自负交付（commit 用 draft 语义化措辞、按交付协议 push），最后只输出一行 JSON：
{"summary": "<你起草/精炼了什么的一句话概述>"}

issue 正文：
$issue_body
"""
)

OUTPUT_SCHEMA = {"summary": str}
