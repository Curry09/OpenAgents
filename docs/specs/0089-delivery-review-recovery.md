---
number: "0089"
title: 中断交付恢复与评审版本一致性
issue: 0
slug: delivery-review-recovery
summary: 中断后续交付，评审与合并绑定同一已推送候选；合法换版重新评审，不误耗执行失败预算。
architecture:
  objective: 中断后保留并完成原开发成果，最终合并实际评审过的已推送候选，正常任务不因版本检查失去可推进性。
  constraints:
    - 复用现有角色、run.status、队列、审批标签及失败预算，不增加持久化实体。
    - 不清空或重建已有工作区；未推送和未提交成果不得冒领远端审批。
    - 合法换版使旧裁决失效；读取失败和未交付代码不能伪装成换版。
  non-goals:
    - 不实现设计摘要失配后的架构评审回流，不修改 Spec-0088 的待实现要求。
    - 不部署镜像、重启实验、修写历史归档或保证真实模型的需求理解能力。
  candidates:
    - id: existing-recovery-and-sha-gates
      layer: existing Vigil recipe, Workspace and forge adapters
      boundary:
        - 开发交接
        - 候选检查
        - 原生条件合并
      evidence:
        - tests/test_delivery_recovery_git.py
        - tests/test_delivery_recovery_stress.py
        - scripts/stress_delivery_recovery.py
      tradeoffs: 增加少量 Git 事实检查；真实换版需要重新评审，不要求正常路径新增模型调用。
    - id: strict-rejection-only
      layer: delivery gate
      boundary:
        - 仅拒绝本地与远端不一致
      evidence:
        - docs/specs/2026-09-09-delivery-review-snapshot-tests-design.md
        - docs/specs/2026-09-09-delivery-recovery-stress-design.md
      tradeoffs: 能阻止错合，但无法完成超时续交付，连续换版会烧光执行失败预算。
  selected: existing-recovery-and-sha-gates
  affected-components:
    - recipes.vigil
    - recipes.stages
    - utils.workspace
    - runtime.gates
    - utils.github
    - utils.gitea
    - cli
    - agents
  failure-modes:
    - 超时后仅因 PR 存在就跳过实现，导致只合入 Spec。
    - 评审读取未提交代码，审批却绑定已推送的旧提交。
    - 连续合法换版被误当执行失败，第三次后永久挂起。
    - 检查后远端再变化或合并失败，仍以旧审批合入新版或关闭 issue。
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: 在 commit 前、commit 后或 push 后中断开发，再恢复同一任务。
      expected: 保留原工作区和成果，续交付、重新评审、合入对应实现；补 push 不制造空提交。
      observation: tests/test_delivery_recovery_git.py 检查真实 bare remote main 内容及原工作区；专项脚本验证三种 flow。
    - id: BC2
      polarity: positive
      stimulus: 评审期间连续三次合法更新远端，随后候选稳定。
      expected: 前三次裁决失效，第四次评审并合并；执行失败 attempts 不累计。
      observation: 压测 remote-churn-3 的 40 个目标全部完成，只批准最终 SHA；同批 104 个正常对照完成。
    - id: BC3
      polarity: negative
      stimulus: 工作区未提交、评审者留下未推送提交或 Git/forge 读取失败。
      expected: 不批准不一致候选；真实持续故障沿既有三次预算停止，不影响其它任务。
      observation: 真实 Git 读边界回归及常规压力中的 96 个持续故障对照。
    - id: BC4
      polarity: positive
      stimulus: 混合正常、一次超时、补 push、换版、REWORK、缓存和一次读取失败并发运行。
      expected: 912 个正常或可恢复任务完成，合并内容与实际评审 SHA 一致，无重复认领和队列残留。
      observation: scripts/stress_delivery_recovery.py 的 1/4/8/16-worker 两组固定种子压力，共 1008 个任务。
  repository-invariants:
    - 开发阶段允许改动；只在交付和读者验收边界检查干净候选，保留终态、回复、依赖和 draft 转正顺序。
    - 所有自动合并调用传递已批准 SHA，GitHub 使用 match-head-commit，Gitea 使用 head_commit_id。
    - 合并报告未成功时不得标记 done 或关闭 issue；Git 已忽略的缓存不算未交付源码。
  exemptions: []
