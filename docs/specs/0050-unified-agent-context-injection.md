---
number: "0050"
title: 统一 agent 上下文注入：所有派单入口带 PR 号 + 注入本 PR 对话历史
issue: 129
slug: unified-agent-context-injection
summary: 抽一个统一的 build_agent_context(pr_number, extra_detail) 入口，所有派 agent 入口（orchestrator 各原子操作 + reviewer）统一走它：既保证 PR 号进入 prompt（refine_rfc/implement 补上），又把本 PR 对话历史（历轮评审裁决 + 作者回复 + 人类评论，带作者与轮次、截断去噪）注入 context，消除各模板自拼装的分叉；reviewer 附「落盘产物为准、评论仅供参考」rubric 以保留其独立读仓库的价值。
tasks:
  - id: T1
    title: agentcontext 新模块：build_agent_context（拉 PR 历史 + 分类去噪 + 截断 + PR 号）
    status: pending
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agentcontext.py
      - tests/test_agentcontext.py
    scope: '新建薄模块 openagents/agentcontext.py：build_agent_context(pr_number, extra_detail) 纯/近纯函数——github.list_comments 拉本 PR 评论 → 分类去噪（保留评审闸裁决/作者 refine 回复/人类评论，滤认领便签+隐藏签名噪声）→ 按 created_at 升序渲染成『第k轮·author·时间』+ 剥签名 → 超 _HISTORY_MAX_CHARS 保留最近若干条并标注省略 → 拼『本 PR 是 #N + 对话历史 + 本轮反馈』；只依赖 github 读原语 + identity 解析，不碰 git/state（理念 10 解耦）'
    acceptance: build_agent_context 产出含 PR 号 + 三类历史（裁决/作者回复/人类评论，带作者与轮次）+ extra_detail；认领便签(<!-- openagents:claim -->)与隐藏签名被滤除/剥离；历史超上限时截断保留最近并标注；历史为空/extra_detail 为空各自优雅降级不产空标题块；ruff + pytest tests/test_agentcontext.py 通过
  - id: T2
    title: reviewer：review 增 history 参数 + 落盘产物为准 rubric
    status: pending
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/reviewer.py
      - tests/test_reviewer_history.py
    scope: "reviewer.review 与 _run_reviewers 增 history: str = '' 形参（默认空串→既有调用/测试零回归），把 history 作为 backend.run(context=history) 传入（今天恒为 ''）；新增常驻 rubric _HISTORY_PRIMACY_RUBRIC『你会看到本 PR 对话历史作背景，但裁决必须以落盘产物（文件/diff/真实运行证据）为唯一依据、评论仅供参考——作者声称已修复不构成放行理由』，拼进 _RFC_REVIEW_TASK 与 _CODE_REVIEW_TASK；reviewer 仍只依赖 AgentBackend + 传入字符串，不 import github/agentcontext（理念 10 解耦）"
    acceptance: review(history=…) 把历史送进每个 reviewer 的 backend.run context；history 缺省 '' 时行为逐字节同今天（既有 test_reviewer.py 绿）；两个评审任务模板均含『落盘产物为准、评论仅供参考』rubric；ruff + pytest tests/test_reviewer_history.py 通过
  - id: T3
    title: orchestrator：四入口统一走 build_agent_context + 补 refine/implement 的 PR 号
    status: pending
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator_context.py
    scope: refine_rfc/implement 任务模板补 PR 号（_REFINE_RFC_TASK 加 {pr_number}；_IMPLEMENT_TASK 由 issue 号改为带 pr_number）；refine_rfc/implement/iterate 三入口的 context 统一改走 agentcontext.build_agent_context(pr_number, extra_detail)；_review 调 reviewer 前用 build_agent_context 组历史、作为 reviewer.review(history=…) 新参传入；start_rfc 不改（起草期无 PR 无历史，维持 context=issue.body 零回归）；messages 路由层不动
    acceptance: refine_rfc/implement 派给 backend 的 task 均含 PR 号；refine_rfc/implement/iterate 派给 backend 的 context 含本 PR 历史；_review 把历史经 reviewer.review(history=…) 送达 reviewer；start_rfc 行为不变；既有 test_orchestrator.py 绿；ruff + pytest tests/test_orchestrator_context.py 通过
  - id: T4
    title: 成果测试：#128 式历史复现集成测试 + e2e 脚本
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0050-agent-context-injection.sh
      - tests/test_agent_context_integration.py
    scope: '内存假 github（评论账本）复现 PR #128 式历史：历轮 reviewer FAIL 裁决 + 作者『已把 result.md 改成 PASS』说明 + 一条人类评论 + 一条认领便签噪声。集成测试断言：①build_agent_context 产出含 PR 号+三类历史（带作者与轮次）+extra_detail；②认领便签/隐藏签名被滤除；③捕获 prompt 的假 backend 驱动 refine_rfc/implement/iterate→task 含 PR 号且 context 含历史；④reviewer.review(history=…) 把历史送进 backend context 且模板含落盘产物为准 rubric。e2e 脚本跑 ruff+定向 pytest+spec validate 打印可复现证据（浏览器 e2e 不适用：本改动是后端 prompt/context 组装、无产品前端界面可截图断言）'
    acceptance: bash scripts/e2e-spec-0050-agent-context-injection.sh 退出码 0；集成测试四条断言（PR 号进 prompt / 三类历史进 context / 噪声被滤 / reviewer 得历史且 rubric 生效）全部通过；脚本输出可作 PR 指路牌收录的可复现证据
