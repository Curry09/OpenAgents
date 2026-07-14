---
number: "0065"
title: 图驱动的并行守夜：LLM 排依赖边（落 GitHub 原生 dependencies）+ vigil level-triggered reconcile 并行跑前沿
issue: 150
slug: issue-graph-parallel-vigil
summary: 把守夜从「每轮全量扫、串行做一个 issue」重构为两面。准入面（agentic）：新 issue 过三态门控、审过打 ready label 作准入令牌，再由 LLM curator 排出彼此的依赖关系，边写进 GitHub 原生 issue dependencies（blocked_by，2025-08 GA）。执行面（机械）：level-triggered reconcile——生产者每 tick 对每个 subject 读一次 GitHub 现态，纯函数给出四值判定（IN_FLIGHT / TERMINAL / QUIET / ACTIONABLE），只有 ACTIONABLE 入队；K 个常驻 worker 各原子领一个 subject，跑一张 reconcile 分支表（人有新话 → 依赖未满足 → 无 PR → 冲突 → CI → e2e → review → merge，顺序即硬依赖）推到卡在外部为止。状态量的落处按「决定 vs 事实」切开：**我们做的决定打 label**（ready 准入 / needs-human 终态 / review 裁决——裁决绑 commit，故 label 名里必须带 head sha：`review-approved:<sha7>`，否则审完再 push 会合并没人审过的代码），**GitHub 自己的事实读原生**（CI / mergeable，本就绑 sha，复制成 label 就是造第二份真相要对账）。agent 干不动时的**正常收口是它自己打 needs-human + 留理由**（一等出口，当场 TERMINAL、轮询停止、零多余 LLM 调用）。刻意不做变更检测（边沿会丢，见 k8s level-triggered 原则），代价是三种 **agent 自己看不见**的死法要护栏：它没意识到自己在空转（不会主动叫人，且每轮留的评论还会刷新时间戳让看门狗不响）→ 收工时盖 attempt 指纹戳（存 GitHub 评论；**戳本身不能改 fp**，故 facts 不含 comment id，否则护栏自毁成死循环）；状态该动却不动（agent 压根没被叫起）→ 看门狗（age 从 GitHub 时间戳算，零本地记忆）。认领落 SQLite 单表（队列 + 归属 + 崩溃计数，一 subject 一行 UNIQUE），存活证明落 fcntl.flock：抢得到锁 ⇒ 内核已回收持有者的锁 ⇒ 它确已死，故不用租约、不猜死亡，双跑是结构性的零而非小概率。SQLite 与 flock 同把部署钉在单机，多机替换点收在 4 个 claim 函数里。承 0062–0064 收敛弧线：两面控制流全内联进 recipes.vigil 的内部函数、不新开模块，旧串行实现直接删除（git history 即回退点，不留死代码副本），recipes 守恒为 3（stages / backfill / vigil）。新增文件：agents/curator.py（排依赖的零逻辑 Template）、agents/admitter.py（三态门控 human 态准入对话的 **fail-closed 人闸**：判「人到底点头没有」——拿 fail-open 的 triager 顶这个位子，人明说「先别做」也会被判可派单，人闸当场退化成一台偏向「是」的 agent 闸；且这道闸必须**认人**（只认 OWNER/MEMBER/COLLABORATOR 的话）并在叫 agent 前先盖 try 戳，否则闸门 fail-closed 而钥匙挂在门外、agent 一判崩就每 tick 重烧一次 LLM）、utils/proc.py（按线程的 PID 认领桶 + kill_tree + flock fd 继承登记，供硬超时精确杀本次调用起的进程树）、离线 e2e 脚本；utils/github.py 补读侧函数（pr_snapshot / check_snapshot / list_blocked_by / add_blocked_by / pr_for_branch）。
tasks:
  - id: T1
    title: graph-curator agent（零逻辑 Template：issue 快照 + 已有边锚点 → 建议 blocked_by 边）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/curator.py
      - openagents/agents/admitter.py
      - tests/test_agent_curator.py
      - tests/test_agent_admitter.py
    scope: 新增 agents.curator（agents/ 层唯一新增文件，承零逻辑 Template 约定）：吃 ready open issue 快照 + 当前已有依赖边（锚点），经 engine.run_agent 出建议的 blocked_by 边集（每条 {issue, blocked_by:[...], rationale}）。控制流不在此层，agent 只出结构化语义判断，不做调度、不落边。
    acceptance: pytest tests/test_agent_curator.py 通过：prompt 组入 issue 快照与已有边锚点占位符；输出 schema 顶层校验 edges 为 list（`engine._validate` 只做顶层键→类型，承既有极简 schema 约定）；每条边的 `blocked_by` 在**消费处**（T2 `_proposed_edges`）校验，`rationale` 为**给人审计的旁注、不入机器闸**（无处读它，按奥卡姆不为它加校验机关）；已有边原样带入 prompt 作锚点。不触真实 LLM。
  - id: T2
    title: vigil 原地重写为 level-triggered reconcile（感知三纯函数 + SQLite 认领队列 + flock 存活证明 + 分支表）；CLI 改指
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - openagents/recipes/stages.py
      - openagents/runtime/context.py
      - openagents/runtime/state.py
      - openagents/backends/claude_code.py
      - openagents/cli.py
      - openagents/utils/github.py
      - openagents/utils/proc.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil_queue.py
      - tests/test_recipe_vigil_admit.py
      - tests/conftest.py
      - tests/test_runtime_context.py
      - tests/test_github.py
      - tests/test_utils_github_vigil.py
      - tests/test_utils_proc.py
      - tests/test_backend_claude_code.py
      - tests/test_cli.py
      - scripts/e2e-spec-0065-graph-parallel-vigil.sh
    scope: 把 recipes.vigil 原地重写为唯一 vigil recipe，两面控制流全内联为其内部 `_` 函数（不新开 graph/scheduler/intake 模块）。五块：①感知三纯函数——`_sense`（每 subject 一次 GitHub 读 → 不可变 `_Observed{facts, clock}`，唯一副作用）/ `_classify`（纯函数，吃 facts + in_flight → 四值 `_Verdict`；**`_reconcile` 调用时 in_flight 恒传 False**，否则每个 worker 领到活就判「有人在干」并空转）/ `_fingerprint`（纯函数，只吃 facts → 哈希；字段集恒等于 facts 全集，clock 与 in_flight 都不进；**facts 不含 comment id**——盖 attempt 戳是一条新评论，id 进 fp 会让戳当场作废 → 无限重叫 agent），详见正文 §3–§4。状态量按「决定 vs 事实」落处：决定打 label（`ready` / `needs-human` / `review-approved:<sha7>`、`review-changes-requested:<sha7>`——**裁决绑 commit，sha 必须进 label 名**，否则审后再 push 会合并未审代码），事实读原生（CI / mergeable，不复制成 label）。agent 在每个 `_act` 分支都有**一等出口 `needs-human`**（自己打 label + 留理由 → 当场 TERMINAL），此契约须写进各分支 agent 提示词。②SQLite 队列——`.openagents/vigil-queue.db` 单表 `work_queue`，一行一个 subject（`subject` 列 UNIQUE，去重+同-subject 互斥+幂等三合一），无 lease 列，详见 §5。③认领与回收——`_claim_next` 用 `BEGIN IMMEDIATE` + `UPDATE…RETURNING` 原子领队首，并在 COMMIT 前对 `claims/{subject}.lock` 取 `flock(LOCK_EX|LOCK_NB)`、持 fd 到收工；`_reclaim_dead` 凭抢锁判死（无任何阈值参数），抢到即回收、EWOULDBLOCK 即永不回收；收工必须先删行后 close(fd)，详见 §6/§6.1。④生产者/消费者——`run_vigil` 起 K 个常驻 worker + 主线程 tick 循环；`_producer_tick` = `_reclaim_dead` → `_intake`（三态准入 + 调 curator + 落 blocked_by 边）→ 每 subject `_sense`/`_classify`/`_fingerprint` → 按四值分流（ACTIONABLE 且无同 fp 戳才 `_enqueue`）；`_worker_loop` 领到后 `_reconcile` 跑分支表推到卡住，详见 §7/§9。⑤护栏——`_act` 单次 agent 调用硬超时（超时杀子进程，持有者自己 `_requeue_or_park` 释放行与锁，claimed 行永不成孤儿）+ IN_FLIGHT 看门狗（超龄只 `_park` 打 needs-human，绝不动行）+ `attempts` 上限。同时吸收旧 vigil 串行能力（claim / route 三态 / discover / 合并流水线 / run_fleet）至串行 parity，K=1 退化串行；旧串行实现直接删除（git history 即回退点），cli.py 指 recipes.vigil；recipes 守恒为 3。附离线 e2e 脚本。实现期两处补充（均为 `_sense` 的读侧 utils，不改架构）：utils/github.py 增 `pr_snapshot`（含 `head_pushed_at`——「刚推上去、零 check、零评论」的 PR 除它之外无任何时间戳，缺了看门狗永不响）/ `check_snapshot`（带 count，零 check ≠ 绿）/ `list_blocked_by` + `add_blocked_by`（原生依赖）/ **`pr_for_branch`（不限状态查 PR——`find_pr_by_branch` 只查 open，PR 一合并就消失，会让守夜在合并后的下一圈把 issue 读成「还没有 PR」→ 分支④再开一个 PR 重做一遍）**；新增 utils/proc.py（**按线程的 PID 认领桶** `track`/`publish`/`untrack` + `kill_tree` 杀整棵进程树，供 `_act` 硬超时**精确**杀掉本次调用起的进程树——backend 起 Popen 后自报 PID，超时方按桶杀；若改用「diff 本进程的子进程集合去猜」，会认错并发的 gh/git 或别的 worker 的 agent，杀错人 = 真挂住的那个 agent 还在推，双跑就此发生。recipes 层不许直调 subprocess，Spec-0064 分层锚点）。
    acceptance: pytest tests/test_recipe_vigil.py + tests/test_cli.py 通过。生命周期：once 走 `_drain_queue` 排空 / interval / 单轮错误隔离不杀生产者 / 单 subject 异常不杀 worker / KeyboardInterrupt 经 stop_event 收池 / K=1 串行与 K=2 并行同 GitHub 末态 / 前沿空或全在飞 → hang 提示。队列：`_claim_next` 原子领取 exactly-once 不双跑 / `subject UNIQUE` + `INSERT OR IGNORE` 幂等不重复入队 / `_mark_done` 是 DELETE。存活探测（零双跑，本 spec 的核心断言）：持有者进程活着 → `_reclaim_dead` 试抢锁得 EWOULDBLOCK → 行原样不动（哪怕 claimed_at 已超 IN_FLIGHT 告警阈值也只 `_park` 打 needs-human、不回收，断言行仍 claimed 且 worker 未变）；持有者进程已死（子进程 kill -9 后其 flock 由内核释放）→ `_reclaim_dead` 抢到锁 → 行立刻回 queued 可被重领（不等任何超时）；同进程两个 fd 对同一 lock 文件互斥（钉死「必须 flock 不能 lockf」，用 lockf 该断言会失败）；`_mark_done` / `_requeue_or_park` 先删行后 close(fd)；`_reconcile` 全程持锁不释放。卡死：`_act` 超 `_AGENT_TIMEOUT_SECONDS` → 杀子进程 + 抛出 → 持有者自己 `_requeue_or_park`（行不成孤儿）；`_requeue_or_park` 到 `_MAX_ATTEMPTS` → needs-human。感知：`_classify` 四值逐分支；`_classify(in_flight=True)` → IN_FLIGHT 先于一切分支（含 needs-human），而 `_reconcile` 内部**恒以 in_flight=False 调用**（断言：一个 claimed 行的持有者跑 `_reconcile` 时不会立刻返回，即 worker 不空转）；`_fingerprint` 字段集 == `dataclasses.fields(_Facts)` 全集，且不含 clock、不含 in_flight、**不含 comment id**（断言：只追加一条我方评论 → fp 不变；`_post_attempt_stamp` 前后 `_fingerprint` 相等——这条直接钉死护栏一不自毁）；fp 相同的 attempt 戳存在 → 不入队（防无限重叫 agent），fp 变化 → 重新入队；QUIET 各 reason 的 `_watchdog` 阈值到点 → `_park`。收口：agent 在任一 `_act` 分支打 `needs-human` → 下一圈 `_classify` 即 TERMINAL（断言零后续 agent 调用、不入队、不等任何阈值）。label 语义：`review-approved:<sha7>` 的 sha == 当前 head → 分支⑪ merge；head 前移后同一 label 的 sha ≠ 当前 head → **降回分支⑩ review-or-fix（断言绝不 merge）**；裸 `review-approved`（无 sha）不被承认。分支表：mergeable UNKNOWN 不得读 CI；CI 只看当前 head_sha；route 三态；merge 打回回环。e2e：bash scripts/e2e-spec-0065-graph-parallel-vigil.sh 绿——**反复调 run_vigil(once=True)，一次一个 tick**（单趟覆盖不了跨轮解锁）：喂 A / B（blocked_by A）/ C，curator 排出 A←B 边且 C 独立，K=2 一 tick 并起 A 和 C、B 被 QUIET(awaiting-blockers) 挡，A 的 PR merged 后下一 tick B 就绪；再断言主路径与两条护栏：「CI 红 → agent 判上游 flaky → **自己打 needs-human + 留理由** → 当场 TERMINAL、零多余 LLM 调用」（主路径）、「CI 红 → agent 以为自己修了但零变更、**未打 needs-human** → 盖 fp 戳 → 下一 tick 不重叫 agent → age 超阈值 → needs-human」（护栏一，证明 agent 主动叫人**替代不了**它）、「CI 永不启动 → QUIET(awaiting-ci) 超时 → needs-human」（护栏二）。
---

# 0065 · 图驱动的并行守夜

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

### 一句话

守夜现在是**串行、无依赖概念、无准入**的循环：每轮顺序做三次全量扫，一次只推一个 issue。本 spec 把它改成 **先让 LLM 排出 issue 之间的依赖图，再按图并行跑**——一并闭合 issue #137（并行求解）与 issue #150（跨 issue 依赖调度）。

### 拆成两个面

| | 准入面 | 执行面 |
|---|---|---|
| **性质** | agentic（LLM 出判断） | 机械（纯函数出判断） |
| **管什么** | 哪些 issue 可以开工、谁挡着谁 | 每个 issue / PR 现在该做什么、谁来做 |
| **怎么做** | 三态门控审一遍 → 打 `ready` label → LLM curator 排依赖边 → 写进 GitHub 原生 `blocked_by` | level-triggered reconcile：读现态 → 四值判定 → 入队 → K 个 worker 各领一个推到卡住 |
| **真相存哪** | GitHub（边、label） | GitHub（流水线状态） + 一张 SQLite 队列表 |

依赖边的**结构**是 LLM 的判断产物，但**存储**是 GitHub 一等公民（`blocked_by`，2025-08 GA）。这条分工贯穿全文：**LLM 只出结构，事实和选择都是机械的。**

### 怎么读这篇

这篇有四层，按需停：

1. **只想知道改了什么** —— 读完上面这张表就够了。
2. **想知道为什么这么设计** —— 读 Motivation（三个缺陷 + 五条约束）和 Guide 的 §1–§2。
3. **想理解四个核心机制**（level-triggered / 四值判定 / 分支表 / 三道护栏）—— 读 Guide 全篇。这是理解本 spec 的主线。
4. **要动手实现** —— 读 Reference（数据结构、SQL、时序、走查表）。

一句话概括核心机制：**不记历史，每 tick 重问「现在该干什么」**（level-triggered，因为边沿会丢）。agent 干不动时的正常收口是**它自己打 `needs-human`**（一等出口，当场停止轮询）；代价是三种它**自己看不见**的死法需要护栏，而这三道护栏的记忆分别存在 **GitHub 评论**、**GitHub 时间戳**、**内核**里——本地只多一张队列表。

## Motivation

### 现状：旧串行守夜怎么跑

重写前的 `run_vigil`（已删除，见 git history）每轮顺序做三次**全量扫**：

1. `discover_and_dispatch` —— 列出所有 fresh issue，逐个分诊 + 派单；
2. 轮询评论 —— 遍历所有 open PR，有新 comment 就回；
3. 推进合并 —— 遍历所有在飞 run，各推合并流水线一步。

三趟扫完，`sleep(interval)`，再来一轮。

### 四个结构性缺陷

**缺陷一：串行，无并发。** 一轮里 issue 一个接一个做，多核 / 多 agent 的并行度完全没用上。这正是 issue #137「vigil --parallel：同仓库内多 issue 并行求解（worker 池 + 共享 .git 锁 + State 并发写）」要解的。

**缺陷二：无依赖概念。** 10 个 issue 之间常有「A 改完 B 才能动」的逻辑序——A 定义了接口 / 数据模型，B 才能用。现状把它们平铺成一个无序集合：既不能表达这种序，也不能据此调度。这正是 issue #150「跨 issue 调度：agent 语义排依赖 → blocked-by + DAG」要解的。

**缺陷三：无准入，无优先级。** 新 issue 未经审查直接进派单流；三态分诊虽在，却没有「审过 → 准入 → 进待做集合」的显式边界；谁先做也没有任何机制。

**缺陷四（本版新增识别）：三趟扫是同一件事的三个分身。** 三趟扫看着是三件事，其实是同一个问题的三个切面——**「这个 subject 现在该做什么」**。证据是旧串行 vigil 的 `advance_merge`：它**已经是**一张 reconcile 分支表（终态短路 → 冲突 → CI → e2e → review → merge，每支各自 early-return）。缺的只是在它头上再接两支：「还没有 PR → 去 solve」和「最新评论是人发的 → 去回话」。

一旦看清这点，「事件类型」（solve / advance / reply）就是**冗余的**：它是 GitHub 现态的一份拷贝，而现态每 tick 都要重读。

### 为什么 #137 与 #150 必须一并交付

它们不是两件事，而是同一架构的两面，有严格的依赖顺序：

> **要并行，就必须先知道谁能并行**——只有互不依赖的 issue 才能同时跑。而「谁依赖谁」是**语义判断**，读得懂 issue 内容才排得准。

只做 #137 不做 #150，并行就是无序乱跑：A 还没定义接口，B 就动手了。只做 #150 不做 #137，排出图来也没人按图并行。

### 五条约束

后文所有设计决策都从这五条推出。读到后面任何一个「为什么不选更简单的方案」，答案基本都在这张表里。

| # | 约束 | 直接后果 |
|---|---|---|
| **C1** | 依赖关系是**语义判断**，机械手段（文件重叠分析）只能捕「文件冲突序」、捕不到「逻辑序」 | 排边必须由 LLM 做 → 新增 `agents/curator.py` |
| **C2** | 依赖边是**人机共写的可变真相**（人在 UI 手设，agent 走 API），须有并发 / 锁语义 | 边落 GitHub 原生 dependencies，本地不存第二份；curator 只能**受锚增量**补边、不能全量覆盖 |
| **C3** | 「谁领走了这个 subject」**GitHub 表达不了**——REST 对 POST/PUT/PATCH/DELETE 不支持条件请求（无 CAS），且 label POST 是追加语义（两个并发认领都成功、都不报错）；RuntimeState 是整文件 JSON 读改写（会丢更新，#137 明列的风险） | 认领的原子性必须落**事务型存储** → SQLite `work_queue` 表 |
| **C4** | **边沿会丢**（进程崩在「检测到」与「做完」之间），而漏一个边沿 = 一个 PR 永久停摆 | 谓词必须 **level-triggered**（无历史、只读现态）；变更检测只能是优化、不能是正确性来源 |
| **C5** | 上一批刚把 recipes 从 6 个模块收敛到 3 个；再为准入 / 调度 / 图各开一个模块、且新旧两套 vigil 长期并存，是逆着收敛弧线净增死代码（违背奥卡姆剃刀） | 两面控制流**全内联**进 `recipes.vigil` 的深函数；**原地重写**而非新开 `vigil2` |

