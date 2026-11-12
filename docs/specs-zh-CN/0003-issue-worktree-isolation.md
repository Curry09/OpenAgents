---
number: "0003"
title: issue 求解隔离 —— 每 issue 独立 worktree + 分支基线锁定最新 main
issue: 0
slug: issue-worktree-isolation
summary: 每个 issue 在独立 git worktree 里求解、分支基线锁定最新 origin/main，避免多 issue 互相污染。同时加实时事件流反馈、可中断恢复的幂等求解，以及 CLI 统一错误处理（异常不吐 traceback）。
tasks:
  - id: T1
    title: solve/iterate 改用每 issue worktree + `origin/<base>` 基线 + `--base` 选项
    status: done
    priority: P1
    tags:
      - architecture
      - backend
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - openagents/cli.py
      - tests/test_orchestrator.py
      - tests/test_cli.py
    scope: 重写 Orchestrator 工作区逻辑——solve 先 fetch origin <base>，在 <repo_root>/.openagents/worktrees/issue-<n> 建从 origin/<base> 拉出的 worktree（建前幂等清理残留），在该 worktree 内调后端、add/commit/push、开 PR；iterate 复用/重建同一 worktree 后续写。cli.py 的 solve 子命令新增 --base（默认 main）并透传给 Orchestrator.solve；并在 cli 分发外层统一捕获运行期异常→打印 ✗ 干净退出、不吐 traceback（原 T4）。
    acceptance: solve 调用序列含 git fetch origin main 与 git worktree add -b openagents/issue-<n> <path> origin/main，不再在主树 checkout -b；后端 work_dir 为 worktree 路径；commit/push 正常且不 force-push；solve --base <ref> 时 worktree 自 origin/<ref> 拉出；iterate 在 worktree 内追加 commit；CLI 将 --base 透传、默认 main；ruff check/ruff format --check/pytest 全通过；OrchestratorError/GithubError/RuntimeError 被捕获为非零退出码、无 traceback。
  - id: T2
    title: 求解实时反馈：后端 stream-json 事件流 + 编排阶段进度行
    status: done
    priority: P1
    tags:
      - architecture
      - backend
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backends/claude_code.py
      - tests/test_backend_claude_code.py
    scope: 'ClaudeCodeBackend.run 改用 --output-format stream-json --verbose + Popen，逐行解析 NDJSON 事件，实时打印助手文本与工具动作（🔧 <tool>: <hint>）到 stdout，从 result 事件取摘要；非零退出抛 RuntimeError（带详情），非 JSON 行原样透传并作兜底详情。Orchestrator 在各阶段向 stderr 打 ▶ … 进度行。git status 判定改动逻辑不变。'
    acceptance: 后端 Popen 命令含 --output-format stream-json --verbose；assistant 文本/工具事件经 capsys 实时可见；summary 取自 result 事件；非零退出抛 RuntimeError；solve 各阶段在 stderr 有 ▶ 进度行；子进程 mock 单测全通过。
  - id: T3
    title: solve 幂等可恢复（按 State 分流 fresh/resume）+ issue↔PR 绑定 + gh 兜底
    status: done
    priority: P1
    tags:
      - architecture
      - backend
      - cli
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - openagents/github.py
      - tests/test_state.py
      - tests/test_github.py
    scope: solve 入口 state.find_by_issue 反查并按决策 7 分流——续写复用分支/worktree（不走决策 4 的清理）、追加 commit、find_pr_by_branch 复用或补开 PR；全新走决策 1/2/4 并 begin_run 先记 solving。_commit_and_push 容忍「无改动可提交」（跳过 commit 仍 push）。state.py 加 begin_run / find_by_issue；github.py 加 find_pr_by_branch。
    acceptance: 该 issue 已有 open PR 时 solve 走续写、复用 PR（不调用 create_pr）、不重建分支、状态置 iterating；begin_run 后崩溃场景（无 PR）重跑能补开 PR；find_by_issue/begin_run/find_pr_by_branch 单测通过。
---

# 0003 · issue 求解隔离 —— 每 issue 独立 worktree + 分支基线锁定最新 main

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

让每个 issue 的求解在一条**独立的 git worktree** 里进行，worktree 从最新的 `origin/<base>`（默认 `main`）拉出，分支命名为 `openagents/issue-<n>`，彻底隔离多 issue 间的工作树污染与陈旧基线。在此隔离骨架上再叠三件事：求解过程的**实时事件流反馈**（后端 stream-json + 编排阶段进度行）、**幂等可恢复**的求解（按持久化 State 分流 fresh/resume，issue↔PR 绑定，gh 兜底复用 PR），以及 CLI 的**统一错误处理**（运行期异常打印干净的 `✗` 行并非零退出，不吐 traceback）。

## Motivation

旧实现把求解直接做在主工作树上（`git checkout -b`），带来两类问题：

- **多 issue 互相污染**：同一仓库同时求解多个 issue 时，共享一棵工作树会让未提交改动、分支切换互相干扰；并且基于「当前 HEAD」切分支，容易把陈旧的本地状态带进新求解。
- **基线漂移**：分支不是从最新远端拉出，求解结果可能落后于 `main`，合并时冲突频发。

此外，求解过程对使用者是黑盒（后端跑完才出结果，中途无可见进度）；一旦中断（崩溃 / 手动停）就无法续写，只能重头再来或留下半成品 PR；CLI 在运行期异常时直接抛 Python traceback，对最终面向「成果」的使用者噪音很大。本 feature 用「每 issue 独立 worktree + 锁定最新远端基线」一次性解决隔离与漂移，并顺势补齐反馈、可恢复、干净报错三项体验缺口。

## Guide-level explanation

