---
number: "0040"
title: 重设计 e2e：说明书驱动 + 独立执行 + 证据评审门控（Phase 1 骨架）
issue: 104
slug: e2e-runbook-driven-evidence-gate
summary: 把 e2e 从「实现者顺手写脚本、implement 里一次性跑、贴条不门控」升级为「spec 声明 e2e 意图 → 代码写完由实现者把意图定稿成可执行说明书 → 独立 executor agent 按形态（cli/api/backend）真跑系统产出证据文件 → 证据闸 reviewer 拿 RFC 意图对照证据门控合并」，并把「要不要验」上移到 RFC 闸、「行为验收」从代码 reviewer 划给证据闸。
e2e:
  form: cli
  intent: 证明「独立执行 + 证据固化 + 证据闸门控合并 + 上游强制」骨架真的有牙——证据 FAIL 必须挡住合并、证据 PASS 才放行。
  acceptance:
    - 造 fixture PR/worktree + 声明 cli 形态的 runbook，跑 executor → 证据文件落在 docs/e2e-results/<pr>/。
    - 喂「意图未达成」证据给证据闸 → 判 FAIL 且链路走 iterate(reason=e2e)、不调用 merge_pr。
    - 喂「达成」证据 → 判 PASS 且照常放行 merge。
tasks:
  - id: T1
    title: spec 增 e2e 粗规划字段 + validate 硬化
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/schema.py
      - openagents/spec/model.py
      - openagents/spec/validate.py
      - openagents/spec/render.py
      - tests/test_spec_model.py
      - tests/test_spec_validate.py
      - tests/test_spec_render.py
    scope: 在组级总览新增可选结构化字段 e2e{form∈ui|api|cli|backend, intent, acceptance[]}（承载 RFC 阶段的 e2e 粗规划）；spec render 把它渲进 OVERVIEW；spec validate 加规则：字段存在时 form 必须合法、intent 非空、acceptance≥1 条（不存在则不报错，向后兼容既有 spec）。
    acceptance: 单测：带合法 e2e 块的组 validate 通过且 render 显示意图+验收行为；form 非法/intent 空/acceptance 为空各报 error；无 e2e 块的既有组 validate 不报错（零回归）。ruff + pytest 通过。
  - id: T2
    title: executor 角色：独立运行时验证 agent（cli/api/backend 形态）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/executor.py
      - tests/test_executor.py
    scope: 新建 openagents/executor.py，仿 reviewer.review 结构实现一次性 agent run_executor(*, backend, work_dir, runbook_path, evidence_dir, pr_number)->ExecutorResult：读 runbook（含形态声明）→按 form∈{cli,api,backend} 选工具真跑系统→把每步观察/输出写进 evidence_dir→返回结构化 {outcome:passed|failed, form, notes}。契约上绝不抛错（异常映射成 failed，仿 run_e2e_script）。ui 形态本组不实现（返回 skipped/notes 说明留 Phase 2）。模块 docstring 引用 Spec-0040/T2。
    acceptance: 单测（假 backend）：cli 形态 runbook→run_executor 调 backend 真跑并把证据写进 evidence_dir、outcome 随子过程退出码映射 passed/failed；backend 抛错→outcome=failed 不抛出；ui 形态→skipped 且 notes 标注 Phase 2。ruff + pytest 通过。
  - id: T3
    title: 证据固化 + 证据闸 reviewer
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/evidence_gate.py
      - tests/test_evidence_gate.py
    scope: 新建 openagents/evidence_gate.py：evidence_dir_for(*, pr_number)->Path 给出 docs/e2e-results/<pr>/ 路径约定（单一来源）；review_evidence(*, backend, work_dir, intent, evidence_dir, pr_number)->EvidenceDecision 仿 reviewer——把 RFC 批准意图对照 evidence_dir 里的 result.md 证据，判 {passed, feedback}（passed=False 时 feedback 汇总哪条验收行为没达成/避重就轻，供 iterate 喂回）。tautology guard 防线③落此。模块 docstring 引用 Spec-0040/T3。
    acceptance: 单测（假 backend）：证据显示意图达成→passed=True、feedback 空；证据缺失/与意图不符/避重就轻→passed=False 且 feedback 非空；evidence_dir_for 对 pr=12 返回 docs/e2e-results/12/。ruff + pytest 通过。
  - id: T4
    title: reviewer 职责收口 + RFC rubric 硬规则
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/reviewer.py
      - tests/test_reviewer.py
    scope: 职责收口两处：① 从 _CODE_REVIEW_TASK 删掉条件式 _BROWSER_E2E_RUBRIC，并明写「运行时行为由证据闸负责、代码 reviewer 不判运行时行为」，只留静态代码质量/安全/结构；② 把「要不要有 e2e」上移到 _RFC_REVIEW_TASK，加一条更硬的规则：前端/交互类改动的 spec 没声明 e2e 粗规划 → REWORK。改动处注释引用 Spec-0040/T4。
    acceptance: 单测：_CODE_REVIEW_TASK 不再含 browser-e2e 措辞且含「不判运行时行为」；_RFC_REVIEW_TASK 含「前端/交互类改动未声明 e2e 粗规划→REWORK」硬规则；既有 reviewer.review 聚合/裁决解析用例零回归。ruff + pytest 通过。
  - id: T5
    title: 编排接线：定稿→执行→证据闸门控合并 + 退役旧 smoke
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - openagents/messages.py
      - openagents/e2e.py
      - tests/test_orchestrator.py
      - tests/test_messages.py
      - tests/test_e2e.py
    scope: ① orchestrator 新增 finalize_runbook（派实现者 backend 把 spec e2e 粗规划定稿成 docs/e2e-results/<pr>/runbook.md 并 commit）；② messages._process_coding 在 review_code 全票 PASS 之后、merge_pr/hold-merge 之前插入证据闸：finalize_runbook→executor.run_executor→evidence_gate.review_evidence，PASS 照常合、FAIL 走 iterate(reason='e2e')、攒满 rounds>=MAX_ROUNDS 走 _block(gate='e2e')；orchestrator.iterate 的 reason 集合加 'e2e' 文案，_TRIED_BY_GATE 加 'e2e' 一句；③ 退役旧 smoke：删 orchestrator._post_e2e_result 及 implement 内调用与相关 import，删除 openagents/e2e.py + tests/test_e2e.py。改动处注释引用 Spec-0040/T5。
    acceptance: 单测（假 backend + 假 github + monkeypatch executor/evidence_gate）：reviewer PASS 且证据闸 PASS→调用 merge_pr（或 hold 时停）；reviewer PASS 但证据闸 FAIL→调用 iterate(reason='e2e')、不调 merge_pr；证据闸连 FAIL 攒满 K→_block(gate='e2e') 打 needs-human；implement 不再调用 _post_e2e_result；全仓无残留 import openagents.e2e。ruff + pytest 通过。