---

# 0050 · 统一 agent 上下文注入：所有派单入口带 PR 号 + 注入本 PR 对话历史

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

OpenAgents 每次派 agent（起草/精炼 spec、实现、迭代、评审）时喂给它的上下文，今天既**不统一**
也**不完整**：PR 号有的入口写进 prompt、有的不写；所有 agent 都看不到**本 PR 的对话历史**
（历轮评审裁决、作者历轮回复、人类评论）。本 spec 抽一个统一入口
`build_agent_context(pr_number, extra_detail)`，同时负责两件事：**①** 保证 PR 号进入 prompt
（`refine_rfc` / `implement` 两个缺口补上）；**②** 拉取本 PR 的对话历史，按作者身份 + 轮次
渲染、去噪、截断后注入 `context`，让每个 agent 都能看到「这个 PR 之前发生过什么」。所有派 agent
入口（orchestrator 的 `refine_rfc` / `implement` / `iterate` + reviewer 评审闸）统一走它，消除
各模板自行拼装上下文的分叉。对 reviewer 特别处理：注入历史的同时，rubric 明确「以落盘产物为准、
评论仅供参考」，既让它知晓历轮意见/人类指导，又保留其「独立读仓库真实状态、不被说辞蒙蔽」的价值。

## Motivation

**现状（就地复述，不靠裸引用承载）。** OpenAgents 的每个 coding agent 都经统一后端
`ClaudeCodeBackend.run(work_dir, task, context)` 派发，后端把每条 prompt 拼成
`_GUARDRAIL + "任务：" + task + "上下文：" + context`（`openagents/backends/claude_code.py:66-72`
的 `_build_prompt`）。其中 `task`（做什么）与 `context`（背景）由各调用方各自组装，于是产生两类缺口。

**缺口一：PR 号注入不统一。** 各派单入口是否把 PR 号写进 prompt，各写各的：

| 入口 | 代码位置 | PR 号进 prompt？ |
|---|---|---|
| reviewer（spec/code 闸） | `reviewer.py:353-359` `_task_for` → `_RFC_REVIEW_TASK` / `_CODE_REVIEW_TASK`（`.format(pr_number=…)`） | ✅ |
| iterate（代码迭代 ci/review/e2e） | `orchestrator.py:713` `_ITERATE_TASK.format(pr_number=…)` | ✅ |
| iterate（人类解挂 human） | `orchestrator.py:711` `_HUMAN_UNBLOCK_TASK.format(pr_number=…)` | ✅ |
| **refine_rfc（spec 精炼）** | `orchestrator.py:487` `_REFINE_RFC_TASK.format(detail=…)`；模板（`:94-98`）只说"本 issue 的 spec" | ❌ 无 PR 号 |
| **implement（实现）** | `orchestrator.py:517` `_IMPLEMENT_TASK.format(number=record.issue_number)`（`:100-109`） | ❌ 用 issue 号，非 PR 号 |

今天靠「agent 被放进该 PR 的隔离 worktree（`work_dir=worktree`）」兜底定位，能跑通；但 prompt 里
缺 PR 号使 agent 在需要时无法自查 PR 元信息 / 评论线程（它手里有 `gh` 却不知道号码），也让日志与
自证难以溯源到具体 PR。

