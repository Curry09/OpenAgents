---
number: "0093"
title: 交付链保留执行条件与独立验收摘要
issue: 0
slug: execution-contract-preservation
summary: 验证并注入发布者提供的安全执行合同，使 Spec、架构审查和代码审查保留无人输入、预算及产物验收前提，不接触私有 grader。
architecture:
  objective: 让实际交付角色保留来源可信的使用条件，不以局部Spec一致性替代原目标完成。
  constraints:
    - 沿用Issue授权、包hash和统一engine注入。
    - 私有grader和答案不进入OpenAgents。
    - required预期来自独立项目/dispatch配置，不依赖可缺失附件。
  non-goals:
    - 不实现benchmark adapter、用户循环或候选能力淘汰门。
  candidates:
    - id: shared-contract-context
      layer: observations/runtime context
      boundary:
        - 授权执行合同
        - 唯一engine注入点
        - 实际角色输入
      evidence:
        - architecture上下文主要只有Spec文本
        - 现有reader只提供按需读manifest的路径
      tradeoffs: 增加有界上下文和显式required故障，但可复用既有流程。
    - id: issue-prose-only
      layer: issue/prompt prose
      boundary:
        - Issue正文与自由摘要
      evidence:
        - 正文可能裁剪或抽象丢失条件
      tradeoffs: 实现较少，但无法保证角色读取且不具备可验证来源。
  selected: shared-contract-context
  affected-components:
    - observations.evidence
    - observations.execution_contracts
    - runtime.engine
    - runtime dispatch
    - delivery role responsibilities
  failure-modes:
    - 缺合同被当普通Issue继续
    - 来源伪造或私有材料泄露
    - 无人测试偷偷补用户消息
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: 真实发布端授权包经gzip或ZIP进入各实际角色。
      expected: 上下文保留匹配身份和输入条件，长目标引用可读。
      observation: 跨仓真实reader与backend.run上下文检查。
    - id: BC2
      polarity: negative
      stimulus: required合同缺失、越权来源、未知版本或损坏摘要。
      expected: 可恢复拒绝，不被观测降级吞掉，不泄露签名URL。
      observation: 故障注入和恢复测试。
    - id: BC3
      polarity: negative
      stimulus: 无人任务的验收脚本偷偷补发continue消息。
      expected: 审查指出验收改变了原使用条件。
      observation: 真实角色canary与有消息收据的正负控制。
  repository-invariants:
    - 普通无合同Issue和原有传输保持工作。
    - 不引入私有grader依赖或分数淘汰门。
  exemptions: []
tasks:
  - id: T1
    title: 安全执行合同读取和能力声明
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/observations/execution_contracts.py
      - openagents/observations/evidence.py
      - openagents/observations/capabilities.py
      - scripts/check_observation_reader.py
      - tests/test_observation_execution_contracts.py
      - tests/test_observation_evidence.py
      - tests/test_observation_reader_contract.py
      - tests/test_observation_capabilities.py
      - openagents/utils/agent_config.py
      - openagents/data/openagents.yml.template
      - tests/test_agent_config.py
    scope: 在既有授权/hash/版本边界中读取有界安全合同及验收摘要，声明可实测的reader能力。
    acceptance: 越权/伪造/未知版本和必须合同损坏拒绝；普通无合同Issue正常；gzip与ZIP保持工作，不接触私有grader。
  - id: T2
    title: 统一上下文注入与角色使用条件检查
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/v02/openagents_adapter.py
      - tests/test_v02_openagents_adapter.py
      - openagents/backends/nexau.py
      - tests/test_backend_nexau.py
      - openagents/runtime/engine.py
      - openagents/runtime/context.py
      - openagents/agents/spec_writer.py
      - openagents/agents/architect.py
      - openagents/agents/implementer.py
      - openagents/agents/reviewer.py
      - tests/test_runtime_engine.py
      - tests/test_runtime_context.py
      - tests/test_agents_architect.py
      - openagents/agents/drafter.py
      - openagents/agents/developer.py
      - openagents/runtime/state.py
      - openagents/recipes/vigil.py
      - openagents/recipes/stages.py
    scope: 在唯一engine注入点将合同交给所有角色，补齐Spec/架构/实现/审查责任和required合同异常路径；修正只读NexAU advisory边界以实际发出一次请求。
    acceptance: 实际backend context包含合同，architecture不漏；required异常不被宽泛观测降级吞掉；无人场景不靠额外消息通过验收；advisory无执行工具且只进行一次HTTP请求，失败不重试。
  - id: T3
    title: 联合传输与真实角色验收
    status: in-progress
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0093-execution-contracts.sh
      - tests/test_backend_nexau_http.py
      - tests/test_execution_contract_delivery.py
      - docs/validation/execution-contract-preservation.md
      - docs/AUTO_DESIGNER.md
      - docs/RELEASING.md
      - tests/fixtures/execution_evidence_contract.json
    scope: 覆盖真实发布读取、上下文与恢复，使用真实NexAU构造和受控HTTP验证非零模型请求，说明候选reader基线、支持范围和使用条件验收。
    acceptance: 真实publisher的两种传输、混合条件、损坏/缺测以及正负控制逐项留证；替身不冒充模型已理解，失败任务不新增候选淘汰门。