---

# 0040 · 重设计 e2e：说明书驱动 + 独立执行 + 证据评审门控（Phase 1 骨架）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把 OpenAgents 的 e2e 从「实现者顺手写脚本 + implement 里跑一次 + 贴条不门控」这套**静态、自证、
测过期版本**的过程，升级为一条**说明书驱动 + 独立执行 + 证据评审门控**的流水线：

```
① Spec(RFC)      写 e2e 粗规划（意图 + 验收行为，声明执行形态）；RFC 闸审「要不要验、验什么」
② implement       写功能代码（现状不变）
③ 定稿说明书       代码在了，把粗规划落成【具体可执行说明书 runbook】（prose，声明形态 A）
④ executor agent  通用运行时验证 agent 读 runbook → 按形态选工具 → 真跑系统 → 交互 + 断言
⑤ 固化证据         日志 / 截图 / 结构化 pass-fail → 文件（docs/e2e-results/<pr>/）→ commit 进 PR
⑥ 证据闸           reviewer 拿「RFC 批准的意图」对照「实际证据」判是否真达成 → 门控合并
```

两条正交轴贯穿全设计：**A 执行形态可变**（`ui`/`api`/`cli`/`backend`，e2e 不一定起前端，形态由
说明书声明、executor 据此选工具）；**B 独立执行不变**（无论何形态，都由一个**独立 agent**——跑的人
≠写代码的人——真起系统走真实路径、产出独立证据）。**Phase 1（本组）只做骨架 + 非浏览器形态**
（`cli`/`api`/`backend`），把「独立执行 + 证据评审 + 上游强制 + 合并前门控」立起来；`ui` 浏览器形态
留给 Phase 2（见 Future possibilities）。

