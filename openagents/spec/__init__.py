"""spec —— 「Spec 活快照 + 演化历史」数据层与工具。

Spec-0014: 用「Spec 活快照 + 演化历史」取代 RFC

把 RFC 拆成两件本质不同的东西：当前规格沉淀为「活快照」（docs/specs/ 源数据树，
基本单元是 Task，与活代码一一对应），执行演化沉淀为「历史」（追加式版本列表）。

本包是纯函数式数据层 + 薄 CLI（理念 1 奥卡姆、理念 10 解耦），不感知 git / GitHub /
orchestrator，只读写 docs/specs/ 下的文件：
- model：源数据加载 / 写回（ruamel round-trip 保真）
- schema：Task / metadata / history 的 JSON Schema（单一真源）
- validate：schema + 语义校验（files 重叠 / DAG 无环 / 血缘引用）
- render：派生唯一人读视图 OVERVIEW.md（看板 / 关系图 / 冲突 / DAG / 演化图）
- mutate：amend / abandon（改快照 + append 历史 + 自动 render）
- cli：console_script `spec`
"""
