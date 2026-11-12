---
number: "0083"
title: v0.2 因果 Spec 契约
issue: 0
slug: v02-causal-spec-contract
summary: 将实验验证过的深证据 Spec Writer 固化为 v0.2 的唯一单 issue 设计角色。
architecture:
  objective: 单个 issue 在进入开发前形成目标守恒、可实施、可证伪的 compact Spec，并明确区分可达性、控制效果和最终行为证据。
  constraints:
    - 原 issue 是目标权威；Spec 不得缩减困难目标。
    - 当前 worktree 是唯一可写仓库；实际加载的 NexAU 与运行时依赖全部允许只读调查。
    - 所有候选使用同一证据字段；prompt 存在或被配置引用不等于实际可达，更不等于行为有效。
    - READY、PARTIAL、BLOCKED fail-closed；只有 READY 可进入 v0.2 DAG。
  non-goals:
    - 在 Spec 阶段实现代码或运行完整产品验收。
    - 为不同 issue 写特例关键词规则。
  candidates:
    - id: single-causal-writer
      layer: design
      boundary:
        - issue objective to frozen compact spec
      evidence:
        - 四 issue 对照显示连续调查能找到实际 NexAU 控制点并避免假 READY
      tradeoffs: 单角色调查较慢，但避免跨角色重复建立上下文。
    - id: split-design-committee
      layer: design
      boundary:
        - research, architecture and review handoffs
      evidence:
        - 旧流程具备对应角色
      tradeoffs: 每层重读上下文并产生逐层缩减目标的激励。
  selected: single-causal-writer
  affected-components:
    - openagents/agents/spec_writer.py
    - openagents/recipes/stages.py
    - tests/test_agents_prompts.py
    - tests/test_recipe_stages.py
  failure-modes:
    - 候选比较被压成自由文本；生产硬闸拒绝缺少统一字段的 READY/PARTIAL。
    - 未来计划被冒充为已有证据；角色必须分别标记 HYPOTHESIS、STRUCTURAL、BEHAVIORAL。
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: Spec Writer 对真实运行时控制点形成闭合证据链。
      expected: 输出 READY、compact Spec、完整候选字段和按目标分列的证据等级。
      observation: engine 输出通过 minimal_spec 的结构与 head/digest 硬闸。
    - id: BC2
      polarity: negative
      stimulus: 候选只给 reason，或把 prompt 配置引用当成行为效果。
      expected: 输出降级为 PARTIAL，或由统一字段硬闸拒绝。
      observation: 针对性 pytest 抛 GateError，真实四 issue 实验无假 READY。
  repository-invariants:
    - Spec 只写 docs/objectives/issue-N.md。
    - PARTIAL/BLOCKED 不进入 Developer。
  exemptions: []
tasks:
  - id: T1
    title: 固化深证据 Spec Writer 与生产硬闸
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/spec_writer.py
      - openagents/recipes/stages.py
      - tests/test_agents_prompts.py
      - tests/test_recipe_stages.py
    scope: 固化 NexAU 只读开放、统一候选标尺、prompt reachability、delivery/control_effect 分离、证据等级和三态收口。
    acceptance: 角色契约测试、统一字段负例与 minimal_spec 交付硬闸全部通过。
---

# 0083 · v0.2 因果 Spec 契约

## Summary

v0.2 只保留一个单 issue 设计角色。Spec Writer 连续完成目标拆解、仓库与实际 NexAU 调查、候选比较、因果链和证伪设计，产出 compact objective contract；不再把这一认知链拆给多个角色重复深挖。

## Motivation

最简版 Spec Writer 会把“文件存在”“prompt 被引用”直接当成行为改善，并优先选择容易实现的 prompt 改动。四 issue 对照证明，开放实际 NexAU 后才能找到 `before_model`、`wrap_tool_call` 与 tracer 等真实控制点；统一证据标准则防止读完源码后继续选择性推断。

## Guide-level explanation

每个 issue 独立运行 Spec Writer。READY 表示完整目标具有闭合机制和独立验收；PARTIAL 表示有价值路径但仍有未闭合目标；BLOCKED 表示当前能力不足。后两者作为正常可审计结果停止，不制造 PR。

## Reference-level explanation

候选固定记录 ownership、delivery、control_effect、evidence、assumptions、failure_modes 和 verdict。每个 objective 固定记录 scope_coverage 与 evidence_level。`stages.minimal_spec` 在模型 schema 之后再次执行嵌套字段、HEAD 前移和证据戳硬闸。

## Drawbacks

复杂运行时问题会产生 20–35 次工具调用、耗时 5–8 分钟。v0.2 接受这一成本，但不再继续向角色堆入调度、实现或验收权力。

## Rationale and alternatives

重新拆分 Researcher/Architect/Reviewer 会让每一小步重新建立上下文。单角色保留连续认知，独立性改由实现后的 Acceptance 提供。

## Prior art

承接 Spec-0082 的 minimal flow 和 `glm52fp8-1m-specwriter-deep-clean-r2/r3` 实验结果。

## Unresolved questions

后续可优化 NexAU 证据索引与停止条件，但不得以恢复固定读取次数换取速度。

## Future possibilities

将 compact Spec 改为结构化 `submit_spec` stop tool，由宿主机械渲染和提交，以移除 Claude Code 依赖。
