---
number: "0058"
title: 跨 issue 调度：agent 语义排依赖（逻辑+文件冲突）→ blocked-by 标签 + 本地 DAG 拓扑图
issue: 150
slug: issue-scheduler
summary: 派一个调度 agent 读所有已出 RFC 的 open issue，语义判读跨 issue 依赖（逻辑前提 + 文件冲突），产出 DAG；把边落成 blocked-by:#N 标签（派生 sched-ready），本地渲拓扑图 PNG；实现派单据未满足的 blocked-by 门控，能并行尽量并行。独立 openagents schedule 命令 + vigil 每轮可调保鲜。
tasks:
  - id: T1
    title: scheduler 核心：可控提示词 + plan 判读 + reconcile 标签差分（纯逻辑）
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/scheduler.py
      - tests/test_scheduler.py
    scope: '新建纯逻辑模块 scheduler.py（镜像 align/issuecheck：无 IO、backend 注入）：可控提示词 _SCHEDULE_TASK 指示调度 agent 读各 issue 标题/正文/RFC，判读两类跨 issue 依赖边（逻辑前提：A 建的接口/模块 B 要用；文件冲突：两 RFC files 分配有交集须串行），按固定标记回吐『边：#下游 <- #上游（理由）』；plan(*, specs, backend)->SchedulePlan 派单+解析成 Edge/SchedulePlan 冻结 dataclass；reconcile(*, plan, open_numbers, labels_by_issue)->list[LabelDiff] 纯算 blocked-by:#N（剪掉已关上游）+ 派生 sched-ready 的加/删；常量 SCHED_READY_LABEL、helper blocked_by_label(n)/parse_blocked_by(labels)/is_blocked(labels)。解析 fail-open（判不出边→无边放行，不凭空造依赖）。'
    acceptance: '喂三 issue 样本（#150<-#134/#141、#151<-#134）+ 返回三条『边：』行的 backend 桩 → plan 出 3 条 Edge、nodes 含全部；reconcile 对 #150 出 add blocked-by:#134/#141 且无 sched-ready，对源节点 #134 出 add sched-ready；标记 #134 已关后 reconcile 剪掉相关边、下游转 sched-ready；空/跑偏桩 → 无边(fail-open)；模块不 import github/argparse；ruff+pytest 全绿。'
  - id: T2
    title: scheddiag：SchedulePlan → graphviz DOT → 本地 DAG PNG（安全降级）
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/scheddiag.py
      - tests/test_scheddiag.py
    scope: '新建 scheddiag.py（镜像 conflictdiag：渲染与 IO 解耦、安全降级）：render_dot(*, plan)->str 把 SchedulePlan 渲成 graphviz DOT（节点=issue #N、边=上游→下游、ready 节点着色区分）；write_graph(*, plan, out_path, run) 注入 run 跑 dot -Tpng 出 PNG，dot 不可用/失败则安全降级为落 .dot 源文件、不抛（渲图只是成果展示，绝不因缺 graphviz 拖垮排程主流程）。'
    acceptance: 'render_dot 对样本 plan 出合法 DOT（含各 #N 节点、每条 upstream->downstream 边、ready 节点样式）；write_graph 注入假 run 断言调 dot -Tpng -o <out>；假 run 抛错时降级写 .dot 且不抛、返回降级路径；不 import github/argparse；ruff+pytest 全绿。'
  - id: T5
    title: vigil 保鲜钩子：每轮 discover 后调注入的排程回调（默认 no-op，零回归）
    status: pending
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/vigil.py
      - tests/test_vigil_schedule_hook.py
    scope: vigil 每轮发现段之后调一次『排程保鲜』以让 DAG 标签跟上最新合并：Vigil.__init__ 加可注入 schedule 回调（默认 no-op，保既有构造/行为逐字节零回归），_run_one_round 在 discover_and_dispatch 与 messages.poll 之间调它，纳入 per-round except 隔离（排程失败只记一行、不拖垮守夜）。真实回调由 cli 的 vigil 工厂注入（T3）。
    acceptance: 注入假排程回调的 Vigil 单轮 → 回调在 discover 之后、poll 之前恰调一次；回调抛错被隔离(记日志/不掀翻守夜)；未注入(默认 no-op)时行为与既有逐字节一致(零回归)；ruff+pytest 全绿。
  - id: T3
    title: cli schedule 子命令：拉 issue→映射 spec→plan→reconcile→落标签→出图 + 注入 vigil 回调
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: 'cli 加 schedule 子命令：github.list_issues 拉带发现标签 open issue → 按 docs/specs/*.md frontmatter issue: 字段映射出『已出 RFC』的可调度 issue（无 spec 的跳过并提示待起草）→ scheduler.plan(backend 注入) → reconcile → 逐条 github.ensure_label + issue_add_label/issue_remove_label 落标签 → scheddiag.write_graph 出本地 PNG（默认 issue-dag.png）→ 回显边表+ready 清单+图路径；--dry-run 只算不落标签、仍渲图。同时把上述端到端排程封成回调注入 vigil 工厂 _vigil_for（T5 的 schedule 钩子），使守夜每轮保鲜。'
    acceptance: openagents schedule 走『拉 issue→映射 spec→plan→reconcile→落标签→出图』全链（monkeypatch github/backend/scheddiag 断言标签操作与出图调用）；无 spec 的 issue 被跳过并提示；--dry-run 不调 issue_add_label/issue_remove_label 只打印计划+渲图；vigil 工厂注入的排程回调可被调用；test_cli 全绿。
  - id: T4
    title: messages 实现门控：被 blocked 的 issue 停在 rfc-review 等上游（enforcement）
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages_schedule_gate.py
    scope: 在 _process_rfc_review 派 implement 前插一道调度门控：取该 PR 对应 issue 的当前标签，scheduler.is_blocked(labels) 为真（仍有未满足 blocked-by:#N）则本轮不 implement、停在 rfc-review 等上游（与 hold-spec 同款『停在闸门』语义，产出 sched-blocked 事件），下轮上游合并后 blocked-by 被 reconcile 剪掉即自动放行。只在 implement 分支前置本闸，不改既有 hold/skip 闸、不改 implement 本身。
    acceptance: 带 blocked-by:#134 标签的 issue 的 PR 过 rfc-approved → _process_rfc_review 不调 _report_implement、返回 sched-blocked、停在 rfc-review；无 blocked-by（或 sched-ready）→ 照常 implement（零回归）；上游关闭、标签被剪后重 poll 正常 implement；ruff+pytest 全绿。
  - id: T6
    title: 端到端离线脚本：打桩 backend/gh/dot 跑通 排程→落标签→出图 与 门控放行两路径
    status: pending
    priority: P2
    tags: []
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0058-issue-scheduler.sh
    scope: 新增离线 e2e 脚本（沿用两段式：默认离线确定性，OPENAGENTS_E2E_REAL=1 追加真实冒烟）：打桩 backend/gh/dot，跑通『多 issue 想法+RFC → schedule 判依赖 → 落 blocked-by/sched-ready → 出 DAG 图文件』与『被 blocked issue 的 implement 被门控、上游合并后放行』两条路径，无网络依赖。
    acceptance: bash scripts/e2e-spec-0058-issue-scheduler.sh 退出码 0，断言：schedule 对样本产出预期 blocked-by/sched-ready 标签操作 + 生成 DAG 图文件；门控路径下 blocked issue 不 implement、上游合并后放行；被 PR 指路牌拾取。
