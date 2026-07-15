---
number: "0016"
title: issue 页面新增评论 agent 自动回复（把评论回复从 PR 扩展到 issue）
issue: 149
slug: issue-comment-agent-reply
summary: 把「新人类评论→agent 签名回复」闭环从 PR 扩展到 issue 页：vigil 的 reply 分支②对**已准入、尚无 PR** 的 issue subject 也读 issue 页评论、按签名滤新人类评论、派 replier（issue 语境提示词，只答疑不改代码）经 issue 级签名出口回帖。读侧/写侧 issue 原语补齐（identity.new_human_comments_on_issue / post_signed_comment_on_issue，复用已存在的 github.list_issue_comments/issue_comment），state 加 issue 评论游标，reply-comment CLI 加 --issue 手动出口。准入面 admitter（triage:human 一次性入闸对话）与本回复面（已准入 issue 的持续答疑）按 issue 准入态天然切开、互不打架。
e2e:
  intent: 证明「issue 页面出现新人类评论 → agent 感知 → 派 replier → 带签名回帖到该 issue」闭环在离线确定性链路上成立，且不自触发（自己的签名回复不会被下一轮当成新人类评论）。
  method: "形态：纯后端编排，无 product-facing 前端可导航；自检工具列表无 Playwright / Chrome DevTools MCP，\n故不设浏览器 e2e，改用离线确定性测法（承 Spec-0061/0065 的 fake-github 离线 e2e 风格）：\n脚本 scripts/e2e-spec-0016-issue-comment-agent-reply.sh 反复调 run_vigil(once=True)，用注入的\nfake github + fake backend 构造一个**已准入（带 ready label）、尚无 PR** 的 issue，其评论流最新一条\n是无签名的人类评论。断言：\n1. 该 tick vigil 对此 issue 判 ACTIONABLE:reply（而非 solve），派出 replier；\n2. replier 的回复经 identity.post_signed_comment_on_issue 落到该 issue（gh issue comment），且带本\n   实例签名 `<!-- openagents:agent=… -->`；\n3. 再跑一 tick：最新评论已是我方签名 → `_latest_is_ours` True → 不再重复回帖（不自触发死循环）；\n4. 手动出口 `oa reply-comment --issue N --body …` 同样经签名出口落到 issue。\n"
