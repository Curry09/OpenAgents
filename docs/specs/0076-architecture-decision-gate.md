---
number: "0076"
title: 交付面技术架构决策与实现前质量闸
issue: 0
slug: architecture-decision-gate
summary: 将已确认需求转化为可审查的技术架构决策，在实现前验证干预层、备选方案与行为证据，并在合并前复核全局仓库不变量。
tasks:
  - id: T1
    title: Spec 架构决策与行为验收契约
    status: pending
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/schema.py
      - openagents/spec/model.py
      - openagents/spec/mutate.py
      - openagents/spec/validate.py
      - tests/test_spec_model.py
      - tests/test_spec_mutate.py
      - tests/test_spec_validate.py
    scope: 扩展单文件 Spec 的结构化 architecture/verification 数据模型、规范化 design digest 与仓库级编号/slug 唯一性校验；只硬化可确定不变量，不用关键词替代语义判断。
    acceptance: 正反 schema 测试证明候选与选择关系、行为正反例或显式豁免、设计摘要稳定边界及编号/slug 唯一性；Task 状态和派生物变化不改变摘要，设计字段或验收语义变化必改变摘要；既有 Spec 兼容迁移策略明确且全量 validate 无 error。
  - id: T2
    title: Drafter 技术架构产出契约与 skill 接线
    status: pending
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/agents/drafter.py
      - openagents/runtime/context.py
      - tests/test_agents_drafter.py
      - tests/test_runtime_context.py
    scope: 将 draft/refine 模式定义为从已确认目标到技术架构的转换，显式区分目标与建议实现，接入现行 spec-driven-development 方法，并要求基于仓库证据填写结构化架构候选、选择、失败模式和行为案例。
    acceptance: scripted 正反测试证明 Drafter 保持 issue 目标但可替换错误实现建议，输出包含仓库证据和可证伪行为验收；Prompt 引用的 skill 名与实际安装名称一致；backfill/implement/iterate 既有模式契约不回归。
  - id: T3
    title: 独立 Architect 角色与架构裁决
    status: pending
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/agents/architect.py
      - tests/test_agents_architect.py
    scope: 新增只负责实现前技术架构审查的 Architect，按目标保真、干预层匹配、边界完整性和行为证据强度输出 PASS/REWORK 及结构化 findings，不重新进行产品准入或代码实现。
    acceptance: 角色输出 schema 与值域可机检；正例通过，机械接受 issue 实现建议、只有关键词验收、忽略进程/并发所有权或缺少反例的设计均 REWORK；证据不足可走统一 needs-human，不能静默 PASS。
  - id: T4
    title: Vigil 实现前架构闸与最终集成闸
    status: pending
    priority: P0
    tags: []
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - openagents/runtime/gates.py
      - openagents/runtime/state.py
      - openagents/utils/agent_config.py
      - tests/test_recipe_stages.py
      - tests/test_recipe_vigil_act.py
      - tests/test_runtime_gates.py
      - tests/test_runtime_state.py
      - tests/test_utils_agent_config.py
    scope: 拆开当前 draft 后立即 implement 的竖切路径；新增独立 architecture stage 执行 agent/human/skip 设计评审并保存绑定 design digest 的批准；实现和合并均拒绝陈旧批准；在最新 base+head 候选树上运行全局 Spec/生成物/DAG 检查并将结果绑定 base、head、design 三元组。
    acceptance: 配置测试证明 architecture 缺省值兼容推导且非法 rfc/architecture 组合被拒绝；状态机测试证明未批准设计不调用 Implementer、REWORK 返回 refine、human 真暂停、设计变化使批准失效；并发分支复用 Spec 编号时后合入者在最新 base 上被拒绝；base/head/design 任一变化使 integration stamp 失效；现有代码 review、CI 配置和 needs-human 语义不回归。
  - id: T5
    title: 行为证据清单、实现评审与端到端反证
    status: pending
    priority: P0
    tags: []
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/agents/tester.py
      - openagents/agents/reviewer.py
      - openagents/runtime/evidence.py
      - tests/test_agents_tester.py
      - tests/test_agents_reviewer.py
      - tests/test_runtime_evidence.py
      - scripts/e2e-spec-0076-architecture-decision-gate.sh
    scope: 让 Tester 按 Spec 行为案例生成绑定当前 head 的 evidence manifest，Reviewer 核对实现与已批准设计及证据覆盖；静态存在性检查只能证明格式，不能单独放行行为主张；提供完全离线的全链路反证脚本。
    acceptance: evidence manifest 可追溯到 head、案例、观测值和证据路径；行为变更只有 grep/字段存在证据时 Reviewer 必须 REWORK；正反案例齐备且结果匹配时可 PASS；e2e 脚本覆盖错误干预层、设计修订失效、证据不足和并发编号冲突，使用 scripted backend 与临时仓库且不调用外网/真实模型。
