---
number: "0091"
title: Lightweight advisory coordination
issue: 0
slug: lightweight-preflight
summary: Add bounded, advisory preflight planning and soft queue coordination without turning planning into a delivery barrier.
architecture:
  objective: Keep optional coordination useful and bounded while preserving the original issue, acceptance, dependency, and delivery gates as authoritative.
  constraints:
    - Planning is advisory and must not create an execution-wave barrier.
    - Planner calls are bounded, cached, restart-safe, and isolated from worker claims.
    - Raw issues and existing forge blockers remain unchanged.
  non-goals:
    - Do not claim that scheduling measurements establish semantic developer correctness.
    - Do not introduce a new persistent role or replace the existing queue and claim model.
  candidates:
    - id: bounded-advisory-planner
      layer: coordinator, preflight cache, and Vigil queue ordering
      boundary:
        - issue intake
        - queue discovery
        - worker claim ordering
      evidence:
        - tests/test_preflight.py
        - docs/e2e-results/preflight-20260911/REPORT.md
      tradeoffs: Adds a bounded advisory call and cache while leaving eligibility and delivery gates unchanged.
    - id: mandatory-planning-barrier
      layer: execution scheduler
      boundary:
        - every intake wave
        - worker admission
      evidence:
        - would delay existing workers and make planner failure a product failure
      tradeoffs: Rejected because planning latency and failure would block otherwise eligible work.
  selected: bounded-advisory-planner
  affected-components:
    - openagents/agents/coordinator.py
    - openagents/recipes/vigil.py
    - openagents/runtime/preflight.py
    - openagents/runtime/engine.py
    - openagents/backends/claude_code.py
    - openagents/backends/nexau.py
  failure-modes:
    - invalid planner output
    - planner timeout or process failure
    - cache corruption or restart during persistence
    - advisory cycles or lock contention
verification:
  behavior-cases:
    - id: bounded-planning
      polarity: positive
      stimulus: soft coordination is enabled with ready issues
      expected: one bounded planner call produces at most eight clusters, order suggestions, and reuse notes without blocking existing workers
      observation: tests/test_preflight.py and validation report
    - id: invalid-or-timeout
      polarity: negative
      stimulus: planner returns invalid output or exceeds its wall budget
      expected: advisory failure is recorded and queue eligibility remains available
      observation: preflight failure and timeout tests
    - id: restart-cache
      polarity: positive
      stimulus: process restarts with unchanged or changed ready issue inputs
      expected: unchanged fingerprints are cached; changed inputs retry after cooldown
      observation: cache/restart/edit tests
    - id: advisory-ordering
      polarity: positive
      stimulus: hints include overlapping clusters, cycles, or stale suggestions
      expected: all eligible issues remain claimable and ordering only affects priority-1 preference
      observation: scheduling and concurrent claim tests
  repository-invariants:
    - Planner output never edits raw issues or overrides acceptance and delivery gates.
    - Claims retain SQLite BEGIN IMMEDIATE and flock protection.
    - Disabling soft coordination clears the advisory cache on startup.
  exemptions: []
tasks:
  - id: T1
    title: Bounded advisory preflight and soft scheduling
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/coordinator.py
      - openagents/backends/claude_code.py
      - openagents/backends/nexau.py
      - openagents/data/openagents.yml.template
      - openagents/recipes/vigil.py
      - openagents/runtime/engine.py
      - openagents/runtime/preflight.py
      - openagents/utils/agent_config.py
      - tests/test_backend_claude_code.py
      - tests/test_backend_nexau.py
      - tests/test_preflight.py
      - tests/test_recipe_vigil_act.py
      - tools/preflight_stress.py
      - docs/e2e-results/preflight-20260911/REPORT.md
      - docs/specs/0091-lightweight-preflight.md
    scope: Implement bounded advisory planning, durable input fingerprints, sanitized cache persistence, cooldown/retry behavior, and queue ordering that never changes issue eligibility.
    acceptance: Unit and concurrency tests cover invalid output, timeout, cache/restart/edit, partial admission, lock contention, advisory cycles, and concurrent claims; validation records scheduling cost without presenting it as developer correctness.