tasks:
  - id: T1
    title: identity issue 签名读/写原语（new_human_comments_on_issue + post_signed_comment_on_issue）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/identity.py
      - tests/test_identity_issue_reply.py
    scope: 补 identity 的 issue 版签名读/写原语，与既有 PR 版对称、既有 PR 版函数零改动（零回归）。读侧 new_human_comments_on_issue(*, number, since) 镜像 new_human_comments，改调 github.list_issue_comments(number=…)，沿用「created_at > since 且 parse_agent_id is None」双约束（仅新 + 仅人类，防自触发）。写侧 post_signed_comment_on_issue(*, number, body, agent_id)：sign 盖签名 → github.issue_comment(number=…, body=…) → issue 版回读校验漏签则补签（回读经 list_issue_comments、补签经 issue_comment），闭合 Spec-0064 约束③（非只 warn）。复用既有 github.list_issue_comments/issue_comment，不改 github.py。
    acceptance: 'pytest tests/test_identity_issue_reply.py 通过：new_human_comments_on_issue 只返回 since 之后的无签名人类评论、滤掉一切带签名机器评论、按 created_at 升序（monkeypatch github.list_issue_comments）；post_signed_comment_on_issue 盖签名后经 issue_comment 落 issue，回读最新评论已含本实例签名则 no-op、漏签则补一条签名评论（monkeypatch list_issue_comments/issue_comment）；既有 PR 版 new_human_comments/post_signed_comment 行为不变。ruff clean，注释引用 # Spec-0016/T1。'
  - id: T2
    title: state issue 评论游标（get/set_issue_cursor，独立命名空间）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/state.py
      - tests/test_runtime_state_issue_cursor.py
    scope: 给 RuntimeState 加 issue 评论游标，与既有 PR 游标（cursors 键，按 pr_number）平级但独立命名空间（如 issue_cursors 键，按 issue number），避免 issue N 与 PR N 撞键。get_issue_cursor(*, number) -> str | None / set_issue_cursor(*, number, comment_id)，落 runtime-state.json；写路径持 RuntimeState._LOCK（同 set_cursor，丢一条游标=对同一人类评论重复回帖）。既有 get_cursor/set_cursor 零改动。
    acceptance: 'pytest tests/test_runtime_state_issue_cursor.py 通过：set 后 get 读回同值；缺省 get 返回 None；issue N 与 PR N 游标互不干扰（写 issue N 不影响 get_cursor(pr_number=N)）；写路径在锁内。ruff clean，注释引用 # Spec-0016/T2。'
  - id: T3
    title: replier issue 提示词 + context issue 回复占位符（只答疑、不改代码）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/replier.py
      - openagents/runtime/context.py
      - tests/test_agents_replier_issue.py
      - tests/test_runtime_context_issue_reply.py
    scope: '给 replier 加 issue 语境提示词、给 context 加 issue 回复占位符组装，与既有 PR 版并存零改动。replier.ISSUE_PROMPT（string.Template，占位符 $issue_number / $comment_body，**无** $branch、**无**「若需要改代码就改」分支——只答疑、不触发交付协议，对齐 issue #149「只要回复、不要解决」），复用既有 replier.OUTPUT_SCHEMA={reply:str, resolved:bool}（resolved 表这条评论诉求是否已被本轮答复充分解决）。context.for_issue_reply(*, work_dir, issue_number, comment) -> dict 组 {issue_number, comment_body, context} 占位符（对齐 for_reply 风格，issue 键，读侧惰性注入）。既有 replier.PROMPT / context.for_reply 不动。'
    acceptance: 'pytest tests/test_agents_replier_issue.py + tests/test_runtime_context_issue_reply.py 通过：ISSUE_PROMPT.substitute 能填入 issue_number/comment_body 且渲染文本不含 branch/改代码字样、含「只回复不改代码」意图；for_issue_reply 产出含 issue_number/comment_body/context 键的占位符 dict（monkeypatch github 读侧 hermetic）；既有 PR 版 PROMPT/for_reply 行为不变。ruff clean，注释引用 # Spec-0016/T3。'
  - id: T4
    title: vigil 接线：_sense 填 issue latest_comment_is_ours（限 ready 无-PR）+ _do_reply issue 分派 + 离线 e2e
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - tests/test_recipe_vigil_issue_reply.py
      - scripts/e2e-spec-0016-issue-comment-agent-reply.sh
    scope: 把 issue 页回复接进 vigil reconcile，改动面最小、与 PR 侧同构。_sense：当 kind==_KIND_ISSUE and pr_number is None and _LABEL_READY in labels 时，读 github.list_issue_comments(number) → latest_comment_is_ours=_latest_is_ours(comments)（复用既有纯函数）；否则维持现状（未 ready 归 admitter、有 PR 走 PR 流）。不新增携 comment id 的 _Facts 字段——只改既有 latest_comment_is_ours 的取值来源，_fingerprint 全集与「盖 attempt 戳不改 fp」不变式不动（护栏一不自毁）。_do_reply：pr_number is None（且 kind issue）分支——new_human_comments_on_issue(number, since=state.get_issue_cursor) → context.for_issue_reply → engine.run_agent(replier, ISSUE_PROMPT 占位符) → identity.post_signed_comment_on_issue → state.set_issue_cursor；拼 _NEEDS_HUMAN_CONTRACT 一等出口。分支②(_classify:738)/看门狗/优先级白送不改。附离线 e2e 脚本（见 frontmatter e2e.method）。
    acceptance: 'pytest tests/test_recipe_vigil_issue_reply.py 通过：ready 无-PR issue 最新评论是无签名人类 → _sense 置 latest_comment_is_ours=False → _classify 判 ACTIONABLE:reply（非 solve）；未 ready 的无-PR issue / 有 PR 的 issue → latest_comment_is_ours 维持现状（不误激活）；_do_reply issue 分支经 post_signed_comment_on_issue 落 issue 并推 issue 游标；回帖后最新评论我方签名 → 下一 tick _latest_is_ours True → 不重复回帖；_fingerprint 字段集仍 == dataclasses.fields(_Facts) 全集、不含 comment id。bash scripts/e2e-spec-0016-issue-comment-agent-reply.sh 绿。ruff clean，注释引用 # Spec-0016/T4。'
  - id: T5
    title: reply-comment --issue 手动出口（与 --pr 互斥二选一）
    status: done
    priority: P2
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli_issue_reply.py
    scope: 给隐藏内部命令 reply-comment 加 --issue N，与既有 --pr N 组成互斥参数组（二选一、至少一个）。--issue 路由到 identity.post_signed_comment_on_issue(number=…, body=…, agent_id=…)，--pr 维持既有 post_signed_comment。仍不传 help=（隐藏命令，Spec-0064/T5 定位不变）。既有 --pr 路径零改动。
    acceptance: 'pytest tests/test_cli_issue_reply.py 通过：oa reply-comment --issue N --body X 经 post_signed_comment_on_issue 落 issue（monkeypatch）；--pr 与 --issue 同给报错、都不给报错（argparse 互斥必选组）；--pr N --body X 仍走既有 post_signed_comment（零回归）。ruff clean，注释引用 # Spec-0016/T5。'
