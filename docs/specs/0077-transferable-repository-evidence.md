---
number: "0077"
title: 跨角色可传递仓库证据
issue: 0
slug: transferable-repository-evidence
summary: 将角色已核实的客观仓库事实保存为有界证据包并沿交付链传递，使后续角色按差异渐进取证，减少重复扫描而不复用判断结论。
architecture:
  objective: 在保持各角色独立判断的同时复用已经核实的仓库事实，缩短实现与复审前的重复调查。
  constraints:
    - 证据包只包含客观事实，不携带架构裁决或候选评价
    - 内容和条目数必须有确定性上限
    - 旧运行状态与未提供证据包的调用方保持兼容
  non-goals:
    - 跳过实现者或评审者的职责判断
    - 将模型上下文或完整命令输出持久化
    - 用固定读取次数阻止必要调查
  candidates:
    - id: prompt-only
      layer: agent-prompts
      boundary:
        - Drafter
        - Implementer
      evidence:
        - 角色提示可以要求减少重复读取但无法传递前序角色已经掌握的事实
      tradeoffs: 改动较小，但后续角色仍需从头重建仓库上下文。
    - id: bounded-evidence-pack
      layer: role-protocol-runtime-state
      boundary:
        - Drafter output
        - Runtime state
        - Implementer and Reviewer context
      evidence:
        - 当前角色间只传递摘要，缺少路径、符号、验证方式和源版本等可复用定位信息
      tradeoffs: 增加一个小型持久化协议，但能确定性限制上下文并按版本判断证据是否仍有效。
  selected: bounded-evidence-pack
  affected-components:
    - openagents.agents
    - openagents.recipes.stages
    - openagents.recipes.vigil
    - openagents.runtime.state
  failure-modes:
    - 把设计判断包装成事实导致后续角色机械接受
    - 证据对应旧版本但未标识来源而被错误复用
    - 无界证据包反而扩大上下文和 token 消耗
verification:
  behavior-cases:
    - id: reuse-current-evidence
      polarity: positive
      stimulus: 前序角色提供含路径、符号、验证方式和当前 source revision 的证据
      expected: 后续角色收到规范化证据包并仅对缺口或变化补充取证
      observation: scripted stage 调用上下文和状态往返测试
    - id: reject-subjective-or-malformed-data
      polarity: negative
      stimulus: 输入包含无路径事实、非对象条目、超长字段或超过条目上限
      expected: 规范化层丢弃无效条目并确定性截断其余内容
      observation: runtime research 单元测试
  repository-invariants:
    - 证据包最多包含 24 条记录
    - 持久化字段仅来自公开白名单且不包含候选评价或审核结论
    - 不提供证据包时既有角色调用行为不变
  exemptions: []
tasks:
  - id: T1
    title: 有界客观证据包模型
    status: pending
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/research.py
      - tests/test_runtime_research.py
    scope: 定义证据字段白名单、条目与字段上限、规范化、确定性合并和紧凑渲染；仅接受可定位且可验证的客观事实。
    acceptance: 单元测试覆盖非法条目丢弃、字段截断、24 条上限、相同路径与符号的后到记录刷新，以及 Unicode 紧凑渲染。
  - id: T2
    title: 角色协议与渐进取证契约
    status: pending
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/agents/drafter.py
      - openagents/agents/implementer.py
      - tests/test_agents_prompts.py
    scope: Drafter 输出客观 evidence_pack；Implementer 优先按任务、接口和版本定位，只在证据缺失、过期或冲突时补充调查并说明超预算原因。
    acceptance: Prompt 契约测试证明 evidence_pack 字段、客观性边界、六次首次编辑前补充取证预算及例外理由均存在，且获批 Spec 仍是实现权威输入。
  - id: T3
    title: 证据状态传递与角色接线
    status: pending
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/state.py
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - tests/test_runtime_state.py
      - tests/test_recipe_stages.py
      - tests/test_recipe_vigil_act.py
    scope: 将规范化证据包保存到 issue run，沿 draft、architecture、implement 和 review 传递；refine 只合并新增或变化的事实，缺省调用保持兼容。
    acceptance: scripted 测试证明证据在状态往返后不丢失、refine 合并结果传给实现与评审、缺省空包不改变上下文，并且旧状态文件可读取。
