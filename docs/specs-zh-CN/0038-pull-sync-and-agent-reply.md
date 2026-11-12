---
number: "0038"
title: 合并冲突改拉式同步 + 解冲突 agent 用带签名工具自回评论
issue: 96
slug: pull-sync-and-agent-reply
summary: 守夜人合并/冲突处理从「推式扇出+确定性 heal」改为「门2 拉式同步+agent 能动性」；解冲突 agent 用带签名 reply-comment 工具亲自回人类评论（根治牛头不对马嘴）
tasks:
  - id: T1
    title: 门2 拉式同步 + 删 push 扇出
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
      - tests/test_messages_resolve.py
      - tests/test_messages_conflict_diag.py
      - tests/test_messages_merge_unblock.py
      - tests/test_messages_comment_reply.py
    scope: 门2(_process_coding) 新增 BEHIND 分支→update_branch 拉 main（synced/behind-conflict）；删门1(is_merged)/门3(reviewer PASS) 的 eager 扇出，reconcile 只留 done+关 issue；armed 路径删框架代发回复，仅保留跑完清 unblock_detail。
    acceptance: BEHIND→update_branch 被调返回 synced、其冲突→behind-conflict；合并事件不带 synced 且无扇出；armed 解冲突成功清 armed+清 detail 且不代发回复；ruff + pytest 全绿。
  - id: T2
    title: 删死代码 + CONFLICT_COMMENT 迁移
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/conflictdiag.py
      - tests/test_conflictdiag.py
      - scripts/e2e-spec-0034-conflict-diagnostics.sh
    scope: 删 rebase.py（扇出）与 indexheal.py（确定性 heal）及其测试；CONFLICT_COMMENT 常量从 rebase 迁至 conflictdiag（单一来源）；e2e-spec-0034 改为只演练幸存的 conflictdiag 管线。
    acceptance: rebase/indexheal 及其测试删除、全仓无残留 import；conflictdiag.CONFLICT_COMMENT 为唯一来源、format_blocker 空诊断退回它；e2e-spec-0034 离线退出 0；ruff + pytest 全绿。
  - id: T3
    title: 解冲突 agent 用带签名工具自回评论
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/conflict.py
      - openagents/cli.py
      - openagents/orchestrator.py
      - tests/test_conflict.py
      - tests/test_conflict_guidance.py
      - tests/test_cli.py
      - scripts/e2e-spec-0036-unblock-comment-read-and-reply.sh
    scope: 新增 CLI reply-comment（盖签名薄封装 post_signed_comment）；conflict._REPLY_TOOL_SECTION 在 guidance+pr_number 时要求 agent 用工具亲自回评论（禁裸 gh）；resolve_branch/make_resolver 透传 pr_number；删 sync-prs 命令；implement/iterate 收尾对齐 main。
    acceptance: reply-comment 以本 agent_id 盖签名发评论；_resolve_task 在 guidance+pr_number 时含 reply-comment 指令、缺 pr_number 时不含；sync-prs 从 CLI 移除；e2e-spec-0036 离线退出 0；ruff + pytest 全绿。
---

# 0038 · 合并冲突改拉式同步 + 解冲突 agent 用带签名工具自回评论

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把守夜人（`messages.Messages.poll`）的合并/冲突处理从「**推式扇出 + 确定性 indexheal**」重构为
「**门2 拉式同步 + agent 能动性**」：一个 PR 轮到自己被处理时，若落后 main（`BEHIND`）就由
`github.update_branch` 把最新 main 并进来触发 CI 重跑，若冲突（`DIRTY`）就派 coding agent 语义解冲突；
删掉「合并即把 main 推给其余 PR」的 eager 扇出与其配套的 `rebase.py`/`indexheal.py`/手动 `sync-prs`。
同时把 merge 闸解挂后的**回评论**从「框架代发两句写死罐头」改为「解冲突 agent 用新 CLI 工具
`openagents reply-comment`（自动盖签名、防自循环）**亲自**回人类评论」。

## Motivation