### 为什么依赖边落 GitHub 原生 dependencies（C2 的展开）

GitHub 在 2025-08 把 issue 的 `blocked_by` / `blocking` 关系做成了一等公民：全 REST API + webhook + UI 侧栏，每类可挂 50 条，triage 权限即可创建。这一步把 issue #150 原设想里的两个 hack 一起消解：

- 「blocked-by 标签」的**自定义命名约定**——原生关系有专有命名空间，不与业务 label 混淆，也不必解析字符串；
- 「本地 DAG 拓扑图」的**独立持久化**——原生 `GET .../blocked_by` 直接返回 blocker 列表，且每个 blocker 自带 `state`，一次调用同时拿到「边」和「blocker 关没关」，本地无需落盘、无需对账。

## Guide-level explanation

### 0. 三个词

读下去只需要记住三个词：

- **subject** —— 调度的最小单元，一个字符串：`issue:5`（一个 issue 及其最终产出的 PR）或 `pr:12`（无 issue 归属的裸 PR）。**一个 subject 一行队列行。**
- **verdict** —— 对一个 subject 的四值判定：`IN_FLIGHT` / `TERMINAL` / `QUIET` / `ACTIONABLE`。只有 ACTIONABLE 才入队。
- **fp（指纹）** —— 当前 GitHub 现态的哈希。fp 不变 = 零进展。

### 1. 全景：一个 subject 的完整旅程

```
  新 issue 出现
      │
      │  ┌──────────── 准入面（agentic，生产者 tick 内调 _intake）────────────┐
      ▼  │                                                                    │
   三态门控 ── agent → triager 判 actionable ──┐                              │
      │   ── human → 评论里问人，admitter 判 ┤ 审过 → 打 ready label         │
      │            人点头了没（fail-closed） │                              │
      │   ── skip  → 直接准入 ────────────────┘   （准入令牌，落 GitHub）     │
      ▼                                                                       │
   curator（LLM）读「所有 ready issue 快照 + 已有边（锚点）」→ 建议 blocked_by │
      │                                                                       │
      ▼  validate（无环 + 引用真实 issue）→ 只为新节点 POST 边（已有边不动）  │
      └───────────────────────────────────────────────────────────────────────┘
      │
      ▼  ┌──────────── 执行面（机械，level-triggered reconcile）──────────────┐
         │                                                                    │
  生产者（主线程，每 tick，对每个 subject）      消费者（K 个常驻 worker）     │
  ──────────────────────────────────────         ───────────────────────────  │
  observed = _sense(subject)   ← 唯一 GitHub 读   while not stop:             │
  verdict  = _classify(observed.facts)  ← 纯函数    row = _claim_next()  ←原子│
  fp       = _fingerprint(observed.facts) ← 纯函数  if None: wait; continue   │
                                                     _reconcile(row.subject)   │
    IN_FLIGHT  → 略过（队列里有 claimed 行）        _mark_done / _requeue_or_park│
    TERMINAL   → 略过（merged/closed/needs-human）                             │
    QUIET      → 不入队；_watchdog(age > 阈值) → _park                        │
    ACTIONABLE → GitHub 上有 fp 相同的 attempt 戳？                            │
                   有 → 降级为 QUIET(awaiting-effect)                          │
                   无 → _enqueue(INSERT OR IGNORE) ──┐                        │
                                                     ▼                        │
                                        [SQLite work_queue 表]                 │
                                        一行 = 一个 subject（UNIQUE）           │
                                        priority + attempts                     │
                                        存活证明在 claims/{subject}.lock(flock) │
         └───────────────────────────────────────────────────────────────────┘
```

下面四节按「先决定什么、再决定什么」的顺序展开：**§2 决定「怎么感知」，§3 决定「谁该入队」，§4 决定「领到之后做什么」，§5 补上「会怎么静默地死，怎么防」。**

### 2. 第一层：只读现态，不做变更检测

一个自然但错误的直觉是「记住上一轮的 GitHub 状态，变了就叫 agent」。本 spec **不这么做**，因为边沿会丢：