---

# 0058 · 跨 issue 调度：agent 语义排依赖（逻辑+文件冲突）→ blocked-by 标签 + 本地 DAG 拓扑图

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把「跨 issue 的执行顺序」从今天的**隐式**（vigil 逐 issue 串行发现起草、messages 反应式推进、
全程无任何全局排序）变成**显式**：派一个提示词可控的**调度 agent**，读所有「已出 RFC」的 open
issue（标题 / 正文 + 其 spec 的文件分配与设计），语义判读两类跨 issue 依赖——**逻辑前提**（B 的
实现依赖 A 的成果，如 A 建的接口 / 模块 / 数据结构 B 要用）与**文件冲突**（两 spec 的 `files`
分配有交集，同一文件多 writer 必须串行）——产出一张 issue DAG。把每条边落成下游 issue 的
`blocked-by:#<上游>` GitHub 标签（无未满足上游者派生 `sched-ready`），并在本地用 graphviz 渲一张
拓扑图 PNG，让人一眼看清波次与并行面。实现派单侧（messages 的 implement 闸）据未满足的
`blocked-by` 门控：被挡的 issue 停在 rfc-review 等上游合并，**能并行的尽量并行**。入口是独立的
`openagents schedule` 命令（人 / cron 按需跑），vigil 每轮发现段后也调一次保鲜，让上游合并后下游
自动解封。核心是「一个调度 agent + 一层确定性 utils（解析 / 落标签 / 渲图）」——决策全下放 agent，
代码只留最小硬闸（对齐 issue #145「agents + recipes、最小硬闸」方向）。

