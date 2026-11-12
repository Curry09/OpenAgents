---
number: "0078"
title: Agent 调用协议保真与隐私遥测
issue: 0
slug: agent-invocation-observability
summary: 将供机器解析的完整输出与面向人的限长摘要分离，并只记录工具名称序列以统计取证预算，使结构化协议可靠且实验耗时可解释。
architecture:
  objective: 保证结构化 Agent 输出不因展示截断而损坏，并以最小化数据度量各角色的工具使用和首次编辑前调查量。
  constraints:
    - 旧后端仅返回 summary 时保持兼容
    - 遥测失败不得影响工作流结果
    - 不记录工具参数、命令正文、文件内容或模型推理
  non-goals:
    - 精确统计模型 token
    - 阻止超过调查预算的调用
    - 保存完整 Agent transcript 供分析
  candidates:
    - id: parse-display-summary
      layer: runtime-parser
      boundary:
        - AgentResult summary
      evidence:
        - 展示摘要允许限长，结构化 JSON 位于截断位置之后时无法解析
      tradeoffs: 无需扩展后端协议，但展示需求会持续破坏机器协议。
    - id: split-protocol-and-telemetry
      layer: backend-result-runtime-observability
      boundary:
        - AgentResult
        - Backend adapters
        - Runtime engine
        - CLI report
      evidence:
        - 后端本身持有完整最终输出和有序工具事件，运行时目前只消费限长 summary
      tradeoffs: 扩展可选结果字段并增加本地 JSONL，但能把机器协议、展示摘要和最小遥测职责分开。
  selected: split-protocol-and-telemetry
  affected-components:
    - openagents.backends
    - openagents.runtime.engine
    - openagents.runtime.tool_usage
    - openagents.cli
  failure-modes:
    - 长输出被截断后结构化协议无法解析
    - 遥测记录敏感工具参数或命令正文
    - linked worktree 各自写报告导致一次实验的数据分散
    - 遥测写入异常阻断 Agent 主流程
verification:
  behavior-cases:
    - id: parse-unabridged-protocol
      polarity: positive
      stimulus: 展示摘要被截断但 raw output 包含完整末行 JSON
      expected: runtime 从 protocol_output 成功解析结构化结果
      observation: backend 与 runtime engine 单元测试
    - id: telemetry-write-failure
      polarity: negative
      stimulus: 遥测目录不可写或事件不完整
      expected: Agent 调用结果保持不变且报告加载器忽略无效记录
      observation: tool usage 单元测试
  repository-invariants:
    - tool-usage.jsonl 不包含工具参数和命令正文
    - linked worktree 的事件汇总到主工作树
    - 旧 AgentResult 不提供 raw_output 或 tool_events 时行为不变
  exemptions: []
tasks:
  - id: T1
    title: 完整机器协议输出
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backends/base.py
      - openagents/backends/claude_code.py
      - openagents/runtime/engine.py
      - openagents/utils/align.py
      - tests/test_base.py
      - tests/test_backend_claude_code.py
      - tests/test_runtime_engine.py
    scope: AgentResult 增加可选 raw_output 与 protocol_output 回退属性；后端保留完整最终输出，所有结构化协议消费者不再解析限长展示摘要。
    acceptance: 测试证明旧结果回退 summary、长 JSON 即使展示摘要截断仍可解析、alignment 使用完整输出，且既有摘要展示行为不变。
  - id: T2
    title: 最小化工具调用遥测
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/tool_usage.py
      - tests/test_runtime_tool_usage.py
    scope: 从有序工具名称计算总调用数、首次编辑位置、此前调查次数和默认预算是否超出；追加写入主工作树 JSONL，异常 fail-open。
    acceptance: 测试覆盖工具分类、预算边界、超预算理由、linked worktree 汇总、损坏行忽略和按角色聚合；落盘事件只含工具名及派生计数。
  - id: T3
    title: 后端事件接线与报告
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli_timing.py
    scope: Claude streaming 适配器只提取 tool_use 名称并随 AgentResult 返回；runtime 在成功解析协议后记录调用，report 在既有时延段之后输出按角色聚合的取证预算表。
    acceptance: 测试证明工具顺序保留但输入不落盘、无遥测数据时旧 timing 报告不变、仅有遥测时仍可报告、写入失败不改变 Agent 返回值。