## Motivation

**背景（就地复述，不靠裸引用承载必要信息）。** OpenAgents 是 RFC/spec 驱动的多 agent 框架：守夜人
`messages.Messages.poll` 每隔一段时间扫描所有 open 状态的 run，按阶段路由。一个 issue 的典型生命：
`solving`→起 RFC 草稿 PR→`rfc-review`→RFC 获批→`orchestrator.implement` 写代码并把 draft PR
转正→`pr-open`→守夜人 `_process_coding` 每轮查 CI/mergeability，CI 全绿则调 `review_code`（N 个
独立 reviewer agent 投票），全票 PASS 则 `merge_pr`（或 `hold.at_merge` 时停在「待人 merge」），非
PASS 则 `iterate` 迭代代码 / 攒满 K 轮 `_block` 挂起等人。e2e 就嵌在这条链路里——**而它今天是坏的**。
逐行核对（`orchestrator.py` / `e2e.py` / `reviewer.py` / `messages.py` / `spec/signpost.py`）后，
现有 e2e 有四个结构性病灶：

1. **测过期版本。** e2e 只在 `orchestrator.implement`（`orchestrator.py:349-373`）里经
   `self._post_e2e_result(...)`（`:367`）**跑一次**，测的是「第一版实现」。之后 `_process_coding`
   的 `iterate`（`reason="ci"` / `"review"`，`messages.py:419` / `:447`）反复改代码却**从不重跑
   e2e**——最终 `merge_pr`（`messages.py:432`）合进去的版本**从没被 e2e 测过**。
2. **没牙。** `_post_e2e_result`（`orchestrator.py:461-487`）是 best-effort 贴签名评论，异常直接吞掉
   （`:486` `except … 已忽略`），**不门控任何东西**；紧接着 `github.mark_ready`（`:369`）无条件把
   PR 转正，merge 判据只有 reviewer 全票 PASS（`messages.py:426`）——**e2e 失败照样转正、照样合**。
3. **结果没人消费。** 代码 reviewer 经 `reviewer.review` 调 `backend.run(..., context="")`
   （`reviewer.py:116-118`，context **恒为空串**），任务模板 `_CODE_REVIEW_TASK`
   （`reviewer.py:64-72`）只让它「用 `git diff` 看改动 + 读涉及文件」，**从不读 e2e 结果评论**——
   e2e 的 pass/fail 不进任何判定路径。
4. **名不副实 + 惰性。** `e2e.run_e2e_script`（`e2e.py:48`）恒跑脚本的**离线段**（不设
   `OPENAGENTS_E2E_REAL`），实质是 hermetic 的 `ruff + mock pytest + grep 断言`——**没有真实系统
   被跑起来**；脚本路径由 `signpost.script_path_for_group`（`spec/signpost.py:32`）从 spec 正文抓首个
   `scripts/*.sh`，**脚本由实现者顺手写**（既写功能又写自己的测试），不声明就 `skipped`。

**核心转变。** 「跑脚本 + 审脚本」（静态、自证）→「给一份**说明书**，让**独立 agent** 照着把系统
**真跑起来**验证行为，把**证据固化成文件**，再由 reviewer **评审证据**是否达成 RFC 意图」（动态、
独立、门控）。这四个病灶不是四个孤立 bug，而是同一个根：**没有一个独立主体在最终要合的版本上真跑
系统、并把结果接进合并判据**。本组把这个主体（executor）和这道判据（证据闸）补进 merge 前的链路。

## Guide-level explanation

落地后，一个「交互/行为」类 issue 的 e2e 体验变成一条有据可查的流水线。以一个 CLI 行为改动为例
（比如「`openagents init` 在缺 origin 时应报错退出而非静默」）：

**① Spec 阶段只写粗规划（意图 + 验收行为）。** 起草 spec 时，在组级总览声明 e2e **意图**与**验收
行为**，并声明**执行形态**——但**不写死具体命令/选择器/路由**（那是实现细节，代码没写出来之前定不
下来）。例如：

```
e2e 粗规划（意图）：init 在无 origin 远端时必须显式失败并给出可操作提示，不得静默成功。
验收行为：① 在无 origin 的仓库跑 init → 非零退出 + stderr 含「缺少 origin」类提示；
          ② 补上 origin 再跑 → 正常成功。
执行形态：cli（executor 用命令行真跑，不需要浏览器）。
```