## Motivation

**现状**：OpenAgents 今天有两层并行（CLAUDE.md 理念 5）——组内多 Task 协同（靠 spec 的 `files`
分配互斥）、跨 issue 多 worktree 并行。但**跨 issue 之间没有任何顺序概念**：`vigil.discover_and_dispatch`
按发现标签列出 open issue，逐个 `start_rfc` 起草 RFC（决策 5 串行仅为避免抢分支，非语义排序）；
RFC 之后由 `messages.poll` 按 PR 的 rfc-approved / 评论 / CI 反应式推进 implement。谁先谁后完全
取决于发现顺序与各 PR 的推进节奏，**没人回答过「这批 issue 里，哪些必须等哪些先做完」**。

**痛点 / 为什么改**：

1. **逻辑序缺失**：现实里 issue 常有前后依赖——「先重构模块 A 的接口（#134），依赖它的 #150 才好
   动」。今天两者会被同时派单、同时进 implement，下游在上游未落地时写代码，要么返工、要么撞设计。
2. **文件冲突序缺失**：spec 的 `files` 分配只在**单组内**保证互斥（issue #71 的「单一 writer」也只到
   组级）。**跨 issue** 若两个 spec 的文件分配有交集（都改 `messages.py`），并行 implement 必然
   在 rebase / merge 阶段撞车——这是本可提前排开的确定性冲突，却被推迟到最贵的合并期才爆。
3. **RFC 之后才谈得上排序**：issue 的真实依赖藏在 RFC 里（文件分配、要复用谁的接口）。**必须先写
   RFC、再据 RFC 排**——光看 issue 标题 / 正文排不准（#150 标题未必提它依赖 #134 的新接口）。这正是
   本 spec 把调度定在「已出 RFC 的 issue」上、而非发现即排的根。
4. **人要的是宏观把控，不是手排 DAG**（理念 2 / 5）：让人手工盯着十几个 issue 排先后、算并行波次，
   正是把人拉回细节层。理想形态是 agent 读完所有 RFC，一次判出依赖图，人只审这张图。
5. **成果要可视**（理念 8）：拓扑图本身就是「现在这批活怎么并行、卡在哪」的成果视图，是未来前端
   排程面板的数据底座。

本 spec 让「跨 issue 排序」变成一次「已出 RFC → 调度 agent 判依赖 → blocked-by 标签 + DAG 图 →
implement 门控」的自主流程。

## Guide-level explanation

对使用者，多出一个「排程」动作。典型用法：一批 issue 各自的 RFC 已起草（甚至已合入 main），此时跑：

```
openagents schedule
# → 🔍 拉取 12 个 open issue，其中 8 个已出 RFC（4 个待起草，跳过）…
# → 🤖 调度 agent 判读跨 issue 依赖（逻辑前提 + 文件冲突）…
# → 🔗 依赖边：
#      #150 ← #134   (理由：#150 复用 #134 重构后的 scheduler.reconcile 接口)
#      #150 ← #141   (理由：#150 与 #141 都改 messages.py，须串行；#141 先)
#      #151 ← #134   (理由：#151 依赖 #134 的 blocked-by 标签常量)
# → 🏷  落标签：#150 +blocked-by:#134 +blocked-by:#141；#151 +blocked-by:#134；
#            #134 #141 +sched-ready（源节点，可立即执行）
# → 🖼  拓扑图已渲染：./issue-dag.png
```