---

# 0078 · Agent 调用协议保真与隐私遥测

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

OpenAgents 将一次 Agent 调用的机器协议载荷、面向人的展示摘要和工具使用遥测明确分离。后端保留完整最终输出
供结构化解析，同时仅提取有序工具名称用于本地预算统计；工具参数、命令正文和文件内容均不进入遥测。

## Motivation

当前 `AgentResult.summary` 同时承担 PR 展示文本和机器协议输入。展示层为了可读性会截断长结果，而 Drafter、
Reviewer 等角色的末行 JSON 可能位于截断位置之后，导致模型实际遵守协议但 runtime 仍解析失败。另一方面，
实验显示角色花费大量时间重复取证，却缺少按角色解释调查次数的数据，只能从总墙钟时间推测。

这两个问题共享同一个边界：后端已经观察到完整最终输出和 streaming 工具事件，但结果协议只暴露展示摘要。
需要把机器数据与展示数据分开，并对可观测信息执行数据最小化。

## Guide-level explanation

后端完成调用后，`summary` 仍是一段适合评论或 PR 正文的短文本；`raw_output` 保存模型最终返回的完整文本。
runtime 通过 `protocol_output` 读取完整值，旧后端没有提供时自动回退到 summary。因此长响应不会再因为展示
截断而破坏末行 JSON。

Claude streaming 事件中的 `tool_use` 只提取名称和顺序，例如 Read、Grep、Edit。系统计算首次编辑前的调查
调用数并追加到 `.openagents/tool-usage.jsonl`。`openagents report` 可按角色显示调用次数、平均及最大编辑前
调查量和超预算次数。报告无法回答 token 用量，也不保存工具具体读取或执行的内容。

## Reference-level explanation

`AgentResult` 新增可选 `raw_output`、`tool_events` 和只读 `protocol_output`。Claude 适配器从 result event 保存
完整最终文本，并从 assistant content block 中按顺序提取 `tool_use.name`。`runtime.engine` 与 alignment 解析器
统一消费 `protocol_output`，保证旧后端兼容。

`runtime.tool_usage` 将 Read、Bash、Grep、Glob、Search、Find 视为调查工具，将 Edit、Write、MultiEdit、
NotebookEdit 视为编辑工具，默认基线为首次编辑前六次调查。没有编辑时统计整次调用的调查量。记录包含随机
调用 ID、UTC 时间、角色、工具名称和派生计数；只有超预算且角色明确返回理由时才保存限长理由。

linked worktree 通过 `.git` 指针定位主工作树，使同一 Vigil 实验的事件进入一个 append-only JSONL。所有遥测
异常均被隔离，不能改变 Agent 的业务结果。CLI 在 timing 数据之后追加独立表；两类数据任一存在即可生成报告。

任务依赖为 `T1 → T2 → T3`。离线测试覆盖截断协议、后端事件提取、主工作树定位、损坏数据和报告组合，
不调用真实模型或外网。

## Drawbacks

完整输出在一次调用的内存中保留更久，工具名称序列也会增加少量结果体积。本地 JSONL 会随调用增长，需要由
部署方按已有运行资产策略轮转。工具名称是近似信号，不能等同于真实认知工作量。

## Rationale and alternatives

选择扩展 `AgentResult`，因为完整输出和工具事件都在后端边界产生，向 runtime 暴露可选字段即可保持旧实现兼容。
备选一是取消 summary 截断，但会让评论和终端输出失控；备选二是要求模型把 JSON 放在开头，但仍把展示策略与
机器协议耦合。遥测方面，保存完整 tool input 能提供更多细节，却会记录命令、路径和内容，隐私与审计成本不成
比例；工具名和顺序足以回答当前预算问题。

## Prior art

日志系统通常区分完整结构化事件与面向人的格式化视图，分布式 tracing 也优先记录 span 名称和聚合指标而非
任意业务载荷。本设计采用相同的数据分层与最小化原则。

## Unresolved questions

不同后端的工具名称是否需要统一词表，以及 JSONL 的默认轮转上限，需在接入第二种可报告工具事件的后端后决定。

## Future possibilities

未来可关联模型侧 token ledger 和阶段 timing，形成不含敏感参数的调用成本视图；也可为不同角色配置调查预算，
但预算仍应作为可观测基线而非强制终止器。