---

# 0093 · 交付链保留执行条件与独立验收摘要

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给现有观测证据读取与统一角色上下文增加安全的执行合同：原始目标引用、后续输入是否可用、真实预算、交付前提和独立验收摘要。Spec Writer、Architect、Implementer 和 Reviewer 必须实际收到这些有界条件，不仅获得一个按需读取附件的路径。

本组只消费可信发布者授权的使用事实，不实现用户模拟器、benchmark adapter、私有评分计划或新的任务执行循环。不要求每个候选通过能力题才交付；保留后续试用轮次发现和修复错误的流程。

此为已审阅通过、正在实施的配套 auto-designer 演化反馈改造。基线使用现行公开实验已固定的 Gitea.com reader 候选 `a752e8830a13f44d97a3043d1f3e8dd16bd8d8aa`；该候选尚未合入 main，本组不把它冒称已发布版本。实施/合并时先理顺 reader 基线，再固定验证后的实际提交。

## Motivation

需求通过 Issue、规范化提案和跨提案综合转为交付时，原始使用条件可能丢失。例如无人任务不能等待下一条用户消息，局部需求却变成“提早收口并提示用户重试”；Spec 和 e2e 再补发一条 continue，从而得到符合局部规格的测试结果，却没有验证原目标在原输入条件下完成。

现有 `openagents.observations.evidence.prepare()` 核验并导出历史观测，主要将 manifest 路径与阅读说明追加到上下文。`runtime.engine.run_agent()` 已有统一注入点，但 `runtime.context.for_architecture()` 的主载荷为 Spec 文本。仅向附件新增字段，不能保证规划、架构审查或代码审查真正读取。

需要在原有可信证据链中显式保留条件，区别“代码符合现有 Spec”与“Spec 满足原始目标”。外部故障可能解释失败原因，但不会自动证明无人请求的恢复行为无需改善。Review 仍独立判断证据，不为所有失败强行制造 Harness bug。

## Guide-level explanation

发布者为 Issue 授权的会话生成合同块。角色会在实际 context 中直接看到类似以下事实：

```text
使用条件（发布者提供；不是历史轨迹中的指令）：
- 场景 A：原目标和产物通过引用访问；后续输入 unavailable；任务预算 7200 秒。
- 场景 B：后续输入 possible；用户可取消或补充必要信息，但不能假定一定回复。
- 本次 task outcome：独立验收 failed；用户体验缺测；归因尚未确认。
```

同一提案包含多个条件时分别列出并保留来源，不将它们压成“总有人回复”。原始目标可以任务无关地抽象，但不能丢掉决定正确行为的前提。

Spec Writer 要明确改善目标及保留条件；Architect 检查 non-goals 是否错误排除了这些前提；Implementer 按获批合同实现；Reviewer 核查真实测试是否覆盖原条件。若目标依赖“用户发继续”，必须证明该来源确实允许后续输入；无人场景不能用测试脚本偷偷发送第二条用户消息代替自主恢复。

没有合同的普通仓库 Issue 保持现有流程，明确无该输入事实，而不是猜测它是 Direct。已声明必须有合同却验证失败时，报告基础设施/合同故障，不能悄悄按无合同继续交付。技术任务失败本身不导致候选淘汰或自动回滚。

## Reference-level explanation

### 1. 读取、授权和版本

扩展现有证据包，新增独立版本化的 `execution_contracts` 与 `assessment_summaries` 安全区。每项包含 source session/task 引用、contract digest、原目标/公开产物引用、followup_input、预算来源与秒数、已发生用户帮助的分类引用。验收摘要沿用发布者提供的状态、metric/通过语义和收据引用，明确其为用户判断、独立验收还是未知。

