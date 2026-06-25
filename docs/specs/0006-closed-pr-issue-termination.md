---
number: "0006"
title: 守夜人识别 PR/issue 关闭作为终止信号
issue: 0
slug: closed-pr-issue-termination
summary: 守夜人要懂得收手：当一个 PR 或 issue 被关闭时，把它识别成终止信号，不再继续求解，避免对已放弃的工作空转。
tasks:
  - id: T1
    title: closed PR 识别为终止信号
    status: done
    priority: P1
    tags:
      - protocol
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - openagents/state.py
      - openagents/messages.py
      - tests/test_github.py
      - tests/test_messages.py
---

# 0006 · 守夜人识别 PR/issue 关闭作为终止信号

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据，正文为各 Task 设计 prose。 -->

## T1 · closed PR 识别为终止信号

### Scope

1. `github.py` 新增 `is_closed(*, pr_number)`，读 `gh pr view --json state` 判定 `CLOSED`。 2. `state.py` 新增 `STATUS_CLOSED = "closed"` 常量。 3. `messages.py` `_process_run` 在 merged 判定之后、阶段路由之前插入 closed 分支：置 `STATUS_CLOSED`、返回 `reason="closed"`，不触发任何编排动作。

### Acceptance

- 一个 `state=CLOSED`、带 `rfc-approved` 标签、本地状态 `rfc-review` 的 run 经 `poll` 后：不调用 `implement`，状态被置为 `closed`，事件 `reason="closed"`。 - `closed` 状态的 run 在后续 `poll` 中被跳过（不在 `_OPEN_STATUSES`）。 - merged 仍优先于 closed 与阶段路由，既有测试不回归。 - `ruff check` / `ruff format --check` / `pytest` 全绿。