RFC 闸此时就审「**要不要验、验什么**」：前端/交互类改动若没声明 e2e 粗规划 → REWORK（硬规则，见
Reference-level）。

**② implement 照常写功能代码。** 与现状一致。

**③ 代码在了，实现者把粗规划定稿成 runbook。** 具体命令、期望输出、判定点这时才定得下来，落成一份
**prose 说明书** `docs/e2e-results/<pr>/runbook.md`：声明形态 `cli`、列出「怎么起、跑什么、看什么算
过」。定稿人**倾向实现者**（它最懂代码），但受 tautology guard 约束——runbook 必须落在 RFC 批准的
意图内，不能把「无 origin 报错」偷换成「跑个 `--help` 看不崩」。

**④ 独立 executor 照 runbook 真跑系统。** 一个**独立的运行时验证 agent**（≠写代码的人）读 runbook，
按形态选工具（`cli`→在 worktree 里真执行命令，`api`→发 HTTP，`backend`→跑真实集成），**真起系统走
真实路径**，交互 + 断言。

**⑤ 证据固化成文件、commit 进 PR。** executor 把每步观察、命令输出/截图、结构化 pass-fail 写进
`docs/e2e-results/<pr>/result.md`（+ 附件），commit 进 PR——durable、可被 reviewer 读、也给人看成果
（理念 8）。

**⑥ 证据闸门控合并。** 一个证据 reviewer agent 拿「**RFC 批准的意图**」对照「**实际证据**」，判有没有
**真达成 / 避重就轻**。PASS → 放行合并；FAIL → 走现成 `iterate`（`reason` 新增 `e2e`）回去改，攒满
K 轮走现成 `_block(gate="e2e")` 挂起等人。**顺序上代码 reviewer 先过、证据闸后跑**：代码 reviewer
PASS（代码看着对）但证据闸 FAIL（真跑跑不通）**不是冲突，正是要抓的**——FAIL 就 iterate。

**关键不变量：说明书两阶段。** 粗规划（意图）在 spec 里锁死、由 RFC 闸批准；具体 runbook 在代码之后
才定稿。这既解决「实现细节定不下来」，又是 tautology guard 的支点——**意图不能在定稿阶段被偷换**。

## Reference-level explanation

### 核心机制：merge 前插入一段「定稿 → 执行 → 证据闸」

改动集中在 `messages._process_coding` 里 **reviewer 全票 PASS 之后、`merge_pr`/`hold-merge` 之前**
（`messages.py:426-432`）插入一段证据闸；配套两个**一次性 agent 角色**（仿现有 `reviewer.review`
的结构）、一个 spec 结构化字段、一条 RFC rubric、一个证据目录约定。新链路：

```
CI 全绿 → review_code 全票 PASS
        → ③ orchestrator.finalize_runbook：派实现者 backend 把 spec 的 e2e 粗规划定稿成
             docs/e2e-results/<pr>/runbook.md（声明形态），commit 进 PR
        → ④ executor.run_executor：独立 agent 读 runbook → 按形态选工具 → 真跑系统 → 写证据
        → ⑤ 证据落 docs/e2e-results/<pr>/{result.md, *.log, *.png}，commit 进 PR
        → ⑥ evidence_gate.review_evidence：reviewer 拿 RFC 意图对照证据 → PASS / FAIL
             ├─ PASS → 照常 merge_pr / hold-merge（现状逻辑不变）
             └─ FAIL → iterate(reason="e2e") 回去改；攒满 K 轮 → _block(gate="e2e") 挂起
```

### tautology guard（防「自定说明书自己过」）——三道防线

1. **意图在 RFC 锁死**：e2e 粗规划（意图 + 验收行为）是 spec 结构化字段，RFC 闸批准后即冻结；具体
   runbook **必须落在批准意图内**，不能偷换（证据闸负责核对）。
2. **executor 独立**（运动员≠裁判）：executor 是与实现者不共享上下文的独立 agent，真起系统走真实路径，
   而非 hermetic 打桩自证。
3. **证据 reviewer 独立核对**：证据闸拿「RFC 批准的意图」对照「实际证据」，判有没有**真达成 / 避重就
   轻**——runbook 即便被实现者写宽松，证据对不上意图仍 FAIL。