**背景（就地复述，单 spec 自包含）**：OpenAgents 是 RFC/spec 驱动的多 agent 框架，守夜人
`messages.Messages.poll` 周期扫描所有 open PR，按阶段路由：合并/关闭优先 reconcile，再走 rfc 评审闸
（draft PR 承载 RFC）或代码闸（`_process_coding`：先做可合并性预检，再等 CI、跑 reviewer）。可合并性
预检本文称「**门2**」。原设计里，一个 PR 合并进 main 是个信号，会**扇出**（`rebase.rebase_open_prs`）
对其余每个 open PR 跑 `github.update_branch`，冲突时按 `indexheal`（确定性重渲 `OVERVIEW.md`）→
`conflict.resolve`（agent 语义解冲突）→ 留言 分层降级。

**三个毛病**：

1. **扇出两个调用点能力不对称**：`is_merged` reconcile 路径注入了 heal/resolve/diagnose，而
   reviewer-PASS 后框架自己 merge 那处**只注入 diagnose**——于是 `OVERVIEW.md` 这类**本可确定性
   自愈**的冲突，若从后一个门冒出来就被直接升级 `needs-human`。同一个冲突的命运取决于它从哪个扇出口
   进来，形同抛硬币（这正是 issue #96 / PR #99 报告的不对称）。
2. **门2 只「看」不「拉」**：预检只读 `mergeability`，从不把 main 并进来——落后但无冲突的 PR 既不被
   重新集成测试，在「require branches up to date」下甚至永远合不了。
3. **merge 闸解挂后「牛头不对马嘴」**：人在被 merge 冲突挂起的 PR 下回评论，框架把评论当 guidance
   喂给解冲突器，但解冲突器只返回 bool，于是回复永远是两句写死的罐头（`已解冲突并 push` /
   `本轮未能自动解决`），跟人说了什么无关。

**为什么这么改**：把「谁来集成/解冲突」从「合并时 push 给所有人」收敛成「各 PR 轮到自己时在门2 拉」，
只剩一个处理点、能力天然对称，issue #96 的不对称从结构上消失；把回评论交给 agent 亲自用带签名工具发，
既复用 rfc/code 闸已验证的「agent 自己回话」模式，又靠签名防住自循环。

## Guide-level explanation

站在 PR 的视角看新流程：

- **我落后 main 了（BEHIND）**：轮到我时门2 调 `update_branch` 把最新 main 并进来，我的 CI 在「集成后
  代码」上重跑；本轮不评审，下一轮以集成态推进。
- **我跟 main 冲突了（DIRTY）**：门2 派解冲突 agent 在临时 worktree 里 `git merge` + 语义解冲突 + 自测
  + push。`docs/specs/OVERVIEW.md` 这类生成式索引，agent 被要求用 `spec render` 重渲而非手工合并。
- **有人合并了别的 PR**：不再有人主动把 main 推给我；我各自轮到时自己拉（拉式取代推式）。
- **人在我这条挂起的 PR 下回了评论**：评论作 guidance 喂解冲突 agent；agent 解完**自己**用
  `openagents reply-comment --pr <我> --body "..."` 回那条评论——该命令自动盖 OpenAgents 签名，故我的
  回复不会被下一轮 poll 当成新人类评论（不自循环）。框架不再代发罐头回复。

人类可见变化：`openagents sync-prs` 命令移除（拉式后多余）；新增 `openagents reply-comment` 命令
（主要给 coding agent 用）。

## Reference-level explanation

**核心改动**：

- **门2（`_process_coding`）新增 `BEHIND` 分支**：`merge_state_status == "BEHIND"` → `try
  github.update_branch(pr_number)`；成功返回 `synced`，撞冲突（`GithubError`）返回 `behind-conflict`
  （下一轮 mergeability 即 `DIRTY`，落到既有 agent 解冲突路径——脏活只此一个解冲突脑子）。
- **删门1（`is_merged`）/门3（reviewer PASS）的 eager 扇出**：两处 `rebase.rebase_open_prs` 调用删除，
  reconcile 只留「置 done + 关 issue」，merged 事件不再带 `synced`。
- **删死代码**：`openagents/rebase.py`（扇出）、`openagents/indexheal.py`（确定性 heal）、`_make_heal`、
  CLI `sync-prs` 命令；`rebase.CONFLICT_COMMENT` 常量迁至 `conflictdiag.CONFLICT_COMMENT`（单一来源）。
