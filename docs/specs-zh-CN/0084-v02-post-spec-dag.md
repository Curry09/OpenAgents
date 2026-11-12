---
number: "0084"
title: v0.2 post-Spec Curator DAG
issue: 0
slug: v02-post-spec-dag
summary: 在一批 Spec 完成后统一生成依赖 DAG 与并行批次，Curator 不再参与入口技术审核。
architecture:
  objective: 使用 READY Spec 的结构化机制、文件和证据生成可验证 DAG，使独立 issue 并行、依赖 issue 有序执行。
  constraints:
    - Curator 只读取冻结 Spec 摘要，不重新调查仓库或否决技术方案。
    - PARTIAL/BLOCKED 不进入图。
    - 边必须引用真实节点、不得自指或成环；坏图整批拒绝，不执行开发。
    - 拿不准依赖时不造边；文件重叠与显式接口依赖使用确定性锚点。
  non-goals:
    - 处理运行中出现的 git 内容冲突。
    - 替代 Spec Writer 判断单 issue 的实现机制。
  candidates:
    - id: post-spec-batch-plan
      layer: orchestration
      boundary:
        - frozen READY specs to validated DAG batches
      evidence:
        - Spec 已包含预测文件、控制点与接口依赖
      tradeoffs: 必须等待本批 Spec barrier，但依赖判断有可靠输入。
    - id: intake-issue-plan
      layer: orchestration
      boundary:
        - raw issue text to dependency edges
      evidence:
        - 现有 Vigil curator 使用该方式
      tradeoffs: 过早猜测文件和机制，或被迫重新调查仓库。
  selected: post-spec-batch-plan
  affected-components:
    - openagents/agents/spec_curator.py
    - openagents/v02/model.py
    - openagents/v02/planner.py
    - tests/test_v02_planner.py
  failure-modes:
    - Curator 幻觉不存在的 issue；图校验 fail-closed。
    - 同文件节点被错误并行；确定性文件冲突边补在模型建议之前。
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: 四个 READY Spec，其中两个共享文件、一个显式依赖、一个独立。
      expected: 输出稳定拓扑批次，独立节点并行，共享文件节点错峰。
      observation: 纯内存测试断言 batches 与 edges。
    - id: BC2
      polarity: negative
      stimulus: Curator 输出环、自指或未知节点。
      expected: planner 抛 PlanError，零 Developer 调用。
      observation: runner 记录 plan_failed 终态。
  repository-invariants:
    - 同一 issue 在 DAG 中最多一个节点。
    - 每个开发批次只含当前入度为零的节点。
  exemptions: []
tasks:
  - id: T1
    title: 实现冻结 Spec 节点、DAG 校验与拓扑批次
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/spec_curator.py
      - openagents/v02/model.py
      - openagents/v02/planner.py
      - tests/test_v02_planner.py
    scope: 定义 SpecNode、Curator 输出契约、确定性文件冲突锚点、无环校验和稳定分层拓扑排序。
    acceptance: READY 过滤、未知节点/自指/环负例和独立节点并行测试通过。
---

# 0084 · v0.2 post-Spec Curator DAG

## Summary

Curator 从入口分诊者改为 batch planner：等待本批 Spec 完成后，仅对 READY Spec 排实现依赖和并行批次。

## Motivation

Issue 原文不足以可靠预测修改文件与控制点。过早排边会猜测依赖；让 Curator 再次读仓库又会重建 Spec Writer 已经获得的上下文。冻结 Spec 已包含 selected intervention、files、ownership 与 evidence，是排 DAG 的正确输入。

## Guide-level explanation

runner 先并行写所有 Spec，然后过滤 READY。Curator 对 READY 摘要建议语义边；planner 同时根据确定性文件交集增加稳定冲突边，最后校验并生成 batches。

## Reference-level explanation

边方向为 `issue -> blocked_by`。拓扑层每轮选择 blockers 已全部完成的节点并按 issue number 排序。共享文件的两个无语义依赖节点按较小 issue 在前，保证确定性且避免双写。

## Drawbacks

预测文件可能与 Developer 实际写入不同；运行时仍需 git mergeability 和写集合审计兜底。

## Rationale and alternatives

直接复用 Vigil 的入口 curator 会继续依据 issue 文本猜图。新 planner 复用其无环思想，但输入改为冻结 Spec。

## Prior art

Spec-0065 的 `_proposed_edges` 与 `_cycle_members` 已证明边校验和并行 worker 模型可行。

## Unresolved questions

跨仓接口依赖暂不进入 v0.2 简化版。

## Future possibilities

将实际 changed-files 反馈给尚未启动的批次，动态收紧冲突边。