### 与现有 reviewer 的职责收口（避免重叠/冲突）

代码 reviewer（静态读代码）与 executor/证据闸（动态验行为）本质互补，收口两处：

- **「要不要有 e2e」上移到 RFC 闸**：把今天挂在代码 reviewer 上的条件式 browser-e2e rubric
  `_BROWSER_E2E_RUBRIC`（`reviewer.py:59-63`，追加在 `_CODE_REVIEW_TASK` 末尾）**从代码 reviewer
  删掉**，改为 RFC 闸（`_RFC_REVIEW_TASK`，`reviewer.py:48-54`）里一条**更硬**的规则：前端/交互类
  改动的 spec 没声明 e2e 粗规划 → REWORK。
- **「行为验收」划给证据闸**：代码 reviewer **显式不判运行时行为**，只留静态的代码质量/安全/结构
  （是否真实现 Task、tautological test、边界安全、破坏性改动）——在 `_CODE_REVIEW_TASK` 里明写
  「运行时行为由证据闸负责，你不判」。

### 状态机影响（几乎不动，不新增 status）

- **不新增 status**：证据闸 FAIL 走现成 `iterate`（`reason` 集合从 `{comment,ci,review,human}` 扩为
  含 `e2e`）+ 现成 `STATUS_ITERATING`；攒满 K 轮走现成 `_block(gate="e2e")` + `needs-human` 标签。
- **复用回合预算**：证据闸 FAIL 的重试计入现有 `rounds`（`increment_rounds`），与代码闸共用 K
  （`MAX_ROUNDS`，默认 3）——总迭代预算一份，达上限即挂起。`blocknote` 的 `_TRIED_BY_GATE`
  （`messages.py:137-143`）新增 `"e2e"` 一句文案，`_block(gate="e2e")` 即复用既有结构化挂起评论。
- **退役旧的一次性 smoke**：删除 `orchestrator._post_e2e_result` 及其在 `implement` 的调用
  （`:367`），退役 `openagents/e2e.py`（hermetic 离线段 runner，病灶 4 根）——它测的是过期版本、
  又不门控，被 merge 前的证据闸完全取代。`signpost.script_path_for_group` 的去留见 Unresolved。

### 证据落地约定

`docs/e2e-results/<pr>/` 目录下：`runbook.md`（③ 定稿说明书）、`result.md`（⑤ 结构化证据：验了什么、
每步观察、pass/fail、证据引用）、随附 `*.log` / `*.png`（Phase 2 截图）。**commit 进 PR** → durable、
可被证据闸读、也给人看成果（理念 8）。

### 本组自身的 e2e 粗规划（吃自己的狗粮）

- **意图**：证明「独立执行 + 证据固化 + 证据闸门控合并 + 上游强制」骨架真的有牙——证据 FAIL 必须挡住
  合并，证据 PASS 才放行。
- **验收行为**：① 造一个 fixture PR/worktree + 一份声明 `cli` 形态的 runbook，跑 executor → 断言证据
  文件落在 `docs/e2e-results/<pr>/`；② 喂一份「意图未达成」的证据给证据闸 → 断言判 FAIL 且链路走
  `iterate(reason="e2e")`、**不调用** `merge_pr`；③ 喂「达成」证据 → 断言 PASS 且照常放行。
- **执行形态 = `cli`/`backend`（不起浏览器）**：本组交付物是纯后端编排机制，仓库内**无任何前端/web UI**
  （已核对：无 `.tsx/.jsx/.vue`、无 `frontend/web/dashboard/server` 目录、无 HTTP 服务启动代码）。
  **自检工具后的取舍**：本会话具备 Playwright / Chrome DevTools MCP 浏览器工具，但**执行形态跟着交付
  物走，而非跟着工具走**——交付物没有前端可导航/截图，`ui` 形态无处施展。选 `cli` 恰是本 spec 决策
  A（形态可变、e2e 不一定起前端）的第一个活样本；浏览器形态待 Phase 2 有真实前端可验时才引入。
- **e2e 脚本**：`scripts/e2e-spec-0040-runbook-driven-evidence-gate.sh`（离线段 dogfood 上述三条断言，
  被 PR 指路牌拾取）。

### DAG 与文件分配