行为要点：

- **只排「已出 RFC」的 issue**：命令按各 spec frontmatter 的 `issue:` 字段把 open issue 映射到它的
  RFC；没有 spec 的 issue 还在起草阶段，本轮跳过（打印提示，不排它）。
- **两类依赖一起判**：逻辑前提 + 文件冲突都交给**一个**调度 agent 语义判读（你选的方案）——文件
  冲突虽可确定性比对，但让 agent 连带判，可结合语义定「谁先谁后」（不只是「须串行」）。
- **边即标签**：每条 `下游 ← 上游` 落成下游的 `blocked-by:#<上游>` 标签；一个 issue 若所有上游都已
  合并（或本就无上游）→ `sched-ready`。标签就是 DAG 的持久真值，也是执行门控与出图的唯一数据源。
- **能并行尽量并行**：agent 被要求**只在确有依据时连边**，独立 issue 之间不连——于是同一波（无
  互相依赖）的 issue 天然并行。拓扑图按层排开，一眼看清每一波能同时动几个。
- **顺序被真的执行**：`messages` 在派 implement 前查该 issue 是否还挂着未满足的 `blocked-by`——是则
  这轮不写代码、停在 rfc-review 等上游合并（RFC 起草不受此闸，仍可并行；卡的只是**写代码**这一步）。
- **上游合并即自动解封**：vigil 每轮发现段后调一次 schedule 保鲜——上游 PR 合并、issue 关闭后，
  reconcile 剪掉下游那条 `blocked-by`，下游转 `sched-ready`，下一轮 implement 自动放行。
- **本地 DAG 图**：默认渲成 `./issue-dag.png`（graphviz `dot`）。缺 `dot` 时安全降级为落 `.dot` 源
  文件、不报错——渲图只是成果展示，绝不因缺渲染器拖垮排程主流程。

## Reference-level explanation

### 架构与既有约定对齐

沿用仓库「注入 backend、纯逻辑模块、I/O 下沉、安全降级」四件套。三个新模块各司一层：

- `openagents/scheduler.py`（决策核心，纯逻辑 + 一个注入式编排入口）——镜像 `align.py` / `issuecheck.py`：
  可控提示词 + `plan` 派单解析 + `reconcile` 纯标签差分；另有一个 `schedule_repo` 编排入口，github /
  backend / diag 全注入（同 `orchestrator` 的 IO-with-injected-deps 形态），供 cli 与 vigil 复用。
- `openagents/scheddiag.py`（渲染层）——镜像 `conflictdiag.py`：`SchedulePlan → DOT → PNG`，渲染与
  IO 解耦、缺 graphviz 安全降级。
- 接线层：`cli.py`（`schedule` 命令 + 注入 vigil 回调）、`messages.py`（implement 门控）、`vigil.py`
  （保鲜钩子）——都只调上面两个模块，不含调度决策。

### 关键契约

1. **提示词常量 `_SCHEDULE_TASK`（可控点）**：模块级字符串，指示调度 agent：读「上下文」里逐个
   issue 的 `#编号 / 标题 / 正文 / RFC 摘要（文件分配 + 设计）`，判读跨 issue 依赖，只连两类边——
   **逻辑前提**（下游实现依赖上游成果）与**文件冲突**（两 RFC `files` 有交集须串行）；**仅在确有依据
   时连边**（独立 issue 不连，最大化并行）；不得凭空捏造依赖。输出以固定机器可读行回吐，每行
   `边：#<下游> <- #<上游>  (理由：…)`，末尾以 `（无更多边）` 收束。