---

# 0016 · issue 页面新增评论 agent 自动回复（把评论回复从 PR 扩展到 issue）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把 OpenAgents 已有的「**新人类评论 → agent 带签名回复**」闭环从 **PR** 扩展到 **issue 页面**。今天这个闭环只在 PR 上成立：vigil 的 reconcile 分支表里，`_classify` 分支②（`not facts.latest_comment_is_ours` → `ACTIONABLE:reply`）→ `_do_reply` 读 PR 评论、派 `replier` agent、经 `identity.post_signed_comment`（PR 版）签名回帖。issue 页面上的人类评论没有回复出口：`_sense` 对**尚无 PR 的 issue** 刻意**不**设 `latest_comment_is_ours`（`vigil.py:654-655`「无-PR issue 的人机对话归准入面 admitter，reply 分支②要 PR 语境，此处不激活」），reply-comment CLI 只接 `--pr`。

本 spec 定向解除这条限制：让 vigil 对**已准入（`ready`）、尚无 PR** 的 issue subject 也读 issue 页评论、按签名滤出新人类评论、派 `replier`（issue 语境提示词——只答疑、**不改代码**，对齐 issue #149「只要回复、不要解决」）经 **issue 级签名出口**回帖。底层 gh 读/写原语（`github.list_issue_comments` / `github.issue_comment`）**已存在**，缺的是它们之上的三层：签名读/写 issue 版（identity）、issue 评论游标（state）、issue 回复上下文与提示词（context/replier）、以及 vigil 的分支接线与 reply-comment 的 `--issue` 手动出口（cli）。

## Motivation

**现状（就地复述，证据驱动 · 理念 8）。** 评论即消息、每条新评论 agent 收到一条并回应，是 CLAUDE.md 理念 2 的核心闭环。这个闭环今天的落点是 `openagents/recipes/vigil.py` 的 level-triggered reconcile 循环（**不是** issue 正文里提到的 `messages.poll`——`messages` 模块已在 Spec-0062/0064 的两栈合一里**整体删除**，`messages.poll` 只在历史注释里残留；这是 issue #149 正文基于旧心智模型的过时表述，本 spec 据实更正）。具体链路：

