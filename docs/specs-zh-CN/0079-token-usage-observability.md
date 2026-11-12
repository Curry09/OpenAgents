---
number: "0079"
title: OpenAgents Claude Code API token 用量可观测性
issue: 0
slug: token-usage-observability
summary: 从 OpenAgents 已使用的 Claude Code stream-json 最终事件采集其 API token usage，按角色与调用写入本地账本，并在报告中同时展示消耗和采集覆盖率；拿不到用量时显式记录 unavailable，绝不把缺失当作零。
architecture:
  objective: 建立从 ClaudeCodeBackend 已读取的 stream-json result.usage 到 AgentResult、runtime 账本和 oa report 的完整链路，使开发等角色经用户 API 运行时的消耗与采集覆盖率都可审计。
  constraints:
    - 数据源必须是 OpenAgents 自己启动的 Claude Code 调用所输出的最终 result.usage，不得借用 harness 或其他进程的统计
    - 只记录计数、模型、backend、角色、时间和状态，不记录 prompt、response、工具参数或推理正文
    - API 未报告 usage 时必须记录 unavailable，不得估成零或静默漏行
    - 遥测失败 fail-open，不得改变 Agent 的业务结果或异常语义
    - 旧 backend 不提供 usage 时保持 AgentResult 源码兼容
    - cache read、cache creation、reasoning 与普通 input/output 分栏保留，禁止无依据重复相加
  non-goals:
    - 监控 OpenAgents 之外的模型调用
    - 改写 Claude Code 的 API client、代理用户网关或要求更换现有 backend
    - 从文本长度反推精确计费 token
    - 在本 feature 中实现价格表或费用结算
    - 保存完整模型请求响应
  candidates:
    - id: outer-text-estimation
      layer: runtime
      boundary:
        - runtime.engine prompt/result text
      evidence:
        - OpenAgents 能看到外层 prompt 和最终文本
      tradeoffs: 看不到 API backend 内部多轮工具调用、缓存和 reasoning；数字貌似完整但系统性低估，拒绝。
    - id: harness-telemetry
      layer: unrelated-external-process
      boundary:
        - harness usage frames
        - harness usage ledger
      evidence:
        - harness 可能已经记录自己的 API 用量
      tradeoffs: 统计对象不是 OpenAgents 发起的 Claude Code 角色调用，角色和调用边界不同，拒绝。
    - id: claude-result-usage-ledger
      layer: claude-code-stream-result-runtime-observability
      boundary:
        - ClaudeCodeBackend stream-json parser
        - AgentResult
        - runtime.engine
        - local JSONL ledger
        - oa report
      evidence:
        - Claude Code 2.1.12 的最终 result 事件直接给出整次 CLI 调用聚合后的 usage 与 modelUsage
      tradeoffs: 依赖 Claude Code stream-json 契约；字段缺失或版本漂移必须显式记 unavailable。
  selected: claude-result-usage-ledger
  affected-components:
    - openagents.backends.base
    - openagents.backends.claude_code
    - openagents.runtime.engine
    - openagents.runtime.token_usage
    - openagents.cli
  failure-modes:
    - Claude Code result.usage 字段变化导致采集静默缺失
    - 同时累加 assistant.message.usage 与 result.usage 导致整次调用重复计算
    - 把 unavailable 当零导致角色成本被低估
    - cache token 被同时算入 input 和 total 导致重复计算
    - linked worktree 分散写账本导致同一运行无法汇总
    - 遥测写入失败阻断正常 Agent 流程
    - 只用自造 fixture 测试而从未确认已安装 Claude Code 的真实 stream-json 事件形状
