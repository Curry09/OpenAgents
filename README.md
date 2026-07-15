# OpenAgents

**RFC 驱动的多 Agent 协作框架。** 让 AI agent 替你完成「从 issue 到 PR」的完整工程闭环——先把要做的事写成 RFC、由人评审批准,再派一个 coding agent(如 Claude Code)按 RFC 写代码、开真实 GitHub PR,并根据评审评论与 CI 结果自动迭代,直到合并。

人退到宏观位置:你审 RFC、审 PR、按一次 release;**细节交给 agent**。

---

## 🚀 启动

```bash
# 1. 安装(改了源码加 --force 重装)
uv tool install --from . openagents

# 2. 鉴权(OpenAgents 不存 token,全委托 gh)
gh auth login && gh auth status

# 3. 在目标仓库根目录绑定项目
openagents init

# 4. 提一个需求(自动打上 openagents 发现标签,才能被 vigil 发现)
openagents issue "你的需求"

# 5. 启动守夜人,无人值守跑到合并
#    --parallel 4 开并行(同时最多 4 个 subject);--once 只跑一轮后退出
openagents vigil
```

> ⚠️ `vigil` / `issue` 会**真的**调用 Claude 改代码、用 `gh` 开真 PR / 发评论。**建议先在练习仓库上试。**

---

## 前置条件