- **感知**：`_sense`（`vigil.py:598`）每 tick 对每个 subject 读一次 GitHub 现态。对有 PR 的 subject，读 `github.list_comments(pr_number=…)`（PR 版，走 `gh pr view --json comments`）→ `_latest_is_ours`（`vigil.py:858`：最新一条带我方签名？无评论视作 True）→ 落到不可变的 `facts.latest_comment_is_ours`。
- **分类**：`_classify`（`vigil.py:686`）是纯函数分支表；分支②（`vigil.py:738`）`if not facts.latest_comment_is_ours: return _Verdict(ACTIONABLE, action=reply)`——**这一支本身是 subject 无关的**，只要 `facts.latest_comment_is_ours` 被填成 issue 语义即可复用。它排在 solve/rebase/ci/… 之前（人在等，优先级最高）。
- **执行**：`_do_reply`（`vigil.py:2548`）`if pr_number is None: return ""`（无 PR 直接空返回）→ `identity.new_human_comments(pr_number, since=游标)` 拉新人类评论 → `context.for_reply(pr_number, branch, comment)` 组占位符 → `engine.run_agent(replier, …)` → `identity.post_signed_comment(pr_number, …)` 签名回帖 → `state.set_cursor(pr_number, …)` 推游标。全链**每一环都以 `pr_number` 为键**。
- **防自触发**：`identity.sign` 在正文尾追加隐藏 HTML 签名 `<!-- openagents:agent=<id> -->`；`identity.new_human_comments`（`identity.py:94`）滤掉 `parse_agent_id(body) is not None` 的评论（一切机器评论），只留 `created_at > since` 的无签名人类评论。两道约束（仅新 + 仅人类）使 agent 永远读不到自己的回复自问自答。

**缺口。** 三处把上述能力**焊死在 PR** 上：
1. `_sense` 对无-PR issue **不激活** `latest_comment_is_ours`（`vigil.py:647-656`，只把 issue 评论时间戳喂进度时钟给看门狗，`latest_comment_is_ours` 留默认 True）→ 分支②对 issue 永不触发。
2. issue 页面无 agent 回复出口：`identity.new_human_comments` / `post_signed_comment` / `_verify_signature_or_fix` 全部只接 `pr_number` 且调 `gh pr view` / `gh pr comment`；`context.for_reply` 也是 PR 键；`replier` 提示词是 **PR 语境**（`$pr_number` / `$branch` / 「若需要改代码就改」）。
3. `reply-comment` CLI（`cli.py:149`）只接 `--pr`。

结果：issue 提出后人在 issue 页追加评论（补需求、提问、纠偏），当前流程**完全不响应**，issue 层的对齐/澄清全靠人手动搬运——与理念 2 不一致。**这正是 issue #149 要补的洞。**

**为什么现在做、为什么值得。** issue 是自主环的入口（vigil 发现 issue → 派 agent 解决）。issue 页评论是 issue 提出到第一个 PR 落地之间**唯一的人机对齐通道**；这段窗口今天是哑的。补上它，人对 issue 的追问/纠偏能被 agent 当场接住（哪怕只是「收到、我理解成 X，对吗」或「这点超出我能定的，交人」），把宏观把控真正搬到 issue 层（理念 2「人负责宏观、不负责细节」）。

## Guide-level explanation

从使用者视角，本 feature 加一条自然行为：**你在一个 OpenAgents 正在管理的 issue 页面留一条评论，稍后会收到一条署名的 agent 回复。**

- **谁会被回复**：一个**已准入**（带 `ready` label，已过三态入闸）、**尚无 PR** 的 issue，其评论流里最新一条是**人类**（无 OpenAgents 隐藏签名）评论。
- **回复什么**：replier（issue 语境）读懂你这条评论想要什么（追问？补充需求？纠偏？），**只答疑、不改代码**（issue #149 明确「只要回复、不要解决」——改代码/开 PR 是 solve 分支的事，不在本 issue 范围）。答不了/超出授权/需求有歧义 → 走一等出口：打 `needs-human` + 留理由，守夜当场判终态、停轮询交人。
- **回复长这样**：一条落在 issue 页的评论，尾部带隐藏签名 `<!-- openagents:agent=… -->`（GitHub 不渲染、对人零干扰）。这个签名是防自触发的关键：下一 tick vigil 读到最新评论是自己签的 → `_latest_is_ours` True → 不再重复回帖。
- **手动出口**：被派的子 agent（或运维）可 `oa reply-comment --issue N --body "…"` 手动往 issue 回一条签名评论，与既有 `--pr` 出口对称（二选一，互斥）。