verification:
  behavior-cases:
    - id: claude-result-usage-roundtrip
      polarity: positive
      stimulus: OpenAgents 启动的 Claude Code 最终 result 事件含 input/output/cache usage 与 modelUsage
      expected: AgentResult 保留规范化计数，runtime 落一条 reported 账本，oa report 聚合值与 result.usage 一致
      observation: 真实事件 fixture 单元测试 + 一次 opt-in Claude Code API canary 的脱敏 usage 与账本对照
    - id: backend-without-usage-is-visible
      polarity: negative
      stimulus: 旧 backend 返回不含 usage 的 AgentResult
      expected: 业务结果不变，账本新增 unavailable 行，报告覆盖率分母包含该调用
      observation: fake backend 集成测试
    - id: telemetry-write-failure-isolated
      polarity: negative
      stimulus: .openagents 路径不可写
      expected: 原 Agent 返回或原 backend 异常不被遥测覆盖
      observation: runtime ledger 与 engine 异常测试
    - id: real-claude-schema-drift-visible
      polarity: negative
      stimulus: opt-in live canary 的 Claude Code result 事件没有可解析 usage
      expected: canary 失败并只打印脱敏字段名，feature 不得以 live-verified 状态验收
      observation: Claude Code live canary 退出码
  repository-invariants:
    - token-usage.jsonl 不含 prompt、response、工具参数和推理正文
    - 每次 engine.run_agent 调用恰有一条 reported 或 unavailable 记录，包括 backend 抛错
    - linked worktree 的账本写入主工作树 .openagents
    - oa report 同时显示调用数、reported 数和 unavailable 数，不把覆盖率缺口隐藏在总量中
    - total 的来源必须标注 reported 或 derived-components
  exemptions:
    - 未在真实 Claude Code 成功模型响应上取得 result.usage 前，公共契约、账本和报告即使测试全绿也不代表 live 验收完成；不得用 harness 结果代替。
tasks:
  - id: T1
    title: TokenUsage 后端结果契约
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backends/base.py
      - tests/test_base.py
    scope: 在 AgentResult 增加可选 TokenUsage；字段分离 input/output/cache-read/cache-creation/reasoning/total，并携 model 与 total_source；旧构造方式零修改兼容。
    acceptance: 测试证明旧 AgentResult 默认 usage=None；负数、布尔值等非法计数不能进入规范化结果；total_source 仅允许 reported/derived-components。
  - id: T2
    title: Claude Code stream usage 适配与真实接线
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/backends/claude_code.py
      - openagents/runtime/engine.py
      - tests/test_backend_claude_code.py
      - tests/test_runtime_engine.py
    scope: 保持既有 backend=claude_code 与用户 API 配置不变；ClaudeCodeBackend 在现有 stream-json 读取循环中只解析最终 result.usage，并用 modelUsage 或 init.model 标识模型。result.usage 已是整次 CLI 调用聚合，禁止再累加 assistant.message.usage。计数随 AgentResult 返回；字段缺失时 usage=None。不得读取 prompt、回复正文、harness 账本或 API 密钥代填。
    acceptance: agents.implementer.backend=claude_code 时开发阶段无需换 backend 即可采集；真实 Claude Code 2.1.12 result fixture 覆盖 input/output/cache、单/多模型、部分/畸形/无 usage、显式/派生 total；assistant usage 不参与合计；原 stream 输出、工具事件、协议结果和异常语义不变。
  - id: T3
    title: 调用级 token 账本与 runtime 接线
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/token_usage.py
      - tests/test_runtime_token_usage.py
    scope: 每次 run_agent 成功或失败均向主工作树 .openagents/token-usage.jsonl 追加一行；记录 role/backend/model/status/source 和 token 分量；聚合器按角色汇总并报告覆盖率；写入失败 fail-open。
    acceptance: 测试覆盖 reported/unavailable、backend 异常、不可写目录、损坏行、linked worktree、按角色聚合、恰好一调用一行和隐私字段白名单；业务结果及原异常保持不变。
  - id: T4
    title: Token 报告与用户契约
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - tests/test_cli_timing.py
      - docs/cli.md
    scope: oa report 增加按角色 token 表，分别展示调用/reported/unavailable、input/cache-read/cache-write/reasoning/output/total；解释 total_source 和覆盖率，不改变既有 timing/tool 报告。
    acceptance: 测试覆盖仅 token 数据、与 timing/tool 并存、全 unavailable、混合覆盖率及空数据；文档明确 total 口径与 unavailable 不等于零。
  - id: T5
    title: 离线端到端与真实 Claude Code API canary
    status: done
    priority: P0
    tags: []
    depends-on:
      - T2
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0079-token-usage-observability.sh
      - scripts/live-spec-0079-token-usage-observability.sh
      - scripts/live_spec_0079_token_usage_observability.py
    scope: 离线脚本跑 lint、针对性测试、spec validate/render/graph check；opt-in live canary 通过 OpenAgents 的现有 ClaudeCodeBackend 发最小请求，对照 result.usage、AgentResult、ledger 与 report，只保存字段名、计数和版本等脱敏证据。
    acceptance: 离线脚本全绿；在 Claude Code 已配置用户 API 的验收环境中 live 脚本至少成功一次，证据包含 backend/model、result usage 字段、账本值、报告值及三者一致性；没有成功模型响应时 T5 不得标 done。
