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
    scope: 在 `State` 上新增 `get_agent_id` / `set_agent_id`，state.json 顶层增可选键 `"agent_id"`；`_load` 容错（缺键返回不含 agent_id 的状态），保持既有 runs/cursors 不变。
    acceptance: set 后 get 取回同值；未设过时 get 返回 None；写入不破坏既有 runs/cursors；文件缺失/损坏仍容错为空状态。
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
    scope: 新建 `openagents/identity.py`，实现 `resolve_agent_id`（env > state > 生成落盘）、`sign`、`parse_agent_id`、`post_signed_comment`，及签名标记常量与字符集约束。
    acceptance: '`sign` → `parse_agent_id` 往返一致；无签名/真人正文 `parse_agent_id` 返回 None；`resolve_agent_id` 三级优先级正确，自动生成时落盘且跨调用稳定；`post_signed_comment` 调 `github.post_comment` 且正文带签名（monkeypatch 断言）。'
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
    scope: '`Messages.__init__` 增 `agent_id`；`_latest_new_comment` 额外剔除「我自己签名」的评论；`_process_rfc_review` 游标只推进到触发评论；删除 `_newest_comment_id`；`poll` 合并分支把 `agent_id` 透传给 `rebase.rebase_open_prs`。'
    acceptance: 自己签名的评论不触发处理（含「post 后未推游标即崩溃重启」场景）；其他 agent 签名 / 无签名评论照常触发；refine 后游标等于触发评论的 `created_at`；干活期间到达的真人评论下一轮被处理。
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
    scope: '`Orchestrator.__init__` 增 `agent_id`；`refine_rfc` 的回贴改走 `identity.post_signed_comment(..., agent_id=self._agent_id)`。'
    acceptance: '`refine_rfc` 发出的评论正文带本实例签名（monkeypatch `identity.post_signed_comment` 或 `github.post_comment` 断言）；其余流程（commit/push、状态流转）不变。'
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
    scope: '`rebase_open_prs` 增必填 `agent_id`；冲突留言改走 `identity.post_signed_comment(..., agent_id=agent_id)`。'
    acceptance: 冲突时留言带签名；`agent_id` 正确透传；错误隔离/结果分类行为不变。
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
    scope: '`cli` 解析 `agent_id` 并注入 `Orchestrator` / `Messages`，`_cmd_sync_prs` 透传 `agent_id`；删除 `github.current_login` 及其测试。'
    acceptance: poll / vigil / sync-prs 端到端拿到一致 agent_id；`current_login` 全仓无引用；ruff + 全量 pytest 通过。
---

# 0011 · 本地 Agent 身份 + 评论签名（区分自评论与真人评论，根治 poll 自循环）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给每个本地运行的 agent 一个**持久且稳定的身份**（`agent_id`），并在它发出的每条 PR 评论正文上盖一枚**可解析的签名标记**。这样 poll 在拉取评论时就能机械地区分「这条是我自己刚发的」与「这条是真人或其他 agent 发的」，从而根治 poll 把自己的回贴当成新消息、再次触发处理的**自循环**。

## Motivation

OpenAgents 的 agent 通过 GitHub 式的 PR + comment 机制互相传递消息：每当 PR 上出现一条新评论，agent 就收到「your PR 收到一条评论」并据此推进流程（如 refine RFC、回贴结论）。这套机制有一个致命的反身性缺陷：**agent 自己回贴的评论，对它自己的 poll 而言也是「一条新评论」**。

旧实现靠「最新评论的作者 != 当前 GitHub 登录名（`github.current_login`）」来过滤自评论。这条判据在多场景下失效：

- 同一个 GitHub 账号下并行跑多个 agent 实例时，登录名相同，无法区分「是我这个实例发的」还是「另一个实例发的」——后者本应被当作真消息处理。
- 依赖一次额外的网络调用（取 current login），既慢又是一个可失败点。
- 「post 评论后、还没来得及推进游标就崩溃重启」这一窗口里，重启后的 poll 会把那条自评论当新消息，触发**重复处理 / 自循环**。

根因是 agent **没有一个独立于 GitHub 账号的、进程级稳定的身份**，也没有把这个身份**钉在它产出的消息上**。本 feature 引入持久 `agent_id` + 评论签名，把「这条评论是谁发的」从「猜作者登录名」变成「读正文里的签名」，使自评论判定变得确定、本地、可在重启后保持。

## Guide-level explanation

引入两个概念：

- **agent_id（身份）**：一个进程级稳定的标识符。解析优先级为 **env > state > 自动生成并落盘**：显式给了环境变量就用它；否则读 state.json 里持久化的 `agent_id`；都没有就生成一个、写回 state.json，于是后续调用（含重启后）拿到的是同一个 id。
- **评论签名（消息盖章）**：agent 发评论时，正文里嵌一枚带 `agent_id` 的签名标记。任何一方读到这条评论，都能用 `parse_agent_id` 从正文还原出发送者的 `agent_id`；真人评论或无签名评论解析结果为 `None`。

接好之后，poll 的判定从「最新评论作者 != 我的登录名」改为「最新评论的**签名** != 我的 `agent_id`」。于是：自己刚发的评论被精确剔除（即便崩溃重启、即便同账号多实例并行）；别的 agent 盖了**不同**签名的评论、以及真人发的**无**签名评论，照常被当作新消息处理。`github.current_login` 这条旧判据随之整体下线。

## Reference-level explanation

落到改动，分解为 6 个 Task（DAG 见末尾；`files` 互斥，各 Task 单一 writer）：