2. **`plan(*, specs, backend) -> SchedulePlan`**：`specs` 是 `[(issue_number, title, body, rfc_text)]`；
   组装提示词 → `backend.run(...)` → 从 summary 解析所有 `边：#a <- #b` 行为 `Edge(downstream, upstream,
   reason)`。返回冻结 `SchedulePlan(nodes: tuple[int,...], edges: tuple[Edge,...])`。**fail-open**：一条边
   都解析不到（agent 跑偏 / 空输出）→ `edges=()`（全体 `sched-ready`），绝不凭空造依赖把人挡死。
3. **`reconcile(*, plan, open_numbers, labels_by_issue) -> list[LabelDiff]`**（纯函数，标签真值算法）：
   对每个节点 v，`期望 blocked-by = { blocked_by_label(u) | Edge(v<-u) 且 u ∈ open_numbers }`（**剪掉
   已合并 / 关闭的上游** u）；期望 `sched-ready` ⟺ 该集合为空。与 `labels_by_issue[v]` 里**调度器自有
   标签**（匹配 `blocked-by:#*` 或 `sched-ready`）比对，产出 `LabelDiff(issue, add=[...], remove=[...])`；
   非调度器标签一律不碰。标签因此始终反映**未满足**的阻塞——门控只需读标签、无需实时查上游状态。
4. **标签方案**：`blocked_by_label(n) == f"blocked-by:#{n}"`（DAG 的每条边一个标签，`ensure_label`
   兜底存在）；`SCHED_READY_LABEL == "sched-ready"`。`parse_blocked_by(labels) -> list[int]` /
   `is_blocked(labels) -> bool`（存在任一 `blocked-by:#*` 即阻塞）——供 messages 门控与出图复用。
5. **implement 门控（enforcement，`messages._process_rfc_review`）**：派 `_report_implement` 前取该 PR
   对应 issue 的当前标签，`is_blocked(labels)` 为真 → 本轮不 implement、停在 rfc-review、产出
   `sched-blocked` 事件（与 hold-spec「停在闸门」同款语义）。**只挡 implement**，不挡 RFC 起草 /
   评论 / 合并收口；不改既有 hold / skip 闸。上游合并后标签被 reconcile 剪掉即自动放行（无需人工）。
6. **issue → spec 映射**：扫 `docs/specs/*.md` frontmatter 的 `issue:` 字段建 `{issue_number: rfc_text}`；
   open issue 命中则可调度，未命中（RFC 未起草 / 未合入）→ 本轮跳过并提示。这就是「先写 RFC 再排」
   的落点：无 RFC 的 issue 根本进不了排程输入。

### 与 backend 的边界

调度 agent 只读 issue / RFC、只输出依赖边判读，**不改工作区、不碰 gh**（标签由代码侧 `reconcile` +
`github.issue_add_label/remove` 确定性落，出图由代码侧 `dot` 落）——故本 spec 不依赖
`AgentResult.changed`，只解析 `summary` 里的 `边：` 行。这与 Spec-0055 issue agent「让 agent 自己跑
gh」相反：排程的写操作（标签 / 图）是确定性的，收回代码侧更可验证（对比 Rationale 备选 A）。

### DAG + 文件分配

| Task | 内容 | files（互斥所有权） | depends-on |
| --- | --- | --- | --- |
| T1 | scheduler 核心：`_SCHEDULE_TASK` + `plan` 解析 + `reconcile` 差分 + 标签 helper（纯逻辑） | `openagents/scheduler.py`, `tests/test_scheduler.py` | — |
| T2 | scheddiag：`SchedulePlan → DOT → PNG`，缺 graphviz 安全降级 | `openagents/scheddiag.py`, `tests/test_scheddiag.py` | T1 |
| T5 | vigil 保鲜钩子：每轮 discover 后调注入的排程回调（默认 no-op 零回归） | `openagents/vigil.py`, `tests/test_vigil_schedule_hook.py` | — |
| T3 | cli `schedule` 命令：拉 issue→映射 spec→plan→reconcile→落标签→出图 + 注入 vigil 回调 | `openagents/cli.py`, `tests/test_cli.py` | T1, T2, T5 |
| T4 | messages implement 门控：被 blocked 的 issue 停在 rfc-review 等上游 | `openagents/messages.py`, `tests/test_messages_schedule_gate.py` | T1 |
| T6 | 端到端离线脚本（排程→标签→出图 与 门控放行两路径） | `scripts/e2e-spec-0058-issue-scheduler.sh` | T3, T4 |