```mermaid
graph TD
    T1[T1 spec e2e 粗规划字段 + validate 硬化]
    T2[T2 executor 角色（独立运行时验证 agent）]
    T3[T3 证据固化 + 证据闸 reviewer]
    T4[T4 reviewer 职责收口 + RFC rubric 硬规则]
    T5[T5 编排接线：定稿→执行→证据闸门控合并 + 退役旧 smoke]
    T1 --> T3
    T1 --> T5
    T2 --> T5
    T3 --> T5
    T4 --> T5
```

| Task | 拥有文件（互斥） | depends-on |
|---|---|---|
| T1 | `openagents/spec/schema.py`, `openagents/spec/model.py`, `openagents/spec/validate.py`, `openagents/spec/render.py`, `tests/test_spec_model.py`, `tests/test_spec_validate.py`, `tests/test_spec_render.py` | — |
| T2 | `openagents/executor.py`, `tests/test_executor.py` | — |
| T3 | `openagents/evidence_gate.py`, `tests/test_evidence_gate.py` | T1 |
| T4 | `openagents/reviewer.py`, `tests/test_reviewer.py` | — |
| T5 | `openagents/orchestrator.py`, `openagents/messages.py`, `openagents/e2e.py`, `tests/test_orchestrator.py`, `tests/test_messages.py`, `tests/test_e2e.py` | T1, T2, T3, T4 |

（T1/T2/T4 为并行叶子；T3 在 T1 之后；T5 收口所有。`e2e.py`/`test_e2e.py` 由 T5 删除退役。）

### 接口契约（角色仿 `reviewer.review` 的一次性 agent）

- `executor.run_executor(*, backend, work_dir, runbook_path, evidence_dir, pr_number) -> ExecutorResult`
  ——读 runbook（含形态）→ 按形态选工具真跑系统 → 把证据写进 `evidence_dir` → 返回结构化
  `{outcome: passed|failed, form, notes}`；契约上绝不抛错（异常映射成 `failed`，仿 `run_e2e_script`）。
- `evidence_gate.review_evidence(*, backend, work_dir, intent, evidence_dir, pr_number) -> EvidenceDecision`
  ——读 RFC 意图 + `evidence_dir` 证据 → 判 `{passed, feedback}`（`passed=False` 时 feedback 汇总
  「哪条验收行为没达成/避重就轻」，喂给 `iterate(reason="e2e")`）；结构镜像 `ReviewDecision`。
- `evidence_gate.evidence_dir_for(*, pr_number) -> Path`——`docs/e2e-results/<pr>/` 路径约定单一来源，
  orchestrator 计算后透传给 executor / gate（二者不互相 import，保持解耦，理念 10）。

## Drawbacks

- **merge 前多两个 agent 跑**（定稿 + executor + 证据闸），增加合并延迟与 token 成本；对纯文档/重构类
  PR 是净开销（缓解：RFC 闸只对「前端/交互类」强制粗规划，非交互 PR 的粗规划可为空 → 证据闸空过）。
- **executor 真跑系统可能不稳定**（起服务、装依赖、环境漂移）→ 假阴 FAIL 挡住本可合并的 PR；本组把
  重试并进现成 `rounds`/`MAX_ROUNDS`，攒满转 needs-human，不无限空转，但仍可能误挂。
- **证据文件进 repo**（`docs/e2e-results/<pr>/`）会随 PR 累积，截图（Phase 2）体积不小 → 仓库膨胀
  （Unresolved：是否定期清理/是否 `.gitignore` 大附件只留 `result.md`）。
- **runbook 由实现者定稿**仍有自证残余风险；靠 tautology guard 三道防线兜底，但证据闸判「避重就轻」
  本身依赖 reviewer agent 的判断力，非机械可证。

## Rationale and alternatives

**为什么这样设计。** 四个病灶同根于「没有独立主体在最终版本上真跑系统并接进合并判据」。把 e2e 从
implement 内的一次性 best-effort 上移到 **merge 前的门控段**，一举解决「测过期版本（此刻测的就是要合
的集成态）+ 没牙（FAIL 即 `iterate`/`_block`）+ 结果没人消费（证据闸就是消费者）」；把「跑脚本」换成
「独立 agent 照 runbook 真跑」解决「名不副实/自证」。复用现成 `iterate`/`_block`/`rounds`/`blocknote`
使状态机几乎不动（奥卡姆，理念 1）。