- **Python ≥ 3.12** 与 [uv](https://docs.astral.sh/uv/)
- **已鉴权的 [`gh` CLI](https://cli.github.com/)**:首次用 `gh auth login` 登录,用 `gh auth status` 确认通过。
  > OpenAgents **不存储任何 token**,鉴权全部委托给 `gh`。
- **已安装的 [`claude` CLI](https://docs.claude.com/claude-code)**(默认 coding 后端)

---

## 安装

```bash
uv tool install --from . openagents
```

装好后 `openagents` 在任意目录可用。改了源码后用 `--force` 重装更新:

```bash
uv tool install --force --from . openagents
```

> 注意:`openagents` 是一份 uv tool 快照——改了代码不重装,命令会跑旧代码。

---

## 用法

人真正要拍板的宏观动作只有四个,加上一次性绑定与只读观测,共六条命令:

```bash
openagents init                 # 绑定当前目录到仓库(一次性)
openagents issue "你的需求"      # 主动提 issue(自动打 openagents 发现标签)
openagents vigil                # 守夜人:发现 → 派单 → 开 PR → 守候到合并(全程无人值守)
openagents vigil --parallel 4   # 同上,但同时最多 4 个 issue/PR 并行推进
openagents backfill-rfc <path>  # 追溯补 RFC:扫存量代码反推 spec 开 draft PR
openagents release              # 把 main 当前 HEAD 物化成一个版本
openagents board                # 打开本地成果看板(只读)
```

> `rfc` / `implement` / `iterate` / `poll` / `watch` / `fleet` 等早期的手动单步命令已全部并入 `vigil`——它们不过是 `vigil` 每轮自动做的事的手动版,人不再需要单敲(Spec-0064)。

### `init` —— 绑定项目

把当前目录绑定 / 初始化为 OpenAgents 项目,并确保流程标签就位。缺 git / 远端时会提示你新建。除 `board` 外的所有命令执行前都会先做这项绑定预检。全新仓库也可以直接 `vigil`(无需先 `init`)——进主循环前会自举一次流程标签。

### `issue` —— 立一个需求

```bash
openagents issue "支持导出 CSV"        # 建前先复述对齐、请你确认
openagents issue "修复登录超时" --yes  # 跳过确认(供自动化)
```

往当前仓库提一个 issue,自动打上 `openagents` 发现标签,这样才能被 `vigil` 发现、派单。也可以直接在 GitHub 网页提 issue,但需手动打上 `openagents` 标签。

常用选项:`--body <正文>`、`--label <标签>`(可重复)、`--yes`(跳过复述确认)。

### `vigil` —— 守夜人,一条命令跑完全程

`vigil` 让 OpenAgents **无人值守**地跑完整闭环:发现带标签的新 issue → 派单求解 → 起草 RFC 开 PR → 守候 PR 的评论 / 冲突 / CI / e2e / 评审 → 迭代 → 合并,人只需要审 RFC、审 PR。

```bash
openagents vigil                          # 读 .openagents/openagents.yml,默认串行、间隔 60s
openagents vigil --once                   # 只跑一轮、排空队列后退出(测试/单趟)
openagents vigil --parallel 4             # 并发上限 K=4:同时最多 4 个 subject 在跑 agent
openagents vigil --label bug --label p0   # 覆盖发现标签门控(可重复)
openagents vigil --interval 30            # 覆盖轮询间隔(秒)
openagents vigil --base develop           # 覆盖派单起草的分支基线
openagents vigil --hold merge             # 单次把某阶段交给人(停等):等价 stages.merge=human
openagents vigil --skip ci,e2e            # 单次跳过某阶段(当 PASS 放行):等价 stages.<stage>=skip
```

`--hold` / `--skip` / `--base` / `--interval` / `--label` 都是**对单次运行的覆盖**,不改磁盘上的 `openagents.yml`;两者对同一阶段给出矛盾意图(如 `--hold ci --skip ci`)会立即报错。

#### 图驱动的 level-triggered 守夜

新版守夜的核心是 `recipes.vigil.run_vigil`——一个**图驱动、level-triggered reconcile** 的调度器(Spec-0065)。它不再是「发现段 + 守候段」两趟批处理,而是:

- **调度单元是 subject**(`issue:5` / `pr:12`),不是「事件」。`--parallel K` 是并发上限;**串行不是另一种模式,而是 `K=1` 的退化**。真正的并发上限由 issue 依赖图(GitHub 原生 `blocked_by`)天然约束。
- **生产者 / worker 单向数据流**:主线程每 tick 按 GitHub 现态判定该动哪些 subject、入队;K 个常驻 worker 从队列领活、把 PR 推进到卡住为止。两者对 `work_queue` 的并发写全部由 SQLite `BEGIN IMMEDIATE` 序列化,无进程内锁。**没有批屏障**——worker 跑完立即领队首,慢活不拖住空闲 slot。
- **level-triggered(边沿无关)**:谓词无历史,不问「跟上一轮比变了没」,只问「现在该不该动手」。每 tick 对每个 subject 重算,丢一轮丢一百轮都能自愈——这是 Kubernetes 的架构第一原则([设计原则](https://github.com/kubernetes/design-proposals-archive/blob/main/architecture/principles.md))。进程崩在「检测到 CI 变绿」和「真去合并」之间也不会丢事:下一 tick 从 GitHub 重新读到当前态就继续。

##### reconcile 判定表(一个 subject 现在该做什么)

每 tick 对每个 subject 走一遍 `_sense`(唯一的 GitHub 读)→ `_classify`(纯函数四值判定)→ 入队 / 看门狗。判定表按顺序短路,顺序本身是正确性依赖:

```
① merged / closed / needs-human ............... 终止,轮询停止(人摘 label 自动复活)
② 最新评论是人发的 ............................ reply     回话
③ 依赖(blocked_by)未全关闭 .................. 等待上游
④ 还没有 PR ................................... solve     竖切开 PR
⑤ mergeable = unknown(GitHub 还没算完) ...... 等待可合并性
⑥ 冲突(mergeable = dirty) ................... rebase    变基/解冲突(必须排在 CI 前)
⑦ 当前 head 上 CI = pending / 零个 check ...... 等待 CI
⑧ 当前 head 上 CI = failure ................... fix-ci    修 CI
⑨ e2e 证据缺失 / head_sha 陈旧 ................ e2e       补端到端证据
⑩ 无 review 裁决 / 其 sha≠当前 head / 打回 .... review    评审或按意见改
⑪ 全绿 + review-approved:<当前 head sha7> ..... merge     合并回 main
```

##### `needs-human` 是 agent 的一等出口

agent 干不动时(CI 是上游 flaky、需求有歧义、改动超出授权)**自己打 `needs-human` label + 留一条说明理由的评论**,判定①当场终止、轮询立刻停止——不烧多余 LLM、不等超时,理由直接写在 issue 上给人看。人摘掉 label,谓词自动重新活过来(level-triggered 白送的自愈)。

三道**护栏**只兜 agent 自己看不见的三种死法(它们在日志里都跟「一切正常」长得一样):

1. **空转**(agent 以为干了活但 fp 没变)→ 零进展收工时盖一条带 fingerprint 的 attempt 戳,同 fp 的活降级为「等副作用」不再入队,不无限重跑烧钱。
2. **状态该动却不动**(CI 永不启动 → 没人叫 agent → PR 静默烂掉)→ **看门狗**:QUIET 的 age 超阈值就打 `needs-human` + 贴机械诊断。「卡了多久」是当前态的纯函数,零本地记忆。
3. **agent 崩溃 / 被 kill / 挂死**(GitHub 上零痕迹)→ 硬超时杀子进程、`flock` 判死回收、`attempts` 计数超上限交人。

##### 存储职责:两个存储,各管一层

- **GitHub = 领域真相**:依赖结构(原生 `blocked_by`)、我们做的**决定**(label:`ready` 准入 / `needs-human` 终态 / `review-approved:<sha7>` 裁决)、GitHub 自己维护的**事实**(checks / mergeable,读原生、**不复制成 label**)、e2e 证据评论。**分界线:决定打 label,事实读原生。**
- **SQLite `work_queue`** 只存 GitHub 表达不了的三样:谁原子地领走了 subject、领了几次没收工、领取时的定序。丢了无害——queued 行一 tick 从 GitHub 重建。
- **`.openagents/claims/{subject}.lock`(flock)** 是持有者的存活证明,由内核持有:进程一死锁自动释放。回收凭 flock 判死,不凭租约猜死。

> 队列 DB 落在 `<repo>/.openagents/vigil-queue.db`;`SQLite + flock` 把部署钉在**单机**(禁止跨网络文件系统共享同一库,会数据损坏——[SQLite 官方](https://www.sqlite.org/whentouse.html))。多机需要换掉 4 个认领函数的实现,当前版本不预建这层抽象(奥卡姆:不为「可能」付费)。

##### 硬闸(CLI 关不掉)

`runtime.gates` 里有三道**确定性硬闸**,恒机器把关、`--skip` 关不掉,是防空转的安全底线:`head-advanced`(交付后 head 必须前移)、`evidence-stamp`(e2e 证据溯源戳必须匹配当前 head)、`round-cap`(reconcile 单次推进轮数上限,兜振荡)。此外 `implement` / `deliver` 恒派 agent,无「归谁把关」可选。

另有 **GitHub 仓库分支保护规则**强制的 required status checks(lint / test / commitlint / spec-validate 等),要调整须去仓库 **Settings → Branches** 改——`--skip ci` 只让守夜人不再**等** CI,改不了 GitHub **允不允许合**。

### `backfill-rfc` —— 追溯补 RFC

```bash
openagents backfill-rfc openagents/utils/git.py     # 单文件
openagents backfill-rfc openagents/recipes/         # 目录
```

针对「实现先行、设计后补」的存量代码:扫描代码路径反推一份 spec,并开一个 draft PR 承载它(`--base` 指定分支基线,默认 `main`)。

### `release` —— 物化一个版本

```bash
openagents release              # 默认 patch
openagents release --bump minor
```

人唯一的宏观决策点:预检通过则把持续推进的 main 当前 HEAD 物化成 `release/vX.Y.Z` 分支 + tag。确定性动作、不派 agent。

### `board` —— 成果看板

只读观测,渲染新栈 `RuntimeState` 的成果看板(不要求 git / 远端,可离线查看)。

---

## 声明式配置 `.openagents/openagents.yml`

一份 `.openagents/openagents.yml` 是「**用哪些 agent + 每道闸归谁把关**」的单一真源(Spec-0064)。**整份可省**——文件不存在或空则全回落内建默认(= 全自动、全 agent、单仓、间隔 60s),不写 YAML 的用户零感知。

```yaml
version: 1

# 每个角色接哪个后端(同项目可混接 Claude Code / Codex / nexau)。缺省角色回落 claude_code。
agents:
  implementer: { backend: claude_code }
  reviewer:    { backend: claude_code }

# 每个可配阶段归谁把关,三态:agent(自动) / human(停等打 needs-human) / skip(当 PASS 放行)。
stages:
  triage:   agent      # 准入门控(triage: human 则开 PR 前问一句再放行)
  rfc:      agent      # RFC 起草(仅 agent / skip;skip 会告警——撞「先改 RFC 再改代码」)
  conflict: agent      # 解冲突(不可 skip)
  ci:       agent      # 等 CI 全绿(可 skip)
  e2e:      agent      # 端到端取证(可 skip)
  review:   agent      # 代码评审(可 skip,但 review:skip + merge:agent 会被拒——不许零闸)
  merge:    agent      # 合并(不可 skip;merge:human 则合并前停下等人点合)

release: manual        # manual(人决定何时发版,默认) / auto

defaults:              # 单仓库默认(多仓时被每仓 override 覆盖)
  interval: 60
  base: main
  labels: [openagents]

repos:                 # 多仓库统管:每仓一子进程跑 run_fleet(gh/git 绑进程 cwd,一仓一进程隔离)
  - path: .
```

约束:

- **不许零闸**:`review: skip` + `merge: agent` 会让未审代码自动盲合进 main,直接报错——要么开 review,要么 `merge: human`(理念 5「PR 需人审」的底线)。
- **硬闸名进不了 stages**:`head-advanced` / `evidence-stamp` / `round-cap` 是确定性硬闸、恒机器把关;`implement` / `deliver` 恒派 agent。写进 `stages` 均 reject。
- **三态 skip 在感知层归一**:`ci: skip` → CI 当 success,`e2e: skip` → 证据戳记当前 head,`review: skip` → 裁决记 APPROVED@head。这样 `_classify` 保持纯粹的机械分支表、不吃 config,策略只在两处出现。

---

## 搭配 Claude Code 使用(推荐)

OpenAgents 默认的 coding 后端就是 **[Claude Code](https://docs.claude.com/claude-code)**,两者天然互补:

- **用 Claude Code 开发 OpenAgents 本身,用 OpenAgents 跑闭环**。本项目正在「用自己开发自己」(dogfooding):在仓库里用 Claude Code 交互式地改 RFC / 写代码,再让 `openagents vigil` 无人值守地把 issue 推进到 PR。
- **交互式补位,自治式兜底**。需要人紧密参与、边想边改的部分交给 Claude Code 面对面协作;明确成型、可无人值守推进的 issue 交给 `vigil` 自动跑。
- **确保 `claude` CLI 已登录可用**:OpenAgents 会调用它作为 coding agent,先用 `claude` 跑通一次交互确认鉴权无误,再启动 `vigil`。

> ⚠️ `vigil` / `issue` 会**真的**调用 Claude 改代码、用 `gh` 开真 PR / 发评论。**建议先在练习仓库上试。**