**准入面 vs 回复面（关键边界，读者最容易混）。** 今天 vigil 已经会在 issue 评论里跟人对话——但那是**准入面** admitter（`_ask_human`，处理 `triage: human` 态：一次性回答「这 issue 到底该不该做」的入闸问题）。本 feature 是**回复面**：issue **已准入之后**、对人后续追加评论的**持续答疑**。两者天然切开、互不打架，因为：admitter 只在 `_intake`（生产者的准入段）里对 `triage:human`（**未 ready**）的 issue 跑；一旦 issue 打上 `ready`，它就离开准入段、进入 reconcile 前沿，此后的人类评论归本 feature 的 reply 分支。准入态（有没有 `ready`）就是这条边界的单一判据，不需要新增协调机关。

## Reference-level explanation

### 总体方案

复用「分支②本身 subject 无关」这个事实：**只要把 `facts.latest_comment_is_ours` 对已准入无-PR issue 填成 issue 语义，分支②与看门狗全部白送**；`_do_reply` 补一条 issue 分派路径；底层原语补 issue 签名版。范围严格限定在**已准入、尚无 PR** 的 issue——有 PR 的 subject 走既有 PR 评论路径不变（issue 页 + PR 页双流合并是 Future，见下）。

### 关键契约与不变式

- **fp 安全（护栏一不自毁）**：`_Facts.latest_comment_is_ours` 是既有 bool 字段、已在 `_fingerprint` 全集内；本 feature **只改它的取值来源**（无-PR issue 从 issue 评论算），**不新增携 comment id 的字段**。我方回帖后最新评论变我方签名 → 该 bool 翻 True → fp 变化 = 合法进展（人被答复了），分支②停火；这与 PR 侧语义完全同构，`_Facts` 仍不含 comment id（盖 attempt 戳不改 fp 的不变式不动）。
- **防自触发**：issue 版读侧 `new_human_comments_on_issue` 沿用「`created_at > since` **且** `parse_agent_id is None`」双约束；issue 版写侧 `post_signed_comment_on_issue` 沿用「签名后 post + 回读校验漏签则补签」闭环（Spec-0064 约束③，非只 warn），只是读经 `list_issue_comments`、写经 `issue_comment`。
- **准入/回复边界硬化**：reply 分支②对 issue subject 只在 `ready in facts.labels` 时激活（无 `ready` 的 issue 仍归 admitter）。把「准入前归 admitter、准入后归 replier」从注释软约定变成 `_sense`/`_classify` 里的显式条件（理念：软约定硬化）。
- **只答疑不改代码**：issue replier 提示词**不含**「改代码就改」分支、**不**触发交付协议；输出 schema 收敛为 `{"reply": str, "resolved": bool}`（与 PR replier 同 schema，`resolved` 表「这条评论诉求是否已被本轮答复充分解决」）。

### DAG + 文件分配

| Task | 内容 | files（互斥单一 writer） | depends-on |
|---|---|---|---|
| T1 | identity issue 签名读/写原语 | `openagents/utils/identity.py`, `tests/test_identity_issue_reply.py` | — |
| T2 | state issue 评论游标 | `openagents/runtime/state.py`, `tests/test_runtime_state_issue_cursor.py` | — |
| T3 | replier issue 提示词 + context issue 回复占位符 | `openagents/agents/replier.py`, `openagents/runtime/context.py`, `tests/test_agents_replier_issue.py`, `tests/test_runtime_context_issue_reply.py` | — |
| T4 | vigil 接线：`_sense` 填 issue `latest_comment_is_ours`（限 ready 无-PR）+ `_do_reply` issue 分派 + 离线 e2e | `openagents/recipes/vigil.py`, `tests/test_recipe_vigil_issue_reply.py`, `scripts/e2e-spec-0016-issue-comment-agent-reply.sh` | T1, T2, T3 |
| T5 | `reply-comment --issue` 手动出口 | `openagents/cli.py`, `tests/test_cli_issue_reply.py` | T1 |