**缺口二：本 PR 的对话历史从不注入。** 所有 agent 的 `context` 都**不含 PR 评论线程**：
- reviewer 直接 `context=""`（`reviewer.py:369,373` 的 `backend.run(..., context="")`），模板明确
  「与起草者/作者不共享上下文」（`_RFC_REVIEW_TASK:71` / `_CODE_REVIEW_TASK:120`）；
- 解题 agent 的 `context` 只有**单轮**反馈：`refine_rfc` 传 `context=detail`（reviewer 本轮意见）、
  `iterate` 传 `context=detail`（本轮 CI/评论/人类反馈）、`implement` 传 `context=""`。看不到历轮
  评审、作者历轮回复、其他人类评论。

**为什么要改——#128 卡死实证。** 触发本 issue 的是本仓库 PR #128 的卡死：e2e/证据闸每轮起**全新
进程**、`context=""`，看不到评论线程里作者已说明「已把 `result.md` 改成 PASS」，只读到文件真实内容
仍是 `skipped` → 反复判 FAIL → 攒满 K 轮 → `needs-human`。虽然「只认落盘文件、不认口头说辞」在该案
里**恰好正确**（作者确实没真改到位），但普遍看，reviewer 与解题 agent 都**无法把历轮澄清、已达成的
共识、人类补充判断纳入本轮**，导致：反复挑同一类**已澄清**的问题、忽略人类在评论区给出的指导、
多轮之间**无记忆**。

**期望行为（验收目标）。**
1. 所有派 agent 的入口一律把 PR 号写进 task 文本（`refine_rfc` / `implement` 补上），形成统一约定，
   不再靠「运气在对的 worktree」定位。
2. 把本 PR 的对话历史（按需截断/去噪，**至少含**历轮评审裁决 + 作者回复 + 人类评论，带**作者身份与
   轮次**）注入进 `context`，让每个 agent 看到「这个 PR 之前发生过什么」。
3. 对 reviewer 保留其「独立读仓库真实状态、不被说辞蒙蔽」的价值（这是 #128 能**正确**判 FAIL 的原因），
   同时让它知晓历轮意见/人类指导——注入历史但 rubric 明确「以落盘产物为准、评论仅供参考」。
4. **反向约束**：不推翻 reviewer 与起草者「不共享草稿上下文」的刻意隔离（`reviewer.py:1-13` 顶部注释
   记录的取舍），本 spec 只补充「可见的历史评论」这一层，不让 reviewer 与作者共享私有草稿状态；
   不引入新的 state 字段 / 配置文件 / 外部依赖（奥卡姆，理念 1）。

## Guide-level explanation

把这次改动理解成「给每个上工的 agent 发一份**统一的交接单**」，而不是让每个工种自己临时拼一张。

- **交接单长什么样。** 一个新的纯函数 `build_agent_context(pr_number, extra_detail)` 产出一段
  `context` 文本，结构固定为三块：**①** 一行「本 PR 是 #N」把 PR 号带进上下文；**②**「本 PR 对话历史
  （供背景参考）」——按时间顺序、每条标注**作者 + 第几轮/时间**，含历轮评审闸裁决、作者的历轮回复
  说明、人类评论；**③**「本轮具体反馈」——即调用方原本要传的 `extra_detail`（reviewer 本轮意见 /
  单条人类评论 / CI 日志……）。历史块过长时按「保留最近若干条 + 截断到长度上限」压缩。

- **谁来发这张单。** orchestrator 是唯一同时持有 `pr_number` 与 github 读能力的位置，所以由它在
  `refine_rfc` / `implement` / `iterate` 三个原子操作里调 `build_agent_context` 组 `context`；评审闸
  `_review` 也在这里把历史组好、作为参数传给 reviewer。**messages 路由层不动**（它照旧只把单轮 `detail`
  传给 orchestrator，历史注入收口在 orchestrator，理念 10 解耦）。

- **PR 号从此人人都有。** `refine_rfc` 的任务模板补上 PR 号（今天只说「本 issue 的 spec」）；
  `implement` 的任务模板把「issue #N」改为**同时**带 PR 号（今天误用 issue 号）。加上 `build_agent_context`
  在 context 里也复述一遍 PR 号，agent 无论读 task 还是 context 都能拿到号码去 `gh pr view` 自查。