`files` 跨 Task 两两不相交（单一 writer，理念 6）。并行面：T1 与 T5 为根可并行；T1 后 T2 / T4 并行；
T3 待 T1+T2+T5；T6 待 T3+T4。e2e 脚本：`scripts/e2e-spec-0058-issue-scheduler.sh`。生成物
`OVERVIEW.md` / `ARCHITECTURE.md` 由 `spec render` / `spec graph` 重渲，不手改。

## Drawbacks

1. **排序质量吃 agent 判读**：逻辑依赖靠语义判读，可能漏连（该串的没串→下游返工）或错连（不该串的
   连了→白白串行、损失并行）。缓解：文件冲突这半本可确定性比对，本 spec 选「全 agent」是随你的决策
   （更少代码、能连带定先后），但把「确定性文件冲突」列为可回退强化项（见 Future）；且 `--dry-run`
   让人先审边表再落标签。
2. **标签保鲜依赖 schedule 重跑**：`blocked-by` 只在 reconcile 重跑时才剪。若上游合并后**既没跑
   `openagents schedule` 也没走 vigil**，下游会一直挂 `blocked-by`、卡在门控。缓解：vigil 每轮保鲜
   （T5）在自主环里自愈；手动 / cron 场景需自觉重跑。这是「标签即真值、门控纯读标签」换来的简单性的
   代价（对比实时查上游状态的备选 C）。
3. **标签增殖**：每条边一个 `blocked-by:#N` 标签，DAG 稠密时仓库标签变多。缓解：都由 `ensure_label`
   幂等创建、reconcile 满足即删；语义清晰（一眼看出挡在谁上）胜过省标签。
4. **门控与 messages 现有闸叠加的复杂度**：implement 前又多一道闸，与 hold / skip / review 门控并存。
   缓解：门控只读标签、逻辑极薄（`is_blocked` 布尔），且只前置于 implement 一处，不改既有闸。
5. **RFC 未合入 main 时的可见性**：只在 PR 分支的 spec 尚未合入 main 时，其它并行分支的 schedule 扫
   本地 `docs/specs` 可能看不到它——与「RFC 审核通过即合入 main」的既有约定（note.md）配套才完整。
   本 spec 假定该约定成立（RFC 先合、再据其排执行），不额外处理未合入 RFC 的跨分支可见性。

## Rationale and alternatives

**本方案（一个调度 agent 判依赖 + 代码侧确定性落标签 / 出图 + messages 门控）** 最贴合你的三个决策
（全 agent 判读 / 成对 blocked-by 标签 / 独立命令且 vigil 可调），且分层干净：决策在 agent、副作用
在确定性 utils、门控是最小硬闸——正对 #145 的收敛方向。

**备选 A：文件冲突边走确定性、只逻辑依赖交给 agent（混合）**。优点：文件冲突是 `files` 集合求交，
确定、零漏判、可解释。缺点：agent 判读时看不到「哪些是确定性冲突边」，先后定序割裂成两处。**你已
选全 agent**；本方案把 A 记为「若排序质量成痛点」的首选回退（Future 1）。

**备选 B：波次标签 `sched-wave-N`（topological 分层）**。优点：直接表达并行波次、标签少。缺点：粒度
粗——某 issue 只依赖上一波某一个也得等整波；且波次是静态快照，上游单独合并无法解封下游（要整波
重算）。成对 `blocked-by:#N` 精确到边、随上游合并逐条解封，更贴「能并行尽量并行」。**你已选成对**。

**备选 C：门控实时查上游 open / closed，不靠标签保鲜**。优点：无 Drawback 2 的保鲜依赖。缺点：每次
implement 门控都要按 `blocked-by` 逐个查上游状态（N 次 gh 调用），慢且把「DAG 真值」分裂到「标签存
边 + 实时查态」两处。本方案让标签既存边又存「未满足」态（reconcile 剪已满足），门控纯读标签、零
网络。**否**（用 vigil 保鲜 + 手动重跑覆盖保鲜缺口）。