tasks:
  - id: T1
    title: 恢复交付并验证同一候选直至合并
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/deliver.py
      - openagents/agents/executor.py
      - openagents/agents/merger.py
      - openagents/agents/reviewer.py
      - openagents/agents/tester.py
      - openagents/cli.py
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - openagents/runtime/gates.py
      - openagents/utils/gitea.py
      - openagents/utils/github.py
      - openagents/utils/workspace.py
      - tests/test_forge.py
      - tests/test_gitea_driver.py
      - tests/test_github.py
      - tests/test_recipe_stages.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil_timing.py
      - tests/test_runtime_gates.py
      - tests/test_workspace.py
      - tests/test_delivery_recovery_git.py
      - tests/test_delivery_recovery_stress.py
      - scripts/e2e-delivery-review-recovery.sh
      - scripts/stress_delivery_recovery.py
      - docs/specs/2026-09-09-delivery-review-recovery-design.md
      - docs/specs/2026-09-09-delivery-review-snapshot-tests-design.md
      - docs/specs/2026-09-09-delivery-recovery-stress-design.md
    scope: 复用已有状态与角色完成中断开发；读取真实 Git 候选并绑定原生合并 SHA；合法换版重新评审；归档正反例压力与可复现入口。
    acceptance: 全量及专项回归通过；原 40 个连续换版目标稳定后完成；912 个常规可恢复任务完成且 96 个持续故障有界停止；错合、意外阻断、重复认领、队列残留均为零；未提交和未推送的评审改动不得冒领 PASS。
  - id: T2
    title: 清理 Claude 进程组并闭合恢复后的退出边界
    status: in-progress
    priority: P1
    tags: []
    depends-on: [T1]
    relates-to: []
    parallel: false
    files:
      - openagents/backends/claude_code.py
      - tests/test_backend_claude_code.py
      - docs/specs/0089-delivery-review-recovery.md
    scope: Claude 主进程收到停止信号后，即使 leader 已退出，也必须确认其独立进程组没有遗留 shell/MCP 子进程；若进程组仍存在，升级为 SIGKILL，并保持恢复下一次交付所需的退出边界。
    acceptance: 在 leader 对 SIGTERM 正常退出但子进程仍存活的故障注入中，先发 SIGTERM、确认进程组仍存在后发 SIGKILL；leader 已退出且进程组消失时不误杀新复用的进程组；定向 backend 测试通过。
---

# 0089 · 中断交付恢复与评审版本一致性

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

代码修改完毕。本组把中断恢复、交付检查、
评审验收与条件合并作为一个原子修复交付：开发未完成时继续原工作区，评审只认证已推送候选，
合并只接受该候选；合法换版重新评审，不消耗执行失败预算。不新增运行时角色或状态实体。
日期设计文档保留原诊断、失败与修复证据，本文件是当前实现的正式规格。

## Motivation

实验中开发先推送了 Spec 提交 `472621c`，随后实现和测试留在本地；调用超时后重试发现已有 PR，
跳过剩余开发。Reviewer 检查了未提交实现并给 PASS，宿主却将 PASS 绑定远端 Spec 提交，最终
实现未合入。根因不是没写代码，而是“开发交接完成”和“实际评审版本”没有在交付边界核对。

最初增加严格相等检查虽然防止错合，却把评审期间的远端合法前进当成未交付错误；压力测试中
连续三次换版的 40 个任务全部耗尽失败预算。修复必须同时保证不错误合并与正常任务最终完成，
不能通过增加重试次数或只统计拒绝来掩盖不可推进。

## Guide-level explanation

1. 开发前写入已有状态 `iterating`，真正交付后才写 `pr-open`。超时恢复同一 PR 与工作区，
   继续原需求和剩余开发；不能把已有 PR 或 draft 转正当成交付完成。
2. 未提交则完成实现和提交；已经提交则只补 push；已经推送但丢返回则核验收尾，不制造空提交。
3. 评审前同步干净且仅落后的工作区；本地有改动或分叉时交回现有开发/交付，不删除源码。
4. 评审和测试结束后再次核对候选。合法换版丢弃旧裁决并重新评审；改脏、未推送和读取失败
   仍按真实失败处理。缓存走 Git 的既有忽略规则，不按扩展名豁免未知文件。
