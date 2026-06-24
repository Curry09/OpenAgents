---
number: "0011"
title: 本地 Agent 身份 + 评论签名（区分自评论与真人评论，根治 poll 自循环）
issue: 28
slug: agent-identity-comment-signature
summary: 给本地 agent 一个持久身份并在评论上盖签名，从而区分「自己发的评论」和「真人评论」，根治 poll 把自己评论当新消息的自循环问题。
tasks:
  - id: T1
    title: state 层 agent_id 持久化
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
  - id: T2
    title: identity 模块（身份解析 + 评论签名）
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/identity.py
      - tests/test_identity.py
  - id: T3
    title: poll 判定剔除自评论 + 游标简化
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T2
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
  - id: T4
    title: orchestrator 回贴评论盖章
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
  - id: T5
    title: rebase 冲突评论盖章
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/rebase.py
      - tests/test_rebase.py
  - id: T6
    title: CLI 接线 + 下线 current_login
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T3
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/github.py
      - tests/test_cli.py
      - tests/test_github.py
---

# 0011 · 本地 Agent 身份 + 评论签名（区分自评论与真人评论，根治 poll 自循环）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据，正文为各 Task 设计 prose。 -->

## T1 · state 层 agent_id 持久化

### Scope

在 `State` 上新增 `get_agent_id` / `set_agent_id`，state.json 顶层增可选键 `"agent_id"`；`_load` 容错（缺键返回不含 agent_id 的状态），保持既有 runs/cursors 不变。

### Acceptance

set 后 get 取回同值；未设过时 get 返回 None；写入不破坏既有 runs/cursors；文件缺失/损坏仍容错为空状态。

## T2 · identity 模块（身份解析 + 评论签名）

### Scope

新建 `openagents/identity.py`，实现 `resolve_agent_id`（env > state > 生成落盘）、`sign`、`parse_agent_id`、`post_signed_comment`，及签名标记常量与字符集约束。

### Acceptance

`sign` → `parse_agent_id` 往返一致；无签名/真人正文 `parse_agent_id` 返回 None；`resolve_agent_id` 三级优先级正确，自动生成时落盘且跨调用稳定；`post_signed_comment` 调 `github.post_comment` 且正文带签名（monkeypatch 断言）。

## T3 · poll 判定剔除自评论 + 游标简化

### Scope

`Messages.__init__` 增 `agent_id`；`_latest_new_comment` 额外剔除「我自己签名」的评论；`_process_rfc_review` 游标只推进到触发评论；删除 `_newest_comment_id`；`poll` 合并分支把 `agent_id` 透传给 `rebase.rebase_open_prs`。

### Acceptance

自己签名的评论不触发处理（含「post 后未推游标即崩溃重启」场景）；其他 agent 签名 / 无签名评论照常触发；refine 后游标等于触发评论的 `created_at`；干活期间到达的真人评论下一轮被处理。

## T4 · orchestrator 回贴评论盖章

### Scope

`Orchestrator.__init__` 增 `agent_id`；`refine_rfc` 的回贴改走 `identity.post_signed_comment(..., agent_id=self._agent_id)`。

### Acceptance

`refine_rfc` 发出的评论正文带本实例签名（monkeypatch `identity.post_signed_comment` 或 `github.post_comment` 断言）；其余流程（commit/push、状态流转）不变。

## T5 · rebase 冲突评论盖章

### Scope

`rebase_open_prs` 增必填 `agent_id`；冲突留言改走 `identity.post_signed_comment(..., agent_id=agent_id)`。

### Acceptance

冲突时留言带签名；`agent_id` 正确透传；错误隔离/结果分类行为不变。

## T6 · CLI 接线 + 下线 current_login

### Scope

`cli` 解析 `agent_id` 并注入 `Orchestrator` / `Messages`，`_cmd_sync_prs` 透传 `agent_id`；删除 `github.current_login` 及其测试。

### Acceptance

poll / vigil / sync-prs 端到端拿到一致 agent_id；`current_login` 全仓无引用；ruff + 全量 pytest 通过。

