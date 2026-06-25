"""spec —— 「Spec 活快照」数据层与工具（markdown 单文件形态）。

Spec-0014 + 2026-06-24 spec-markdown-form：用「Spec 活快照」取代 RFC。

一个 spec 组 = 一个 markdown 文件 docs/specs/NNNN-slug.md：frontmatter 放结构化源数据
（机器读），正文放各 Task 设计 prose（人/agent 读）；基本单元是 Task，与活代码一一对应。
演化历史交给 git + dated 设计文档（决策 D3，per-task history 已退役）。

本包是纯函数式数据层 + 薄 CLI（理念 1 奥卡姆、理念 10 解耦），不感知 git / GitHub /
orchestrator，只读写 docs/specs/ 下的文件：
- model：组 markdown 加载 / 写回（frontmatter + 正文 round-trip）
- schema：Task / frontmatter 的 JSON Schema（单一真源）
- validate：schema + 语义校验（files 重叠 / DAG 无环 / 血缘引用）
- render：派生唯一人读视图 OVERVIEW.md（看板 / 关系图 / 冲突 / DAG / 演化图）
- graph：从代码 import 图 + docstring 生成 ARCHITECTURE.md（对代码的唯一映射）
- mutate：new / add-task / abandon（改快照 + 自动 render）
- cli：console_script `spec`
"""