- **reviewer 依旧是「独立的眼睛」，但不再失忆。** reviewer 现在会收到同一份历史（历轮裁决 + 作者
  回复 + 人类评论），但它的 rubric 明确加一条：**「以落盘产物为准，评论仅供背景参考——不得因作者在
  评论里声称『已修复』就放行，要以仓库里的真实文件/diff 为唯一裁决依据」**。于是 #128 那种「作者说改了
  但文件仍是 skipped」的情形，reviewer 既能**看到**作者的说明（不再盲目反复挑同一句已澄清的话），
  又仍会**以文件为准**判 FAIL（保留它抓真问题的价值）；同时人类在评论区给的指导也进入它的视野。
  reviewer 模块本身仍只依赖「一个字符串 + `AgentBackend` 协议」，不碰 github/state（历史由 orchestrator
  组好传入），保持其 hermetic 可单测的解耦定位。

- **去噪。** 历史里 agent 自己的**认领便签**（`<!-- openagents:claim -->`）、纯 PR 正文摘要指路牌等
  机器噪声会被过滤；**评审闸裁决**评论与**人类评论**保留（它们正是要让 agent 看见的历史）。作者的
  refine「已据评审更新 spec」说明也保留（体现作者历轮回复）。

## Reference-level explanation

### 技术方案

**新模块 `openagents/agentcontext.py`（T1，唯一 writer）。** 一个不碰 git/state、只依赖 `github` 读原语
+ `identity` 解析原语的薄模块，导出纯/近纯函数：

```
build_agent_context(*, pr_number: int, extra_detail: str) -> str
```

流程：
1. `comments = github.list_comments(pr_number=pr_number)`（已存在，返回 `list[Comment]`，每条含
   `author / body / created_at`，`github.py:353,107-118`）。
2. **分类与去噪**（纯函数 `_render_history`）：
   - **保留**：评审闸裁决评论（正文含 `## 评审闸裁决` 抬头，可复用 `reviewer.extract_decision_content`
     判定，`reviewer.py:292`）、作者的 refine 说明（`_REFINE_COMMENT` 「🤖 已根据评审意见更新 spec」）、
     一切**人类评论**（`identity.parse_agent_id(body) is None`，`identity.py:80`）。
   - **过滤**：认领便签（正文含 `identity` 的 `<!-- openagents:claim -->` 标记，`identity.py:39`）、
     其它纯噪声机器评论。
   - 每条按 `created_at`（ISO 8601 字典序即时序）升序，渲染成 `【第 k 轮 · <author> · <created_at>】\n<正文摘要>`，
     正文里的隐藏 HTML 注释签名剥除（避免签名噪声污染）。
3. **截断**：历史块超过长度上限 `_HISTORY_MAX_CHARS` 时，**保留最近若干条**并在头部标注「（更早的
   N 条历史已省略）」——最近的澄清/共识最相关（与 `claude_code._SUMMARY_MAX_LEN` 同源的「控制塞进
   prompt 的长度」思路）。
4. 组装返回：`f"本 PR 是 #{pr_number}。\n\n## 本 PR 对话历史（供背景参考）\n{history}\n\n## 本轮具体反馈\n{extra_detail}"`；
   历史为空 / `extra_detail` 为空各自优雅降级（不产生空标题块）。

**orchestrator 收口（T3，唯一 writer `orchestrator.py`）。** 把三个派单入口的 `context` 组装统一改走
`agentcontext.build_agent_context`，并补两个 PR 号缺口：
- `refine_rfc`（`orchestrator.py:472-506`）：`_REFINE_RFC_TASK` 模板补 `{pr_number}`；
  `context=agentcontext.build_agent_context(pr_number=pr_number, extra_detail=detail)`。
- `implement`（`orchestrator.py:509-533`）：`_IMPLEMENT_TASK` 模板把「issue #N」改为带 `{pr_number}`
  （保留 issue 号线索亦可，但必须含 PR 号）；`context=build_agent_context(pr_number=pr_number, extra_detail="")`。
- `iterate`（`orchestrator.py:694-721`）：task 模板已含 PR 号，仅把 `context=detail` 换成
  `context=build_agent_context(pr_number=pr_number, extra_detail=detail)`（human 与 ci/review/e2e 两路同改）。