---

# 0091 · Lightweight advisory coordination

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

本组给 Vigil 增加一个有界、非阻塞的 advisory preflight：它可以对 ready issue 做轻量聚类、顺序建议和复用提示，
但原始 issue、验收条件、依赖和交付门禁始终是权威。规划失败、超时或重启不会把正常 worker 变成失败。

## Motivation

当 ready issue 较多时，完全 FIFO 会丢失已有的相似性和复用线索；另一方面，把规划调用变成执行波次屏障会把模型延迟和临时故障扩大成整轮阻塞。
因此需要一个可禁用、可缓存、可恢复的 advisory 层，只影响优先级相同任务的排序，不改变资格判断和交付结果。

## Guide-level explanation

`coordination: soft` 启用 advisory planner；兼容默认值为 `dependencies`，`off` 同时跳过 planner。每次 intake 最多观察 64 个 ready issue，
单次输出最多 8 个 cluster、8 个顺序建议和 8 个复用说明。Claude/NexAU 使用无工具单轮调用，输出上限 8,192 tokens，墙钟上限 90 秒，且不做协议修复。
planner 在新 work 入队前运行，但不是执行波次屏障；已有 worker 继续工作。

提示只在最高优先级的 priority-1 issue 内影响 claim 顺序：优先减少活跃 cluster 重叠和建议前置依赖，再按建议首项排序，900 秒后恢复 FIFO。即使提示成环或所有 issue 落入同一 cluster，所有候选仍可 claim。

## Reference-level explanation

输入 fingerprint、清理后的输出、耗时和状态持久化到 `.openagents/preflight.json`；token usage 继续写入已有 ledger。fingerprint 可防止相同输入重复调用，
包括失败和进程重启；120 秒 cooldown 合并增量 admission，输入变化后再尝试。删除已完成 issue 本身不会触发 planner。关闭 soft coordination 时启动过程清除该 cache。

调用使用临时工作目录，planner 异常只作为 advisory failure 记录，绝不写 automation-failed label。原始 issue 文本始终随 developer advice 传递，修改 issue 会使 advice 失效。
Claims 继续使用 SQLite `BEGIN IMMEDIATE` 与 flock。验证覆盖 invalid output、timeout、cache/restart/edit、partial admission、stage priority、aging、advisory cycle、lock contention 和 concurrent claims，
并用既有报告记录 30/300/3000 queued issue 的调度成本；这些指标不等同于开发语义正确率。

## Drawbacks

系统增加了一次可选模型调用、一个本地 cache 和更多排序分支；即使 planner 完全不提供收益，也需要维护其超时、重启和损坏恢复路径。advisory 提示还可能让观察者误以为它是硬依赖，因此输出和日志必须明确标记为 advisory。

## Rationale and alternatives

选择有界 advisory planner，而不是强制规划屏障或无界重试。强制屏障会延迟已有 worker，并把规划故障扩大成调度故障；无界重试会在外部模型不可用时持续占用入口。保留现有 claim eligibility、SQLite/flock 和交付门禁，可以把收益限制在排序层，避免改变系统的事实边界。

## Prior art

实现复用现有 Vigil queue、SQLite claim 和 token ledger；没有引入新的调度器或持久化服务。验证报告位于 `docs/e2e-results/preflight-20260911/REPORT.md`。

## Unresolved questions

调度成本和建议命中率尚不足以证明对真实开发吞吐有稳定收益；真实模型、forge 和部署环境仍需单独闭环验证。planner 的建议也不应被用作需求理解或验收正确性的证据。

## Future possibilities

未来可以在不改变资格和交付门禁的前提下，比较不同 advisory 排序策略的长期收益；如需改变依赖语义、引入新持久化状态或形成执行屏障，应另立 spec。