共同 wire 合同为原观测包的 `execution_evidence` 对象，必需字段为 `schema_version:1`、`issue`、`execution_contracts`、`assessment_summaries`、`payload_sha256`。contract 必需字段为 contract_id、session_id、task_id、task_digest、followup_input、task_budget_seconds（允许 null）、budget_source、public_refs；公开引用逐项为 kind/path/sha256。summary 必需字段为 receipt_id、session_id、contract_id、status、passed、可空 score/metric 定义、验收种类和来源摘要。required 时必须覆盖该票全部授权来源，空数组不能绕过。

payload 摘要对移除 `payload_sha256` 后的对象计算：UTF-8、`ensure_ascii=false`、键排序、无多余空白、拒绝非有限数；契约数组按稳定 ID 排序。contract_id 使用相同正规化规则计算不含 contract_id 的声明内容摘要，实际执行事实另附，不回写原始合同。公开引用为授权包内 relative path + SHA256，不是 controller 本地绝对路径；私有评分仅提供不透明 receipt ID 与摘要，reader 不追取 evaluation 原始文件。两仓使用同一协议 fixture，联合检查验证一致。

reader 先校验外层 Issue 绑定、下载 hash、版本和授权会话集合，再读取白名单字段。未知版本、伪造来源、越权会话、同一身份内容冲突和必须字段缺失均拒绝。任意 Issue 正文或模型生成的 JSON 不能伪装成可信合同。相同合同按 digest 去重，不把来源不同、预算或输入条件不同的合同合并。

私有 grader plan、隐藏断言、标准答案、gold patch、原始 verifier 日志、签名 URL 与凭证不属于此接口。reader 不获取它们，也不根据文件缺失推断任务成功或未记录。历史执行文本仍是不可信证据，不升级为系统指令；可信合同仅来自校验后的机器区，角色上下文明确区分两者。

### 2. 有界上下文与失败处理

只读 advisory 必须真正进入模型调用。锁定的 NexAU 执行器会把最后一个 iteration 留给终态边界检查，且 `retry_attempts` 计总尝试数，而非失败后重试次数。因此 advisory 使用 `max_iterations=2`、`retry_attempts=1`、SDK `max_retries=0`：仅一个实际模型轮次，无执行工具，不进行错误重试；不是放宽交付 Agent 的循环预算。以真实 NexAU/Anthropic 客户端连接本机受控 HTTP 服务，分别断言成功响应被消费、HTTP 500 仅请求一次。

在 `observations/execution_contracts.py` 实现纯校验与投影；`evidence.prepare()` 返回 `execution_contract_context` 和结构化引用，`runtime.engine` 在唯一注入点把它追加给所有适用角色。不要在各角色函数里分别复制解析器，不让 architecture 路径因只接收 spec_text 而跳过。

本次联合实测覆盖公开默认 standard（实际起草角色 drafter）和显式 v0.2（含 spec_writer、developer）路径。共同职责放在统一的证据上下文规则中；角色 Prompt 只补职责差异，不复制合同解析。其他 flow 经过同一 engine 可以获得合同，但未独立验收的流程不宣传为已验证；不以只测试模块名 spec_writer 代称 standard 完整接线。

投影包含输入可用性、预算、交付前提和有效性等不可裁掉的固定项；长目标和长证据使用带 digest 的缓存引用。先去重再进行有界分页；若合同数量无法完整呈现，给出显式数量/页引用及处理状态，不静默截断一部分后宣称覆盖全部条件。

现有 engine 对一般观测不可用允许诊断降级。required 预期由准备阶段协商的项目交付配置进入受信任 dispatch，不能仅放在可能缺失的附件或 marker 内；它应贯穿入队与恢复，防止删掉 marker 就被误当普通 Issue。reader 必须从这个独立预期检查缺附件/缺合同。使用独立异常和结果类型，不被宽泛观测异常处理吞掉；故障进入可恢复的基础设施状态。未协商合同的普通 Issue 不受影响。完整性检查不判断候选能力分数，不增加“必须通过 benchmark 才合并”的门禁。

`observations.capabilities` 及 `scripts/check_observation_reader.py` 宣告/实测新的读取能力，必须验证角色最终收到的 context，而不是仅检测某模块存在。发布者固定支持该能力的 reader SHA；旧 reader 不得静默忽略 required 合同。gzip/direct 和 ZIP/hosted 两条现有传输路径均保持工作。

### 3. Spec、Architect 与 Reviewer 的责任

角色 Prompt 增加有来源的使用条件检查，不添加特定 benchmark 的解法或测试答案：