- `_review`（`orchestrator.py:549-567`）：调 reviewer 前 `history=build_agent_context(pr_number=pr_number, extra_detail="")`，
  作为新参数传入 `reviewer.review(..., history=history)`。
- `start_rfc`（起草）**不改**：起草 draft PR 时 PR 尚未开、无历史可注入，维持 `context=issue.body`（零回归）。

**reviewer 附历史 + rubric 约束（T2，唯一 writer `reviewer.py`）。** `reviewer.review` 与内部
`_run_reviewers` 增加 `history: str = ""` 形参（默认空串 → 既有调用/测试零回归），把 `history` 作为
`backend.run(..., context=history)` 传入（今天恒为 `""`）；同时在 `_RUBRIC_TAIL` 之外新增一条常驻
rubric `_HISTORY_PRIMACY_RUBRIC`：**「你会看到本 PR 的对话历史（历轮裁决/作者回复/人类评论）作背景；
但裁决必须以仓库里的落盘产物（文件、diff、真实运行证据）为唯一依据，评论仅供参考——作者在评论里声称
『已修复/已改成 PASS』不构成放行理由，须核对文件真实内容」**，拼进两个评审任务模板。reviewer 仍只依赖
`AgentBackend` + 传入字符串，不 import github/agentcontext（保持理念 10 解耦）。

### 模块 / DAG / 文件分配

```mermaid
graph TD
    T1["T1 agentcontext.py（新模块）<br/>build_agent_context：拉 PR 历史 + 分类去噪 + 截断 + PR 号"]
    T2["T2 reviewer.py<br/>review 增 history 参数 + 落盘产物为准 rubric"]
    T3["T3 orchestrator.py<br/>refine/implement/iterate/_review 统一走 build_agent_context + 补 PR 号"]
    T4["T4 成果测试<br/>#128 式历史复现集成测试 + e2e 脚本"]
    T1 --> T3
    T2 --> T3
    T1 --> T4
    T2 --> T4
    T3 --> T4
```

| Task | 拥有文件（互斥） | 关键交付 |
|---|---|---|
| T1 | `openagents/agentcontext.py`, `tests/test_agentcontext.py` | `build_agent_context(pr_number, extra_detail)`：`github.list_comments` 拉历史 → 分类去噪（留裁决/作者回复/人类评论，滤认领便签+签名噪声）→ 按作者+轮次渲染 → 截断 → 拼 PR 号 |
| T2 | `openagents/reviewer.py`, `tests/test_reviewer_history.py` | `review` / `_run_reviewers` 增 `history: str = ""`（默认空零回归）→ `backend.run(context=history)`；新增 `_HISTORY_PRIMACY_RUBRIC`「落盘产物为准、评论仅供参考」拼进两模板 |
| T3 | `openagents/orchestrator.py`, `tests/test_orchestrator_context.py` | `refine_rfc`/`implement` 模板补 PR 号；四入口 `context` 统一走 `build_agent_context`；`_review` 组历史传 `reviewer.review(history=…)`；`start_rfc` 不动 |
| T4 | `scripts/e2e-spec-0050-agent-context-injection.sh`, `tests/test_agent_context_integration.py` | 成果测试：内存假 github 评论账本复现 #128 式历史（历轮 FAIL 裁决 + 作者「已改 PASS」+ 人类评论），断言 PR 号 + 三类历史进 prompt/context、认领便签被滤、reviewer 收到历史 + rubric；e2e 脚本跑 ruff+pytest+spec validate 打印证据 |

文件跨 Task 互斥（理念 6 单一 writer）：`agentcontext.py`(T1) / `reviewer.py`(T2) / `orchestrator.py`(T3) /
脚本+集成测试(T4) 无重叠；各 Task 自带独立新测试文件，既有 `test_orchestrator.py` / `test_reviewer.py`
因新参数带默认值而保持绿（不被任何 Task 占有、不需改动）。

### 成果测试（理念 8）与 e2e 脚本