5. 合并前核对实时 PR SHA 与审批标签，再把同一 SHA 带进平台原生合并条件；未成功不关闭任务。

## Reference-level explanation

### 契约与文件分配

一个 Task `T1` 覆盖完整交接修复、回归和交付说明，无新增 Task 依赖；精确文件清单在 frontmatter。
开发恢复与评审闸必须一起交付，避免只加拒绝而没有恢复路径。

| 层 | 改动 |
| --- | --- |
| Workspace | `delivery_heads` 检查 Git 读取和干净工作区；`assert_delivered` 要求本地等于远端；`sync_delivered` 只快进干净落后目录 |
| Vigil | 用现有状态恢复未完成开发；统一 implement→deliver；读者前后检查候选；换版沿既有 `MergeNotReady` 重判 |
| Stages/角色 | 补 push 不要求新提交；standard/minimal/generate-only 保留原上下文和策略；读者不修改候选 |
| Gates/CLI/forge | 实时核对 SHA；GitHub 条件合并及 Gitea 的执行/幂等验证都保留 SHA；合并失败不写 done |
| 验证工具 | 真实本地 Git、RuntimeState、队列/worker/claim 故障注入，独立核对批准 SHA、合并内容与完成率 |

`delivery_heads` 只刷新远端跟踪引用，不修改被评审文件；网络读取前后都检查工作区。
本地仍是原候选而远端换版，或本地与远端已一起换版，均令旧裁决失效。评审者产生的未推送
新提交不是合法远端换版，仍抛交付错误。新起草仍有 HEAD 前移要求，恢复交付允许同 SHA。

成果验收入口：`bash scripts/e2e-delivery-review-recovery.sh`。全量测试使用
`.venv/bin/python -m pytest -q`；桌面服务测试需要回环端口权限。压力命令与完整历史结果在
[并发故障注入记录](2026-09-09-delivery-recovery-stress-design.md)，脚本不读取凭证或访问真实模型。

已有本地证据：1322 项全量回归、507 项专项回归；1152 个压力任务中 1056 个正常/可恢复任务
全部合并，96 个持续故障按原三次预算停止。错误合并、意外阻断、重复认领和队列残留均为零。
本轮正式归档会对实际提交树重新验证，不把工作区未提交内容的测试结果当作提交证据。

## Drawbacks

增加少量 Git 检查开销，合法新候选需要重新测试/评审。忽略规则不完整的仓库仍可能因未知
文件被拒绝，不能直接将所有 untracked 文件视为缓存。若远端永不稳定，则不能保证有限完成。
机制保证评审版本和合并版本一致，不自动证明需求完整实现，也不替代真实模型验收。

## Rationale and alternatives

选择复用现有状态、角色和失败分支。仅加相等性拒绝不能恢复中断工作，压力已证明会误挂起；
提高重试次数只能推迟误挂起；吞掉所有 Git 异常会让真故障无界重试；宿主自动提交全部脏文件
可能发布半成品；评审前重建工作区会丢实现。上述方案均不采用。
合并本身使用平台已有 SHA 条件，不新增锁、审批版本数据库或提交台账。

## Prior art

直接扩展本仓既有 Git 交付、PR 生命周期与有界调度。开发角色负责提交推送，Workspace 提供
确定性 Git 事实；Vigil 根据事实决定恢复或重判。平台既有能力参考
[GitHub CLI 条件合并](https://cli.github.com/manual/gh_pr_merge) 和
[Gitea merge API](https://docs.gitea.com/api/operations/repo-merge-pull-request/)。

## Unresolved questions

本次需求与修复方案已由用户确认，无待选设计。真实模型/远端服务闭环、镜像部署及历史实验恢复
不在本次提交内。旧记录若已被误写为 `pr-open` 且只留下干净 Spec，无法凭新机制重建缺失的历史事实。

## Future possibilities

在明确授权后，将固定提交构建为新镜像，运行真实用户闭环；保留旧实验与归档不变。
继续用同一正反例压力入口验证后续流程修改，不以更多角色或更多重试代替交付契约。