---

# 0076 · 交付面技术架构决策与实现前质量闸

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

OpenAgents 在接收已经完成需求侧判断的 issue 后，应把需求目标转换为一项独立、可审查的技术架构决策，
而不是把 issue 中的建议实现直接扩写为 Spec。该阶段不重新定义用户问题，也不重复产品准入；它负责判断
系统应在哪个技术层介入、现有边界如何受影响、为什么选择当前方案、哪些失败模式必须防范，以及用什么
行为证据证明实现达成目标。

本组把这一职责从 Prompt 软要求提升为四个相互制约的机制：Spec 保存结构化架构决策与行为验收计划；
独立 Architect 在任何实现发生前审查该决策；Vigil 以设计摘要绑定评审结论并阻止未获批准的实现；合并前
再基于最新主干验证设计摘要、行为证据和全局仓库不变量。代码 Reviewer 继续审查实现，但不再兼任架构
批准者。

## Motivation

当前交付路径表面上是 Spec-first，实际控制流却是：Drafter 根据 issue 写 Spec 并提交，Vigil 创建 draft PR，
随后在同一次 `_do_solve` 中立即调用 Implementer。Drafter 的直接输出只有 `delivered/head_sha/summary`，
确定性门禁只证明提交确实前移且自报 SHA 正确；它们不表达或检验技术干预层、接口边界、备选方案质量与
行为验收。现有 Reviewer 在实现完成后仅对照 Spec 的 Task acceptance、测试和证据裁决，因此 Spec 一旦
把未经验证的实现建议写成 acceptance，后续实现和评审会在同一前提内闭环。

一次五 issue、并发度为二的无人值守实验提供了具体反证：五个 PR 均自动评审并合并，完整测试也能通过，
最终主干仍出现重复 Spec 编号；一个命令重复保护把不同文件上的非连续命令视为同一重复操作；一个宣称
三十秒终止命令的方案只停止等待路径，没有证明子进程被终止；多项 Prompt 变更仅用关键词存在性作为
验收。这些缺陷不是“缺少某一句 Prompt”能够完整解释的：局部 Spec、局部测试和逐 PR Reviewer 全部可以
自洽，而批次级一致性、技术层选择和真实行为仍然错误。

历史方法要求 RFC/Spec 经过人工阶段批准后再实现，但声明式 Vigil 把 `rfc: agent` 解释成由 Agent 起草，
没有提供等价的自动架构评审状态；`rfc: human` 也没有在现行竖切控制流中形成真正的实现前暂停点。同时，
Drafter Prompt 引用的 skill 名称与仓库现行 `spec-driven-development` 名称存在漂移。这说明当前缺陷位于
角色契约、上下文、阶段机和门禁的组合边界，而非单个模型或单段文案。

## Guide-level explanation

新的交付语义明确区分三类交付信息：

1. **需求目标**来自已准入 issue，说明要取得的结果与约束。OpenAgents 接受该目标，不重新进行产品发现或
   准入。
2. **实现建议**即使出现在 issue 中，也只作为候选技术假设。Drafter 必须结合当前仓库选择实际干预层，
   可以采用、修改或否决建议实现，但不得改变需求目标。
3. **技术架构决策**记录所选干预层、受影响边界、至少一个真实备选、失败模式，以及正例和反例行为验收。

以“避免无效重复操作”为例，需求目标保持不变；架构设计需要比较 Prompt 提醒、编排状态机、工具调用边界
和进程执行器等落点。如果目标要求可靠终止外部命令，设计不能只因为修改 Prompt 最容易就选择 Prompt；
它必须说明哪个组件真正拥有子进程生命周期，并以进程退出和副作用停止作为行为证据。相反，若目标只是
统一面向用户的表达格式，角色 Prompt 可能正是正确干预层，设计应明确其边界，并以正反交互样例而不是
仅检查字符串存在来验收。

自动流程变为：

`准入 issue → 起草 Spec → Architect 评审设计 → 实现 → Tester/Reviewer 验证行为 → 最新主干集成校验 → 合并`

Architect 的 PASS 绑定规范化后的设计摘要，而不是绑定一个永久标签。设计相关内容发生变化后，旧批准自动
失效并重新评审；仅 Task 状态、实现提交引用或派生索引变化不改变设计摘要。声明式配置新增独立的
`architecture` stage：`agent` 表示自动架构评审，`human` 表示 Spec 起草后等待人工批准；`skip` 只允许与
`rfc: skip` 配套，表示仓库明确不要求 Spec，不能伪造架构批准。

## Reference-level explanation

### 架构决策契约

