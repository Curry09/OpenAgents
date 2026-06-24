---
number: "0005"
title: solve 原子化拆分 + RFC-first 评审循环
issue: 0
slug: solve-atomization-rfc-first-loop
summary: 把原来一坨的 solve 拆成四个原子操作，并引入 RFC-first 评审循环（先写 RFC 再写代码）。抽出 workspace 模块、扩展 github/state、把消息按阶段过滤掉自评论，CLI 去掉 solve 换成 4 个子命令。
tasks:
  - id: T1
    title: workspace 模块抽取
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/workspace.py
      - tests/test_workspace.py
  - id: T2
    title: orchestrator 瘦身为四原子操作
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on:
      - T1
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
  - id: T3
    title: github 扩展（draft / mark_ready / has_label / current_login）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
  - id: T4
    title: state 扩展（rfc-review 状态）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
  - id: T5
    title: messages 阶段化 + 过滤自评论
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on:
      - T2
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
  - id: T6
    title: cli 改造（去 solve，加 4 子命令）+ e2e
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on:
      - T2
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
      - scripts/e2e-rfc-0005-rfc-first.sh
---

# 0005 · solve 原子化拆分 + RFC-first 评审循环

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据，正文为各 Task 设计 prose。 -->

## T1 · workspace 模块抽取

### Scope

新建 `Workspace` 类，把 orchestrator 现有的 worktree/git 逻辑（`_prepare_worktree` / `_ensure_worktree` / `_commit_and_push` / `_remote_branch_exists` / `_worktree_path` / `_git`）原样迁入，对外暴露 `prepare` / `ensure` / `commit_and_push` / `remote_branch_exists`。纯 git，无 GitHub / backend / state 依赖。本子任务只新增文件，不改 orchestrator（由 T2 改）。

### Acceptance

单测覆盖 prepare（fetch + 幂等清理 + worktree add）、ensure（存在则复用 / 缺失则重建）、commit_and_push（无改动跳过 commit 仍 push）；ruff 通过；注释引用 `RFC-0005`。

## T2 · orchestrator 瘦身为四原子操作

### Scope

删除 `solve` / `_fresh_solve` / `_resume` 及已迁出的 git/worktree 私有方法；改为持有 `Workspace`，实现 `start_rfc` / `refine_rfc` / `implement`（保留既有 `iterate`，改为走 `Workspace`）。`start_rfc` 的 backend 任务需指示其遵循 rfc-driven skill 起草 RFC（含取号）。`_pr_body` / `_open_or_reuse_pr` 按需保留。

### Acceptance

单测用假 backend / monkeypatch github、注入假 Workspace，覆盖四操作的「确保工作区→run→提交推送→GitHub 动作→状态流转」；ruff 通过；注释引用 `RFC-0005`。

## T3 · github 扩展（draft / mark_ready / has_label / current_login）

### Scope

`create_pr` 增加 `draft: bool = False`（透传 `gh pr create --draft`）；新增 `mark_ready`（`gh pr ready`）、`has_label`（`gh pr view --json labels`）、`current_login`（`gh api user --jq .login`）。

### Acceptance

单测 monkeypatch gh 子进程，覆盖 draft 透传、mark_ready、has_label（命中/未命中）、current_login 解析；`create_pr` 旧调用（不传 draft）行为不变；ruff 通过。

## T4 · state 扩展（rfc-review 状态）

### Scope

新增 `STATUS_RFC_REVIEW = "rfc-review"` 常量，纳入合法状态；不改既有方法签名（start_rfc 复用 `record_run` + `update_status`）。更新 `RunRecord` docstring 的状态枚举说明。

### Acceptance

单测验证 `update_status(status=rfc-review)` 落盘与读取；既有用例不回归；ruff 通过。

## T5 · messages 阶段化 + 过滤自评论

### Scope

`_process_run` 按 run 状态分阶段路由（见接口契约）；新增 `APPROVAL_LABEL`；评论处理取「游标之后的最新评论」（不论作者）；`rfc-review` 阶段命中标签调 `implement`、否则最新评论调 `refine_rfc` 并把游标推进到回贴后 PR 上最新评论之后（消费掉 agent 自己的回贴）。

### Acceptance

单测覆盖：rfc-review + 标签 → implement；rfc-review + 新评论 → refine_rfc 且游标推进到 PR 最新评论；游标已越过最新评论 → 不重复触发（防自循环）；coding 阶段 CI/comment → iterate；merged → done；ruff 通过。

## T6 · cli 改造（去 solve，加 4 子命令）+ e2e

### Scope

删除 `solve` 子命令与 `_cmd_solve`；新增 `rfc` / `refine-rfc` / `implement` / `iterate` 子命令及处理函数（`refine-rfc`/`iterate` 取最新人类评论作 detail）；更新 `_dispatch` 路由表。新增端到端脚本 `scripts/e2e-rfc-0005-rfc-first.sh`（起草 RFC → 模拟评论 → refine → 打标签 → implement → poll 转 done 的演示）。

### Acceptance

单测对工厂打桩，验证四子命令分发到对应操作、`solve` 已移除；e2e 脚本可读且步骤完整；ruff 通过。

