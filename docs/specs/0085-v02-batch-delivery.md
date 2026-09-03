---
number: "0085"
title: v0.2 最小批次开发与验收
issue: 0
slug: v02-batch-delivery
summary: 以一个 batch runner 执行 Spec、DAG、Developer、客观结果、Acceptance 和机械合并。
architecture:
  objective: 提供无同步 NeedHuman、无多层审核和无自动返工的最小可审计开发闭环。
  constraints:
    - LLM 角色仅 Spec Writer、Curator、Developer、Acceptance。
    - Developer 不得重写 Spec 或自验收；Acceptance 不得修改代码。
    - 每个 DAG batch 可并行开发；不可逆 merge 串行且只接受 PASS@当前 HEAD。
    - PARTIAL、BLOCKED、FAILED、NEEDS_DECISION 都是非阻塞终态，其他节点继续。
  non-goals:
    - 在首版删除 standard Vigil 与全部历史迁移代码。
    - 自动返工或让人类在 worker 内同步答题。
  candidates:
    - id: additive-v02-batch
      layer: orchestration
      boundary:
        - isolated batch recipe over existing adapters and gates
      evidence:
        - 旧 Vigil 可继续提供 standard 兼容，batch 核心可 hermetic 验证
      tradeoffs: 稳定期内存在两个入口，但避免直接改写庞大旧状态机。
    - id: mutate-vigil-in-place
      layer: orchestration
      boundary:
        - existing per-issue reconcile loop
      evidence:
        - 可复用现有 queue
      tradeoffs: batch barrier 与 post-Spec DAG 会侵入单 issue 状态机并扩大回归面。
  selected: additive-v02-batch
  affected-components:
    - openagents/agents/developer.py
    - openagents/v02/runner.py
    - openagents/v02/audit.py
    - openagents/utils/agent_config.py
    - openagents/cli.py
    - tests/test_v02_runner.py
  failure-modes:
    - 一个节点失败拖停整批；runner 必须把失败限定到依赖后继，独立节点继续。
    - Acceptance 自述 PASS 与旧 head 绑定；runner 复读 HEAD 并执行机械 gate。
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: 两个独立 READY Spec 与一个依赖节点，Developer 全部交付且 Acceptance PASS。
      expected: 首批两个 Developer 并行，依赖节点后执行，merge 串行。
      observation: 记录型 adapter 的事件序列与 topo batches 一致。
    - id: BC2
      polarity: negative
      stimulus: 一个 Developer 失败或 Acceptance PARTIAL。
      expected: 节点不合并、后继标记 blocked，其他独立节点继续；没有 NeedHuman 等待或返工。
      observation: BatchResult 中每节点终态和零错误 merge 调用。
  repository-invariants:
    - PASS 必须绑定当前 HEAD 和冻结 Spec digest。
    - runner 不产生 review-changes-requested 循环。
  exemptions: []
tasks:
  - id: T1
    title: 实现 Developer 契约与可注入 batch runner
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/developer.py
      - openagents/v02/runner.py
      - openagents/v02/audit.py
      - tests/test_v02_runner.py
      - tests/test_v02_audit.py
    scope: 按 DAG 分层执行单次 Developer 与 Acceptance，局部失败、阻断传播、串行 merge，所有外部动作通过 adapter 注入。
    acceptance: 并行层、依赖阻断、PARTIAL/FAIL、异常和 merge 序列测试通过。
  - id: T2
    title: 声明 v0.2 flow 与命令入口
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/utils/agent_config.py
      - openagents/data/openagents.yml.template
      - openagents/cli.py
      - tests/test_agent_config.py
      - tests/test_cli.py
    scope: 配置接受 flow=v0.2，并提供显式批次入口；standard/minimal/generate-only 保持兼容。
    acceptance: 配置 round-trip、CLI 参数和旧默认测试通过。
---

# 0085 · v0.2 最小批次开发与验收

## Summary

v0.2 batch runner 只编排四次职责：Spec、DAG、Developer、Acceptance；测试、head/digest、PR 与 merge 都是机械动作。没有 Owner、Architect、传统 Reviewer、Tester 或 Merger LLM。

## Motivation

旧开发链在每层重新读取上下文并排除困难实现，最后形成 prompt-only 改动和繁重自证。最小闭环让设计认知集中在 Spec Writer、实现集中在 Developer、最终目标裁决保持独立。

## Guide-level explanation

用户显式启动一个 v0.2 batch。runner 并行生成 Spec，调用一次 Curator，按拓扑层并行开发；每个交付只验收一次。失败节点终止并阻断后继，但不影响无依赖节点。

## Reference-level explanation

首版 runner 以 adapter 协议隔离 forge/worktree/backend，核心调度可 hermetic 测试。节点状态包括 READY、DEVELOPED、PASS、PARTIAL、FAIL、FAILED、BLOCKED_BY_DEPENDENCY、NEEDS_DECISION。只有 PASS 调用串行 merge callback。

## Drawbacks

无自动返工会降低一次成功率；这是显式选择，失败结果比隐藏目标缩水更可审计。

## Rationale and alternatives

直接修改旧 Vigil 状态机会把 batch barrier 塞进单 issue reconcile 并扩大回归面。独立 v0.2 recipe 复用底层 adapter，待行为稳定后再替换默认入口。

## Prior art

承接 Spec-0082 的三拍流、Spec-0065 的并发队列和 Spec-0081 的机器失败收口。

## Unresolved questions

首版不做跨批动态重排；实际写集合冲突交给 forge/rebase fail-closed。

## Future possibilities

稳定后令 v0.2 成为默认并删除 standard 兼容栈与旧 needs-human 迁移代码。