Spec frontmatter 增加 `architecture` 与 `verification` 两个结构化对象。它们是九段正文的机器可读索引，
不是重复正文：

- `architecture.objective`：从准入 issue 保真的交付目标；
- `architecture.constraints`：兼容性、安全、性能、运行环境和明确的非目标；
- `architecture.candidates[]`：候选干预层、所需边界、证据与主要代价；
- `architecture.selected`：所选干预层、受影响组件/接口及选择理由；
- `architecture.failure_modes[]`：并发、状态、进程、兼容和回滚等相关失败模式；
- `verification.behavior_cases[]`：任务无关的正例、反例、观测方法和预期结果；
- `verification.repository_invariants[]`：编号唯一、生成物一致、依赖图有效等仓库级不变量；
- `verification.exemptions[]`：纯文档或无外部行为变更时的显式豁免及理由。

`spec validate` 只硬化可确定判断的部分：字段完整、枚举合法、候选非空、所选项属于候选、行为变更至少有
一个正例和一个反例、豁免理由非空、Spec 编号/slug 全仓唯一。它不使用关键词推断“架构是否优秀”。
`design_digest` 对上述设计字段、九段正文中的设计内容以及 Task 的 scope/files/dependencies/acceptance 做
规范化摘要，排除 Task status、实现引用和 OVERVIEW 等派生物。

### 独立 Architect

新增 Architect 角色，输入为准入 issue、候选 Spec、仓库结构和按需读取的相关实现。它只审查从需求目标到
技术架构的转换，不重新做产品价值判断，也不编写代码。结构化输出至少包含：

- `verdict: PASS | REWORK`；
- `objective_fidelity`：设计是否保持需求目标且区分建议实现；
- `intervention_fit`：所选技术层是否真正拥有待改变的行为；
- `boundary_integrity`：接口、状态、一致性和失败模式是否闭合；
- `verification_strength`：验收是否观察结果，并含能推翻方案的反例；
- `reason/findings`：可执行的修订意见。

Architect 与 Drafter 使用不同角色契约；配置允许使用不同 backend。相同模型仍可运行，但 trace 必须保留
角色、模型、设计摘要和裁决，便于识别相关性偏差。Architect 的 REWORK 返回 Drafter refine，超过预算或
无法取得必要证据时走现有 `needs-human` 控制出口，不降级为 PASS。

### 实现前状态闸

Vigil 不再在 `_do_solve` 内无条件连续执行 draft 与 implement。`rfc` stage 继续只决定 Spec 由谁起草；
创建 draft PR 后计算设计摘要，再路由新增的 `architecture` 闸：

- `agent`：派 Architect；PASS 后写入 `design-approved:<digest>` 证据，REWORK 后修订 Spec 并重新计算；
- `human`：停在 draft PR，人工批准必须绑定当前 design digest；
- `skip`：仅当 `rfc: skip` 时合法，不创建虚假的批准证据，按配置明确走无 Spec 路径。

配置校验拒绝 `rfc != skip` 且 `architecture = skip`，避免“写了 Spec 但无人审查”的静默旁路。为兼容既有
配置，缺少 `architecture` 时按 `rfc` 推导：`rfc: agent` 默认 `architecture: agent`，`rfc: human` 默认
`architecture: human`，`rfc: skip` 默认 `architecture: skip`；模板与迁移提示会显式写出最终值。

Implementer 的前置条件是当前设计摘要已有有效批准。任何会改变摘要的 Spec 修订都使批准失效；Vigil 下一轮
先回到 Architect，而不是继续实现。设计批准与代码 `review-approved:<head>` 分开保存，因为前者回答
“方案是否成立”，后者回答“当前提交是否正确实现方案”。

### 行为证据与代码评审

Tester 读取 `verification.behavior_cases`，产出绑定当前 head 的结构化 evidence manifest：执行了哪些案例、
观察值、预期值、结论和证据路径。静态文本、grep 或字段存在性可以验证载入和格式，但当目标声称改变运行
行为时，不能成为唯一 PASS 证据。Reviewer 同时读取 Spec、实现 diff 和 manifest，检查实现符合已批准设计，
并确认每项行为主张有对应证据；Reviewer 无权补写或默许缺失的架构决策。

### 合并时全局完整性闸

逐分支 `spec validate` 只能看到当前分支，不能证明并发 PR 合入后的主干一致。合并前增加确定性 integration
gate：获取最新 base，构造 `base + PR head` 候选树，运行 Spec schema/编号唯一性、render/graph 漂移、Task
DAG/文件所有权和项目配置的仓库级检查。结果绑定 `(base_sha, head_sha, design_digest)`；任一值变化即作废并
重跑。Merger 只能处理带有效 integration stamp、当前代码评审和（配置要求时）CI 结论的 PR。这样两个并行
分支即使同时选到一个编号，后合入者也会在最新 base 上被拒绝或自动改号，而不是把冲突带进 main。