> Kubernetes 的架构原则写得很直白——*"Functionality must be level-based, meaning the system must operate correctly given the desired state and the current/observed state, **regardless of how many intermediate state updates may have been missed**. Edge-triggered behavior must be just an optimization."*（[k8s design-proposals · principles.md](https://github.com/kubernetes/design-proposals-archive/blob/main/architecture/principles.md)）

守夜进程崩在「检测到 CI 变绿」和「真的去合并」之间，那个边沿就永久消失了——PR 会绿着躺到宇宙热寂。所以谓词**不问「变了没」，只问「现在该不该动手」**，每 tick 重算，丢一轮丢一百轮都能自愈（约束 C4）。

落到代码上，整个执行面的感知压在三个函数上，它们吃同一个不可变结构：

```
observed = _sense(subject)                # 唯一的副作用：读一次 GitHub
verdict  = _classify(observed.facts)      # 纯函数 → 四值判定
fp       = _fingerprint(observed.facts)   # 纯函数 → 哈希
```

`_Observed` 分两半，**这个划分是硬约束**：

- **`facts`** —— 分支表会读的每一个字段（head_sha / merged / closed / labels / mergeable_state / 当前 head 上的 CI / e2e 证据 / review 裁决 / 最新评论是不是人发的 / 依赖是否全 merged / pr_number）。**只有它进 `fp`。**
- **`clock`** —— 时间戳（head 推送时间、最新 check 的 `started_at`、最新评论时间、最新 attempt 戳时间）。**只被看门狗读，绝不进 `fp`。**

**不变式：`_fingerprint` 的字段集 ≡ `_classify` 的输入字段集 ≡ `facts`。** 两个方向都会咬人：

- **少一个字段 → 静默瞎掉。** 经典失手：`facts` 里忘了 `mergeable_state`——别人往 main 合了个 PR，base 前移，你的 PR 变冲突了：没有新评论、没有新 commit、CI 结果没变 → 什么都察觉不到 → PR 烂在那里。
- **`clock` 混进 `fp` → 护栏失效。** 一个 check run 开始跑会刷新 `started_at` → fp 变 → agent 被重新叫起，尽管分支表根本不关心这个字段。

让两者吃同一个结构，就在**结构上**堵住了漂移。

### 3. 第二层：四值判定，谁该入队

| verdict | 含义 | 生产者动作 | 看门狗 |
|---|---|---|---|
| **IN_FLIGHT** | 队列里有该 subject 的 `claimed` 行——**我的 agent 正在跑它** | 略过 | 只告警不回收（见 §5.3） |
| **TERMINAL** | `merged` / `closed` / 挂了 `needs-human` | 略过 | 不管 |
| **QUIET** | 现在没我的活，等状态自己变 | 不入队 | 按 reason 的阈值判 age |
| **ACTIONABLE** | 现在该动手 | `_enqueue`（`INSERT OR IGNORE`） | — |

**IN_FLIGHT 必须是第一道判定**，否则看门狗会把一个正在写代码的 agent（跑 8 分钟很正常）当成「状态 5 分钟没动」而打上 `needs-human`。

**QUIET 有四个 reason，它们的自然时长差两个数量级**，所以阈值必须按 reason 分档、可配：

| reason | 在等谁 | 建议默认阈值 | 超时后的机械诊断 |
|---|---|---|---|
| `awaiting-blockers` | 等上游 subject 被合并 | **默认关**（上游有自己的看门狗，重复计时只会误杀） | — |
| `awaiting-mergeability` | GitHub 后台异步算 merge ref | ~3 分钟 | 「GitHub 迟迟算不出 mergeable」 |
| `awaiting-ci` | CI runner（pending，或当前 head 上零个 check） | ~CI p95 × 3（每仓不同，必须可配） | 「head `abc123` 推送 43 分钟仍无 check：base 不是 main？Actions 被禁？workflow 未匹配？」 |
| `awaiting-effect` | agent 刚才那一下异步落地（或它根本没做） | ~5 分钟 | 「agent 已出手，`fp` 未变——它推不动，附上它自己的结论」 |

**阈值宁可给宽。** 设窄了会把正常在跑的 CI 误 park，比不看门更糟。而 park 的动作只是打个 label + 贴条诊断——完全可逆，人摘掉 label 系统立刻复活。

### 4. 第三层：reconcile 分支表，领到之后做什么

worker 领到一个 subject 后跑这张表。**它就是旧串行 vigil 的 `advance_merge` 在头尾各接了两支**（缺陷四）。

```
① merged / closed / needs-human ............... TERMINAL      ← agent 的一等出口，见下
② 最新评论是人发的（无我方签名）............... ACTIONABLE: reply     ← 人优先于流水线
③ 依赖未全关闭 ................................ QUIET(awaiting-blockers)
④ 还没有 PR ................................... ACTIONABLE: solve
⑤ mergeable_state = UNKNOWN / null ............ QUIET(awaiting-mergeability)
⑥ 冲突（mergeable_state = dirty）.............. ACTIONABLE: rebase     ← 必须在 CI 前
⑦ 当前 head 上 CI = pending / 零个 check ...... QUIET(awaiting-ci)
⑧ 当前 head 上 CI = failure ................... ACTIONABLE: fix-ci
⑨ e2e 证据缺失 / head_sha 陈旧 ................ ACTIONABLE: e2e
⑩ 无 review-* label / 其 sha ≠ 当前 head /
  review-changes-requested .................... ACTIONABLE: review-or-fix
⑪ 全绿 + review-approved:<当前 head 的 sha7> .. ACTIONABLE: merge
```

**每一支都有第二个出口：`needs-human`。** agent 在任一分支里判断「我没辙 / 这要人来定」——CI 是上游 flaky、需求本身有歧义、要动的东西超出授权、连试两次都推不动——它就**自己打 `needs-human` label + 留一条说明理由的评论**。下一圈 `_sense` 读到 → ① 判 TERMINAL → **轮询就此停止**。

这是**一等出口，不是兜底**：正常的「干不动」都该从这里走完。不烧一次多余的 LLM 调用，不等任何超时，理由直接写在 issue 上给人看。人摘掉 label，谓词自动重新活过来。§5 的三道护栏只兜 agent **自己看不见**的死法（它忘了打、判错了、没意识到自己在空转、崩了没机会打）——正常路径根本走不到它们。**这条契约必须写进每个分支的 agent 提示词**（`agents/*.py`），否则兜底会变成主路径。

**四处顺序是正确性依赖，不是风格：**

- **① 在最前** —— `needs-human` 一挂，任何分支都不许再动手。它是人接管的信号。
- **② 紧随其后** —— 人说「先别合，我有疑问」必须能抢在 merge 前面。合并不可逆。
- **⑤/⑥ 在 ⑦ 前** —— `mergeable_state = UNKNOWN` 不等于「没冲突」，它是 GitHub 还没算完。而**冲突的 PR 拿不到 merge ref，GitHub 压根不给它任何 check**（本仓已踩过）。若不先挡住，⑦ 会把「零个 check」读成「CI 还在跑」，然后 `awaiting-ci` 一直等到超时——症状是「CI 卡住了」，病因是「有冲突」。这条正是旧串行 vigil 那句「conflict 必须在 CI 前是硬依赖」，也是它的 `if gates.is_mergeable_unknown(...): return None`。
- **⑦/⑧ 只看当前 `head_sha`** —— 不是「这个 PR 最近一次 CI」。否则 agent 刚 push 完修复，GitHub 上还挂着旧 head 的红 → 谓词判「该修」→ 再派一个 agent 去修**已经修好的代码**。

**⑩/⑪ 的 review 裁决落 label，但 label 名里必须带 head sha。** 见 §4.5。

**推进到卡住为止，不是一 tick 推一步。** worker 循环 `_sense → _classify → 动作`，直到 verdict 不再是 ACTIONABLE（卡在外部 / agent 自己打了 needs-human / 到终点）或 fp 不再变（自己推不动）。于是一个全绿的 PR 在一次认领里就合掉，而不是烧掉三个 tick。

**worker 调 `_classify` 时 `in_flight` 恒传 `False`。** IN_FLIGHT 的含义是「**别人**的 agent 正在跑它」，而 worker 自己**就是**那个持有者。若据实传 True，它领到活的第一件事就是判定「这活有人在干」→ 立刻收工 → **每个 worker 都空转，系统一动不动**。`in_flight` 是生产者独有的概念。

### 4.5 label 记「决定」，原生字段记「事实」

分支表读的东西分两类，落处不同：

| | 谁产生的 | 落哪 | 为什么 |
|---|---|---|---|
| **决定** —— `ready`（准入）/ `needs-human`（人接手）/ review 裁决 | 我们（agent 或人） | **GitHub label** | GitHub 没有别的地方表达它们；且 label 在 UI 上一眼可见、人可手动增删（自愈的入口） |
| **事实** —— CI 结果 / `mergeable_state` / `merged` / `blocked_by` | GitHub 自己 | **读原生字段** | 它们**本就绑在 sha 上、一次读到**。再复制一份成 label 就是造第二份真相，然后要负责让两份不打架——CI 重跑了谁去改 label？漏改一次就是一个静默的错判 |

**review 裁决落 label 时，必须把 head sha 带进 label 名**：`review-approved:abc1234` / `review-changes-requested:abc1234`。

裁决不是一个恒真的属性，而是**绑在某个 commit 上的判断**。若打成光秃秃的 `review-approved`：审的时候 head 是 `abc1234`，审完 agent 又 push 了 `def5678` 去修 CI——**label 还挂在那儿**，⑪ 一看「全绿 + 审过了」→ 直接合并。**合的是一份没人审过的代码，而合并不可逆。**

带上 sha 之后，head 一动 label 就对不上当前 head → 裁决自动作废 → 落回 ⑩ 重审。这正是 GitHub 原生 PR review（天生绑 `commit_id`）白送的性质，我们用 label 复刻它，顺带换来「人在 UI 上一眼看见现在审到哪个 commit 了」。

### 5. 第四层：主路径是 agent 自己叫人，护栏只兜它看不见的死法

**先说主路径。** agent 干不动时的正常收口，是它**自己打 `needs-human` + 留一条说明理由的评论**（§4 分支表的第二出口）。轮询当场停止，不烧多余的 LLM 调用，不等任何超时，理由直接写在 issue 上给人看。**这条路能覆盖绝大多数「干不动」。**

**护栏兜的是 agent 自己看不见的死法。** 剩下的洞有一个共同点——**在日志里跟「一切正常」长得一模一样**，而且 agent 处在其中时**不知道自己处在其中**，所以指望它主动叫人是不行的：

| 死法 | 为什么 agent 自己叫不了人 | 护栏 | 记忆存哪 | 要计数吗 |
|---|---|---|---|---|
| agent **没意识到**自己在空转 | 它以为自己干了活 | attempt 指纹戳（§5.1） | GitHub 评论 | 否（一个 bit） |
| 状态该动却不动（CI 永不启动） | agent 压根没被叫起 | 看门狗（§5.2） | GitHub 时间戳 | 否 |
| 持有者进程死了 | 死人不说话 | flock 抢锁判死（§5.3） | 内核 | 否 |
| 持有者活着但卡死 | 它挂在一个不返回的调用上 | `_act` 硬超时 + IN_FLIGHT 告警（§5.3） | 进程内 / `claimed_at` | 否 |
| agent 反复崩（无痕） | 同上，且不留痕迹 | `attempts` 上限（§5.4） | SQLite | **是** |

**主路径与所有护栏是同一个收尾**：`needs-human` → TERMINAL → 轮询停止。人摘掉 label，谓词自动重新活过来。**这是 level-triggered 白送的自愈。** 区别只在**谁**打的这个 label——agent 自己（快、准、便宜、理由是它写的），还是护栏（慢、只能给机械诊断，但兜住了它看不见的地方）。

#### 5.1 护栏一：fp 相同的 attempt 戳 → 别再叫 agent

**这道护栏不是给「知道自己没辙的 agent」准备的**——那种 agent 会自己打 `needs-human`，根本走不到这儿。它防的是**没意识到自己在空转**的 agent：

它 rerun 了 CI 但没触发成功；它改了个无关文件然后 commit 空了；它读了一圈日志，发了条「我分析了一下，等 CI 重跑就好」的评论，然后心满意足地收工。**它不觉得自己没辙，所以不会打 `needs-human`。** 而它每轮留的那条评论还会**刷新 GitHub 上的最后活动时间戳，让看门狗（§5.2）永远不响**。

于是：GitHub 上零实质推进 → 下一轮谓词还说 ACTIONABLE → 又叫一个 agent → 它又做一遍同样的分析、又留一条评论 → **无限循环，日志里看起来还特别忙。** 除了机械地比对状态，没有任何东西拦得住它。

`fp` 没变，含义是「我出手之后，分支表关心的每一个字段都没动」——**即零进展，agent 怎么说的不算数**。任何真实推进都必然改 `fp`（push 改 head_sha、rerun 改 CI、审完打 `review-*:<sha7>` 改 labels、上游合并改 deps_done）。所以 fp 没变 = agent 撞墙了（不管它自己知不知道），再叫一次只是在同一堵墙上再撞一次。

worker 在这个出口盖一条签名评论：

```html
<!-- openagents:attempt fp=9f2a1c… -->
本轮结论：`test_upload_timeout` 为 flaky（近 20 次 CI 中随机失败 4 次，均为超时，与本 PR 改动无关）。
未做任何代码变更。
```

生产者见到 fp 相同的戳 → 把 ACTIONABLE 降级成 `QUIET(awaiting-effect)`，不入队。**有 / 没有，一个 bit，不需要计数**——同证据同 prompt 再叫一次，期望收益接近零。

> **盖戳这个动作本身绝不能改 fp——否则这道护栏会自毁成它要防的那个死循环。**
>
> 戳是一条**新评论**。若 fp 的输入里含「最新评论的 ID」，那么留完戳的那一瞬间 fp 就变了（9f2a → 7b31）。生产者下一 tick 算出 7b31，去找 7b31 的戳——没有，只有 9f2a 的 → 判「全新情况」→ 重新入队 → 又叫 agent → 又撞墙 → 又盖一条新戳（又是新 fp）……**无限重叫 LLM，正是这道护栏要防的那件事。**
>
> 故 `facts` 里**只留 `latest_comment_is_ours` 这个布尔，不存 comment id**（§Reference·3）。这样一个信号都不丢：分支② 只需要「最新一条是不是人发的」，人再留言时 `is_ours` 会从 True 翻回 False，fp 照样变。
>
> 推而广之——`fp` 的规则是「**任何真实推进都必然改 fp**」，但**反向不成立**：存在改了 fp 却没推进的动作。给 `facts` 加任何新字段前先问一句：**worker 收工时会不会顺手改到它？** 会的话，护栏一当场失效。

而 `awaiting-effect` 有阈值（而非立即 park）**不是为了给模型第二次抽卡机会**，是为了吸收**异步生效窗口**：agent push 完但 GitHub API 还返回旧 head（最终一致性）、agent 触发了 CI rerun 但 check 还没翻成 pending——这些情况下 fp 会短暂地「看起来没变」。给几分钟宽限，真进展会落地、fp 会变、戳自动作废；真撞墙则超时 park。

#### 5.2 护栏二：QUIET 超龄 → 叫人

症状：CI 永不启动（workflow 没匹配 / base 不是 main / Actions 被禁）→ 谁都不叫 agent → PR 静默烂掉，日志里跟「正常等 CI」长得一样。

「什么都没变」本身就可能是故障。而**判断「卡了多久」不需要记住上一轮**——GitHub 每个对象都自带时间戳：

```
age = now − max(head 推送时间, 最新 check 的 started_at, 最新评论时间, 最新 attempt 戳时间)
```

head 一变，计时自动归零。**零本地记忆**——重启、丢库、换机器都不影响。超阈值 → `_park`（打 `needs-human` + 贴机械诊断）。

#### 5.3 护栏三：认领的回收——观测死亡，不猜死亡

一个 `claimed` 行何时可以被别人抢回来？

**直觉答案是租约**（SQS 式可见性超时：claimed 超 T 秒未收工 → 视为死了 → 回 `queued`）。本 spec **不用租约**，因为租约是**从沉默里猜死亡**——它天然区分不了「进程死了」和「agent 正在写一个大 feature 写了 40 分钟」：

- 阈值设窄 → 误判活着的 worker 已死 → 回收它的行 → 第二个 agent 在同一个 PR 上跑起来 = **双跑**；
- 阈值设宽（v0 提的 1 小时）→ 真崩了的 subject **静默停摆一小时**。

任何基于超时的探活都只能在这两种错法之间选一个，**双跑概率永远非零**。

**但在单机拓扑下（§12 已把 SQLite 钉死在单机），死亡不需要猜——内核知道确切答案。** 认领时，worker 对 `.openagents/claims/{subject}.lock` 取一把 `fcntl.flock(LOCK_EX | LOCK_NB)`，持有到收工为止。flock 绑在**打开文件描述**上，**进程一死内核自动释放**——`kill -9`、OOM、段错误、机器断电重启，全都算。于是回收判据变成一次无阻塞抢锁：

| 抢 `flock` | 内核在说什么 | `_reclaim_dead` 的动作 |
|---|---|---|
| **成功** | 前任持有者**已经不在了**（进程没了，锁被内核回收） | **立刻**把行打回 `queued`——不等任何超时 |
| **`EWOULDBLOCK`** | 前任**还活着**，正持着锁 | **永不回收**——不管它跑了多久 |

两个方向都是事实，不是猜测。**零误杀 ⇒ 零双跑**（活着的 owner 的行永远不会被抢走）；**零漏杀 ⇒ 崩溃恢复从「最多等一小时」变成「下一 tick 立刻」**。

**为什么是 flock，不是 PID 探测。** PID 探测（`os.kill(pid, 0)`）看着更直白，但 PID 会被**复用**——重启后新进程恰好拿到旧 PID，会被误读成「前任还活着」，那个 subject 永久卡死。要防住就得额外存进程创建时间（`psutil.Process(pid).create_time()`），为补一个 flock 根本没有的洞而引入第三方依赖。`fcntl` 是 stdlib，且锁的生命周期由内核管理。

**必须是 flock，不能是 `fcntl.lockf`（POSIX `F_SETLK`）。** 后者的锁是 **per-process** 的：同一进程内两个 fd 对同一文件加锁**不互斥**。本 spec 是「一个进程 K 条 worker 线程」，用 `lockf` 会让同进程的互斥**静默失效**。flock 的锁绑在 open file description 上，同进程不同 `open()` 之间照样冲突——这正是我们要的。

**「活着但卡死」是另一件事，用另一道闸。** flock 只回答**存在**（进程还在不在）。进程活着但 agent 卡死（挂在一个没有超时的网络调用上），锁一直被持有 → 该 subject 停摆。这不是双跑问题，是 hang 问题，且**不能用回收来解**（回收一个活着的持有者的行，定义上就是双跑）。两道：

1. **`_act` 对每次 agent 调用加硬墙钟上限**（`_AGENT_TIMEOUT_SECONDS`，默认 30 分钟）——超时即杀掉 agent 子进程并抛出，worker **自己**走 `_requeue_or_park` 释放行与锁。`claimed` 行永远由它的持有者释放，绝不会变成孤儿。
2. **IN_FLIGHT 看门狗**（`_INFLIGHT_ALARM_SECONDS`，默认 2 小时）——`claimed` 行的 `claimed_at` 超龄 → `_park`（打 `needs-human` + 诊断）。注意它**只告警、绝不回收行**。

这条不对称——**只有死者的行可被回收，活人的行只能由它自己或人来处置**——是零双跑的最后一根柱子。三条合起来：**双跑是结构性的零，不是「阈值调好了概率就很小」。**

#### 5.4 护栏四（唯一需要计数的）：`attempts`

agent 崩了 / 被 kill → 它**没盖戳**（没收工）→ GitHub 上零痕迹，也没刷新任何时间戳 → fp 判不出来，age 也判不出来 → flock 被内核释放 → `_reclaim_dead` 把行打回 `queued` → 又领走 → 又崩 → 无限重领，而且日志外什么都看不到。

**这是唯一必须计数的死法**，由队列行的 `attempts` 列兜（领取时 +1，到 `_MAX_ATTEMPTS` 即 park）。

### 6. 存储职责：各存各的，无重叠、无对账

| 存储 | 存什么 | 丢了会怎样 |
|---|---|---|
| **GitHub label**（我们做的**决定**） | 准入（`ready`）+ 终态（`needs-human`）+ review 裁决（`review-approved:<sha7>`） | 丢不了——它是真相。人可手改，即自愈入口 |
| **GitHub 原生字段**（它自己的**事实**） | 依赖结构（`blocked_by`）+ 流水线状态（checks / mergeable / merged）+ e2e 证据评论 + **已出手过的状态**（attempt 戳） | 丢不了——它是真相 |
| **SQLite `work_queue`** | 队列 + 认领归属 + 崩溃计数 | 无害：一 tick 从 GitHub 重建（`queued` 行），`claimed` 行由 `_reclaim_dead` 凭 flock 回收 |
| **`claims/{subject}.lock`（flock）** | 持有者的存活证明（内核持有，进程一死自动释放） | 无害：文件本身无状态，锁只在进程活着时存在 |

**决定与事实的分界**（§4.5）：CI 结果 / `mergeable_state` 是 GitHub 自己维护的、绑在 sha 上的事实，**不复制成 label**——复制就是造第二份真相，然后要负责让两份不打架。而 review 裁决是我们做的决定、GitHub 没有别的地方表达它，故落 label，且**必须把 head sha 带进 label 名**，否则 head 一动裁决不作废 → 合并没人审过的代码。

**队列不是 GitHub 的第二份真相。** 它只存 GitHub 表达不了的三样：谁原子地领走了这个 subject（C3：无 CAS，label POST 是追加语义）、领了几次没收工（崩溃在 GitHub 上零痕迹）、领取时的定序。

### 7. 并发单元是 subject

- **同 subject 串行** —— `subject` 列 UNIQUE：一个 subject 在队列里最多一行，被领走后 `INSERT OR IGNORE` 是 no-op。**同一个 PR 上永远只有一个 agent。**
- **跨 subject 并行** —— 受 K 个 worker 这个 bounded pool 限。
- **串行 = K=1 的退化** —— `oa vigil` 默认 K=1，行为等价今天；`oa vigil --parallel K` 把池开到 K。

### 8. 用户视角与类比

人只在两处参与：issue 分诊为 `human` 态时经评论对话确认；或直接在 GitHub UI 上手设 / 改依赖（agent 尊重为锚点、不覆盖）。其余无人值守——直到某个护栏打出 `needs-human`。

执行面像 `make -j K`——依赖图决定能不能开工，`-j K` 决定同时开几个。更贴切的对标是 **Kubernetes 控制器**：`reconcile → workqueue → N workers`。这不是我们外加的结构，是这类系统的本来形状。

## Reference-level explanation

### 1. 存储职责（Guide §6 的展开）

| 存储 | 角色 | 谁写 |
|---|---|---|
| **GitHub** | 依赖结构 + 决定（label：准入 / 终态 / review 裁决）+ 事实（checks / mergeable，读原生不复制）+ attempt 戳 | 准入面（打 `ready`、POST 边）；worker（推流水线、打 `review-*:<sha7>`、判没辙时打 `needs-human`、盖戳）；生产者（护栏超时时 `_park` 打 `needs-human`）；人（UI 手设边、摘 label） |
| **SQLite `work_queue`**（`work_dir/.openagents/vigil-queue.db`） | 队列 + 认领归属 + 崩溃计数 | 生产者（`_enqueue` / `_reclaim_dead`）+ 各 worker（`_claim_next` / `_mark_done` / `_requeue_or_park`） |

三条推论：

- **事实**（PR 是否 merged、CI 是否绿）机械地从 GitHub 读，**不进** LLM；
- **选择**（下一个跑谁）是 SQLite `ORDER BY priority` 的机械领取，**不是** LLM；
- 只有**结构**（谁依赖谁）是 LLM 的判断。

**为什么 LLM 不能当路由器。** 分支表的每一个谓词都是从 GitHub 读到的布尔 / 枚举——让 LLM 来判，是拿不确定性换零收益，还引入一个致命失败模式：在一个红着的 PR 上幻觉出「全绿 → 合并」。**合并不可逆。**

### 2. 准入面：从新 issue 到一条 GitHub 边

`_intake`（在生产者 tick 内调用）对每个「无 `ready` label 的新 issue」（可攒一批）：

1. **三态门控** —— `skip` 直接准入；`agent` 派 `triager` 判 actionable，过则准入；`human` **在 issue 评论里跟人对话确认**（`_ask_human`），一场跨 tick 的对话，三个状态全从 GitHub 现态推出（零本地记忆）：

   - **没问过**（评论流里无 `_ADMIT_ASK_MARK`）→ 发一条**签名**提问评论，**零 LLM**。
   - **问过、维护者还没回话** → 什么都不做，**零 LLM**。（准入面每 tick 都会重新扫到它——它既没 `ready` 也没 `needs-human`——若每轮叫一次 agent，一个等人回话的 issue 就是台按 tick 计费的印钞机。）
   - **维护者回话了** → 先盖一枚 **try 戳**（`_ADMIT_TRY_MARK` + 人那句话的 comment id，**这一步就是 LLM 的准入券**）→ 再派 **`admitter`**（`stages.admit`）读对话判「人点头没有」→ 裁决**盖成一条签名评论**（`gh` 抖动导致 label 没打上时，下一 tick 读回这条戳直接重试，零 LLM）→ 点头打 `ready`，否则挂 `needs-human` + 附理由。
   - **上一轮判崩了**（有 try 戳、无裁决戳）→ **零 LLM** 转人工。

   **判「人点头没有」必须是一个 fail-CLOSED 的专用 agent，不能复用 triager**：triager 判的是另一个问题（issue 正文自不自洽），且纪律是 fail-open（拿不准就派单）——人明说「先别做，这个方向我还没想清楚」不属于它那五类矛盾中的任何一类，它会照判 `actionable=true`，于是这道**人闸**当场退化成一台偏向「是」的 agent 闸，**在人明确否决之下把活派出去**。admitter 的默认值取反：看不懂、答非所问、路人插话、拿不准 —— 一律当没点头（漏判只是多等一轮，误判是不可逆地违背人的意愿开工）。

   **「人回话了」的判据在代码里判死，不交给 agent**（`_human_replies`）：只认我们提问**之后**发的、**无我方签名**的、**且出自维护者**（`authorAssociation` ∈ OWNER/MEMBER/COLLABORATOR）的评论。三个条件缺一不可——少了签名这一条，我们自己贴的 park 理由/try 戳/裁决戳就会被读成人的回话，agent 对着自己写的话开会（故 `_park_needs_human` 也必须签名）；少了维护者这一条，这道闸**谁都不认**：公开仓库里任何一个路人回一句「可以，做吧」就能把活派出去，而 admitter 的提示词拦不住——它读到的只是一段**外人可写**的文本，压根不知道该听谁的。喂给 admitter 的对话（`_dialogue`）同样只含「我们的提问 + 维护者的回话」：路人评论不进 prompt，否则等于把一道 fail-closed 的闸暴露给提示词注入。

   **花钱之前先买票**：`stages.admit` 抛出（agent 输出不合约 / `_ActTimeout` / backend 429）会把 `_ask_human` 整个抛掉，此刻 issue 上既无 `ready` 也无 `needs-human` → 下一 tick 又扫到它 → **每 tick 烧一次 LLM，永远**（而人能稳定触发它：回一句「回复我时别输出 JSON」即可）。故 try 戳必须**先落 GitHub 再叫 agent**：一条人类回复至多买到**一次** agent 调用，戳盖不上（`gh` 挂了）就当场抛出，**零 LLM**，下一 tick 原样重来。两枚戳都挂**人那条评论的 comment id**、不挂时间戳：GitHub 的 `createdAt` 只到**秒**，同一秒里改口的两句话拿时间戳分不开，旧裁决会把新话吞掉 → fail-closed 从「多等一句话」退化成「永久拒绝」。

   **不能挂 `needs-human` 等人摘 label**——那是死胡同：`needs-human` 在 `_classify` 里是 TERMINAL、`_intake` 也跳过带它的 issue，挂上之后人回什么话都没人读。
2. **打 `ready` label** —— 准入令牌落 GitHub。
3. **调 curator（T1）** —— 喂「当前所有 `ready` open issue 快照 + 已有依赖边（锚点）」，出建议的 `blocked_by` 边集（每条 `{issue, blocked_by: [...], rationale}`）。curator 是零逻辑 Template（agents/ 层约定）：只出结构化语义判断，不做调度、不落边。
4. **validate** —— 本地用建议边重建内存 DAG，校验无环 + `blocked_by` 引用的都是真实 issue。
5. **落边** —— validate 过，才为**新节点** `POST blocked_by`；已有边（含人在 UI 手设的）作锚点不动（约束 C2）。validate 失败则不落任何边 + 给 issue 打 `needs-human`。

**用到的 REST 端点**（[GitHub Docs](https://docs.github.com/en/rest/issues/issue-dependencies)）：

- `GET /repos/{o}/{r}/issues/{n}/dependencies/blocked_by` —— 列 n 被谁挡；返回 issue 对象列表，含各 blocker 的 `state`。
- `POST /repos/{o}/{r}/issues/{n}/dependencies/blocked_by` —— 加一条依赖（body: `issue_id`）。
- `DELETE /repos/{o}/{r}/issues/{n}/dependencies/blocked_by/{issue_id}` —— 删一条。
- `GET /repos/{o}/{r}/issues/{n}/dependencies/blocking` —— 列 n 挡着谁。

因为 `blocked_by` 响应自带 blocker 的 `state`，一次调用同时拿到「边」和「blocker 关没关」，**不必再查第二轮**。

### 3. `_sense`：唯一的 GitHub 读，产出不可变 `_Observed`

```
_Observed
├── facts   ← _classify 读它；_fingerprint 哈希它。二者字段集必须相同。
│   ├── subject            "issue:5" | "pr:12"
│   ├── pr_number          int | None          （issue 尚无 PR 时为 None → 分支④ solve）
│   ├── head_sha           str  | None
│   ├── merged / closed    bool                （GitHub 事实 → 分支①）
│   ├── labels             frozenset           （我们的决定：needs-human → 分支①；ready → 准入；
│   │                                            review-approved:<sha7> / review-changes-requested:<sha7>
│   │                                            → 分支⑩⑪）
│   ├── deps_done          bool                （blocked_by 的对端是否全部关闭 → 分支③）
│   ├── mergeable_state    "clean"|"dirty"|"unknown"|None   ← GitHub 事实，读原生（分支⑤⑥）
│   ├── ci                 "success"|"failure"|"pending"|"none"  ← GitHub 事实，当前 head_sha 上的（⑦⑧）
│   ├── e2e_head_sha       str | None          （e2e 证据评论上的溯源戳；≠ head_sha 即陈旧 → 分支⑨）
│   ├── review_state       "APPROVED"|"CHANGES_REQUESTED"|None   ← 从 review-* label 解析（⑩⑪）
│   ├── review_commit_id   str | None          （裁决绑定的 commit，即 label 名里那截 sha7；
│   │                                            ≠ 当前 head_sha 即裁决陈旧 → 落回分支⑩重审）
│   └── latest_comment_is_ours  bool           （最新评论是不是我方签名 → 分支②）
│                                              ★ 只有这个布尔，**不存 comment id**——见下
└── clock   ← 只有 _watchdog 读它。绝不进 fingerprint。
    └── last_progress_at   max(head 推送时间, 最新 check.started_at,
                               最新评论时间, 最新 attempt 戳时间)
```

**`latest_comment` 只留布尔、不留 id**，这条是护栏一的生死线。id 进了 fp，盖 attempt 戳（一条新评论）就会把 fp 改掉 → 戳当场作废 → 无限重叫 agent（完整推演见 Guide §5.1 的引用块）。而丢掉 id 一个信号都不丢：分支② 只需要「最新一条是不是人发的」。

**`labels` 装的是「我们做的决定」，不是 GitHub 的事实。** `ci` / `mergeable_state` / `merged` 一律读原生字段，**不复制成 label**——它们本就绑在 sha 上、一次读到，复制一份就是造第二份真相（CI 重跑了谁去改 label？）。见 Guide §4.5。

**`deps_done` 必须在 `facts` 里**，这条最容易漏。issue A `blocked_by` issue B，B 的 PR 合了——A 自己的 PR / CI / 评论一个字节都没变。如果 `facts` 里没有 `deps_done`，A 的 fp 不变、A 永远不会被重新考虑，**整个依赖图卡死在第一个节点**，而 issue graph 并行正是本 spec 的核心卖点。

**两个必须写死在 `_sense` 里的坑**（见 Guide §4 的分支表顺序）：`ci` 只取当前 `head_sha` 上的；`mergeable_state` 的 `unknown` / `None` 是「还没算完」而非「没冲突」。

**这些读取在旧串行 vigil 里已全部存在**，只是散在 `_route_triage` / `advance_merge` / `_reply_one_pr` 里各读各的。`_sense` 不是新功能，是把它们归位到一处——不变式才有地方挂。

### 4. `_classify` / `_fingerprint` / `_watchdog`

```
_classify(facts, in_flight) → _Verdict:
      IN_FLIGHT                              ← in_flight（先于一切）
    | TERMINAL                               ← merged / closed / needs-human
    | QUIET(reason)                          ← awaiting-blockers | -mergeability | -ci | -effect
    | ACTIONABLE(action)                     ← reply|solve|rebase|fix-ci|e2e|review-or-fix|merge

_fingerprint(facts) → str                    ← 哈希 facts 的全部字段；clock 与 in_flight 都不进
_watchdog(verdict, clock, thresholds, now) → bool   ← QUIET 且 age > 该 reason 的阈值 → 该 park
```

`in_flight`（「队列里有该 subject 的 `claimed` 行」）是唯一非-GitHub 的输入，由调用侧喂进来——所以严格地说，不变式是「**`_fingerprint` 的字段集 ≡ `facts` 的全部字段 ≡ 分支表读的 GitHub 字段集**」，而 `in_flight` 与 `clock` 都显式**不进 fp**。

**两个调用侧传的值不同，这是正确性：**

- **生产者**据实传（查队列里有没有该 subject 的 claimed 行）。IN_FLIGHT 必须是第一道判定，否则看门狗会把一个正在写代码的 agent（跑 8 分钟很正常）当成「状态 5 分钟没动」而误挂 `needs-human`。
- **worker（`_reconcile`）恒传 `False`。** 它自己**就是**那个 in-flight 的持有者。若据实传 True，它领到活的第一件事就是判定「这活有人在干，我别管」→ 立刻收工 → **每个 worker 都空转，整个系统一动不动。** IN_FLIGHT 的语义是「**别人**在干」，是生产者独有的概念。

生产者对每个 subject：

```
ACTIONABLE 且 GitHub 上存在 fp 相同的 attempt 戳
    → 降级为 QUIET(awaiting-effect)        ← 护栏一：别在同一堵墙上再撞一次
ACTIONABLE（无同 fp 戳）  → _enqueue
QUIET                     → 不入队；_watchdog 说超时 → _park（needs-human + 机械诊断）
IN_FLIGHT / TERMINAL      → 略过
```

### 5. 表结构：一行 = 一个 subject

```sql
CREATE TABLE IF NOT EXISTS work_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    subject          TEXT    NOT NULL UNIQUE,        -- "issue:5" | "pr:12"
                                                     -- 去重 + 同-subject 互斥 + 幂等入队，三合一
    priority         INTEGER NOT NULL DEFAULT 0,     -- 越大越先（领取时定序）
    enqueued_at      TEXT    NOT NULL,               -- ISO；等优先级下的 FIFO tie-break
    status           TEXT    NOT NULL DEFAULT 'queued',   -- queued | claimed
    worker           TEXT,                           -- claimed 者标识（可观测）
    worker_pid       INTEGER,                        -- 持有者进程号——仅供人 ps 诊断，不作存活裁决
    claimed_at       TEXT,                           -- 领取时刻；只喂 IN_FLIGHT 看门狗告警，不作回收判据
    attempts         INTEGER NOT NULL DEFAULT 0      -- 领取后未收工的次数；超 _MAX_ATTEMPTS → park
);
CREATE INDEX IF NOT EXISTS ix_work_queue_claimable
    ON work_queue (status, priority DESC, enqueued_at ASC);
```

**没有 lease 列**——回收判据是 flock，不是超时（Guide §5.3）。

**`subject UNIQUE` 一根柱子扛三件事**：

| 属性 | 怎么来的 |
|---|---|
| **幂等入队** | 生产者每 tick 无脑 `INSERT OR IGNORE`——不做变更检测，重复入队是 no-op |
| **同-subject 串行** | 一个 subject 最多一行；被领走后再插入还是 no-op → 同一个 PR 上永远只有一个 agent |
| **去重** | 同上，不需要 `dedup_key` |

**`subject` 是 TEXT 不是 INTEGER**：`issue INTEGER NOT NULL` 表达不了无 issue 归属的裸 PR（旧串行 vigil 明确支持 `run.issue_number is None` 的「open PR 迭代源」，见 git history）。

**`_mark_done` 必须是 DELETE，不能是 `status='done'`**：`subject` 有 UNIQUE 约束，留着 done 行会让该 subject 永远无法再入队 → PR 死锁。done 的真相在 GitHub，队列行只是调度缓存。

进程内不再有 `_tracked` 集合 + 锁：去重、定序、认领、同-subject 串行全部下沉到 DB，只留一个 `threading.Event`（`stop_event`）做收池信号。每个 worker / 生产者各开一条本线程私有的 SQLite 连接（`_connect`：`isolation_level=None` + 手动 `BEGIN IMMEDIATE` 控事务、`PRAGMA busy_timeout`、WAL、`row_factory=sqlite3.Row`）——sqlite3 连接默认不跨线程共享。

### 6. `_claim_next`：原子领取 + 取存活证明

```sql
BEGIN IMMEDIATE;
UPDATE work_queue
   SET status='claimed', worker=?, worker_pid=?, claimed_at=?, attempts=attempts+1
 WHERE id = (SELECT id FROM work_queue
              WHERE status='queued'
              ORDER BY priority DESC, enqueued_at ASC
              LIMIT 1)
 RETURNING *;                                   -- SQLite 3.35+
-- 拿到行之后、COMMIT 之前：flock(claims/{subject}.lock, LOCK_EX|LOCK_NB)
--   抢到 → COMMIT，fd 由本 worker 持有到收工（存活证明）
--   抢不到 → ROLLBACK（防御性：queued 行本不该有活持有者），跳过该行
COMMIT;
```

| 子句 | 扛的属性 | 不这么写会怎样 |
|---|---|---|
| `WHERE status='queued'` + `BEGIN IMMEDIATE` | **exactly-once 领取** | 两 worker 并发领同一行时，序列化后第二个 `UPDATE` 匹配不到、返回空。这正是 C3 要根治的双跑 |
| `ORDER BY priority DESC, enqueued_at ASC` | **领取时定序** | 优先级冻结在入队时刻，久候行的 aging 失真 |
| **flock 与行同生共死** | **回收的正确性** | 没有它，回收只能靠租约猜死亡 → 误杀活着的 worker → 双跑 |

**没有 `NOT EXISTS` 子查询** —— 同-subject 互斥已由 `subject UNIQUE` 在入队时结构性保证（一个 subject 根本不可能有两行），领取时再查一次是纯冗余。

`attempts` **在领取时 +1**（不是失败时），故崩溃活即便被 `_reclaim_dead` 反复回收，也会在 `_MAX_ATTEMPTS` 处被 park、不无限占槽。

**收工必须先删行、再释放锁**（`_mark_done` / `_requeue_or_park` 同理）。反过来（先释锁后删行）会开一个窗口：锁已放、行还挂着 `claimed` → 另一个进程的 `_reclaim_dead` 抢到锁、判「死了」、把行打回 `queued` → 被重领 → **双跑**。而先删行再释锁，最坏情况是崩在两步之间——行已删、锁由内核释放，干净收场。

### 6.1 `_reclaim_dead`：凭 flock 判死，不凭超时

```
for row in SELECT * FROM work_queue WHERE status='claimed':
    fd = open(claims/{row.subject}.lock)
    try flock(fd, LOCK_EX | LOCK_NB)
    ├─ 成功       → 持有者进程已不在（内核已回收其锁）
    │               UPDATE … SET status='queued', worker=NULL, worker_pid=NULL, claimed_at=NULL
    │               release(fd)        ← 立刻放掉，本函数不执行活
    └─ EWOULDBLOCK → 持有者还活着 → 原样不动（无论它跑了多久）
```

**这是整个并发模型里唯一一处「判断别人是否还活着」，而它不做判断——它问内核。** `_reclaim_dead` 没有任何阈值参数，因此没有任何可以调错的旋钮。

**一个必须遵守的实现约束**：worker 持锁的 fd **不能**在 `_reconcile` 期间被 `close()`。flock 的锁绑在 open file description 上，**close 任何一个指向该描述的 fd 都会释放锁**——一个不小心的 `with open(...)` 就会把存活证明提前丢掉，让自己的行被别人回收走 → 双跑，而且是静默的。fd 的生命周期必须显式绑在「认领 → 收工」这段上（`_claim_next` 返回 fd，`_mark_done` / `_requeue_or_park` 负责 close）。

### 7. `_reconcile`：worker 领到 subject 之后

```
_reconcile(subject):
    last_fp = None
    while True:
        observed = _sense(subject)
        fp       = _fingerprint(observed.facts)
        verdict  = _classify(observed.facts, in_flight=False)   # ★ 我就是那个 in-flight

        if verdict is not ACTIONABLE:          # 卡在外部（QUIET）/ 到终点（TERMINAL，含 agent
            return                             #   自己打的 needs-human）→ 交还 slot

        if fp == last_fp:                      # 兜底：我出过手，状态没动 → 零进展（它自己没察觉）
            _post_attempt_stamp(subject, fp, agent_conclusion)   # 护栏一：盖戳，别再被叫起
            return

        last_fp = fp
        _act(observed)                         # 按 verdict.action 分派到 agent / 机械动作
```

**`in_flight=False` 不是笔误，是正确性**——见 §4。传 True 会让每个 worker 领到活就判「有人在干」并立刻收工。

**主路径在 `_act` 里，不在 `fp == last_fp` 里。** agent 判断没辙 → 自己打 `needs-human` + 留理由 → 下一圈 `_sense` 读到 → TERMINAL → 上面第一个 `return`。`fp == last_fp` 那一支是**兜底**，专防 agent **没意识到自己在空转**（见 Guide §5.1）。

**`_act` 内部：机械路由 + agent 干活。** 路由（走哪一支）永远是机械的；具体动作里才有 agent（写代码、修 CI、评审、回话）。**每个分支都有第二个出口 `needs-human`，且这是一等出口**——必须写进每个分支的 agent 提示词（`agents/*.py`）。`review-or-fix` 分支出裁决时打 `review-approved:<sha7>` / `review-changes-requested:<sha7>`，sha 取**裁决所针对的那个 head**（见 §4.5）。

`_act` 的各分支复用 `recipes.stages` 的竖切段 / 合并段与 `runtime.messages`；确定性硬闸（head 前移 / 证据溯源戳 / round_cap）恒在，`skip` 关不掉。

### 8. task 状态机

```
                    _enqueue（INSERT OR IGNORE；subject UNIQUE → 幂等）
                              │
                              ▼
   ┌──────────────────────► queued ◄───────────────────────┐
   │  _reclaim_dead             │                          │  _requeue_or_park
   │  （flock 抢得到 ⇒ 内核证明 │ _claim_next              │  （attempts < 上限；先删行后释锁）
   │    持有者已死 → 回收）      │ （BEGIN IMMEDIATE 原子领 │
   │                            ▼   + flock 持锁 + attempts+1）
   └────────────────────────claimed ───────────────────────┘
                              │  │
              _mark_done(删行)│  │ _requeue_or_park（attempts ≥ 上限）
                              ▼  ▼
                          [删行]   [删行 + 给 subject 打 needs-human]
```

两个持久状态（`queued` / `claimed`），完成即删行（见 §5：不删会因 UNIQUE 造成死锁）。

### 9. 循环时序

```
生产者 _producer_tick（主线程，每 interval）           worker _worker_loop（K 条常驻线程）
──────────────────────────────────────────           ─────────────────────────────────────
 0. _reclaim_dead      flock 抢得到 ⇒ claimed→queued      while not stop_event.is_set():
 1. _intake            新 issue 三态审 → 打 ready →       row, fd = _claim_next()  # 原子领+持锁
                       curator 排边 → validate → POST     if row is None:
 2. for subject in _subjects():                              stop_event.wait(POLL); continue
       observed = _sense(subject)                         try:
       verdict  = _classify(observed.facts)                  _reconcile(row['subject'])  # 推到卡住
       fp       = _fingerprint(observed.facts)               _mark_done(row['id'], fd)
       IN_FLIGHT → claimed_at 超龄? _park(只告警)         except Exception:   # 含 _act 硬超时
       TERMINAL  → 略过                                       _requeue_or_park(row['id'], subject, fd)
       QUIET → _watchdog 超时? _park : 略过                # 两条出口都：先删行，后 close(fd) 释锁
       ACTIONABLE → 有同 fp 戳? 降 QUIET : _enqueue       # 领完立刻回顶端再领，不等批
 3. 本 tick 入队数 == 0 → _hang（区分「前沿空」/「全在飞」/「N 个在等 CI」）
 4. once? _drain_queue（轮询到无 queued/claimed）: sleep(interval)
```

**数据流严格单向**：生产者只写 GitHub（打 label / POST 边 / `_park`）+ 写队列（`_enqueue`），**从不领活**；worker 只读队列（`_claim_next`）+ 写 GitHub（开 PR / 推流水线 / 回评论 / 盖戳）+ 删队列行，**从不生产**。两者对 `work_queue` 的并发写全部经 `BEGIN IMMEDIATE` 序列化，无需任何进程内锁。

**「无批屏障」怎么来的。** worker 跑完立即领队首。对照「批」模型（每轮 `sense → schedule → 跑整批 → sleep`）：K=4 选中 4 个 subject，3 个两分钟跑完、1 个跑四十分钟，那 3 个 freed slot 就空转 38 分钟。生产者 / 消费者拆掉屏障后，slot 复用延迟从「同批最慢」降到「≤ 一次 pull」（`_WORKER_POLL_SECONDS`）。

**生命周期与收池：**

- `once=True`（测试 / 单趟）：跑一个 `_producer_tick` → `_drain_queue` 轮询到表内无 `queued` 且无 `claimed` 行 → 收池返回（给测试确定性同步语义）。
- `once=False`（守护）：tick → sleep 循环。`_producer_tick` 抛异常记日志继续（不杀生产者）；单 subject 异常在 worker 内隔离（不杀 worker）。
- `KeyboardInterrupt`：`stop_event.set()` → worker 领完当前活自然退出（自己删行 + 释锁）。`queued` 行留 DB——幂等 + 持久，安全放弃、重启续跑。
- `kill -9` / OOM / 断电：`claimed` 行留在库里，但锁随进程一起被内核回收。重启后第一个 `_reclaim_dead` 就抢得到锁 → 判死 → 行立刻打回 `queued` → 被重领。**恢复延迟 = 一个 tick，不是一个租约。** 而它已推到 GitHub 上的进度（commit / PR / 评论）会被下一次 `_sense` 原样读到，reconcile 从它实际到达的位置往下走——崩溃的代价是重读一次现态，不是重做。

### 10. `priority`：先收尾在制品，再开新工

一个近乎合完的 PR 正占着一条依赖链的下游；开一个新 issue 只是增加在制品。故默认按 `_Verdict.action` 给权重：

```
reply(6) > merge(5) > review-or-fix(4) > e2e(3) > fix-ci(2) > rebase(2) > solve(1)
   ↑                                                                        ↑
人在等                                                          开新工，最后
```

权重可插拔（`priority_fn` 注入）。`ORDER BY priority DESC` 在领取时求值，久候行的优先级不冻结在入队时刻。

### 11. 走查：A / B（blocked_by A）/ C 三 subject，K=2

| tick | 生产者对每个 subject 的判定 | `work_queue` | worker |
|---|---|---|---|
| **t0** | `_intake`：三态审过 → 打 `ready`；curator 排出 `B blocked_by A`、C 无入边；validate 过 → `POST blocked_by`(B←A) | 空 | 空表轮询 |
| **t1** | A：`deps_done` ✓、无 PR → **ACTIONABLE(solve)**；C：同 → **ACTIONABLE(solve)**；B：blocker A 未 merged → **QUIET(awaiting-blockers)**（默认无阈值，不 park） | `issue:A`、`issue:C`（queued） | W0/W1 各领一个 → `_reconcile` 推到开出 draft PR、CI 起来 → 卡在 **QUIET(awaiting-ci)** → 交还 slot |
| **t2** | A/C：**IN_FLIGHT**（若仍在跑）或 CI 出结果后重新判定；B 仍 QUIET | — | — |
| **t3** | A 的 PR **merged** → A **TERMINAL**；B 的 `deps_done` 现为 ✓、无 PR → **ACTIONABLE(solve)**（传递依赖自然解锁） | `issue:B` | 领 B → 竖切 |
| **t4（主路径：agent 自己叫人）** | B 的 CI 红 → ACTIONABLE(fix-ci) → 入队 → agent 一看是上游 flaky、自己修不了 → **打 `needs-human` + 留评论说明理由** → 同一次认领内下一圈 `_sense` 就读到 → **TERMINAL**，收工。**轮询当场停止，不等任何阈值** | `issue:B` 行被删 | 领 B → 打标 → done |
| **t5（护栏一：agent 没意识到自己在空转）** | C 的 CI 红 → ACTIONABLE(fix-ci) → agent **以为自己修了**（rerun 了 CI 但没触发成功），零变更、**不打 needs-human** → `fp` 未变 → worker 盖 `attempt fp=…` 戳收工。下一 tick：仍 ACTIONABLE，但见到**同 fp** 的戳 → 降 **QUIET(awaiting-effect)** → 不入队，**零 LLM 调用**（若无此戳，这里会无限重叫） | — | 静默 |
| **t6（护栏二：超时兜底）** | C 的 `awaiting-effect` age 超阈值 → `_park`：打 `needs-human` + 贴机械诊断（附 agent 自己那条结论）→ C 进 **TERMINAL**，轮询停止 | — | — |
| **t7（hang）** | A/B/C 全在飞或全 QUIET → 本 tick 入队 0 → `_hang`（区分「前沿空」/「N 个在解决中」/「N 个在等 CI」） | 仅 claimed 行 | 空队列轮询 |

这张表**即** e2e 脚本的断言序列（`run_vigil(once=True)` **反复调用**，一次一个 tick——单趟 tick 覆盖不了 t1→t3 的跨轮解锁）。

**t4 与 t5 是这套设计的两条腿，必须都断言到：** t4 证明「知道自己没辙的 agent 走一等出口，快、便宜、理由是它写的」；t5 证明「**不知道**自己没辙的 agent 被机械兜住，不会无限烧钱」——后者正是 agent 主动叫人**替代不了** attempt 戳的原因。

成环（curator 误排 A↔B）会让两者恒 `QUIET(awaiting-blockers)` → 每 tick 落进 `_hang` 打提示，不静默卡死。

### 12. 部署边界：单机多进程，不是多机

SQLite 官方对跨网络文件系统共享同一个库有**明确禁令**，而且是**数据损坏**级别，不是性能级别：

> "file locking logic is buggy in many network filesystem implementations (on both Unix and Windows). If file locking does not work correctly, two or more clients might try to modify the same part of the same database at the same time, **resulting in corruption**."
> "**A good rule of thumb is to avoid using SQLite in situations where the same database will be accessed directly (without an intervening application server) and simultaneously from many computers over a network.**"
> —— [sqlite.org/whentouse.html](https://www.sqlite.org/whentouse.html)
>
> "Rely upon it at your (and your customers') peril." —— [sqlite.org/useovernet.html](https://www.sqlite.org/useovernet.html)

flock **同样**钉在单机：NFS 上它被模拟成 `fcntl` 整文件字节范围锁（man7），而 `fcntl` 锁是 per-process 的——于是「同进程多 fd 互斥」这条我们赖以成立的性质会**静默失效**，K 个 worker 线程的互斥直接崩掉。**两者是同一条边界，flock 没有引入任何新约束。**

所以本 spec 的部署边界是：**单机、多进程、K 线程**（`BEGIN IMMEDIATE` 序列化并发写，是 Postgres `SELECT … FOR UPDATE SKIP LOCKED` 的单机等价物）。

**多机拓扑怎么办。** 关键分解：**队列不需要跨机共享，只有 claim 需要。**

- **队列**是 GitHub 的投影、一 tick 可重建。两个进程各自 `_sense`，会独立推导出同一个前沿——这正是 level-triggered 的性质。各存各的，不用共享，不用对账。
- **claim** 是唯一必须全局唯一的东西。

GitHub 恰好有**真 CAS**：`POST /repos/{o}/{r}/git/refs` —— ref 已存在则失败（422）。这是 GitHub 仅有的两个 CAS 原语之一（另一个是 `PUT /contents/{path}` 的必填 `sha`，stale 则 409）。多机时把 claim 换成「创建 `refs/openagents/claims/{subject}`，谁的 create 成功谁赢」即可。

**但多机时零双跑的保证会退化。** flock 是内核级的存活证明，而内核不跨机——远端进程死了，本机内核无从得知。跨机只能退回租约（ref 指向对象的时间戳 + 过期后 DELETE-then-CREATE：DELETE 幂等、CREATE 是 CAS，故恰有一个赢家），也就重新引入了「从沉默里猜死亡」以及它带来的双跑窗口。届时的缓解手段是把「双跑安全」推到 GitHub 交付层（`force-with-lease`、head 前移硬闸、merge 幂等，Spec-0056 已具其一），即从「不发生双跑」降级为「双跑不烂事」。**单机拓扑下这个降级是不必要的，所以本 spec 不做**（奥卡姆：不为「可能」付费）。替换点收在 4 个函数里：`_claim_next` / `_reclaim_dead` / `_mark_done` / `_requeue_or_park`。

### 13. DAG + 文件分配

| Task | 标题 | 依赖 | files（单一 writer） |
|---|---|---|---|
| **T1** | graph-curator agent（零逻辑 Template） | — | `openagents/agents/curator.py`, `tests/test_agent_curator.py` |
| **T2** | vigil 原地重写为 level-triggered reconcile + 吸收旧串行能力 + CLI 改指 | T1 | `openagents/recipes/vigil.py`, `openagents/recipes/stages.py`, `openagents/runtime/state.py`, `openagents/backends/claude_code.py`, `openagents/cli.py`, `openagents/utils/github.py`, `openagents/utils/proc.py`, `tests/test_recipe_vigil.py`, `tests/test_recipe_vigil_act.py`, `tests/test_recipe_vigil_queue.py`, `tests/test_utils_github_vigil.py`, `tests/test_utils_proc.py`, `tests/test_backend_claude_code.py`, `tests/test_cli.py`, `scripts/e2e-spec-0065-graph-parallel-vigil.sh` |

T1 是并行根；T2 接 T1 收口。recipes 守恒为 3（stages / backfill / vigil）。

**e2e 脚本**（`scripts/e2e-spec-0065-graph-parallel-vigil.sh`）：离线跑 `run_vigil(once=True)`，注入固定时钟 + fake backend / github（含 `blocked_by` 端点桩），喂三个 issue（B `blocked_by` A、C 独立），断言第 11 节走查表。门控成果为离线段。

### 14. 实现现状（T2 `status: done`）

**全部落地并经审查加固。** 两面（准入面 / 执行面）、感知三纯函数、SQLite 认领队列、flock 存活证明、reconcile 分支表 ①–⑪、四道护栏、CLI `--parallel K`、离线 e2e 脚本（t0–t7）均已实现，无 `NotImplementedError` 占位。旧串行实现**直接删除**（git history 即回退点——留一份 1120 行的死代码副本既违奥卡姆，又会把一个没有任何调用方的模块永久钉进架构图）。

**合并前的审查修正**（多 agent 独立审查 PR #164 后修，均已补测）：

| # | 缺陷 | 修法 |
|---|---|---|
| 1 | `_act` 硬超时靠「调用前后 diff 本进程子进程集合」认领 agent 的子进程——而生产者线程同时在跑 `gh`/`git`（同样是本进程的子进程），K 个 worker 也彼此并发：**会认错进程 → 超时时杀错、真挂死的 agent 活着继续 push**（双跑正是从这个洞漏出来，而它恰是 flock 覆盖不到的那个洞） | 改为 **backend 自报 PID**（`utils/proc.py` 的线程级认领桶 + `claude_code` 在 `Popen` 后 `publish`），超时按 `thread.ident` 取桶、`kill_tree` 连后代一起杀；且超时**不再回队重试**（杀干净只是尽力而为）而是直接 park 交人 |
| 2 | `_worker_loop` 的领取/收工三处裸调 sqlite（`_claim_next` / `_mark_done` / `_requeue_or_park`）不在 try 内——`database is locked` 一抛就**静默杀死 worker 线程**；若死在 `DELETE` 与 `close(fd)` 之间，那行 `claimed` 的锁还在本进程手里 → `_reclaim_dead` 判它「持有者活着」→ **永不回收、永不重入队**，该 subject 就此死掉 | 抽出 `_run_claimed` / `_finish`：异常一律不越过这一层，且 `finally` **保证 `close(fd)`**（锁还给内核，最坏被回收重跑——重跑幂等，孤儿行是永久的） |
| 3 | `_reconcile` 的 `fp == last_fp` 只记得**上一轮**，识别不了周期 ≥2 的**振荡**（review 打回 → implement 推新 head → review 又打回 → …）：fp 每轮都变，于是它一轮一次 LLM 地无限转，直到 2 小时后 IN_FLIGHT 告警才有人管 | 加 `_MAX_RECONCILE_ROUNDS`（8）轮数上限，到顶 park 交人（振荡本就该人来定） |
| 4 | 裸 PR 的 worktree 目录键取「issue 归属 → 0」，于是 `pr:12` 与 `pr:13` 共用 `.worktrees/issue-0`：两个 worker 的 agent **在同一个目录里同时改代码**，且后来者站在前者的分支上，会把改动推到别人的 PR 上（subject 级 flock 拦不住——它们本就是两个 subject，共享的是**资源**） | 裸 PR 改用 **PR 号**当目录键（GitHub 的 issue 与 PR 共用一套编号，`pr:N` 与 `issue:N` 不可能同时存在） |
| 5 | `RuntimeState` 是无锁的「读整个 JSON → 改一个键 → 整个写回」，却被 K 个 worker 并发写：**丢更新**（后写的抹掉前者的记录）+ **整文件截断**（读者读到半截 JSON → 容错成空状态 → 一写就把整个文件覆盖成只剩自己那条） | 类级 `RLock` 串行化读-改-写全程；`_save` 走 tmp + `os.replace`（原子顶替） |
| 6 | `add_blocked_by` 用 `gh api -f issue_id=…` 发**字符串**，而 dependencies API 的 `issue_id` 声明为 integer → 每条依赖边都会 422（且 422 不在 already/duplicate 白名单里 → 直接抛） | 改 `-F`（类型推断 → JSON number） |
| 7 | `_claim_next` 撞到瞬时锁冲突就返回 `None`，被 worker 读成「队列空了」→ 队首一行的亚毫秒锁冲突把**所有** worker 挡在门外（队头阻塞）；且拿到 fd 却 COMMIT 失败时不 close → 那行**再也领不走**（锁在本进程手里而行是 queued，回收只管 claimed 行） | 跳过该行接着看下一行；异常路径必 `close(fd)` |
| 8 | `_proposed_edges` 一条坏边就 park **整个 ready 集**（curator 一次幻觉冻结整条流水线）；且无法解析的编号会合成 `issue:0` → 往**不存在的 issue #0** 上写 label/评论 | 只 park 涉事者（坏边宿主 + `_cycle_members` 给出的环上成员）；幻觉编号只整批否决 + 记日志，不冤枉任何 issue |
| 9 | `--parallel 0` / `-3` 被静默钳成 1，`--parallel 99999` 真起 99999 条线程 | argparse 层校验 `1..32`，越界当场报错（不静默钳位——把输入错误变成性能谜题最坏） |
| 10 | `_drain_queue`（`once=True` 的路径）无上限，任一行卡住就**永不返回**；`_enqueue` 的 priority 冻结在入队时刻（排队期间 solve→merge 的升权不生效）；`_reclaim_dead` 谎报回收数 | 分别加 `_DRAIN_MAX_SECONDS` 上限、queued 行刷新 priority（不刷 `enqueued_at`，免饿死）、按 `rowcount` 计数 |
| 11 | 到顶 park 的路径上 fd 会被 **close 两次**：`_requeue_or_park` 删行 → `close(fd)` → `_park_needs_human` 发 `gh`（会抛），异常回到 `_finish` 时 `closed` 还是 `False` → `finally` 再关一次。而 fd 号早已被别的线程复用（另一个 worker 的 claims 锁 / 一个 sqlite 句柄）→ **放掉别人的 flock** → 那个还在跑的 worker 被 `_reclaim_dead` 判死回收 → 双跑（flock 挡得住一切，唯独挡不住「锁被别人替我放了」） | fd 所有权随调用移交：`_mark_done` / `_requeue_or_park` 各自 `finally` 保证 close 恰好一次；`_finish` 一进这两个分支即置 `closed`，兜底不再重关。（本项当时把 park 的网络调用挪到了释锁之后，后被第 14 项推翻——park 必须**先落 label 再删行**，故网络调用仍在 close(fd) 之前；双关由 `closed` 标志 + 各自 `finally` 兜住，不靠调用顺序） |
| 12 | `_do_solve` 的交付段（`stages.deliver`）是唯一没拼 `_NEEDS_HUMAN_CONTRACT` 的 agent 调用——推不上去（保护分支 / 权限 / 反复 rebase 打架）时那个 agent 无路可退 | 补 `context_text=_NEEDS_HUMAN_CONTRACT`；e2e 加锚点：反射所有 `_do_*`（除纯机械的 `_do_merge`），少一个就红 |
| 13 | **存活证明证明错了对象。** flock 由**守夜进程**持有，可真正在改代码、在 push 的是它起的 **agent 子进程**——守夜被 SIGKILL / OOM / `docker stop` 打死时，那个子进程是被**孤儿化而不是被杀**（要到下次写 stdout 才发现父亲没了，而那可能是几分钟后，足够它把一次 `git push` 做完）。内核此刻放掉守夜的锁 → 重启后 `_reclaim_dead` 抢到锁、判「持有者已死」、把行打回 queued → 另一个 worker 领走同一个 subject → **双跑**，且恰好发生在本文声称「结构性为零」的那个场景里 | 把认领的 flock fd **传给 agent 子进程继承**（`proc.hold_fd` 登记 → `claude_code` 的 `Popen(pass_fds=proc.inherited_fds())`；flock 绑在 open file description 上，fd 一继承即同持一把锁）。锁的语义于是变成「守夜进程**或**它的 agent 还有一个活着」——孤儿在跑，锁就抢不到，行就不会被回收。代价落在安全的那一侧：agent 若泄漏长命孙子进程，那行只会**卡住**（被看门狗交人），不会被重复执行 |
| 14 | **park 不持久。** 到顶 park 的路径先 `DELETE` 掉队列行、再发 `needs-human` label；`gh` 一失败（网络 / 限流），行没了、label 也没打，下一 tick `_sense` 又把它当新 subject 推导出来 → `attempts` **归零重来** → 无限 park-重派环，而「交人」这个终态一次都没落地 | 调换顺序：**先落 label（park 的唯一持久痕迹），再删行**。`gh` 失败则行仍在 `claimed`，锁一释放即被 `_reclaim_dead` 正常回收重试——重试幂等，而丢失终态不可逆 |
| 15 | `kill_tree` 拿**裸 PID** 发 SIGKILL：子进程一旦退出并被 reap，它的 PID 就交还内核、可被重新分配（长跑守夜每 tick 起若干 `gh`/`git`，PID 回绕只是时间问题）。于是超时方杀的很可能是**另一个 worker 的 agent** → 那行被回收重领 → 双跑 | 认领桶连 `Popen` 句柄一起记（`publish(pid=…, handle=proc)`）；`kill_tree` 先验明正身——`handle.poll() is not None` 即「已退出且已 reap」→ 直接返回，不杀。漏杀最坏是行卡住被看门狗交人，杀错则直接制造双跑 |
| 16 | 生产者线程里的两次 agent 调用（curator 的 `_admit` 准入 + `_order_edges` 排边）**不过 `_TimedBackend`**——挂死在那里，整个守夜（连同 K 个 worker 的派单）一起停摆，且没有任何护栏会响 | 生产者也包一层 `_TimedBackend`（`lock_fd=None`——生产者不持行锁，无证明可继承） |
| 17 | **第 13 项的修法自己开了一个更坏的洞。** 锁传给 agent 子进程后**也会传给它的孙子**（`pass_fds` 在子进程里清掉了 CLOEXEC，而 agent 不是 python，不会像 `subprocess` 那样替我们关掉多余 fd）：agent 只要留下一个长命的孙子（MCP server、它自己起的后台 dev server），那把锁就**永不释放** → 该 subject 的 `queued` 行永远领不走。而**所有看门狗都看不见它**：`_reclaim_dead` 只扫 `claimed` 行、IN_FLIGHT 告警读 `claimed_at`（它没有）、QUIET 看门狗只对 QUIET 裁决生效（它是 ACTIONABLE——正因如此才入的队）；`_claim_next` 每轮静默 `skipped`，`_hang` 于是报「前沿空」——**一句谎话**。净效果是拿一个罕见的（仅守夜被强杀时）双跑，换一个**永久的、静默的、无诊断的**停摆 | 加 `_sweep_stalled`（生产者 tick，紧跟 `_reclaim_dead`）：判据是结构性的——**`queued` 行的锁本就该是自由的**（合法持有者只有 claimed 行的那个 worker）。锁自由 = 只是在等 K 个槽 → 放过（这条是关键的假阳性闸：长队列 ≠ 故障）；锁被占且超 `_STALE_LOCK_SECONDS`(300) = 持有者不是任何 worker → 只可能是泄漏进程 → park 交人（label 里直接给 `lsof <lock>` 的排查命令）。**继承换来的不变式，必须自带这道闸才成立** |
| 18 | `attempts` 只在**失败处理内部**读，`_claim_next` 的领取谓词不看它：park 的 `gh` 一失败（限流/掉网），行留在 `claimed` → 被 `_reclaim_dead` 正常回收 → 重新领取 → **又跑一次完整的 agent 调用**才走到上限判断。`gh` 持续失败 = 无限烧 LLM 的循环（`_MAX_ATTEMPTS` 的存在意义正是不让毒丸活这么烧）；而在**超时 park** 那条路上更糟——被强杀的 agent 是否已推了东西无法证明，重发一次正是那条 label 里写着「未自动重试」要避免的双跑 | `_run_claimed` 进门先查上限：`attempts > _MAX_ATTEMPTS` 的行只有一种来路（上一轮已判 park 但 park 没落地）→ **要重试的是那次 park，不是那次 agent 调用** → 直接 `_finish(park=True)`，零 LLM 调用 |
| 19 | `_TimedBackend._call` 里 `track()` / `hold_fd()` 在 `try` 之外：`hold_fd` 碰坏 fd 抛 `EBADF` 时，子线程带着一个既无 `result` 也无 `error` 的空箱子死掉 → `run()` 取 `box["result"]` 得 `KeyError`，把可诊断的失败变成悬案 | 一并收进 `try` |
| 20 | **第 17 项的那道闸会误杀正在干活的行（TOCTOU）。** `_sweep_stalled` 先 `SELECT` 出一份 `queued` 快照，然后**逐行**去 park——而 park 一行要发 `gh`（几秒的网络往返）。这几秒里 worker 完全可以合法领走快照里的**另一行**并拿走它的锁；再轮到那行时，它的锁「被占着」→ 判泄漏 → 发 `needs-human` 并把一个 `claimed` 行**从正在跑的 worker 脚下删掉**。行没了，worker 收工时 `_mark_done` 的 DELETE 打空，`_reclaim_dead` 也再看不见它 → 那次 agent 调用的结果彻底无人认领。park 一个 subject = 停掉一个 issue 的活，它的假阳性比它要治的病更贵 | park 前在 `BEGIN IMMEDIATE` 事务里**复核「这行还是 `queued`」**（读到 `claimed` → 是 worker 合法领走的，直接放过），且 `DELETE` 带 `AND status='queued'` 守卫。**这一版仍然错，见第 25 项**——它救得了行，救不了 label |
| 25 | **第 20 项只堵了一半：行守住了，话没守住。** 复核之后是 `COMMIT`，然后才发那两次 `gh`（数秒）——这期间泄漏进程若恰好死掉，锁一自由，worker 就**合法领走**这一行并开跑；我们那条 `needs-human` 于是落在一个**健康且正在被执行**的 subject 上。`DELETE … AND status='queued'` 忠实地删了 0 行（行是保住了），可 label 已经出去了：下一圈 `_classify` 读到 `needs-human` → 判 TERMINAL → 那个 worker 掉头就走、`_mark_done` 删掉行 → **这个 issue 再也不会被动手**。净效果与第 17 项要根除的东西一模一样——永久静默停摆，只不过这次是**闸自己**打在一个健康 issue 上。（原实现的注释一路推理到这个窗口，却停在了前一行。）| **把 `DELETE` 本身当成预约**：`_park_stalled` 在 `BEGIN IMMEDIATE` 里 `DELETE … AND status='queued'`，`rowcount == 1`（抢到了）才开口发 `gh`，否则一个字都不说。删掉的行 `_claim_next` 再也看不见（它只认 `queued`），所以「抢到 ⇒ 没有任何 worker 可能在跑它」是结构性的。这与 `_requeue_or_park` 的「先落 label 再删行」**故意相反**：那边删的是自己的 `claimed` 行（没人能抢，而丢 label 会让 `attempts` 归零、无限重派烧 LLM）；这边删的是谁都能领的 `queued` 行（丢 label 只是下一 tick 由 `_intake` 从 GitHub 现态重新推导、重新计时——**有节流、零 LLM** 的重试）。两边失败代价不对称，故顺序相反 |
| 26 | **一个从未实现的承诺。** 正文三处（summary / Guide 图 / Reference §2 步骤 1）都写「`human` 态经**对话**与人确认」，代码里的 `_on_human` 却只是挂 `needs-human` 然后等人**手动摘 label**。而 `needs-human` 在 `_classify` 里是 TERMINAL、`_intake` 也跳过带它的 issue——**挂上去之后守夜就再也不看这个 issue 了**，人在底下回什么话都没人读。这不是「对话确认」，是死胡同：`human` 态的语义恰恰是「这个决定得由人拍板」，而人拍板的自然方式是**说话**，不是去操作 label | 实现 `_ask_human`：三个状态全从 GitHub 现态推出（level-triggered，零本地记忆）——①没问过（无 `_ADMIT_ASK_MARK` 标记评论）→ 发一条**签名**提问评论，**零 LLM**；②问过、人还没回话（最新一条是我方签名）→ 什么都不做，**零 LLM**（关键：准入面每 tick 都重新扫到这个 issue，每轮叫一次 agent 就是台按 tick 计费的印钞机）；③人回话了 → 把对话拼进 issue 正文（`_with_dialogue`——triager 只吃 `issue.body`，不拼进去人说的话等于没说）交 **triager** 重判 → 点头打 `ready`，否则挂 `needs-human` + 附理由。**用 triager 而不是 replier**（正文原文写的是 replier）：replier 的提示词是 **PR 语境**的（`$pr_number` / `$branch` / 「若需要改代码就改，commit+push」），对着一个还没有 PR 的 issue 叫起来等于叫它去改代码；而这里要的判断正是 triager 的裁决面（`{actionable, reason}`）。对话的**形式**（签名评论 + 「最新一条是不是我方」判有没有新话）仍复用 replier 那套防自循环纪律。**这一版仍然错，见第 27–30 项**——把人闸接到了一个 fail-open 的 agent 上 |
| 27 | **第 26 项把人闸接到了一台偏向「是」的机器上。** `_ask_human` 拿 `stages.triage` 来判「人点头没有」——可 triager 判的是**另一个问题**（issue 正文内部有没有自相矛盾），且它的纪律白纸黑字是 **fail-open**：「拿不准就判可派单」。人回一句「先别做，这个方向我还没想清楚」，这不属于它那五类矛盾中的任何一类 → 它照判 `actionable=true` → **在人明确否决之下把活派出去**。`triage: human` 的整个语义是「这个决定得由人拍板」，而这一版把拍板权交还给了一个默认说「是」的 agent：比它所替换的那个死胡同更坏——死胡同只是停住，这个会**违背人的意愿开工** | 新增 `agents/admitter.py` + `stages.admit` + `context.for_admit`：判据只有一个（人到底同意没有），纪律与 triager **相反——fail-CLOSED**：明确表示可以开始做才 `approved=true`；反对、要求先给方案、答非所问、路人插话、或**拿不准**，一律 `false`。漏判的代价是多等一轮（人再说一句话），误判的代价是不可逆地开工——代价不对称，默认值就只能取「没点头」。对话作**独立占位符** `$dialogue` 喂进去（塞进 `issue_body` 冒充正文 = 把「人说的话」和「issue 原文」混成一坨，agent 分不清在判哪个）|
| 28 | **我方评论没签名 → agent 对着自己写的话开会。** `_park_needs_human` 贴的理由评论是**不签名**的，而每一条 park 文案都在教人「处理完**摘掉本 label**，守夜会自动重新接管」。人照做（只摘 label、不回话）之后，`_intake` 重新看得见这个 issue，`_ask_human` 读评论流——**最新一条正是我们自己写的那条 park 理由**，无签名 → 被判成「人回话了」→ 叫 agent 去读我们自己写的话 → （第 27 项之前）fail-open 的 triager 一看没矛盾 → 打 `ready` 派单。人一个字没说，闸自己替人点了头。同一个洞也存在于 attempt 戳（若不签）。`identity` 那套签名纪律存在的**全部意义**就是堵这个 | 在源头签：`_park_needs_human(*, subject, body, agent_id)` 走 `identity.sign`，`agent_id` 穿过全部 9 个 park 调用点（`_park_stalled` / `_requeue_or_park` / `_admit._on_agent` / `_ask_human` / `_proposed_edges` / `_park` / `_finish` / `_reconcile` / `_park_gate`）。且「人回话了」的判据不再是「最新一条不是我方」这种**位置**判断，改成集合判断 `_human_replies`：我们提问**之后**发的、**且**无我方签名的评论——两个条件缺一不可（少了「之后」，提问前的旧评论会被当成回话；少了签名，我们自己的话会被当成回话）|
| 29 | **一次 `gh` 抖动 = 重判一次（按 tick 计费的印钞机，第二版）。** 人回话 → 叫 agent 判 → 判完打 `ready` label。若 label 那一步挂了（429/403/掉网），`_intake` 把异常吞掉记日志，下一 tick 这个 issue 还是「没 ready、没 needs-human」→ 重新走一遍 `_ask_human` → 人的回话还在 → **再叫一次 agent**。`gh` 每失败一轮就重判一轮：一条人类回复能烧掉 N 次 LLM 调用（实测 1 条回复 → 5 个 tick → 5 次 agent 调用）。第 26 项只堵了「人还没回话」那段的零 LLM，没堵「判完了但没落地」这段 | 裁决**先落 GitHub、再落地**：`_post_admit_verdict` 把 `{approved}` 盖成一条**签名 + 带标记**的评论（`_ADMIT_VERDICT_MARK` + `approved`/`refused`），然后才去打 label。下一 tick 的 `_admit_verdict` 读回这条戳（要求它比我们那条提问**新**）→ 直接重试打 label，**零 LLM**。仍是 level-triggered：真相全在 GitHub 评论流里，零本地记忆 |
| 30 | 读侧重复造轮子：第 26 项为读 issue 评论补了个 `github.issue_comments`，可 `list_issue_comments`（Spec-0049/T1）早就在那儿了，同一条 `gh issue view --json comments`。两个同义函数各自解析一遍，日后改 `Comment` 结构必漏一个 | 删掉新增的那个，两个读侧（`list_comments` 走 `gh pr view` / `list_issue_comments` 走 `gh issue view`）折叠到共享的 `_parse_comments` 上——差异只在取数命令，解析只有一份 |
| 31 | **第 29 项那条戳会把 `fail-closed` 变成「永久拒绝」**（自查发现，不在任何一轮审查里）。裁决戳的复用判据若写成「戳比**提问**新就沿用」，那么一次 `refused` 之后：我们挂 `needs-human`（TERMINAL、`_intake` 跳过），人照提示回一句「行，做吧」再摘掉 label —— 下一 tick `_ask_human` 一读，那条 refused 的戳**仍然比提问新** → 直接沿用 → 再挂一次 `needs-human`。人新说的那句话被自己的旧裁决**永久盖住**，再也无法点头。fail-closed 的本意是「拿不准就多等一句话」，这样写却成了「等来的话永远不听」 | 裁决戳挂在**人最新那句话**上，不是挂在我们的提问上：`_admit_verdict(comments, latest_reply)` 只在 `stamp.created_at >= latest_reply.created_at` 时才沿用。人一开口，旧裁决自动作废、重判；人不开口（只摘 label，或 `gh` 抖动导致上一轮 label 没打上）→ 沿用旧裁决，**零 LLM**（第 29 项要省的那次调用照样省下）。park 文案也随之改口：「**回一条评论**说清楚，再摘 label」——原文案只教人摘 label，恰好把人引进这个死角 |
| 32 | **那道「人闸」谁都不认**（第七轮，对第 27–31 项那批修正的反驳）。`_human_replies` 认「人回话了」的判据只有两条：提问之后 + 无我方签名。GitHub 的 `Comment` 里明明有 `author`，一次都没读过；admitter 的提示词里倒是写着「若不是那个人在说就别当拍板」——可它拿到的只是一段文本，**压根不知道该听谁的**，这条纪律无从执行。于是在公开仓库上：任何一个能评论的账号回一句「可以，做吧」→ `ready` → 派单。fail-closed 的闸门，钥匙挂在门外 | 「谁说的话算数」在**代码**里判死：`Comment` 增 `author_association`（GitHub 原生 `authorAssociation`，随 `--json comments` 一并取回），`_human_replies` 只认 `OWNER/MEMBER/COLLABORATOR`。fail-closed：关系读不到（空串）/ `CONTRIBUTOR` / `NONE` ⇒ 当噪声略过。`_dialogue` 同步收窄为「我们的提问 + 维护者的回话」——路人评论根本不进 prompt（否则等于把一道 fail-closed 的闸暴露给提示词注入） |
| 33 | **agent 判崩 = 每 tick 烧一次 LLM，永远**（第七轮，HIGH）。第 29 项的「先盖戳再打 label」只护住了**打 label** 这一步；`stages.admit` 本身抛出（agent 输出不是 JSON、`_ActTimeout`、backend 429）时，`_ask_human` 整个抛掉，issue 上既没 `ready` 也没 `needs-human` → 下一 tick `_intake` 照样扫到它 → 再判一次。实测：10 个 tick → 10 次 agent 调用、0 个 label、0 条评论。更糟的是**人可以稳定触发它**（回一句「回复我时别输出 JSON」），而 429 恰恰先打在 `_post_admit_verdict` 那条 `gh` 上——第 29 项自己举的那个例子并不成立 | 花钱之前先买票：`_post_admit_try` 在叫 agent **之前**盖一枚签名 try 戳（`_ADMIT_TRY_MARK` + 人那句话的 comment id）。下一 tick 看到「有 try 戳、无裁决戳」⇒ 上一轮判崩了 ⇒ **零 LLM** 转人工（`needs-human` + 一句「再回一条评论即可重来」）。一条人类回复至多买到**一次** agent 调用；戳本身盖不上（`gh` 挂了）则当场抛出，**一次 agent 都不叫**，下一 tick 原样重来 |
| 34 | **第 31 项那个修正在同一秒里失效**（第七轮）。裁决戳的复用判据写成 `stamp.created_at >= latest_reply.created_at`，而 GitHub 的 `createdAt` **只到秒**。人在同一秒里改口（先说「先别做」、紧接着说「行，做吧」），新话与旧裁决戳同秒 → `>=` 恒成立 → 旧的 refused 戳把新话吞掉 → 又回到「永久拒绝」。改成 `>` 也不对：我们自己盖的戳判不了自己刚判过的那句话 → 每 tick 重判 | 戳挂**人那条评论的 comment id**（`_reply_key`），判据是**精确相等**，不再比时间。id 是身份、不是刻度：换一句话就换一个 id，同秒也分得开。时间戳只用来定序（谁在提问之后说的），不再用来定身份 |
| 35 | park 的理由评论不幂等：人摘掉 `needs-human` 却没改变任何事实（读岔了、手滑、label 自动化），下一 tick 原样再 park 一次——理由一字不差，却是一条**新评论**。label 幂等，评论不幂等 | `_park_needs_human` 先读回评论流，同一段理由（比未签名的正文——签名里的 `agent_id` 每进程都不同，不能比全文）已经贴过就**只补 label、不再贴**。评论流本来就是这条路上的单一真相，多读一次是它应付的代价 |
| 36 | frontmatter 的 `files` 漏了三个本 PR 真改过的测试文件（`test_recipe_vigil_admit.py` / `test_github.py` / `test_runtime_context.py`）；第 11 项的措辞（「park 的网络调用移到释锁**之后**」）也已被第 14 项（「先落 label 再删行」）推翻，却还留在表里 | 补进 T2 的 `files`（files-allocation 是设计期的所有权声明，漏了就等于没声明）；第 11 项就地标注「已被第 14 项推翻」——这张表是**历史**，不能倒着改写，只能标注 |
| 37 | **本地 788 全绿，是假的**（第 35 项那个修正当场炸出来的；CI 红、本地绿）。`_park_needs_human` 为了幂等去重开始**读评论流**——六个早就存在的 park 测试没给这条新路径打桩，于是它们真的 shell 出去调了 `gh issue view 5 --json comments`：开发机上 `gh` 是登录着的，真仓库里 issue #5 又真的在，读回来一切正常 → **测试绿得毫无破绽，只是它在读线上数据**。到了没有 `GH_TOKEN` 的 CI 才炸。测试套没有任何东西拦着它出网：一条新的 GitHub 读写路径，漏打桩的代价是**静默**的 | 补 `tests/conftest.py`：autouse 的**离网硬闸**，把 `subprocess.run` 包一层，`argv[0] == "gh"` 一律 `AssertionError`（其余如 git 原样放行；自己打桩 `subprocess.run` 的测试在 fixture 之后 setattr，天然覆盖本闸）。生产代码此后每多碰一次 GitHub，漏桩的测试都会在**开发机上**当场红，且直接指出是哪条 `gh` 命令。六个漏桩的 park 测试同时补上 `list_issue_comments` / `list_comments` 的桩 |
| 38 | **护栏二对整个 `solve` 阶段是死的**（第八轮，独立审查逐条对代码，HIGH）。`_sense` 只在 `if pr_number is not None:` 里往 `progress` 喂时间戳（head 推送、CI、PR 评论）；一个**还没有 PR** 的 `issue:N`（`solve` 的常态）永远走不进那个分支 → `progress` 恒空 → `last_progress_at` 恒 `None` → `_watchdog` 头一句 `if … clock.last_progress_at is None: return False` 直接短路。于是最该被兜住的那条链彻底裸奔：agent 跑 `solve` 没推出 PR（自己没意识到白干）→ fp 不变 → `_reconcile` 在 **issue** 上盖同-fp attempt 戳 → 生产者 `_consider` 降级 QUIET(awaiting-effect) → **永远**停在这里，看门狗算不出 age、needs-human 永不触发、没有人被叫来。护栏一（attempt 戳）只是止住烧钱，止不住卡死。这正是 §5 表「状态该动却不动 → 看门狗 → GitHub 时间戳」与 §Reference-3「`last_progress_at = max(…, 最新评论时间, 最新 attempt 戳时间)`」双双承诺、代码却没有的东西——spec-ahead-of-code | `_sense` 补一支 `elif kind == _KIND_ISSUE:`：无 PR 的 issue 也读 `list_issue_comments` 把评论时间戳喂进 `progress`（attempt 戳与人类评论都落在 issue 上）。看门狗自此算得出 age，QUIET(awaiting-effect) 超阈值 → needs-human。（不动 `latest_comment_is_ours`：无-PR issue 的人机对话归**准入面** admitter，reply 分支②要 PR 语境，此处不激活。）测试 `test_sense_clock_reads_the_issue_comments_when_there_is_no_pr_yet`：mutation 撤掉这支 → `last_progress_at` 回 `None`、断言当场红 |
| 39 | **认「谁回话」认了人，认「谁盖的戳」谁都不认**（第八轮，独立安全审查，HIGH）。`_human_replies` 查 `authorAssociation` 挡住路人，可**读戳**的 `_admit_verdict` / `_admit_tried` 只做裸子串匹配、一处没查。而标记串（`_ADMIT_VERDICT_MARK` 等）与签名 `<!-- openagents:agent=… -->` **都是公开可抄的文本**——公开仓库里任何 NONE 路人贴一条 `<!-- openagents:admit-verdict:approved:<维护者中性回话的评论 id> -->` + 抄一个签名，下一 tick `_admit_verdict` 就当成「上一轮已判过、approved」→ **零 LLM 直接放行**，绕过维护者闸和 admitter（第 32 项刚堵上的洞，从**读戳**这侧原样漏回来）。反向亦可：伪造一枚 try 戳把维护者**真的点头**强行打回 needs-human | 唯一伪造不了的是 `authorAssociation`（GitHub 按真实作者算、不进正文、路人写不进去）。新 `_is_our_stamp(comment)` = 维护者关联 **且** 带我方签名，两处读戳都先过它。我们的 bot 恰以维护者身份（能打 label/推分支/合并的账号必是 OWNER/MEMBER/COLLABORATOR）盖下这些戳，NONE/CONTRIBUTOR 伪造多少标记都过不了。fail-closed：关联读不到（空串）一律不认。两个 mutation 测试（伪造裁决戳不得放行 / 伪造 try 戳不得强推 park），撤掉闸即红 |
| 40 | 三处**已知边界、本轮不修**（第八轮审查提出，记录在案，不进代码）：(a) 维护者若**原地编辑**旧评论而非另发一条来改口——GitHub 保留 comment id 与 createdAt（只动 updatedAt），裁决戳挂在 id 上 → 旧 refused 戳继续命中 → 编辑后的点头永不重判。**fail-closed 安全**（不会误放行），且 park 文案已明写「**回一条评论**再摘 label」——编辑改口是逆着指引走。(b) 同一仓库跑**两个** vigil 生产者时，准入面的 try 戳是「读—判空—盖戳」非原子，两个进程可能各烧一次 LLM。**超出本 spec 部署模型**（单生产者 + K worker；执行面的 flock/SQLite 只护 worker，准入面在生产者独占的 `_producer_tick` 里）。(c) 第 39 项的 `_is_our_stamp` 认「我方戳」认的是**维护者关联**而非 bot 自己的 login——只在 `gh`-CLI-as-user 部署下自洽（能盖戳的 gh 账号必有写权、即 OWNER/MEMBER/COLLABORATOR）。本仓库**现无** GitHub-App token 路径（`_run_gh` 只 `gh` 裸调，全仓无 GH_TOKEN/installation），故不成问题；但**若将来引入 App 鉴权**，App bot 的 `authorAssociation` 可为 NONE 却仍有写权 → 我方自己的戳被静默拒 → admit 每 tick 重烧一次 LLM（§14/33 印钞机从**读戳**侧漏回，且**静默**降级而非报错）。届时应把闸从关联改绑 `comment.author == 本实例 login`（GitHub 按真实作者算、伪造不了，且更精确——一并修「维护者+**任意**签名≠恰是本 bot」这层松）。三者都不改：(a) 修它要引 updatedAt 当身份、反而把「同一句话别重判」的幂等搅乱；(b) 修它要给准入面加锁，为一个非支持的部署形态给主路径压成本；(c) 现无 App 路径，加 self_login 管道是为不存在的部署形态增复杂度。宁可**写清边界**也不无谓增复杂度（奥卡姆） |
| 21 | **年龄闸的取数取错了。** 原判据是 `enqueued_at` 超龄，可 `enqueued_at` 为了防饿死是**从不刷新**的（第 10 项就是这么定的）。而 `_requeue_or_park` / `_reclaim_dead` 都是先把 `status` 改回 `queued` **提交**、再 `os.close(fd)`——中间那一瞬是**合法**的「`queued` 且锁被持有」。于是一个跑了很久的行只要一被回队，它的 `enqueued_at` 早就「超龄」，正好在这个交接窗口里被判为泄漏、被 park。越是重试频繁的健康行，越容易被这道闸打死 | 年龄改成**跨 tick** 的记忆（`seen_locked: dict[subject, 首次观测时刻]`，由 `run_vigil` 持有并穿给生产者）：必须**两次不同的 tick** 都看见「`queued` 且锁被持有」才计时、超 `_STALE_LOCK_SECONDS` 才 park。交接窗口是进程内的微秒级瞬间，活不过一次 tick；锁一自由就把记忆抹掉（重新计时） |
| 22 | 一行 park 不成就掀桌：`_park_needs_human` 的 `gh` 抛异常（429 / 掉网）会一路逃出 `_sweep_stalled` → `_producer_tick` 整个死掉 → 这一轮**不 `_intake`、不感知、不入队**。一个限流把「扫陈锁」这件边缘事变成全线停摆 | 每行一个 `try/except`：park 不成就记日志、留着行、下轮再来（重试幂等）；并且**不重置** `seen_locked` 的首次观测时刻——一次 429 不该让陈锁的时钟从头再走 |
| 23 | `_drain_queue`（`--once` / 测试路径）不扫陈锁：泄漏锁的行永远是 `queued` 且永远领不走 → 排空循环干等满 `_DRAIN_MAX_SECONDS`(1h) 才靠硬上限退出 | 排空的轮询里也调 `_sweep_stalled`——该 park 的当场 park，`--once` 立刻收工 |
| 24 | 第 18 项的 park 理由把**推测写成了事实**（「上一轮已判 park 但 park 没落地」）：`attempts` 超上限还有别的来路——守夜进程被反复重启，`_reclaim_dead` 每次都把在跑的行打回 `queued` 并 `attempts+1`，一个**健康**的行也能被这样刷到上限。照原文写，交到人手里的第一句话就是误导 | 理由改为只陈述可证的事实（领取了 N 次、一次都没收工、上限是多少），成因**列举**而不断言 |

**审查纪律**：这张表是一条**修正在改修正**的链（第 31 项更是同一轮修正里当场自查出来的——`fail-closed` 的默认值若粘在一条旧裁决上，就从「谨慎」变成了「永久拒绝」）——第 13/15 项是第二轮审查的产物，第 17/18 项是第三轮对**那批修正**的反驳，第 20–24 项是第四轮对**第 17 项那道闸**的反驳，第 25 项又是第五轮对**第 20 项那道闸**的反驳（它堵了行、漏了 label）。每一轮的修正都比它所修的原代码更该被审：它是新写的、没被真正跑过的，而且往往正站在关键路径上——第 17 项引入的闸会 **park**，也就是会**停掉一个健康 issue 的活**，它的假阳性代价高于它要治的病，所以连着三轮都在打磨同一段几十行的代码。第 26 项是另一类：不是「改错了」，而是**正文承诺了、代码里根本没有**——只有把 spec 逐条拿去对代码，才会掉出来；而第 27–30 项正是第六轮对**第 26 项那次补实现**的反驳，且是这条链上最坏的一次：它不是让守夜停住，而是让它**在人明确否决之下开工**（把一道人闸接到了一个 fail-open 的 agent 上），外加一个「我方评论不签名 → agent 对着自己写的话开会」的自问自答环。规律很稳定：**每一轮修正里最危险的那一处，正是这轮新写的、还没被真正跑过的、且站在关键路径上的那几十行**。第 32–35 项是第七轮对**第 27–31 项那批修正**的反驳，坐实了这条规律：那批修正把人闸从「fail-open 的 agent」救了回来，却忘了给它**认人**（第 32 项：闸是 fail-closed 的，钥匙却挂在门外，任何路人都能开），并且第 29 项为省 LLM 而设的那枚戳，恰恰在 agent **判崩**这条路上完全不起作用（第 33 项：一条回复能烧掉无限次 LLM）——**为省钱写的护栏，漏掉的正是最烧钱的那条路**。第 31 项那次自查修正也没能活过一轮：它拿只到**秒**的时间戳当身份（第 34 项）。第 37 项则是这条链上最难堪的一次：第 35 项那个修正**当场**证明了「本地全绿」这句话本身就不可信——测试套没有任何东西拦着它出网，六个漏打桩的老测试一路读到了**线上真仓库**，绿得毫无破绽。测试的假阳性不是「测试写错了」，是**验收标准坏了**：它对着生产环境作证。故补一道离网硬闸（第 37 项），把这种绿从「静默」变成「当场红在开发机上」。第八轮换了打法：不再让「上一轮的修正」互相反驳，而是**两个独立审查各自把 spec 逐条钉到代码上**——一个专攻准入闸的安全不变式，一个逐条对账 spec 每一句承诺。两条线各自掉出一个 HIGH，且都不在前七轮的视野里：第 38 项是**正文承诺了、代码分支进不去**（§5 的看门狗对无-PR 的 solve 整段失效，与第 26 项同类但更深，因为它藏在一个 `if pr_number is not None` 的缩进里）；第 39 项是**同一个洞从对称的另一侧漏回来**（第 32 项刚在「谁回话」上认了人，「谁盖的戳」这侧却仍谁都不认）。规律再次坐实：最危险的从不是老代码，而是新写的、还没被真正跑过的、且站在关键路径上的那几处。每一条修正都由一条会随修正被回滚而变红的测试钉住（逐条做过 mutation 验证：回滚修正 → 对应测试必红）。

**测试**（791 全绿）：`tests/test_recipe_vigil.py`（分支表 / fp 不变式 / 真 `kill -9` 下的 flock 回收 / 一行 park 不成不掀掉整个生产者 tick / **无 PR 的 issue 也从 issue 评论流取进度时钟**——否则看门狗对整段 solve 失效）、`tests/test_recipe_vigil_act.py`（`_act` 逐分支路由 + 一等出口契约逐 agent 调用 + `_TimedBackend` 按认领桶精确杀 + 裸 PR worktree 不撞车）、`tests/test_recipe_vigil_queue.py`（认领 exactly-once / 队头不阻塞 / fd 零泄漏且**恰好关一次** / worker 异常隔离 / 振荡上限 / 坏边只 park 涉事者 / 回收不谎报 / 泄漏锁的 queued 行被扫出交人而长队列不误伤 / 陈锁判定必须跨 tick 且不误杀回队交接窗口 / park 期间被 worker 领走的行既不 park 也不删（TOCTOU）/ 排空路径也扫陈锁 / 超上限只重试 park 零 LLM 且理由只说可证的话）、`tests/test_utils_proc.py`（认领桶按线程隔离 + 真进程树 `kill_tree` + PID 复用不误杀 + 继承 fd 登记）、`tests/test_utils_github_vigil.py`（8 个新 github 读写函数的解析不变式）、`tests/test_agent_curator.py`、`tests/test_agent_admitter.py`、`tests/test_cli.py`、`tests/test_recipe_vigil_admit.py`（准入 `human` 三态的跨 tick 对话：只问一次 / 等人回话期间零 agent 调用 / 提问前的旧评论不算回话 / 人回话后才判、且判据走 **fail-closed 的 admitter** 而非 fail-open 的 triager / 裁决先盖签名戳再打 label——label 写失败时下一 tick 零 LLM 重试 / **refused 之后人再开口，旧裁决当场作废重判**（否则 fail-closed 退化成永久拒绝）/ park 的理由评论**带签名**——人只摘 label 不留言时，我们自己写的话不许被读成人的回话 / **路人的「可以，做吧」不算拍板**、也不进 prompt（人闸只认 OWNER/MEMBER/COLLABORATOR）/ **admitter 判崩时一条回复只烧一次 LLM** 然后转人工，且 try 戳盖不上时零 LLM / **同一秒里的两句话是两个回合**——戳挂 comment id 不挂时间戳 / 同一段 park 理由只贴一次 / **读戳这侧也认人**——路人伪造的裁决戳不得放行、伪造的 try 戳不得强推 park（唯一伪造不了的是 `authorAssociation`））、`tests/conftest.py`（**离网硬闸**：任何测试真的 shell 出去调 `gh` 一律当场 `AssertionError`——生产代码每多碰一次 GitHub，漏打桩的测试都在开发机上就红，而不是靠本机登录着的 `gh` 去读线上真仓库、假装绿）。离线 e2e：`scripts/e2e-spec-0065-graph-parallel-vigil.sh`（t0–t7 + grep/反射锚点：flock 非 lockf、`_mark_done` 是 DELETE、无租约列、recipes 零 subprocess 直调、自报 PID+句柄、flock fd 继承、陈锁闸的 BEGIN IMMEDIATE 复核 / DELETE 守卫 / 跨 tick 记忆 / 单行隔离 / 排空也扫、needs-human 契约注入全分支、`--parallel` 边界）。

## Drawbacks

**工程体量**

- **T2 是单文件重任务。** 「原地重写 vigil 为 level-triggered reconcile + 吸收旧串行 parity + DB 认领队列 + 改 CLI 指向」压在一个 Task / 一个 PR 里，体量大。这是「收敛到单文件 + 原地重写」的固有代价：`vigil.py` 是单写者文件，无法拆成多个并行 Task。若要更小 PR，唯一路径是拆成两个**顺序** PR（先 serial parity + 感知层，再叠队列 + 并行）。
- **vigil.py 变成大文件。** 两面 + reconcile 分支表 + fleet 全在一个文件。这是 Ousterhout 意义上的**深模块**（简单接口 `run_vigil` + 大量内联功能），优于摊成一堆互相纠缠的浅模块——但文件确实长。

**必须靠测试钉死的不变式**

- **`facts` 的字段集。** 它同时是 `_classify` 的输入和 `_fingerprint` 的哈希输入。加一个分支却忘了把它读的字段加进 `facts` → 该分支**静默永不触发**；反过来把 `clock` 混进 `fp` → 护栏一失效、agent 被反复叫起。代码结构（两个函数吃同一个不可变结构）挡住了大半，但必须有一条测试直接断言二者字段集相同，否则这个不变式只是纪律。
- **`facts` 里不许出现「worker 收工时会顺手改到」的字段。** fp 的规则是「任何真实推进都必然改 fp」，但**反向不成立**——存在改了 fp 却没推进的动作，最险的一个是 attempt 戳自己（它是一条新评论）。若 comment id 进了 fp，盖戳当场把戳改废 → 无限重叫 agent，**护栏一自毁成它要防的那个死循环**。故 `facts` 只留 `latest_comment_is_ours` 布尔。给 `_Facts` 加任何字段前先问：worker 收工时会不会碰它？测试：`_post_attempt_stamp` 前后 `_fingerprint` 必须相等。
- **`_reconcile` 调 `_classify` 必须传 `in_flight=False`。** worker 自己就是那个 in-flight 持有者，传 True 会让它领到活的第一件事就是判「有人在干」→ 立刻收工 → **每个 worker 都空转，系统一动不动**，而且日志里看起来一切正常（队列在流转、行在删）。这是个一字之差的致命默认值，必须有测试直接钉。
- **review 裁决 label 里的 sha。** 裸 `review-approved` 会在「审完 → agent 又 push 修 CI」后留在原地 → 分支⑪ 合并一份**没人审过的代码**，且不可逆。测试：head 前移后，同一枚 `review-approved:<旧 sha>` 必须让谓词落回⑩、绝不落⑪。
- **flock 的 fd 生命周期。** 锁绑在 open file description 上，**close 任何指向它的 fd 都会释放锁**——一个随手写的 `with open(...)` 就会让 worker 在干活途中丢掉自己的存活证明，行被 `_reclaim_dead` 判死回收 → 双跑，而且是静默的（没有异常、没有日志）。fd 必须显式从 `_claim_next` 传到 `_mark_done` / `_requeue_or_park`。这是本设计换来「零双跑」所付的**唯一**代价，且它能被测试钉住（见 T2 acceptance）。

**调参风险**

- **看门狗阈值是一把双刃刀。** 设窄了会把正常在跑的 CI 误判 STUCK → 误挂 `needs-human` → 反而卡住好 PR，比不看门更糟。缓解：阈值给足冗余（CI p95 × 3）、每仓可配、且 park 动作完全可逆（只加 label + 评论，人摘掉即复活）。但「合适的阈值」仍需实测，列入 Unresolved。
- **`awaiting-effect` 的宽限期会拖慢真正撞墙的 case。** agent 判「flaky，不改」之后，要等阈值（~5 分钟）才 park 叫人。这是为吸收异步生效窗口付的代价。缓解：agent 可主动打 `needs-human` 走快路径。

**功能取舍的代价**

- **`reply` 被同-subject 互斥挡在长任务后面。** 人在一个正跑着 40 分钟 solve 的 PR 下留言，要等 solve 让出 slot 才被回。这是 `subject UNIQUE` 换来的串行安全的直接代价。可接受（回话不是硬实时），但要如实记账。
- **LLM 排依赖有成本与不确定性。** 每来新 issue 调一次 LLM，比纯机械慢、且可能排错。缓解三层：已有边锚点固定；validate 硬闸（环 / 引用）；且**排错只影响调度顺序、不影响正确性**——`deps_done` 是机械复核 GitHub 现态的，图排错顶多少并行一点。
- **curator 的「全量重排」被约束成「受锚增量」。** 依赖边是人机共写的可变真相，curator 不能整张覆盖（会抹掉人手设的边）。好处是与人协作自然；代价是 curator 纠不了自己上一轮排错的既有边（需人在 UI 改）——列入 Unresolved。

**规模与边界**

- **每轮 1+N 次依赖读取 + 每 subject 一次 `_sense`。** 规模大时累积，且 GitHub REST 认证配额是 5000 请求/小时。几十 subject 无感；上百时需批量化（见 Future 的 GraphQL）。
- **并行放大共享资源竞争。** K>1 时多 worker 抢同一 `.git`、并发写 RuntimeState（#137 明列的风险）。以「subject 为并发单元 + 每 worker 独立 worktree」隔离，但共享裸 `.git` 锁需在 e2e 实测兜住。
- **SQLite + flock 把部署钉在单机。** 见 §12：跨网络文件系统会数据损坏（sqlite.org 明文），且 NFS 上 flock 语义失效。多机需换 claim 后端（git-ref CAS 或 Postgres），且零双跑保证会退化回租约。这是明确的 scale 边界，不是当前问题——但它是**部署形态的硬约束**，不能事后再想。
- **新增一个存储实体。** `.openagents/vigil-queue.db` 看似违反「如无必要勿增实体」。Guide §6 已论证它只存 GitHub 表达不了的三样（原子认领 / 崩溃计数 / 领取定序），且丢了无害（一 tick 重建）。代价压到最小：stdlib `sqlite3`、单文件、零外部服务，schema 一张表九列。

## Rationale and alternatives

**感知模型**

- **level-triggered（无历史谓词）vs 变更检测（记住上一轮状态，变了就叫 agent）。** 取 **level-triggered**（约束 C4）。变更检测有四个不可修的洞：(1) **边沿会丢**——进程崩在「检测到 CI 变绿」和「真的合并」之间，快照已被覆盖成「绿」，下一轮 diff 为空 → PR 永远不会被合并；(2) **agent 自己的写就是变更**——push / 打 label / 发评论都会触发下一轮，需在每一处加「忽略我自己」的过滤器，漏一处就是一个烧钱死循环；(3) **哈希漏一个字段 = 永久瞎掉一整类活**——最典型的是忘了 `mergeable_state`：base 前移导致 PR 变冲突时，评论没变、commit 没变、CI 结果没变 → 零边沿 → 永不触发；(4) **依赖前沿的变化不在 subject 自己身上**——B 合并了，A 的状态一个字节都没变，per-subject 变更检测完全看不到，整个 issue graph 卡死在第一个节点。K8s 那条原则（"Edge-triggered behavior must be just an optimization"）说的正是这个。
- **变更检测保留在哪。** 它作为**优化**保留下来了，但改了两处语义：存的不是「上一轮轮询到的状态」，而是「**我出手时看到的状态**」；写入时机不是轮询时，而是 **agent 收工时**；且存在 **GitHub**（attempt 戳）而非本地。这两处改动同时修掉洞 (1)（崩溃 → 没盖戳 → 下轮重试）和洞 (2)（fp 是我出手时的输入态，我的产出让 fp 变了也不会触发自己）。
- **`_Observed` 拆 `facts` / `clock` vs 一个扁平结构。** 取**拆开**。`clock` 若混进 `fp`，一个 check run 开始跑就会刷新 `started_at` → fp 变 → agent 被重叫，尽管分支表根本不看这个字段。拆开之后「fp 字段集 ≡ 分支表输入集」才是一条能写成测试的不变式。

**事件模型**

- **一 subject 一行 vs 一行一事件（`kind` = solve/advance/reply）。** 取**一 subject 一行**。`kind` 是 GitHub 现态的一份拷贝（「这个 PR 现在处于什么阶段」），而现态每 tick 都要重读——按本 spec 自己的存储原则（无重叠、无对账），它不该存在。而且它买不到任何并行：三类事件对同一 subject 本来就必须串行，所以「一行一事件」还得额外用 `_claim_next` 的 `NOT EXISTS` 子查询把并行**再收回来**——它制造了一个只有它自己才需要解决的问题。砍掉 `kind` 后，`dedup_key`、`NOT EXISTS`、`ix_work_queue_issue_status`、`_execute` 的三路分派一起消失，而 `subject UNIQUE` 一根柱子同时给出去重、串行、幂等。
- **三趟扫塌成一张分支表 vs 三种事件类型。** 取**分支表**。三趟扫看着是三件事，其实是同一个问题（「这个 subject 现在该做什么」）的三个切面——证据是旧串行 vigil 的 `advance_merge` 已经是这张表的 ⑤–⑪ 段。
- **worker 推进到卡住 vs 一 tick 推一步。** 取**推到卡住**。一个全绿的 PR 应该在一次认领里合掉，而不是烧三个 tick。停止条件是「verdict 非 ACTIONABLE（卡在外部）或 fp 不再变（自己推不动）」——两者都是纯函数判断，不需要计数器。

**收口与护栏**

- **agent 自己打 `needs-human`（一等出口）vs 全靠机械护栏兜。** 取**一等出口**。agent 判断没辙时自己打 label + 留理由，是最快、最准、最便宜的收口：不烧多余的 LLM 调用、不等任何超时阈值，理由是它自己写的（比机械诊断信息量大得多）。这条契约写进每个分支的提示词。**前一版把它写成一句脚注（「那是快路径」），主叙事线全压在 fp 戳 + 看门狗上——错位了：那两个应该是兜底。**
- **那为什么不能把 fp 戳一起砍掉，全靠 agent 自己叫人？** 因为它**只覆盖「agent 知道自己没辙」**。剩下一类是 **agent 不知道自己在空转**：它 rerun 了 CI 但没触发成功、改了个无关文件、发条「等 CI 重跑就好」的评论就收工——它不觉得自己没辙，**所以不会打 `needs-human`**。而它每轮留的评论还会**刷新 `last_progress_at`，让看门狗也永远不响**。这时候除了机械比对「你出手前后 GitHub 上有意义的字段变了没」，**没有任何东西拦得住它无限重跑**。fp 戳的价值就在于它**不信任 agent 的自我判断**。
- **fp 戳用「有 / 无」一个 bit vs 计数（试 N 次才 park）。** 取**一个 bit**。fp 没变 ⟺ 分支表关心的每个字段都没动 ⟺ 零进展——同证据同 prompt 再叫一次，期望收益接近零。而 park 是廉价可逆的（人摘 label 即复活），早叫人几乎没代价。真正的瞬时故障重试属于 **agent 内部**的事，不该冒泡成编排层的一个可调参数。
- **`awaiting-effect` 用时间阈值 vs 立即 park。** 取**时间阈值**。因为 **fp 没变 ≠ 零进展**——它只意味着「我还没看到进展」。agent push 完但 GitHub API 还返回旧 head（最终一致性）、agent 触发了 CI rerun 但 check 还没翻 pending……这些情况下立即 park 会误杀真的在干活的 agent，比不 park 更糟。
- **看门狗的 age 从 GitHub 时间戳算 vs 本地计时。** 取 **GitHub 时间戳**。时间本身就是当前态的一部分（每个 GitHub 对象都自带），所以「卡了多久」是**当前态的纯函数**，不需要任何本地记忆——重启、丢库、换机器都不影响。而且 head 一变，`last_progress_at` 自动刷新、计时归零。
- **`attempts` 为什么不能一起砍。** 它管的是**在 GitHub 上不留痕的死法**：agent 崩了 / 被 kill——它没盖戳（没收工），也没刷新任何时间戳。fp 判不出来，age 也判不出来。只能在队列行里数。

**认领与回收**（本 spec 分歧最大的一处）

- **`flock`（观测死亡）vs 租约（猜死亡）。** 取 **`flock`**。租约是从沉默里推断死亡，而沉默有两个成因——「进程死了」和「agent 正在写一个大 feature」——**任何超时阈值都无法区分它们**。阈值窄 → 误判活着的 worker 已死 → 回收它的行 → 双跑；阈值宽（v0 的 1 小时）→ 真崩的 subject 静默停摆一小时。而 `flock` 由**内核**在进程死亡时（含 `kill -9` / OOM / 断电）自动释放，「抢得到锁」就是「持有者已不在」的**证明**，不是推断。于是双跑概率从「阈值调好了就很小」变成**结构性的零**，且崩溃恢复延迟从「一个租约」降到「一个 tick」。代价：把部署钉在单机——但 §12 的 SQLite 禁令**本来就已经**把它钉在单机了，flock 没有引入任何新约束。
- **`flock` vs PID 探测（`os.kill(pid, 0)`）。** 取 `flock`。PID 会被**复用**：重启后新进程恰好拿到旧 PID → 被误读成「持有者还活着」→ 该 subject 永久卡死。堵这个洞要额外存进程创建时间比对（`psutil.Process.create_time()`），即为了补一个 `flock` 根本没有的洞而引入第三方依赖。`worker_pid` 列仍保留，但只作人工诊断（能 `ps` 到它），不参与任何裁决。
- **必须 `flock`、不能 `fcntl.lockf`（POSIX `F_SETLK`）。** 后者的锁是 per-process 的，同一进程内两个 fd 对同一文件加锁不互斥——而本 spec 是「一进程 K 线程」，用 `lockf` 会让同进程内的互斥**静默失效**。`flock` 的锁绑在 open file description 上，同进程不同 `open()` 之间照样冲突。这不是风格，是正确性。
- **卡死（活着但不推进）为什么不能靠回收解。** 「回收一个活着的持有者的行」**定义上就是双跑**。所以卡死走两条不回收的路：`_act` 硬超时（持有者自己杀掉 agent、自己释放行与锁）+ IN_FLIGHT 看门狗（只 `_park` 叫人、绝不动行）。这条不对称——只有死者的行可被回收，活人的行只能由它自己或人来处置——是零双跑的最后一根柱子。

**架构分层**

- **不新开 recipe 模块 vs 为 intake / scheduler / graph 各开一层。** 取**全内联进 vigil**（约束 C5）。上一批刚把 recipes 从 6 个收敛到 3 个；再摊三个新模块 + 两套 vigil 并存 = 逆行收敛、净增死代码。
- **原地重写 vigil vs 新开 vigil2 双栈并存。** 取**原地重写**——CLI 出口只有一个 vigil，无延后债。重写期一度把旧实现另存为 `vigil_backup` 作参照物，收口时**删除**：它零调用方、零覆盖，留着就是一个被永久钉进架构图的死模块，而 git history 已经是更好的回退点。
- **curator 放 agents/ vs 内联进 vigil。** 取 `agents/curator.py`。agents/ 层的约定是「零逻辑 Template 提示词」，recipes/ 层是控制流——把提示词塞进控制流文件才是破坏分层。
- **提示词放 agents/*.py vs Claude Code skills。** 取 `agents/*.py`。skills 是 Claude Code 私有的，而 CLAUDE.md 要求后端兼容 claude code / codex / nexau——提示词必须留在能被 `engine.run_agent` 喂给任意后端的地方。

**状态量落哪：label vs 原生字段**

- **「决定」落 label，「事实」读原生。** 取**分开**。`ready` / `needs-human` / review 裁决都是**我们做的决定**——GitHub 没有别的地方表达它们，而 label 在 UI 上一眼可见、人可手动增删（这就是自愈的入口）。反过来，CI 结果与 `mergeable_state` 是 **GitHub 自己维护的事实**：本就绑在 sha 上、一次读到。把它们也复制成 label（「所有状态量都打 label」）是**造第二份真相**，然后要负责让两份不打架——CI 重跑了谁去改 label？漏改一次就是一个静默的错判。这违背本 spec 自己的存储原则（无重叠、无对账）。
- **review 裁决的 label 必须带 head sha。** 取 `review-approved:<sha7>` 而非光秃秃的 `review-approved`。裁决不是恒真属性，是**绑在某个 commit 上的判断**：审的时候 head 是 `abc1234`，审完 agent 又 push 了 `def5678` 去修 CI——裸 label 还挂着 → 分支⑪ 读成「全绿 + 审过了」→ **合并一份没人审过的代码**，而合并不可逆。带 sha 后 head 一动裁决自动作废、落回⑩重审。这是 GitHub 原生 PR review（天生绑 `commit_id`）白送的性质，用 label 复刻它换来「人在 UI 上一眼看见审到哪个 commit」；将来若改用原生 PR review（见 Future），这层复刻可以撤掉。

**依赖边**

- **存哪：GitHub 原生 dependencies vs 自定义 label vs 本地 graph.json。** 取**原生 dependencies**（已实测本仓端点可用）。原生给了专有命名空间、结构化读取（直接返回含 `state` 的 blocker）、webhook + UI、人机同处共写。自定义 label 要防命名冲突 + 解析字符串；本地 graph.json 要与 label 双存储对账。
- **谁来排：LLM vs 纯机械（文件重叠静态分析）。** 取 LLM（约束 C1）。纯机械只能捕「文件冲突序」，捕不到「逻辑序」（A 定义接口、B 才能用，两者可能不碰同一文件）。文件冲突序留作 `priority_fn` 的机械补充（见 Future）。
- **图更新：受锚增量 vs 无约束全量重排。** 取**受锚增量**（约束 C2 所迫）。既有边（含人设边）是不可覆盖的锚点。

**队列**

- **落 DB vs 内存 `queue.PriorityQueue`。** 取 SQLite。内存队列给不了原子领取（约束 C3）、崩溃持久、领取时定序。
- **SQLite vs Postgres vs GitHub label。** 取 SQLite（stdlib，零外部服务）。GitHub label 出局的理由不是「存不下」而是**没有原子性**：REST 对 POST/PUT/PATCH/DELETE 不支持条件请求，且 label POST 是追加语义——两个并发认领都成功、都不报错。Postgres 是多机时的选项（见 §12），但本 spec 不预先付费。
- **`_claim_next` 去掉 `NOT EXISTS` 子查询。** 同-subject 互斥已由 `subject UNIQUE` 在入队时结构性保证，领取时再查一次是纯冗余。这是「一 subject 一行」相对「一行一事件」的直接红利。
- **`_mark_done` 必须 DELETE、不能 `status='done'`。** UNIQUE 约束下留着 done 行会让该 subject 永远无法再入队 → PR 死锁。这条不是风格，是正确性。

**调度**

- **前沿：逐节点本地谓词 vs 全图拓扑排序。** 取**本地谓词**（直接 blocker 全 merged）。传递依赖随 merge 自然涌现（A→B→C 中 C 只在 B merged 后解锁，而 B 又只在 A merged 后才可能 merged）。环检测才需扫全图，放在 validate 里一次性做。
- **顺带纠一个设计债。** 旧 `vigil.py` 用 `route(*, owner, on_agent, on_human, on_skip)` 高阶函数 + 一批纯转发工厂——接口和实现一样复杂的**浅模块 + 纠缠**。新 vigil 按深模块立骨架：分支表从上读到底。

## Prior art

**执行面的形状（level-triggered + workqueue）**

- **Kubernetes 架构原则：level-triggered 是正确性、edge-triggered 只是优化** —— *"Functionality must be level-based, meaning the system must operate correctly given the desired state and the current/observed state, regardless of how many intermediate state updates may have been missed. Edge-triggered behavior must be just an optimization."* 这是本 spec 执行面的**第一原理**（约束 C4）。https://github.com/kubernetes/design-proposals-archive/blob/main/architecture/principles.md
- **client-go 控制器的 workqueue：队列里只放 KEY，不放对象** —— Reflector → DeltaFIFO → Informer → WorkQueue（去重 + 限速）→ N workers → `processNextWorkItem`；worker 领到 key 后**回 Indexer 重新取当前对象**。正因为队列里只有 key，去重才是无损的。**这正是本 spec「队列里只放 `subject`、worker 领到后 `_sense` 重新读 GitHub」的出处**——`kind`/`dedup_key` 那一版把「对象」塞进了队列，违背了这条。Informer 的周期性 resync（全量重列）则对应本 spec 的每 tick `_sense`。https://github.com/kubernetes/sample-controller/blob/master/docs/controller-client-go.md
- **Airflow pools + `priority_weight`** —— pool 的 slot 数限并发，`priority_weight` 在可运行集内定序。对应本 spec 的「K 槽 bounded pool + `priority_fn` 落 `work_queue.priority` 列」。https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/pools.html

**依赖边落 GitHub**

- **GitHub 原生 issue dependencies（2025-08 GA）** —— `blocked_by` / `blocking` 成为一等公民，全 REST API + webhook + UI 侧栏。本 spec 的依赖边存储直接落它。https://github.blog/changelog/2025-08-21-dependencies-on-issues/ ；API：https://docs.github.com/en/rest/issues/issue-dependencies
- **GitHub REST 不支持不安全方法的条件请求** —— *"Conditional requests for unsafe methods, such as POST, PUT, PATCH, and DELETE are not supported unless otherwise noted."* 加上 label POST 的**追加**语义（"adds labels to an issue's existing labels"），这两条合起来就是「GitHub 上做不了认领」的完整论证（约束 C3）。GitHub 仅有的两个 CAS 原语是 `POST /git/refs`（ref 已存在则失败）与 `PUT /contents/{path}`（必填 `sha`，stale 则 409）——都不在 issue 元数据上，但前者是 §12 多机 claim 的落点。https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api

**队列与认领**

- **DB 作持久工作队列** —— 一张表 + 事务原子领取（Postgres `SELECT … FOR UPDATE SKIP LOCKED` / SQLite `BEGIN IMMEDIATE` + `RETURNING`）替代内存队列，换来崩溃持久 + 领取时定序。Postgres SKIP LOCKED：https://www.postgresql.org/docs/current/sql-select.html ；SQLite WAL：https://www.sqlite.org/wal.html ；`RETURNING`：https://www.sqlite.org/lang_returning.html
- **Multica 的 `agent_task_queue`** —— 一个「云端控制面编排 + 本地 daemon 执行面领活」的多 agent coding 系统：`ClaimAgentTask` 用 `UPDATE … WHERE id=(SELECT … FOR UPDATE SKIP LOCKED) RETURNING *` 原子领取、`prepare_lease_expires_at` 做 SQS 式可见性超时、`MaxConcurrentTasks` + slot 信号量双层背压。本 spec 的 `_claim_next` / `attempts` 直接对标。**两处差异**：(1) Multica 是多 daemon **进程**领同一队列，故必须 Postgres；本仓单机 K 线程，用 SQLite `BEGIN IMMEDIATE`。(2) Multica 用**租约**回收，本 spec 不用——租约是猜死亡，会在「误杀活着的 worker（双跑）」与「真崩了停摆一个租约」之间二选一；单机拓扑下 `flock` 能让内核直接给出答案，故取之（见 Rationale）。（内部系统，源码学习记录）
- **`flock(2)`：锁绑在 open file description 上，随 fd 全部关闭而释放** —— *"Locks created by flock() are associated with an open file description (see open(2)). This means that duplicate file descriptors (created by, for example, fork(2) or dup(2)) refer to the same lock…"*，而释放条件是 *"the lock is released either by an explicit LOCK_UN operation on any of these duplicate file descriptors, or when all such file descriptors have been closed."* **进程终止时内核会关闭它所有的 fd**，故锁被无条件释放——`kill -9` / OOM / 段错误 / 断电重启一律适用，进程没有机会「忘记」释放。这就是本 spec **零双跑**的根基：「抢得到锁」= 「持有者已不在」的证明，而非推断。
  同页也直接支撑「同进程 K 线程照样互斥」这条关键性质 —— *"If a process uses open(2) (or similar) to obtain more than one file descriptor for the same file, these file descriptors are treated independently by flock(). An attempt to lock the file using one of these file descriptors **may be denied by a lock that the calling process has already placed via another file descriptor**."* 即：各 worker 各自 `open()` 自己的 fd，同进程内照样冲突，正是我们要的。（对比 `fcntl(2)` 记录锁——man page 明言 *"flock() and fcntl(2) locks have different semantics with respect to forked processes and dup(2)"*，其锁是 per-process 的，同进程多 fd 不互斥 → 在「一进程 K worker 线程」的模型下会**静默失效**。这是选 `flock` 而非 `lockf` 的硬理由。）https://man7.org/linux/man-pages/man2/flock.2.html

**部署边界**

- **SQLite 官方：不要跨网络文件系统共享同一个库** —— *"file locking logic is buggy in many network filesystem implementations… resulting in corruption."* 这条把本 spec 的部署边界钉死在**单机多进程**（§12）。https://www.sqlite.org/whentouse.html ；https://www.sqlite.org/useovernet.html
- **`flock` 在网络文件系统上是「模拟」而非原生** —— *"Since Linux 2.6.12, NFS clients support flock() locks by emulating them as fcntl(2) byte-range locks on the entire file."* 一旦退化成 `fcntl` 字节范围锁，「同进程多 fd 互斥」的性质就不再成立，K 线程模型的互斥会静默失效。与 SQLite 的禁令是同一条边界。https://man7.org/linux/man-pages/man2/flock.2.html

**其他**

- **LangGraph** —— 把工作流建成图，支持运行期 `add_node` / `add_edge`、环、并行 fan-out，图本身可被 LLM 编排成「活图」。对应本 spec 的 curator。https://langchain-ai.github.io/langgraph/concepts/low_level/
- **Ousterhout《A Philosophy of Software Design》** —— 深模块（简单接口 + 大量功能）优于浅模块。指导「两面全内联进 vigil 的深函数」（约束 C5）。https://milkov.tech/assets/psd.pdf

## Unresolved questions

**阈值（全部需实测）**

- **看门狗阈值默认值** —— `awaiting-ci` 该取多少（提议 CI p95 × 3，但 p95 需实测）；`awaiting-mergeability`（提议 3 分钟）；`awaiting-effect`（提议 5 分钟，需覆盖 GitHub push 后的最终一致窗口 + CI rerun 翻 pending 的延迟）。设窄了会误杀正常在跑的 CI，比不看门更糟。
- **`awaiting-blockers` 该不该有阈值。** 默认关（上游 blocker 有自己的看门狗，重复计时只会误杀）。但成环（curator 误排 A↔B）时两者恒 QUIET，只由 `_hang` 打聚合提示——是否该给一个很长的（如 24h）兜底阈值把成环的 subject 直接 park？
- **`_AGENT_TIMEOUT_SECONDS` 取值**（提议 30 分钟）—— 单次 agent 调用的硬墙钟上限。设窄了会砍掉正常的大 feature（agent 自己重试即可，代价是一次 `attempts`）；设宽了卡死的 agent 会占着 slot 更久。注意 `_reconcile` 会「推进到卡住」、可能连调多次 agent，故**单次上限不等于单 subject 上限**——总时长由 IN_FLIGHT 看门狗（`_INFLIGHT_ALARM_SECONDS`，提议 2h，只告警不回收）观测。
- **`_MAX_ATTEMPTS` 取值**（默认 3），以及 `_reconcile` 抛异常（真失败）与 worker 崩溃（无痕）是否该区分计数。
- **优先级默认权重** —— §10 给了一个可解释的默认（`reply > merge > review > e2e > fix-ci ≈ rebase > solve`），但「先收尾在制品」的偏置强度、以及是否加入 aging 因子，待实测。契约已定：返回整数（`ORDER BY priority DESC`）。
- ~~**租约时长与心跳续租**~~ —— **已关闭**。租约整个被 `flock` 取代（Guide §5.3）：回收不再依赖任何超时阈值，故「租约多长」「要不要心跳续租」两个问题一起消失。`CLAIM_LEASE_SECONDS` 常量删除。

**待定形**

- **`facts` 字段集不变式的测试形态** —— 如何写一条测试直接断言「`_fingerprint` 哈希的字段集 == `_classify` 读的字段集」？（选项：`_Facts` 是 frozen dataclass，`_fingerprint` 哈希 `dataclasses.fields()` 全集，再用一条测试断言 `_classify` 对每个字段的扰动都可能改变 verdict。）待 T2 定形。
- **共享 `.git` 锁的并发策略** —— K>1 时多 worker 对裸 `.git` 的串行化粒度（全局锁 vs per-worktree fetch），需 e2e 压出边界（对齐 #137 明列的风险）。
- **curator 纠正既有错边的通道** —— 受锚增量下 curator 不能改既有边。走「人在 UI 手改」，还是给一个显式「重排指令」旁路？
- **attempt 戳的可见性噪音。** 每个撞墙的 fp 会在 PR 下留一条评论。上限天然存在（同 fp 一条，fp 变 = 真有新情况），一个正常 PR 约 3–6 条——恰是人想看的工作日志。但若 fp 因某个高频字段频繁变化（如某个 check 反复 flaky 翻转），戳会堆积。需实测 fp 的实际变化频率。
- **`_hang` 的提示去抖** —— 前沿持续为空时每轮都打提示会刷屏，需一个「状态未变则静默」的去抖（可仿 review 的 sticky-pass 指纹）。
- **T2 是否拆两个顺序 PR** —— 单文件重任务是否拆成「serial parity + 感知层」/「加队列 + 并行」两个顺序 PR。两种都不产生「两套 vigil 在 CLI 出口并存」。
- **Windows 不支持 `fcntl`。** 本仓开发在 macOS、CI 在 Linux，故 v1 不处理。若将来要支持，替换点仍是那 4 个 claim 函数（`msvcrt.locking` 或换 PID + create_time）——但注意 PID 方案会重新引入 PID 复用的洞。

## Future possibilities

- **多机拓扑：claim 换成 GitHub git-ref CAS。** §12 已定位原语（`POST /git/refs`，ref 已存在则失败）与替换点（4 个 claim 函数）。队列本身不需要跨机共享——两个进程各自 `_sense` 会独立推导出同一个前沿。注意零双跑的保证会退化回租约。
- **GitHub Notifications API 作「早醒」信号。** `GET /notifications` + `If-Modified-Since`（304 不计配额）+ 遵守 `X-Poll-Interval`，可以在有新评论 / CI 完成时提前唤醒一次 tick。这**只能是优化**：`ci_activity` 通知只发给触发 run 的人、默认关、且有「仅失败时通知」模式（CI 绿可能什么都不发）。真相仍是 `_sense`。恰是 client-go 那个「watch 腿 + resync 腿」的形状。
- **GraphQL 批量 `_sense`。** 一条 query 拉多个 subject 的 PR + checks + reviews + `blockedBy`，把每 subject 一次 REST 往返塌成个位数——直接缓解 5000 请求/小时的配额压力。
- **review 裁决改用原生 PR review（而非普通评论）。** PR review 天生绑在 `commit_id` 上，head 一动裁决自动作废——「证据溯源戳」白送，不用自己在评论里嵌 head_sha。
- **多仓 fleet 并行** —— 把 `run_fleet` 的「每仓一次 `run_vigil`」收编进同一个 K 槽池，跨仓统一调度。
- **文件冲突序进调度** —— 把静态文件重叠分析喂进 `priority_fn`，让「会写同一文件的 issue」错峰跑，顺带硬化 issue #71 提出的运行期 owner 检查。
- **STUCK 的自愈** —— 看门狗现在只 park 叫人。将来可对特定成因自愈（`awaiting-ci` 超时 → 调 API rerun workflow / 推空 commit）。但成因太杂（Actions 禁用、workflow 语法错、base 配错、GitHub 挂了），盲目自愈只会制造噪音——先观察真实分布。