1. **T1 state 层 agent_id 持久化**（无依赖）—— `State` 新增 `get_agent_id` / `set_agent_id`，state.json 顶层增可选键 `"agent_id"`。`_load` 对缺键容错（返回不含 agent_id 的状态），既有 `runs` / `cursors` 结构不变。这是 `agent_id` 的持久化底座，被 T2 的「生成后落盘」依赖。
2. **T2 identity 模块**（依赖 T1）—— 新建 `openagents/identity.py`：`resolve_agent_id`（env > state > 生成并落盘，落盘走 T1 的 `set_agent_id`）、`sign`（把 `agent_id` 编成正文签名标记）、`parse_agent_id`（从正文反解，无签名返回 `None`）、`post_signed_comment`（包装 `github.post_comment`，正文自动带签名）。同时定义签名标记常量与 `agent_id` 字符集约束，保证 `sign` → `parse_agent_id` 往返无歧义。这是 T3/T4/T5 共享的签名能力中枢。
3. **T3 poll 判定剔除自评论 + 游标简化**（依赖 T2、T5）—— `Messages.__init__` 增 `agent_id`；`_latest_new_comment` 在原有「新于游标」的基础上**额外剔除签名等于自身 `agent_id`** 的评论；`_process_rfc_review` 的游标**只推进到触发评论**（不再跳到最新），消除「post 后未推游标即崩溃」的自循环窗口；删除不再需要的 `_newest_comment_id`；`poll` 的合并分支把 `agent_id` 透传给 `rebase.rebase_open_prs`（故依赖 T5 的签名形参就位）。
4. **T4 orchestrator 回贴评论盖章**（依赖 T2）—— `Orchestrator.__init__` 增 `agent_id`；`refine_rfc` 回贴结论改走 `identity.post_signed_comment(..., agent_id=self._agent_id)`，使其产出的评论自带签名、被 T3 识别为自评论。commit/push 与状态流转逻辑不变。
5. **T5 rebase 冲突评论盖章**（依赖 T2）—— `rebase_open_prs` 增**必填** `agent_id`；rebase 冲突时的留言改走 `identity.post_signed_comment(..., agent_id=agent_id)`。错误隔离与结果分类行为不变。
6. **T6 CLI 接线 + 下线 current_login**（依赖 T3、T4、T5）—— `cli` 在入口解析 `agent_id`（经 `resolve_agent_id`）并注入 `Orchestrator` / `Messages`，`_cmd_sync_prs` 把 `agent_id` 透传给 rebase 路径；删除 `github.current_login` 及其测试（旧自评论判据已被签名取代，全仓无残留引用）。

**端到端验证**：本 feature 的验证以全量单测为准 —— `ruff check` + `pytest`（各 Task 的 `tests/test_*.py` 用 monkeypatch 打桩 `github.post_comment` / state IO，断言签名往返、自评论剔除、游标只进到触发评论、`current_login` 无引用）。仓库 `scripts/` 下暂无本 feature 专属 e2e 脚本；如需对外回归，应新增 `scripts/e2e-spec-0011-agent-identity.sh` 离线串起上述断言。

依赖 DAG：`T1 → T2`，`T2 → T3`，`T2 → T4`，`T2 → T5`，`T5 → T3`，`T3 → T6`，`T4 → T6`，`T5 → T6`。

## Drawbacks

- 评论正文里多了一枚签名标记，对人类读者是轻微噪音（需保证标记紧凑、不喧宾夺主）。
- `agent_id` 一旦落盘即长期存在；若同一工作目录被多个本不相干的用途复用，可能误共享身份（实践中 state.json 与工作树一一对应，风险可控）。

## Rationale and alternatives

- **为什么用「正文签名」而非「靠作者登录名」**：登录名在同账号多实例并行下不可区分，且需额外网络调用、有崩溃重启窗口。把身份钉在消息正文里，判定变成纯本地的字符串解析，确定、可重启保持、零额外网络调用。
- **为什么 `agent_id` 落 state.json 而非纯环境变量**：环境变量适合显式覆盖，但默认场景下需要一个**无需配置即稳定**的身份，故采用 env > state > 生成落盘 三级，兼顾可覆盖与零配置稳定。
- **为什么游标「只推进到触发评论」**：把「处理动作」与「游标推进」对齐到同一条触发评论，消除「已 post 自评论、游标尚未越过它就崩溃」导致下一轮重复处理的窗口；配合签名剔除形成双保险。
- **备选：给评论打 GitHub label / 用 reactions 标记**。否决（YAGNI + 解耦）：label/reaction 需额外 API、且不随正文流转；正文签名零依赖、随消息天然携带。

## Prior art

「在消息体内嵌可解析的发送者标记以实现自我识别 / 防回环」是消息系统的常见做法（如邮件的 `Message-ID` / `In-Reply-To`、机器人为避免响应自身消息而校验 sender id）。本 feature 取其「用稳定身份标识消息来源、据此过滤自身」的核心，落到 PR 评论这一具体载体上。

## Unresolved questions

无。身份解析优先级、签名往返、游标语义、`current_login` 下线均已在本组确定。

## Future possibilities

- 签名可扩展为携带更多结构化元数据（如所接 coding agent 类型 claude-code / codex），供前端区分不同 agent 的产出。
- 多 agent 协同时，可基于签名做评论归属可视化 / 审计。
- 补一条 `scripts/e2e-spec-0011-agent-identity.sh` 离线端到端脚本，串联签名往返 + 自评论剔除回归。