**浏览器 e2e 适用性自检：不适用。** 本 feature 是**后端 prompt/context 组装**改动——改的是喂给
cli-agent 子进程的文本，**无任何产品前端界面可驱动**（无导航/交互/截图可断言的视觉成果）。虽然本会话
具备 Playwright / Chrome DevTools MCP 工具，但此改动没有 UI 表面可截图；据取证判断纪律，这属「UI 看不到
但改变产品对外行为」一类，成果测试形态为**确定性文本复现**（pytest 集成测试 + 一条 shell e2e 脚本跑它
并打印证据），而非浏览器 e2e。

- **集成测试** `tests/test_agent_context_integration.py`：用内存假 `github`（评论账本）复现 PR #128 式
  历史——历轮 reviewer FAIL 裁决评论、作者「🤖 已把 result.md 改成 PASS」说明评论、一条人类评论、一条
  agent 认领便签噪声。断言：
  1. `build_agent_context(pr_number, extra_detail="本轮反馈X")` 产出的 context **含 PR 号**、**含**上述
     历轮裁决 / 作者回复 / 人类评论（带作者与轮次标注）、**且含**本轮反馈 X；
  2. 认领便签 / 隐藏签名噪声被**滤除**，不出现在 context 里；
  3. 用捕获 prompt 的假 backend 驱动 orchestrator 的 `refine_rfc`/`implement`/`iterate`：其派给 backend
     的 **task 含 PR 号**、**context 含历史**（补上两个 PR 号缺口 + 全入口注入历史）；
  4. reviewer 侧：`reviewer.review(history=…)` 把历史送进 `backend.run` 的 context，且评审任务模板含
     「落盘产物为准、评论仅供参考」rubric（保留独立性的同时可见历史）。
- **e2e 脚本** `scripts/e2e-spec-0050-agent-context-injection.sh`：跑 `ruff check` + `ruff format --check`
  + 定向 `pytest`（上述集成测试 + T1/T2/T3 单测）+ `spec validate`，把「PR 号进 prompt / 三类历史进
  context / 噪声被滤 / reviewer 得历史且 rubric 生效」的断言通过输出作为可复现证据（被 PR 指路牌自动收录）。

## Drawbacks

- **prompt 变长、成本上升。** 注入历史使每条 prompt 变长，多轮 PR 上历史累积会显著增大 token 消耗与
  延迟。缓解：`_HISTORY_MAX_CHARS` 截断 + 只留最近若干条 + 去噪；但仍比今日 `context=""`/单轮 detail 大。
- **reviewer 独立性被稀释的风险。** 给 reviewer 看历史，理论上可能被作者的说辞轻微带偏（#128 正是「只认
  文件」才判对）。缓解靠 `_HISTORY_PRIMACY_RUBRIC` 的硬约束，但这是 prompt 层软约束、非结构性保证——
  reviewer 可能仍偶尔被评论影响（见 Unresolved questions 关于「是否给 reviewer 更弱的历史视图」）。
- **每次派单多一次读评论 API。** 每个 orchestrator 入口现在都要 `github.list_comments` 一次；对多 agent
  高频轮询是额外 `gh` 调用（缓解：读评论本就是轻量调用，且 RFC-0010 已有瞬时重试兜底）。
- **去噪启发式可能误伤/漏放。** 「哪些评论算噪声」是启发式（按 claim 标记/签名/裁决抬头分类），规则演进
  时可能误滤有用评论或漏滤噪声；用集成测试固定几类典型评论的期望归类以防回归。

## Rationale and alternatives

**为何选「统一 `build_agent_context` 入口 + reviewer 传参注入」。** 它用**一个纯函数 + 一处 orchestrator
收口**同时解掉两类缺口：PR 号统一（补两个模板 + context 复述）与历史注入（一处组装、四入口复用），
消除「各模板自拼装」的分叉——正是 issue 建议方向 1。把历史**组装**放在 orchestrator（唯一持有 pr_number
+ github 的位置）、reviewer 只**接收字符串**，既让所有入口统一走同一函数，又不破坏 reviewer「只依赖
AgentBackend + 字符串」的 hermetic 解耦（理念 10）。复用现成 `github.list_comments` / `identity`
签名解析（issue 建议方向 2），新增面极小、不引入 state/配置/外部依赖（理念 1）。

**备选 A：reviewer 直接 import `agentcontext`/`github` 自取历史。** 省掉 orchestrator 传参。
**取舍**：破坏 reviewer 模块「只依赖 AgentBackend 协议、可 hermetic 单测」的定位（`reviewer.py:10-12`
明文解耦约束），让 reviewer 耦合 git/github/网络，单测需打桩 github——违背理念 10，故不选。传参法让
reviewer 保持纯函数式、orchestrator 单点收口 github 读，更契合现有架构。