**备选 D：调度器自己跑 gh 落标签（如 Spec-0055 issue agent 让 agent 跑 gh）**。缺点：标签是确定性写
操作，交给 agent 反而丢确定性、难验证。排程的副作用收回代码侧（`reconcile` + `github.*`）更可测。**否**。

## Prior art

- **Spec-0043 issuecheck**（`openagents/issuecheck.py`，issue #111）：**单 issue 内部**修法冲突自检——
  「注入 backend、纯逻辑、按稳定标记回解析、fail-open」的形态本 spec 直接沿用，把判读范围从「一个
  issue 内部」升到「跨 issue 之间」。`needs-human` 作持久冻结信号的用法，启发本 spec 的 `blocked-by`
  作持久阻塞信号。
- **Spec-0020 align**（`openagents/align.py`）：首个「注入 backend 判读 issue 草稿」范例，`plan` 的
  提示词 + 派单 + 解析形态同源。
- **Spec-0028 conflict / Spec-0034 conflictdiag**（`conflict.py` / `conflictdiag.py`）：`conflictdiag`
  的「渲染与 IO 解耦、注入 run、安全降级、`make_diagnoser` IO 工厂闭包」形态是 `scheddiag` 的直接
  模板；两者都在「用 graphviz / git 出结构化视图」这一层。
- **spec `files` 分配 + issue #71**（多 agent 写竞争 / 单一 writer 硬化）：`files` 组内互斥是「设计期
  文件所有权」；本 spec 把「跨 issue 文件冲突」纳入调度边，是同一「文件所有权即排序依据」思路从组内
  延伸到 issue 间。
- **issue #137（vigil --parallel worker 池）/ #145（收敛为 agents+recipes、最小硬闸）**：本 spec 是
  #137 并行执行的**前置规划层**（#137 的 worker 池未来消费 `sched-ready` 决定同时起几个）；分层遵循
  #145 的「决策下放 agent、代码留确定性层 + 最小硬闸」。
- **rust-lang/rfcs**：本总览 9 段结构来源（[github.com/rust-lang/rfcs](https://github.com/rust-lang/rfcs)）。

## Unresolved questions

- 调度 agent 的 `边：#a <- #b` 回吐契约在真实 `claude` 后端下的稳定性，需 Phase 3 用真 backend 抽验；
  离线 e2e 只能验打桩解析路径。
- 大批量 issue（数十个）时把所有 RFC 全文喂一个 agent 会不会超上下文 / 判读质量下降——是否需要按
  文件分配先做确定性预分簇、只把可能相关的喂 agent。留待用量反馈，本 spec 先做全量单次判读。
- `blocked-by:#N` 标签名含 `:` 与 `#`，需确认 `gh label create` / `--add-label` 对该字符集稳定（Phase
  3 首次落标签时验证；若不稳则回退为 `blocked-by-N` 纯连字符命名）。

## Future possibilities

1. **文件冲突边确定性化**（备选 A 回退）：把「两 spec `files` 求交」的冲突边由代码算好，连同已知冲突
   喂给 agent 只判「逻辑序 + 冲突边的先后」，兼得确定性与语义定序——若排序质量成痛点即切。
2. **#137 消费 `sched-ready`**：vigil --parallel 的 worker 池按 `sched-ready` 决定「这一波同时起几个
   issue」，把本 spec 的规划真正兑现成并行吞吐。
3. **拓扑图升级为前端排程面板**（理念 8）：把 DAG 从静态 PNG 升为可交互视图（波次 / 卡点 / 进度实时
   流动，对齐 note.md 的「成果流动侧边栏」），本 spec 的 `SchedulePlan` 即其数据底座。
4. **调度自检串 issuecheck**：排程前对每个 issue 先跑 Spec-0043 issuecheck，把「单 issue 自洽」与「跨
   issue 有序」串成一条判读链。
5. **提示词外置为可配模板**（env / 配置文件），让不同项目定制排序偏好（如「优先重构类 / 优先高优先级」）
   而不改代码。