- T1/T2/T3 三者文件两两不相交，**可并行**（无 mutual dependency）。
- T4 是汇聚点，依赖 T1（读/写原语）+ T2（游标）+ T3（提示词/占位符）。
- T5 依赖 T1（`post_signed_comment_on_issue`）；与 T4 文件不相交，可与 T4 并行。
- `github.py` **不在任何 Task 的 files 里**——`list_issue_comments`（`github.py:447`）/ `issue_comment`（`github.py:432`）已存在、直接复用，零改动（零回归）。

### 各 Task 的接口契约

- **T1**：`identity.new_human_comments_on_issue(*, number: int, since: str) -> list[github.Comment]`（镜像 `new_human_comments`，改调 `github.list_issue_comments(number=…)`）；`identity.post_signed_comment_on_issue(*, number: int, body: str, agent_id: str) -> None`（签名 → `github.issue_comment(number=…, body=…)` → issue 版 `_verify_signature_or_fix`，回读经 `list_issue_comments`、补签经 `issue_comment`）。既有 PR 版函数**不动**（零回归）。
- **T2**：`state.get_issue_cursor(*, number: int) -> str | None` / `state.set_issue_cursor(*, number: int, comment_id: str)`，落 `runtime-state.json` 的独立命名空间键（如 `issue_cursors`，与 `cursors` 平级，避免 issue N 与 PR N 撞键）；写路径持 `RuntimeState._LOCK`（同 `set_cursor`）。
- **T3**：`replier.ISSUE_PROMPT`（Template，占位符 `$issue_number` / `$comment_body`，**无** `$branch`、**无**「改代码」分支，只答疑）+ 复用 `replier.OUTPUT_SCHEMA`；`context.for_issue_reply(*, work_dir, issue_number, comment) -> dict` 组 `{issue_number, comment_body, context}` 占位符（对齐 `for_reply` 风格，issue 键）。
- **T4**：`_sense`——`kind == _KIND_ISSUE and pr_number is None and _LABEL_READY in labels` 时，读 `github.list_issue_comments(number)` → `latest_comment_is_ours = _latest_is_ours(comments)`（复用既有纯函数）；否则维持现状。`_do_reply`——`pr_number is None`（且 kind issue）分支：`new_human_comments_on_issue(number, since=get_issue_cursor)` → `context.for_issue_reply` → `run_agent(replier, ISSUE_PROMPT…)` → `post_signed_comment_on_issue` → `set_issue_cursor`；拼 `_NEEDS_HUMAN_CONTRACT` 一等出口。
- **T5**：`reply-comment` 加互斥参数组 `--pr N | --issue N`（二选一、至少一个）；`--issue` 路由到 `post_signed_comment_on_issue`，`--pr` 维持既有 `post_signed_comment`。

### e2e 脚本

`scripts/e2e-spec-0016-issue-comment-agent-reply.sh`（离线、fake-github + fake-backend，承 Spec-0061/0065 风格）——详见 frontmatter `e2e.method`。

## Drawbacks

- **多一条读请求**：对每个已准入无-PR issue，`_sense` 每 tick 多一次 `gh issue view --json comments`。GitHub 认证配额 5000 req/h，上百 issue 时叠加进 Spec-0065 已记的批量化 Future（GraphQL 一条 query 拉多 subject）。
- **轮询延迟**：沿用轮询（不做 webhook），回复延迟下限 = vigil tick interval，与 PR 侧同构（issue #149 明确「先沿用轮询」）。
- **准入/回复边界依赖 `ready` label 的正确性**：若某 issue 该准入却没打上 `ready`，其评论会继续归 admitter 而非 replier。这把边界押在既有准入闸的正确性上（可接受：`ready` 本就是准入的单一令牌）。
- **单流限制**：本期只覆盖 issue 页评论**在该 issue 尚无 PR 时**；issue 有了 PR 后，issue 页新评论不再被回复（改走 PR 流）。见 Future。

