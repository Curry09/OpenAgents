---
number: "0086"
title: User Test 主导的可审计验收
issue: 0
slug: user-test-acceptance
summary: 用真实用户交互替代组件自证作为 v0.2 Acceptance 的主证据，并在隔离副本中保存完整结果。
architecture:
  objective: 防止验收工作量把开发压缩成 prompt-only/toy 改动；只允许用户可观察目标通过真实交互后合并。
  constraints:
    - User Test 必须在候选 HEAD 的仓库外临时副本执行，候选 worktree 在验收期间不可变。
    - 输入 transcript、stdout、stderr、退出状态和副本 workspace diff 必须持久化到候选仓库外。
    - timed_out、crashed、setup_failed 或缺失 User Test 配置不得产生 PASS。
    - PASS 的 manifest 至少包含一项 source=user_test、kind=behavior、passed=true，并引用实际 artifact 路径。
    - 静态检查、Developer 自报测试和独立变体只能解释结果，不能替代 User Test。
  non-goals:
    - 不在用户测试中修改候选 worktree，也不让 Acceptance agent 修复代码。
    - 不强制每个 issue 凑出固定数量的 replay/variant case。
  candidates:
    - id: disposable-user-test
      layer: acceptance
      boundary:
        - external disposable repository copy
        - interactive harness transcript and process lifecycle
      evidence:
        - candidate worktree remains unchanged while user-visible behavior is exercised
      tradeoffs: requires an explicit harness command and transcript for every production batch.
  failure-modes:
    - harness timeout or crash must remain a terminal non-PASS result.
    - model-cited evidence outside the generated artifact directory invalidates PASS.
    - missing user-test configuration must not silently fall back to component-only review.
  selected: disposable-user-test
  affected-components:
    - openagents/runtime/user_test.py
    - openagents/agents/acceptance.py
    - openagents/recipes/stages.py
    - openagents/runtime/evidence.py
    - openagents/v02/openagents_adapter.py
    - openagents/v02/model.py
    - openagents/cli.py
    - tests/test_runtime_user_test.py
    - tests/test_v02_openagents_adapter.py
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: 对一个已交付候选运行配置的 JSONL 用户 transcript。
      expected: harness 只在候选副本中运行；输入、输出、状态和 diff 均可定位，候选 worktree 无变化。
      observation: runtime user-test tests verify external copy and persisted paths.
    - id: BC2
      polarity: negative
      stimulus: harness 超时或以非零状态退出。
      expected: 结果为 timed_out/crashed，Acceptance 不调用或不接受 PASS，进程组被终止。
      observation: adapter fail-closed tests and runner process tests.
    - id: BC3
      polarity: positive
      stimulus: User Test completed 且 Acceptance 返回 user_test behavior evidence。
      expected: PASS 只在 evidence source=user_test 并绑定当前 HEAD 时继续 merge。
      observation: adapter/stage contract tests.
  repository-invariants:
    - User Test subprocess cwd 永远是 disposable artifact/repo，不是候选 worktree。
    - v0.2 未配置 User Test 时返回 PARTIAL，不能退回组件审查放行。
    - Acceptance 前后候选 HEAD 和 meaningful worktree 状态保持不变。
  exemptions: []
tasks:
  - id: T1
    title: 实现隔离 User Test runner 与 artifact 账本
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/user_test.py
      - tests/test_runtime_user_test.py
    scope: 从配置的命令和 JSON transcript 启动 harness，隔离副本执行，采集进程/帧/工具事件/工作区 diff。
    acceptance: completed、timed_out、crashed、setup_failed 四态和外部 artifact 路径有确定性测试。
  - id: T2
    title: 把 User Test 接入 v0.2 Acceptance 门禁
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/agents/acceptance.py
      - openagents/recipes/stages.py
      - openagents/runtime/evidence.py
      - openagents/v02/openagents_adapter.py
      - openagents/v02/model.py
    scope: User Test 作为唯一生产 PASS 的行为主证据；异常状态 fail-closed，候选 worktree 不接受测试写入。
    acceptance: 超时/崩溃不会调用或接受 PASS；completed 仅允许 source=user_test behavior manifest。
  - id: T3
    title: 提供 CLI 配置入口与可追溯说明
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
      - docs/specs/0086-user-test-acceptance.md
    scope: v0.2 支持 --user-test-command、--user-test-transcript、--user-test-timeout；未配置时显式 PARTIAL。
    acceptance: CLI flags 可构造同一 UserTestPlan，不修改全局环境。
---

# 0086 · User Test 主导的可审计验收

## Summary

过去的验收容易变成组件审查：证据数量很多，但真实用户目标没有执行，Developer 因此倾向选择最容易被规则证明的
prompt-only 或 toy 改动。本组把真实用户交互前移为 v0.2 Acceptance 的主证据，并将交互运行面与候选工作区严格分离。

## Motivation

验收若只看 diff、静态检查和模型自报，系统会奖励容易解释而不是有效的改动。真实用户交互能直接暴露功能是否可达、
是否在原始操作路径上工作，以及实现是否只是绕过困难目标的表面改动。

## Reference-level explanation

`OpenAgentsAdapter.accept` 先从候选 HEAD 建立外部副本，再由 `run_user_test` 启动 harness 并喂入 transcript。
运行结果以结构化 `UserTestResult` 传给 Acceptance；只有正常完成的运行，且模型 manifest 引用了本次 artifact 中的
`source=user_test` 行为证据，才可能得到 PASS。PASS 随后仍需通过 HEAD 未变化和 worktree clean 硬闸。

## Rationale and alternatives

选择外部副本而不是把 harness 直接放进候选 worktree，是为了同时保留真实代码路径和可验证的不可变性。直接在候选目录
运行虽然少一次复制，却允许测试缓存、临时修补或后台进程污染交付对象；只做更多静态检查则无法解决当前“验收很多但功能很 toy”的
根因。旧 recipes 暂保留兼容分支，v0.2 生产入口不允许绕过 User Test。

## Runtime contract

`OPENAGENTS_USER_TEST_COMMAND` 指定交互 harness，`OPENAGENTS_USER_TEST_TRANSCRIPT` 指定非空 JSON 数组。字符串事件
会编码为 `{"message": ...}`，对象事件按原样发送为 JSONL；每项可带 `wait_seconds`。`OPENAGENTS_USER_TEST_TIMEOUT`
默认 900 秒。命令在 artifact 目录下的 disposable `repo/` 执行，候选只通过 `git archive/clone` 读取。

每次运行至少留下 `input.jsonl`、`stdout.log`、`stderr.log`、`status.json` 和 `workspace.diff`。`status.json` 的
`completed` 只表示 harness 正常退出，不等于目标已满足；Acceptance agent 必须根据 transcript 和输出写出
`source=user_test` 的 behavior case。其他证据只能补充说明。

## Failure semantics

用户测试超时会终止该 harness 的进程组并记录 `timed_out`；非零退出记录 `crashed`；复制或启动失败记录
`setup_failed`。这些状态永远不能被模型改写成 PASS。v0.2 没有配置 User Test 时也不会回落到旧的组件审查路径，而是返回
`PARTIAL` 并要求显式配置。

## Migration

旧 recipes 的直接调用仍兼容 replay/variant manifest，以避免破坏 standard flow；v0.2 `OpenAgentsAdapter.accept`
固定传入 `require_user_test=True`，生产批次因此不会绕过真实交互门禁。待 User Test 在真实 harness 上稳定后，再将
legacy acceptance 的兼容分支退役。