**备选 1：只给旧离线脚本加门控（把 `_post_e2e_result` 改成挡合并）。** 最小改动，但**没解决根**——脚本
仍是实现者自写的 hermetic 打桩（自证）、仍只在 implement 跑一次（过期版本）。加了牙也是咬在错的东西
上。否决。

**备选 2：不新增 executor 角色，让代码 reviewer 顺带读 e2e 结果评论。** 省一个角色，但**违反运动员≠
裁判**：reviewer 是静态读代码的，读一条实现者自己贴的评论不构成独立执行；且 reviewer `context=""`
的静态定位与「真起系统」是两种能力，硬塞进一个 agent 会两头不到岸。否决——executor（动态跑）与
reviewer（静态审）解耦更清晰（理念 10）。

**备选 3：引入外部 CI 服务（GitHub Actions）跑 e2e 并回读状态。** 成熟、隔离好，但**违反理念**（执行
应发生在 OpenAgents 派的 agent 里，不引入外部 CI 依赖），且外部 CI 难表达「按 runbook 形态选工具 +
证据对照 RFC 意图」这类语义。否决，记入 Prior art 作参照。

## Prior art

- **rust-lang/rfcs** 的 9 段 RFC 形态（本 spec 组的载体）：<https://github.com/rust-lang/rfcs>。
- **运维 runbook** 概念——把「怎么把系统跑起来验证」写成可照做的说明书，与本组③定稿说明书同源。
- **端到端测试框架**（Playwright / Cypress）把「导航→交互→断言→截图」作为行为验收标准动作，是 Phase 2
  `ui` 形态 executor 的工具面参照。
- **CI 门控**（GitHub Actions required checks）：把测试结果作为合并硬门——本组把这道门内化进 agent
  编排而非外部服务（见 Rationale 备选 3）。
- OpenAgents 内部前身：`spec 0008` PR 指路牌（告诉怎么测）、`spec 0013` implement 内实跑贴条（本组取代
  它）、`spec 0030` 把 browser-e2e rubric 落进 reviewer（本组把该 rubric 上移到 RFC 闸）——均为线索，
  关键内容已在 Motivation/Reference-level 就地复述。

## Unresolved questions

- **runbook 落点**：定稿说明书放 `docs/e2e-results/<pr>/runbook.md`（进 repo、可 diff）还是 PR 评论
  （轻、不污染 repo）？本组倾向文件（durable、给证据闸和人读）——待用户拍板。
- **证据附件膨胀**：`docs/e2e-results/<pr>/` 的 `*.png`/`*.log` 是否定期清理 / 只保留合并 PR 的 / 大附件
  改走 `.gitignore` 只留 `result.md`？
- **回合预算是否独立**：证据闸 FAIL 复用代码闸 `rounds`（共用一份 K）是否够用，还是需要独立
  `e2e_rounds` 计数（避免代码闸耗掉的回合挤占 e2e 重试预算）？MVP 先复用，视实测再拆。
- **`signpost.script_path_for_group` 去留**：`_post_e2e_result` 退役后它失去唯一调用方——是随
  `e2e.py` 一并清理，还是保留让 executor 的 `cli` 形态可选地跑 spec 声明的 `scripts/*.sh` 离线 smoke？

## Future possibilities

- **Phase 2：加 `ui` 浏览器形态。** executor 接 browser MCP（Playwright / Chrome DevTools），支持真实
  前端 e2e（导航 / 交互 / 截图 / console·network 检查 / 断言）+ 截图证据。硬前置：权限开关
  `OPENAGENTS_PERMISSION_MODE=bypassPermissions`（见 issue #85）成为 `ui` 形态 PR 的门槛；且需仓库
  真有前端可验。
- **`api` 形态富化**：executor 直接对起好的服务发 HTTP 断言（状态码 / body / 时序），补齐无头行为验收。
- **证据看板**：把 `docs/e2e-results/<pr>/` 的结构化证据渲染进前端看板，让人「面向成果」审阅
  （理念 8）——与 Phase 2 前端天然合流。
- **runbook 自动生成**：从 spec 粗规划 + 代码 diff 让 agent 起草 runbook 初稿，实现者仅校订，降低③的
  人力。