---

# 0079 · OpenAgents Claude Code API token 用量可观测性

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

OpenAgents 为自己的每次角色 Agent 调用建立 token usage 链路：现有 ClaudeCodeBackend 从 Claude Code
stream-json 最终 `result.usage` 提取整次 CLI 调用的 API 计数，经可选 `AgentResult.usage` 交给 runtime，按调用追加到主工作树本地账本，最后由
`oa report` 按角色展示消耗与采集覆盖率。没有 usage 的调用明确记为 `unavailable`，不估算、不归零。

## Motivation

OpenAgents 目前无法回答一次实现、评审或架构调用消耗了多少 token。外层只看得到任务文本和最终结果，无法覆盖
Claude Code 内部的多轮工具调用、缓存和模型请求。缺失数据若被当作零会系统性低估成本；用文本长度估算则会制造虚假
精确度。因此必须在 OpenAgents 自己的模型 API 调用边界采集 usage。

这里的统计对象严格限定为 OpenAgents。其他进程即使也调用同一个 API，其 usage 也属于另一套运行边界，不能
拿来替代 OpenAgents 的账本和验收。

## Guide-level explanation

每次 `run_agent` 最终产生一条账本记录。若 Claude Code 最终事件报告 usage，记录为 `reported`；若 backend 不支持、
字段缺失或调用在获得 usage 前失败，记录为 `unavailable`。报告把调用数、已采集数、缺失数和 token 合计并列，
让用户不会把部分覆盖误读成完整成本。

## Reference-level explanation

`TokenUsage` 是 backend 结果协议中的可选不可变值，包含 input/output、cache read、cache creation、reasoning、
total、model 和 `total_source`。adapter 只接受非负整数；Claude Code 给显式 total 时标 `reported`，仅在字段
语义确认互斥时才允许从分量派生 total 并标 `derived-components`。runtime 不自行猜测 provider 字段。

本功能复用既有 `claude -p --output-format stream-json --verbose`。Claude Code 的 `assistant.message.usage`
属于中间消息，而最终 `result.usage` 已聚合整次运行；adapter 只读取后者一次，避免多轮重复计数。用户现有
`ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_MODEL` 等 Claude Code API 配置保持不变，OpenAgents
既不读取也不落盘密钥。`modelUsage` 只有一个模型时记录该模型；多模型时保留模型集合标识。

任务 DAG：

```text
T1 公共契约 ─→ T2 Claude stream adapter ──────┐
     └──────→ T3 ledger/runtime → T4 report ─→ T5 真实 API 验收
```

T1、T3、T4 只能证明公共承载链路成立。T2 接入现有 Claude Code stream 后，还必须由 T5 以用户真实 API
配置证明 result usage、账本和报告一致，整个 feature 才能宣称完成。harness 或其他进程的用量不属于本 spec。

## Drawbacks

账本会持续增长，需要后续考虑轮转。不同 API provider 对 cache 和 total 的定义可能不同，跨 backend 比较必须
同时查看 model、分量和 `total_source`。真实 canary 依赖凭据和网络，不适合每次提交必跑，但发布验收必须成功。

## Rationale and alternatives

选择 Claude result usage ledger，因为 OpenAgents 已经逐行读取这条结构化流，最终事件又恰好是整次 Claude Code
调用的聚合边界。外层文本估算会漏掉内部多轮调用；代理网关日志需要额外关联；harness 账本属于不同统计对象。
新增 NexAU 或直接 API backend 会改变用户现有运行链，不能作为本需求的必要条件。

## Prior art

OpenTelemetry 的 LLM semantic conventions 和多家模型 API 的 usage 对象都将计数与消息正文分离，并区分模型、
输入、输出及缓存维度。本设计采用相同原则，但首版保持本地 JSONL，不引入远程 collector。

## Unresolved questions

不同 Claude Code 版本及兼容 API 网关是否始终提供同一组 usage 字段，需要由 live canary 持续取证；缺字段时保持
`unavailable`，不能用 assistant 中间事件或文本估算填补。

## Future possibilities

后续可将 ledger 与 issue/PR/round、阶段 timing 和 API request ID 关联，计算每个有效合并的 token 成本；也可
增加 JSON/CSV 导出、账本轮转以及按角色预算告警。所有扩展仍应保留 unavailable 覆盖率。
