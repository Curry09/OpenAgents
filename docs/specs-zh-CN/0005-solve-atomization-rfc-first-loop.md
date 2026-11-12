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
    scope: 新建 Workspace 类，把 orchestrator 现有的 worktree/git 逻辑（_prepare_worktree / _ensure_worktree / _commit_and_push / _remote_branch_exists / _worktree_path / _git）原样迁入，对外暴露 prepare / ensure / commit_and_push / remote_branch_exists。纯 git，无 GitHub / backend / state 依赖。本子任务只新增文件，不改 orchestrator（由 T2 改）。
    acceptance: 单测覆盖 prepare（fetch + 幂等清理 + worktree add）、ensure（存在则复用 / 缺失则重建）、commit_and_push（无改动跳过 commit 仍 push）；ruff 通过；注释引用 RFC-0005。
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
    scope: 删除 solve / _fresh_solve / _resume 及已迁出的 git/worktree 私有方法；改为持有 Workspace，实现 start_rfc / refine_rfc / implement（保留既有 iterate，改为走 Workspace）。start_rfc 的 backend 任务需指示其遵循 rfc-driven skill 起草 RFC（含取号）。_pr_body / _open_or_reuse_pr 按需保留。
    acceptance: 单测用假 backend / monkeypatch github、注入假 Workspace，覆盖四操作的「确保工作区→run→提交推送→GitHub 动作→状态流转」；ruff 通过；注释引用 RFC-0005。
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
    scope: 'create_pr 增加 draft: bool = False（透传 gh pr create --draft）；新增 mark_ready（gh pr ready）、has_label（gh pr view --json labels）、current_login（gh api user --jq .login）。'
    acceptance: 单测 monkeypatch gh 子进程，覆盖 draft 透传、mark_ready、has_label（命中/未命中）、current_login 解析；create_pr 旧调用（不传 draft）行为不变；ruff 通过。
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
    scope: 新增 STATUS_RFC_REVIEW = "rfc-review" 常量，纳入合法状态；不改既有方法签名（start_rfc 复用 record_run + update_status）。更新 RunRecord docstring 的状态枚举说明。
    acceptance: 单测验证 update_status(status=rfc-review) 落盘与读取；既有用例不回归；ruff 通过。
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
    scope: _process_run 按 run 状态分阶段路由（见接口契约）；新增 APPROVAL_LABEL；评论处理取「游标之后的最新评论」（不论作者）；rfc-review 阶段命中标签调 implement、否则最新评论调 refine_rfc 并把游标推进到回贴后 PR 上最新评论之后（消费掉 agent 自己的回贴）。
    acceptance: 单测覆盖：rfc-review + 标签 → implement；rfc-review + 新评论 → refine_rfc 且游标推进到 PR 最新评论；游标已越过最新评论 → 不重复触发（防自循环）；coding 阶段 CI/comment → iterate；merged → done；ruff 通过。
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
    scope: 删除 solve 子命令与 _cmd_solve；新增 rfc / refine-rfc / implement / iterate 子命令及处理函数（refine-rfc/iterate 取最新人类评论作 detail）；更新 _dispatch 路由表。新增端到端脚本 scripts/e2e-rfc-0005-rfc-first.sh（起草 RFC → 模拟评论 → refine → 打标签 → implement → poll 转 done 的演示）。
    acceptance: 单测对工厂打桩，验证四子命令分发到对应操作、solve 已移除；e2e 脚本可读且步骤完整；ruff 通过。
---

# 0005 · solve 原子化拆分 + RFC-first 评审循环

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把原来一坨的 `solve` 操作拆成四个原子操作（`start_rfc` / `refine_rfc` / `implement` / `iterate`），并引入 **RFC-first 评审循环**：agent 先起草 RFC（draft PR），人类在 PR 上评论或打批准标签，agent 据此 refine 或转入写代码。配套抽出 `workspace` 模块（承载纯 git/worktree 逻辑）、扩展 `github`（draft / mark_ready / has_label / current_login）与 `state`（新增 `rfc-review` 状态）、把消息处理按 run 阶段路由并过滤掉 agent 自己的回贴，CLI 去掉单一 `solve` 子命令换成 4 个原子子命令。