---

# 0077 · 跨角色可传递仓库证据

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

OpenAgents 将前序角色已经核实的仓库事实整理成有界 `evidence_pack`，随同 issue 的运行状态传给后续角色。
证据记录提供路径、符号、验证方式和可选源版本等定位信息，但不携带设计选择、质量评价或审核裁决。后续角色
继续独立判断，只对版本变化、证据缺口或现场矛盾进行渐进式补充调查。

## Motivation

现有链路在 Drafter、Implementer、Tester 和 Reviewer 之间主要传递 Spec、issue 正文和自然语言摘要。即使
Drafter 已经查明实际入口、关键接口和验证方法，Implementer 仍需重新扫描仓库才能重建相同事实；进入迭代后，
后续角色又重复这一过程。实验中的主要耗时并非修改本身，而是多个角色从头取得同一组仓库事实。

单纯要求“少读取”不能解决信息缺失，也可能迫使角色在证据不足时猜测。需要传递的是可核实事实而非前序角色
的判断，并允许接收方根据当前 revision 判断是否仍可复用。

## Guide-level explanation

Drafter 完成仓库调查后，可以记录“入口函数位于某路径和符号、接口接受哪些输入、用哪项测试核实、调查时的
Git SHA”。编排层对这些记录做规范化和限长后保存。Implementer 首先使用任务、接口和行范围定位实现点；如果
当前源码与证据版本一致，就无需再次遍历同一目录。如果文件已经变化、记录缺少验证方法或接口与现场矛盾，
Implementer 正常补充调查，并在超出默认预算时说明具体缺口。

证据包不是批准凭证。Architect 仍对技术架构做独立判断，Reviewer 仍需核对实现和行为证据；任何“方案优秀”
“应该通过”之类评价都不属于可传递字段。

## Reference-level explanation

`runtime.research` 提供 `normalize`、`merge` 和 `render`。每条记录以 `fact/path/symbol/verification` 为核心，
可附 `source_revision/line_range/interface/tasks`。规范化层限制为 24 条，并逐字段限长；没有事实或路径的记录被
丢弃。合并键为路径加符号（无符号时使用事实），后到记录只用非空字段刷新已有记录。

Drafter 的结构化输出新增 `evidence_pack`。`RuntimeState` 将规范化结果保存在相应 issue run 中；refine 返回
的增量证据与旧包确定性合并。`stages` 只在非空时把紧凑 JSON 附加到上下文，依次供 architecture、implement
和 review 使用。旧后端没有该字段、旧状态没有该字段或直接调用 stage 未传该参数时均视为空包。

Implementer 的首次编辑前补充读取/检索默认预算为六次。预算是可观测的调查基线而非终止器：证据缺失、版本
不匹配或代码矛盾时允许继续，并返回 `lookup_exception_reason`。本组不负责统计工具事件；统计属于独立的调用
遥测能力。

任务依赖为 `T1 → T2 → T3`。离线验收由相关 runtime、agent prompt、stage 和 Vigil scripted tests 完成，
不调用模型、forge 或外网。

## Drawbacks

状态文件与 Prompt 增加少量数据；路径或行范围可能随重构过期。字段上限会舍弃较低优先级事实，过度依赖旧
证据也可能遗漏现场变化，因此接收方仍需核对 revision 和矛盾信号。

## Rationale and alternatives

选择有界客观证据包，是因为它同时保留角色独立性与可复用定位信息。备选一是只修改 Prompt，要求每个角色
减少调查；但角色不知道前序角色发现了什么，只能少查或重查。备选二是传递完整 transcript；它包含命令、
推理和评价，体积不可控且会把前序偏差直接注入后续角色。白名单事实协议更小，也更易验证和失效。

## Prior art

构建系统的依赖清单、编译缓存的内容寻址和数据管道的 provenance 都把产物与来源版本绑定后复用。本设计只
借用“事实加来源”的原则，不把模型判断视为可缓存真值。

## Unresolved questions

证据条目是否需要未来升级为内容哈希，以及不同语言的符号定位器是否需要类型化，留待积累实际失效数据后决定。

## Future possibilities

后续可根据 source revision 自动标记可疑记录，或由确定性索引生成部分接口事实；也可统计各角色复用率，但
不能据此自动跳过角色判断。