**备选 B：把历史注入下沉到后端 `_build_prompt`（`claude_code.py`），对所有调用方透明。** 后端自动为
每条 prompt 拼历史。**取舍**：后端适配器不该持有 pr_number / 懂 github（它今天只拼字符串、是纯适配层），
下沉会让后端耦合业务与网络、且 `start_rfc` 起草期无 PR 也要特判——违背分层。故把注入留在业务层
（orchestrator），后端维持薄适配。

**备选 C：只补 PR 号、不注入历史（拆成两个 issue）。** 最小改。**取舍**：issue 明确「两者应一并治理」，
且 #128 卡死的直接推手是**缺历史**而非缺 PR 号，只做一半达不到「多轮之间有记忆」的期望，故 C 仅作为
风险回退（若历史注入引发成本/独立性问题，可先落 PR 号统一），不作为终态。

**备选 D：给 reviewer 与解题 agent 注入不同强度的历史（reviewer 只看人类评论+裁决摘要，解题 agent 看
全量）。** 更细的独立性保护。**取舍**：增加两套渲染路径与配置，先用「同一份历史 + reviewer rubric 硬约束」
的最简方案；若实测 reviewer 被带偏再分化（列入 Unresolved questions），奥卡姆优先。

## Prior art

- **rust-lang/rfcs 的 RFC 形态**（本 spec 9 段结构本身，https://github.com/rust-lang/rfcs）。
- **对话记忆 / 会话历史注入**是交互式 coding agent（对标 Cursor / Windsurf，见 CLAUDE.md 商业定位）的
  标准做法：把同一会话/线程的历轮消息按角色+顺序回灌进上下文，使多轮之间有记忆。本 spec 把「PR 评论
  线程」当作该会话历史的来源，是这一通行手法在「以 PR/comment 为消息总线」（CLAUDE.md 理念 2）架构下的
  自然落地。
- **本仓库既有取舍**：reviewer「与起草者不共享上下文」的刻意隔离（`reviewer.py:1-13` 顶注）、`identity`
  的签名/认领便签溯源（`identity.py`）、RFC-0010 的 gh 瞬时重试——本 spec 复用/尊重这些既有原语，
  现状与约束已在 Motivation/Reference-level 就地复述，此节仅作线索，不承载理解本 spec 所需的必要信息。

## Unresolved questions

- **`_HISTORY_MAX_CHARS` 取值与截断策略。** 保留最近多少条 / 多长最合适，留待实现时以集成测试标定；
  是否需要按评论类型加权（人类评论优先保留）待评审。
- **reviewer 是否需要更弱的历史视图（备选 D）。** 「同一份历史 + rubric 硬约束」是否足以守住独立性，
  还是应给 reviewer 只喂「人类评论 + 裁决摘要」、隐去作者的自辩说辞，待实现期实测 reviewer 行为后定。
- **历史是否需要 LLM 摘要而非机械截断。** 长 PR 上机械截断可能丢中间轮的关键共识；是否引入一次轻量
  摘要（成本 vs 保真）待评审——v1 先机械截断。
- **去噪边界。** 除认领便签外，PR 正文指路牌（e2e signpost / digest）、解冲突回贴等机器评论是否也应
  过滤，需在集成测试里逐类固定期望，避免规则漂移。

## Future possibilities

- **历史注入下沉为可复用「会话上下文」原语**：若未来更多场景（跨 PR 关联、issue 线程）也需回灌历史，
  可把 `build_agent_context` 泛化成按「线程 id」取历史的通用模块。
- **按角色分化的历史视图**（备选 D 落地）：为 reviewer / 解题 agent / 精炼 agent 定制不同的历史强度。
- **LLM 摘要式历史压缩**：长线程用一次轻量摘要替代机械截断，在成本可控下提升多轮记忆保真。
- **把「落盘产物为准」从 rubric 软约束硬化**：探索让 reviewer 的裁决在结构上强制引用文件/diff 证据
  （如要求裁决附 `git diff` 片段），把「评论仅供参考」从自觉变成更难违反的约束（呼应理念：软约定硬化）。