## Motivation

旧的 `solve` 是一坨「领 issue → 切工作树 → 起草改动 → 开 PR → 迭代」的大操作，git/worktree 逻辑、GitHub 动作、状态流转、消息路由全耦合在 orchestrator 里，难以单独测试与复用，且没有「先对齐设计再写代码」的环节——agent 一上来就改代码，人无法在代码层面之前介入。

OpenAgents 的核心理念是 agent 之间通过类似 GitHub 的 PR + comment 机制对齐，并且 **每次改动先改 RFC 再改代码**（理念 4）。要落地这条循环，需要：(1) 把 `solve` 拆成可独立调度的原子操作，让「起草 RFC」与「写实现」成为两个明确阶段；(2) 把纯 git 逻辑从 orchestrator 解耦出去（理念 10）以便瘦身与独立测试；(3) 让消息层能识别「现在处于 rfc-review 还是 coding 阶段」并据此路由，同时避免 agent 把自己的回贴当成新输入而陷入自循环。

## Guide-level explanation

新的工作循环以一个 issue 为单位，按阶段推进：

| 阶段 | 触发 | agent 动作 | 落地状态 |
|------|------|------|------|
| 起草 | `openagents rfc` | 切工作树、按 rfc-driven skill 起草 RFC（含取号）、开 **draft PR** | `rfc-review` |
| 评审 | PR 收到人类新评论 | `refine_rfc`：据评论修订 RFC、回贴、推进游标 | `rfc-review` |
| 批准 | PR 被打上批准标签 | `implement`：把 draft PR mark_ready、开始写实现 | coding |
| 迭代 | CI 反馈 / 评论 | `iterate`：据反馈改代码 | coding |
| 合入 | PR merged | 收尾 | done |

对使用者：`solve` 不再存在，取而代之是四个原子子命令 `rfc` / `refine-rfc` / `implement` / `iterate`，其中 `refine-rfc` / `iterate` 会取 PR 上最新人类评论作为 detail。消息轮询层（`messages`）负责按 run 当前状态自动把 PR 事件路由到对应原子操作，人只需在 PR 上评论或打标签。

## Reference-level explanation

落到改动，分解为 6 个 Task（`files` 互斥，各 Task 单一 writer）：

1. **T1 workspace 模块抽取** — 新建 `Workspace` 类，把 orchestrator 现有的 worktree/git 私有逻辑（`_prepare_worktree` / `_ensure_worktree` / `_commit_and_push` / `_remote_branch_exists` / `_worktree_path` / `_git`）原样迁入，对外暴露 `prepare` / `ensure` / `commit_and_push` / `remote_branch_exists`。纯 git，无 GitHub / backend / state 依赖；本 Task 只新增文件，不改 orchestrator。
2. **T2 orchestrator 瘦身**（依赖 T1、T3、T4） — 删除 `solve` / `_fresh_solve` / `_resume` 及已迁出的 git/worktree 私有方法；改为持有 `Workspace`，实现四原子操作 `start_rfc` / `refine_rfc` / `implement`（保留既有 `iterate`，改走 `Workspace`）。`start_rfc` 的 backend 任务指示其遵循 rfc-driven skill 起草 RFC（含取号）；`_pr_body` / `_open_or_reuse_pr` 按需保留。
3. **T3 github 扩展** — `create_pr` 增加 `draft: bool = False`（透传 `gh pr create --draft`）；新增 `mark_ready`（`gh pr ready`）、`has_label`（`gh pr view --json labels`）、`current_login`（`gh api user --jq .login`）。这些是 RFC-first 循环所需的 GitHub 原语：draft PR 表「RFC 评审中」，mark_ready 表「转入实现」，has_label 用于识别批准，current_login 用于过滤自评论。
4. **T4 state 扩展** — 新增 `STATUS_RFC_REVIEW = "rfc-review"` 常量并纳入合法状态集，使 run 能表达「RFC 评审中」阶段；不改既有方法签名（`start_rfc` 复用 `record_run` + `update_status`），更新 `RunRecord` docstring 的状态枚举说明。
5. **T5 messages 阶段化**（依赖 T2、T4） — `_process_run` 按 run 状态分阶段路由；新增 `APPROVAL_LABEL`；评论处理取「游标之后的最新评论」（不论作者）。`rfc-review` 阶段：命中批准标签 → `implement`，否则有新评论 → `refine_rfc` 并把游标推进到回贴后 PR 上最新评论之后（从而消费掉 agent 自己的回贴，防自循环）；coding 阶段 CI/comment → `iterate`；merged → done。
6. **T6 cli 改造 + e2e**（依赖 T2、T5） — 删除 `solve` 子命令与 `_cmd_solve`；新增 `rfc` / `refine-rfc` / `implement` / `iterate` 四子命令及处理函数（`refine-rfc` / `iterate` 取最新人类评论作 detail），更新 `_dispatch` 路由表。