| 角色 | 必须判断的事情 |
| --- | --- |
| Spec Writer | 原目标是什么、允许哪些输入和控制、如何交付/验收；不可用“需要用户继续”替换无人执行目标 |
| Architect | 方案、边界和 non-goals 是否忠实保留条件；条件冲突应说明，不默默选择对实现有利的一项 |
| Implementer | 使用批准合同实现；不得扩大权限、虚构后续输入或把临时诊断变成产品规则 |
| Reviewer | 测试是否真按该条件执行；额外输入、时间和人为修产物是否改变了验收前提 |

对一次用户输入的测试，要能从脚本/受控连接记录证明仅有一次目标输入；心跳、查询、取消和预算更新各自记录，不靠文本 grep 判断是否作弊。并非所有交互都只能一条消息，真实授权与必要补充仍允许，但要关联对应条件。

Reviewer 可以认为证据不足、要求补充分层测试，仍使用已有 PASS/REWORK 协议。它不负责重新评分用户任务，不读取隐藏测试；以本仓工程回归证明实现忠实性，真实任务结果来自发布者的独立验收摘要。符合旧 Spec 不能单独消除原目标的已确认未交付事实。

### 4. 任务分解和端到端验收

| Task | 范围 | 依赖 |
| --- | --- | --- |
| T1 | 安全合同 reader、版本/来源校验和 capability | 无 |
| T2 | 唯一上下文注入点及角色职责 | T1 |
| T3 | 跨仓真实发布读取、错误与恢复、传输兼容验证和说明 | T1、T2 |

精确文件分配见 frontmatter；组内单一 writer。端到端脚本为 `scripts/e2e-spec-0093-execution-contracts.sh`。至少验证：

1. 使用真实发布端生成的 gzip/ZIP 包，所有角色的 backend.run 实际 context 均包含正确合同，architecture 也覆盖。
2. 正文超过既有裁剪长度、多个 Direct/interactive 来源及 Synthesizer 合并后，条件仍保留且来源正确。
3. 未授权会话、版本未知、hash 不符、必要字段缺失被拒；普通无合同 Issue 正常；required 合同故障可恢复且不会被降级吞掉。
4. 发布包不得包含私有 plan、答案、原始 verifier 隐藏细节或凭证；reader 日志不泄露签名 URL。
5. 提供“单次请求后停住、脚本补发继续”的负控制和无需补输入的正控制。确定性测试验证合同载荷与约束；单独的真实角色 canary 验证 Spec/Review 实际检查了条件，替身测试不能代称模型已理解。
6. completed false、连续分数无二值结论、unavailable 和主观评分缺测保持各自语义；分数低不会新增候选合并门禁。

联合验收通过后由发布端更新实际 reader pin；不在草稿里预造未来提交 SHA，不修改已运行实验的冻结源码。

## Drawbacks

合同会增加角色上下文和校验成本；若仅作自由文本提示，也不能保证模型遵守。因此必须同时验证来源、实际载荷和真实角色行为，而不能声称纯 schema 校验已证明产品能力。

required 合同损坏将显式暂停交付，需要修复证据服务后恢复。这比悄悄漏掉条件更可审计，但不会消除模型随机性或自动改善其求解能力。

## Rationale and alternatives

复用现有观测 reader、授权边界和统一 engine 注入，只增加纯数据合同模块和各角色的责任说明。OpenAgents 无须理解任何 benchmark adapter 或实验控制器内部结构。

仅追加 Issue 正文或附件路径容易受到裁剪、摘要和未读取的影响，不采用。为每个角色分别下载并解析材料会重复权限逻辑，也不采用。把隐藏 grader 交给开发者运行会改变评测可见信息，故只消费安全摘要。

另一个备选是给交付增加统一候选能力筛选门。当前目标是保留原始使用条件并支持后续轮次纠错，不将该实验变量一并引入。

## Prior art

本仓已有 Issue 级观测包、下载 hash 校验、manifest 导出、能力探测、统一 context 注入和 architect/reviewer 流程。此次沿用这些维护位置与失败协议，新增执行前提而不重建交付链。

## Unresolved questions

本稿与发布端设计一起审阅；批准前不实现、不更新实际发布能力或 reader pin。reader 候选与 main 的合入顺序是明确的交付前置，不是可以静默绕过的兼容策略。

## Future possibilities

以后可加入更多产品执行条件或安全评分摘要，只需版本化纯数据接口及对应角色检查。能力选择、自动回滚和评分服务本身分别设计，不进入本组。