## Rationale and alternatives

**选定方案：扩 `latest_comment_is_ours` 语义 + 复用分支②（限 ready 无-PR issue）。** 因为分支②与看门狗已是 subject 无关的纯逻辑，只需把 issue 评论喂进既有 fact 就白送分类/优先级/护栏，改动面最小（理念 1 奥卡姆），且与 PR 侧防自触发/游标/签名机制**完全同构**——一套心智模型两处落地，无第二套并行机制要对账。

**备选 1：复活独立的 `messages.poll` 式 issue 评论轮询器（新模块）。** 贴合 issue #149 正文的原始描述，但 `messages` 栈已被两栈合一整体删除；重开一个平行轮询循环 = 造第二套「读评论→滤签名→回帖→推游标」，与 vigil 的 reconcile 重复、且要另立并发/认领/看门狗，违背 0062-0065 的收敛弧线（recipes 守恒为 3）。**否决。**

**备选 2：直接复用 PR replier 提示词 + 让它可改代码。** 省掉 T3 的 issue 提示词。但 issue #149 范围明确「只要回复、不要解决」；PR replier 的「若需要改代码就改 + 交付协议」会诱导 agent 在只该答疑的场景下开改，越界。且 issue 无 `$branch` 语境，PR 提示词占位符对不上。**否决**（保留「issue 只答疑」的清晰语义边界）。

**备选 3：把 issue 回复并进 admitter（让 admitter 既管入闸又管后续答疑）。** 省掉分支接线。但 admitter 是 **fail-closed 人闸**（判「人到底点头没有」），职责是准入裁决；把持续答疑塞进去会污染它的单一职责、且它的输出 schema/提示词是准入语义。**否决**（准入面/回复面按 `ready` 态切开更干净）。

## Prior art

- **本仓 PR 评论回复闭环**（RFC-0011 签名 / Spec-0032 读侧定向复活 / Spec-0061 replier+poll_comments / Spec-0065 vigil reconcile 分支②）——本 spec 是它到 issue 面的同构延伸，读/写/防自触发全部沿用既有原语与不变式。
- **本仓 issue 评论既有用法**：Spec-0043 `issue_comment`（issue 级写）、Spec-0049 `list_issue_comments` + 署名认领便签、Spec-0065 admitter `_ask_human`（issue 评论入闸对话）——证明 issue 评论读/写原语与 gh 路径已跑通，本 spec 复用而非新造。
- **GitHub 评论模型**：REST 层 PR 评论本质是 issue 评论（同一 endpoint），但本仓刻意走 `gh pr view` / `gh issue view` 两条子命令路径（薄封装 gh，不碰 REST），故 PR 版与 issue 版是两个对称函数而非一个。

## Unresolved questions

> 待与用户在评审阶段确认（只记用户选择保留的问题）：
- 有 PR 后的 issue 页新评论要不要也回？本期定为**不回**（改走 PR 流），若团队希望 issue 页始终可答疑，则需双流合并（见 Future）——是否本期就要？
- `ready` 作为准入/回复边界是否够？若存在「未 ready 但需持续答疑」的 issue，是否要放宽激活条件？

## Future possibilities

- **双流合并**：issue 有 PR 后，issue 页 + PR 页评论合并成一条时间线，`_sense` 取两流最新的人类评论决定回复目标（`reply_target` fact）。
- **webhook 实时推送**：替换轮询，回复延迟从 tick interval 降到近实时（issue #149 明确本期不做）。
- **issue 评论触发解决**：把「回复」升级为「回复 + 按评论诉求改代码/开 PR」（本期明确不做，属 solve 分支的扩展）。
- **批量化读**：并进 Spec-0065 记的 GraphQL 一条 query 拉多 subject 评论，缓解 `_sense` 每 subject 一次读的配额压力。
- **跨仓库 issue 聚合**（issue #149 明确不做）。