**端到端验证**：`bash scripts/e2e-rfc-0005-rfc-first.sh`（演示：起草 RFC → 模拟评论 → refine → 打批准标签 → implement → poll 转 done）。

依赖 DAG：`T1 → T2`，`T3 → T2`，`T4 → T2`，`T2 → T5`，`T4 → T5`，`T2 → T6`，`T5 → T6`。T1 / T3 / T4 无入边，可并行起步。

## Drawbacks

- 把单一 `solve` 拆成四个原子操作 + 一个 `workspace` 模块，文件与子命令数量增加，初次理解成本上升。
- RFC-first 循环多了一个 `rfc-review` 阶段与 draft/ready PR 状态机，相比「直接写代码」多一层往返；但这正是「先对齐设计再写代码」理念的必要代价。
- 消息层的「游标推进以消费自评论」逻辑较微妙，需要单测兜住防自循环。

## Rationale and alternatives

- **为什么拆成四原子操作**：单一 `solve` 把 git / GitHub / state / 消息路由耦合在一起，无法表达「RFC 评审」与「写实现」两个阶段，也难单独测试。拆开后每个操作职责单一、可独立调度与打桩，契合 OpenAgents「最小化、解耦」（理念 1、10）。
- **为什么抽 `workspace` 而非留在 orchestrator**：纯 git/worktree 逻辑与编排逻辑正交，抽出后 orchestrator 可瘦身、Workspace 可独立单测（fetch / 幂等清理 / 复用或重建 / 无改动仍 push）。
- **为什么用 draft PR 表 rfc-review**：复用 GitHub 原生 draft/ready 机制承载阶段，无需自造状态外化；agent 间通过 PR + comment 对齐正是本框架的消息模型。
- **备选：评论处理只认人类作者**。否决：改取「游标之后的最新评论」（不论作者）+ 推进游标消费自评论，逻辑更简单且天然防自循环，不依赖按 login 过滤每条评论。
- **不动评审/CI 内部逻辑**，只在其上叠加阶段路由，把改动半径收到最小。

## Prior art

「先 RFC 后实现」对应 Rust RFC / 各类设计评审流程；draft PR → ready PR 的两段式是 GitHub 上常见的「设计先行」协作模式。git worktree 用于并行隔离工作区是主流做法。本 feature 取其核心，落到 OpenAgents 的多 agent + PR/comment 消息模型上。

## Unresolved questions

无。四原子操作边界、rfc-review 状态机、消息游标推进语义均已在本组确定。

## Future possibilities

- `refine_rfc` 可引入更结构化的评审裁决聚合（多 reviewer 投票）。
- RFC 取号 / 模板可进一步由 skill 自动化校验。
- 阶段路由可扩展更多状态（如 blocked / needs-human）以支撑更复杂的协作。