对使用者而言，工作方式不变——仍是 `openagents solve <issue>`，但底层与体验有四点变化：

1. **隔离**：每个 issue 在 `<repo_root>/.openagents/worktrees/issue-<n>` 下有自己的 worktree，分支 `openagents/issue-<n>` 从 `origin/main` 最新提交拉出。想换基线时 `solve --base <ref>`（默认 `main`）。
2. **可见**：求解时实时看到助手文本与工具动作（`🔧 <tool>: <hint>`），编排各阶段在 stderr 打 `▶ …` 进度行。
3. **可续**：中断后重跑同一 issue，会自动识别已有分支/PR 续写（追加 commit、复用 PR），不重建、不重复开 PR。
4. **干净**：运行期出错只看到一行 `✗ <原因>` 并非零退出，没有 traceback。

## Reference-level explanation

落到改动，分解为 3 个 Task（DAG 见末尾；各 Task `files` 互斥，单一 writer）。注:原先「CLI 统一错误处理」是一个独立小 Task,但它只改 `cli.py` + `tests/test_cli.py`——二者皆 T1 拥有、无独占文件,按单一 writer 原则并入 T1。

1. **T1 worktree 隔离 + 基线锁定 + CLI 统一错误处理**（无依赖，骨架）— 重写 `Orchestrator` 工作区逻辑：`solve` 先 `git fetch origin <base>`，在 `<repo_root>/.openagents/worktrees/issue-<n>` 用 `git worktree add -b openagents/issue-<n> <path> origin/<base>` 建 worktree（建前幂等清理残留），在该 worktree 内调后端、`add/commit/push`、开 PR；`iterate` 复用/重建同一 worktree 后续写。**不再**在主树 `checkout -b`，**不** force-push。`cli.py` 的 `solve` 子命令新增 `--base`（默认 `main`）并透传给 `Orchestrator.solve`；并在分发外层统一捕获 `OrchestratorError` / `GithubError` / `RuntimeError`，打印 `✗ <消息>` 到 stderr 并返回非零退出码，未知异常仍向上抛出（不吞）。
2. **T2 实时反馈**（无依赖，可与 T1 并行）— `ClaudeCodeBackend.run` 改用 `--output-format stream-json --verbose` + `Popen`，逐行解析 NDJSON 事件，实时打印助手文本与工具动作到 stdout，从 `result` 事件取摘要；非零退出抛 `RuntimeError`（带详情），非 JSON 行原样透传并作兜底详情。`Orchestrator` 在各阶段向 stderr 打 `▶ …` 进度行。`git status` 判定改动逻辑不变。
3. **T3 幂等可恢复**（依赖 T1）— `solve` 入口用 `state.find_by_issue` 反查持久化状态并分流：**续写**复用既有分支/worktree（不走全新路径的清理）、追加 commit、`find_pr_by_branch` 复用或补开 PR；**全新**则 `begin_run` 先记 `solving` 再走建 worktree/开 PR。`_commit_and_push` 容忍「无改动可提交」（跳过 commit 仍 push）。新增 `state.py` 的 `begin_run` / `find_by_issue` 与 `github.py` 的 `find_pr_by_branch`（gh 兜底反查 PR）。

**端到端验证**：本组以 `ruff check` / `ruff format --check` / `pytest`（含上述各 Task 的子进程 mock 单测）作为离线 e2e 验收，无独立 `scripts/*.sh` 脚本；验收以「`solve` 调用序列含 `git worktree add ... origin/main`、续写复用 PR、CLI 干净退出」等单测断言覆盖。

依赖 DAG：`T1 → T3`，T2 独立可并行。

## Drawbacks

- 每 issue 一棵 worktree 会在 `.openagents/worktrees/` 下占用额外磁盘与 inode；需要建前幂等清理以免残留累积。
- stream-json 逐行解析比一次性取结果多一层解析逻辑，非 JSON 行需兜底处理。
- 幂等续写引入 fresh/resume 分流分支，状态机复杂度上升。

## Rationale and alternatives

- **为什么用 git worktree 而非多 clone**：worktree 共享同一 `.git` 对象库，建/删轻量、磁盘占用远小于多 clone，天然适合「每 issue 一棵临时工作树」。
- **为什么从 `origin/<base>` 拉而非当前 HEAD**：先 `fetch` 再从远端引用建分支，保证基线是最新主干、避免把本地陈旧状态带入，从根上消除基线漂移。
- **为什么靠 State + `find_pr_by_branch` 兜底而非纯本地记录**：崩溃可能发生在「已开 PR 但未落盘」之间，用 `gh` 按分支反查 PR 能在状态缺失时补全 issue↔PR 绑定，避免重复开 PR。
- **备选：CLI 直接放任 traceback**。否决——面向「成果」的使用者只需知道失败原因，traceback 是噪音；统一捕获已知异常类型、未知异常仍上抛，兼顾可读与可调试。

## Prior art

git worktree 是官方推荐的「同仓库多工作树并行」机制，被广泛用于隔离并行任务；trunk-based 开发主张分支从最新主干拉出、短生命周期合回，本 feature 的「锁定最新 `origin/main` 基线」与之一致。stream-json/NDJSON 事件流是 CLI agent 后端常见的实时输出协议。

## Unresolved questions

无。worktree 路径布局、基线引用、fresh/resume 分流决策、错误处理边界均已在本组确定。

## Future possibilities

- worktree 生命周期管理可扩展为按完成/失败自动归档或清理。
- 实时事件流可进一步结构化（如供前端「成果」视图消费阶段进度）。
- `find_pr_by_branch` 的 gh 兜底可推广到更多 issue↔PR 状态自愈场景。