- **回评论工具化**：新增 CLI `reply-comment`（薄封装 `identity.post_signed_comment`，用本实例 agent_id
  盖签名）；`conflict._REPLY_TOOL_SECTION` 在 guidance + pr_number 齐备时拼进解冲突 task，要求 agent
  「无签名才是人类、只回相关的、必须用工具、禁用裸 gh」；`resolve_branch`/`make_resolver` 透传
  `pr_number`；messages armed 路径删 `_reply_resolve_outcome` 代发回复，仅保留跑完清 `unblock_detail`。

**Task DAG + 文件分配**（三 Task 文件互不重叠，均已 done）：

| Task | owns files | 依赖 |
|---|---|---|
| T1 门2 拉式同步 + 删扇出 | `openagents/messages.py` + `tests/test_messages*.py` | — |
| T2 删死代码 + 常量迁移 | `openagents/conflictdiag.py`、`tests/test_conflictdiag.py`、`scripts/e2e-spec-0034-conflict-diagnostics.sh` | — |
| T3 解冲突 agent 用带签名工具回评论 | `openagents/{conflict,cli,orchestrator}.py`、`tests/test_{conflict,conflict_guidance,cli}.py`、`scripts/e2e-spec-0036-...sh` | — |

**e2e 脚本**：`bash scripts/e2e-spec-0034-conflict-diagnostics.sh`、`bash
scripts/e2e-spec-0036-unblock-comment-read-and-reply.sh`（均离线、不触网/gh/LLM）。

## Drawbacks

- **删掉了确定性 indexheal**：`OVERVIEW.md` 冲突原来由确定性代码重渲（几乎不出错），现改由「被告知去
  `spec render` 的 LLM」处理——可靠性理论上不如确定性代码（能动性换确定性的代价）。
- **回评论工具靠 prompt 纪律**：`必须用工具、禁裸 gh` 是提示约束，未硬性 sandbox；agent 若头铁用裸
  unsigned `gh pr comment`，自循环会回来（本组**不加**作者兜底，属明确取舍）。
- **拉式比推式收敛慢**：集成从「合并瞬间并发推给所有人」变成「各 PR 轮到自己才拉一次」。

## Rationale and alternatives

- **备选 A：只补对称（PR #99 的做法）**——给 reviewer-PASS 那处扇出补回 heal/resolve，使两个扇出口
  对称。否决：只堵一半（门2 首发冲突仍不试 heal），且保留了整套推式扇出的复杂度。本组更彻底：删扇出、
  收敛成门2 单点。
- **备选 B：保留框架代发回复，把 agent summary 顺出来当回复**——改动小，但 agent 的回话要经框架
  中转、且需在返回类型里塞 summary。否决：不够 agent-native，且回复内容仍受框架模板结构约束。本组让
  agent 用工具亲自发，更直接。
- **备选 C：回评论加「作者兜底」**（poll 识别「自己发的」从看签名改成也看作者）——更防弹（裸 gh 也不
  循环）。本组按取舍**暂不做**，记入 Future possibilities。

## Prior art

- issue #48 `indexheal`（确定性重渲 OVERVIEW）、Spec-0028 `conflict.resolve`（agent 语义解冲突）、
  Spec-0034 `conflictdiag`（带诊断的冲突通知）——本组删前者、复用后两者的机制。
- issue #96 / PR #99「扇出两调用点能力不对称」——本组从根上解决（删扇出）而非补对称。
- rfc/code 闸的 `_HUMAN_UNBLOCK_TASK` + `replynote`「agent 自己回话」模式——本组把等价能力（改用带
  签名 CLI 工具）补到 merge 闸。
- RFC-0019 防自循环 / Spec-0032「只读晚于水位线 + 无签名的人类评论」——本组回评论工具盖签名，正是
  依赖这条签名过滤不自触发。

## Unresolved questions

- **livelock**：main 变动快于「一个 PR 同步+CI+评审+合并」时，门2 拉取可能永远追不上。是否引入
  merge queue（串行化合并）留待后续。
- **回评论可靠性**：agent 会不会稳定地调 `reply-comment`（而非忘记/绕过），需真实环境观察。

## Future possibilities

- 作者兜底（备选 C）：把 poll 的「自己发的评论」识别从签名扩展到作者身份，硬防裸 gh 造成的自循环。
- 把「回评论工具 + 读全评论区自选」推广到 rfc/code 闸，统一所有闸的 agent 回话方式。
- merge queue：串行化合并根治 livelock。