### DAG 与文件分配

| Task | 内容 | 依赖 |
|---|---|---|
| T1 | Spec 架构决策、行为验收 schema 与确定性校验 | — |
| T2 | Drafter 的技术架构产出契约与 skill 接线 | T1 |
| T3 | 独立 Architect 角色及结构化裁决 | T1、T2 |
| T4 | Vigil 实现前架构闸、摘要状态与最终集成闸 | T1、T3 |
| T5 | Tester/Reviewer 行为证据消费与端到端反证 | T3、T4 |

各 Task 的文件所有权见 frontmatter，互不重叠。端到端验证脚本为
`scripts/e2e-spec-0076-architecture-decision-gate.sh`：使用临时仓库和 scripted backend，覆盖建议实现被
替换、架构 REWORK 后再审、Spec 改动使批准失效、仅 grep 证据不能放行，以及两个并行分支复用编号时第二个
合并被 integration gate 拒绝。默认测试不调用真实模型或外部 forge。

## Drawbacks

实现前增加一次独立评审会增加模型调用和首次交付时延；设计被打回时还会增加一次 Drafter 往返。结构化架构
字段也提高了 Spec 编写成本，简单变更若错误归类会显得过重。integration gate 构造候选树并重新生成索引，
在大型仓库中会增加合并延迟。不同角色若仍使用同一模型，相关性偏差只能被观测和削弱，无法被结构本身完全
消除。

这些成本通过三种方式控制：无设计决策的单文件变更仍可按现有规则跳过 Spec；确定性 schema 和摘要计算不
调用模型；行为证据按变更类别分级，纯内部或纯文档变更允许有理由的豁免。架构闸不要求重新调查产品问题，
因此其上下文和职责应比需求侧角色窄。

## Rationale and alternatives

选择“结构化设计契约 + 独立 Architect + 两个确定性绑定闸”，因为三者分别解决不同失败：结构化契约使设计
决策可寻址，Architect 判断技术方案质量，摘要和集成闸防止并发/后续修改绕过裁决。只做其中一项都会留下
明显旁路。

未采用“仅增强 Drafter Prompt”。现有 Prompt 已要求架构、Rationale 和备选方案，实验仍产生机械扩写；
没有实现前状态闸时，模型即使遗漏这些要求，流程仍会立刻实现。继续追加禁止项只会扩大文案并制造新的
存在性测试。

未采用“让现有代码 Reviewer 同时审查架构”。代码 Reviewer 发生在实现之后，推翻设计的沉没成本更高，且
其当前基准是“是否符合 Spec”，会形成自指验收。独立 Architect 在实现之前裁决，并以不同输出维度承担责任。

未采用“每个 Spec 必须人工批准”。人工闸质量高但不满足 Vigil 无人值守目标。本方案保留 `rfc: human`，
同时为 `rfc: agent` 提供可审计的自动等价物；证据不足时仍能通过 `needs-human` 收口。

未采用中央数据库预分配 Spec 编号作为唯一修复。中央分配能减少碰撞，却不能防手工文件、离线分支或其它
全局不变量漂移；最新 base 上的 integration gate 是必要安全网。未来可叠加 forge 原子编号租约作为优化。

## Prior art

编译流水线把源语义转换成类型化中间表示，再由独立检查阶段阻止非法程序进入后端；本设计同样把需求目标到
技术方案的转换显式化，而不是只依赖自然语言角色名。数据库乐观并发控制使用版本戳验证“判断依据仍是当前
状态”，对应本组以 design digest 和 `(base_sha, head_sha)` 绑定批准。持续集成中的 required checks 也遵循
相同原则：裁决必须绑定具体提交，状态变化后旧结论失效。

OpenAgents 现有 `review-approved:<sha>`、e2e head 证据戳和 level-triggered Vigil 已证明“结论绑定观测
版本、变化后自动重算”的模式适合本系统；本组把这一模式前移到技术架构，并扩展到最终集成树。

## Unresolved questions

无。首版采用独立 Architect、规范化 design digest、行为 evidence manifest 和最新 base 候选树集成校验；
是否为高并发 forge 增加中央 Spec 编号租约属于后续性能优化，不影响本组正确性边界。

## Future possibilities

积累足够 trace 后，可以比较不同 Drafter/Architect 模型组合的架构打回率、实现返工率和合并后缺陷率，量化
相关性偏差与额外评审成本。架构候选和行为案例也可形成仓库级模式库，但模式只能作为候选证据，不能自动
替代当前代码边界分析。integration gate 后续可扩展为 forge 侧原子 merge queue，使多个已验证 PR 严格按
最新主干串行复核。
