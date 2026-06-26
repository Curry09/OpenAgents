# OpenAgents

**RFC 驱动的多 Agent 协作框架。** 让 AI agent 替你完成「从 issue 到 PR」的完整工程闭环——先把要做的事写成 RFC、由人评审批准，再派一个 coding agent（如 Claude Code）按 RFC 写代码、开真实 GitHub PR，并根据评审评论与 CI 结果自动迭代,直到合并。

人退到宏观位置:你审 RFC、审 PR、按一次 release;**细节交给 agent**。

商业上对标 Cursor、Windsurf 这类交互式 coding agent,但形态不同——OpenAgents 不黏在编辑器里陪你敲代码,而是以 **issue / PR / 评论** 为协作面,让多个 agent 像一支远程团队那样并行干活。

> 现状:这是一个**正在用自己开发自己**(dogfooding)的早期项目。MVP 已能跑通 `issue → RFC → PR → 合并` 的闭环,并以此持续迭代自身。后端目前接 Claude Code,设计上兼容其它 cli-agent(Codex、nexau 等)。

---

## 目录

- [核心理念](#核心理念)
- [心智模型:一切都是 issue、RFC、PR](#心智模型一切都是-issuerfcpr)
- [工作闭环](#工作闭环rfc-first)
- [前置条件](#前置条件)
- [安装](#安装)
- [快速上手:从 0 跑通一个 issue](#快速上手从-0-跑通一个-issue)
- [命令参考](#命令参考)
- [两层并行](#两层并行)
- [Spec / RFC 工具链](#spec--rfc-工具链)
- [守夜人模式(vigil)](#守夜人模式vigil)
- [发布(release)](#发布release)
- [成果看板(board)](#成果看板board)
- [项目结构](#项目结构)
- [本地开发](#本地开发)
- [设计文档](#设计文档)

---

## 核心理念

OpenAgents 的设计建立在几条明确的原则上(详见 [`CLAUDE.md`](./CLAUDE.md)):

1. **奥卡姆剃刀** —— 如无必要,勿增实体。代码与架构追求最小、最简。
2. **RFC 先行,代码在后** —— 每次改动都先改 RFC(标注「代码修改中」)→ 再改代码 → 改完更新 RFC(标注「代码修改完毕」)。RFC 是 agent 之间、人与 agent 之间在代码层面对齐的契约。
3. **去中心化的 agent** —— OpenAgents 维护每个 agent 的状态,但同一个项目里不同 agent 背后接的 coding agent 可以不同(可以既有 Claude Code 又有 Codex)。
4. **PR / 评论即消息总线** —— agent 之间不直接通信,而是借 GitHub 的 PR 与评论机制传递消息:每收到一条新评论,相关 agent 就收到一条「你的 PR xxx 收到评论 xxx」的事件。
5. **人负责宏观,不负责细节** —— 人不再做代码层面的逐行测试,而是面向**成果**把控:审 RFC(做什么)、审 PR(做得对不对)、按 release(发不发)。
6. **证据驱动** —— 涉及的概念都应有真实来源并在对应位置给出引用。
7. **模块解耦** —— 每个模块职责单一,文件清单不重叠;每一层代码注释都引用对应的 RFC/Spec ID。

---

## 心智模型:一切都是 issue、RFC、PR

理解 OpenAgents 只需记住三种对象和它们之间的流转:

| 对象 | 是什么 | 谁产出 | 谁评审 |
|------|--------|--------|--------|
| **issue** | 一个待办需求 | 人 或 OpenAgents 自己(`issue` 命令) | —— |
| **RFC / Spec** | 「准备怎么做」的设计契约(rust-RFC 9 段总览) | agent 起草 | **人**(打 `rfc-approved` 标签批准) |
| **PR** | 真实代码改动 + 自动生成的端到端验证指路牌 | agent 按 RFC 实现 | **人**(合并)+ CI |

每个 issue 在一个**独立的 git worktree + 分支**里求解(分支基线锁定最新 `origin/main`),彼此隔离、互不污染。

PR 在其生命周期里有清晰的状态机(记录在 `.openagents/state.json`):

```
solving ──▶ rfc-review ──▶ (人打 rfc-approved) ──▶ pr-open ──▶ iterating ──▶ done
              │                                                     │
              └──────────── (评审评论 → refine-rfc) ◀──────────────┘
                                                                    │
                            卡住 / 反复失败 ─▶ blocked(打 needs-human 标签,等人介入)
                            PR 被关闭未合并 ─▶ closed(终态,不再求解)
```

- **rfc-review**:draft PR 已开,RFC 等人评审。人在 PR 上评论 → `refine-rfc` 按评论改 RFC。
- **pr-open / iterating**:RFC 获批后转正 PR,根据评论 / CI 失败自动迭代。
- **blocked**:连续多轮过不了,诚实升级为 `needs-human`,挂起等人,而非空转。
- **closed**:PR/issue 被关闭即视为终止信号,agent 收手。

---

## 工作闭环(RFC-first)

完整的一条流水线(对应 RFC-0005):

```
                ┌──────────────────────────── 人介入点 ────────────────────────────┐
                │                                                                  │
   issue  ──▶  rfc  ──▶  draft PR  ──▶  人评论  ──▶  refine-rfc  ──▶  人打         │
 (拉取/自提)   起草 RFC    (rfc-review)              按评论改 RFC    rfc-approved    │
                                                                        │          │
                                                                        ▼          │
                              迭代 ◀── CI/评论 ◀── 转正 PR ◀── implement(按 RFC 写码)│
                            (iterate)                (pr-open)                      │
                                │                                                  │
                                ▼                                                  │
                              合并 ──────────────────────▶ 人按 release ───────────┘
                                │
                                ▼
                  自动 rebase 其余 open PR 到最新 main(sync-prs)
```

**关键设计**:CLI 的每个命令只触发**单步**;跨步骤的编排交给 `poll` / `vigil` 的状态机,它扫描所有 open PR,按各自所处阶段自动路由(评审评论 → 精炼 / 已批准 → 实现 / CI 失败 → 修)。

---

## 前置条件

- **Python ≥ 3.12** 与 [uv](https://docs.astral.sh/uv/)
- **已鉴权的 [`gh` CLI](https://cli.github.com/)**:首次用 `gh auth login` 登录(GitHub.com → HTTPS → 浏览器授权即可),用 `gh auth status` 确认通过。
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

## 快速上手:从 0 跑通一个 issue

> ⚠️ 这些命令会**真的**调用 Claude 改代码、用 `gh` 开真 PR / 发评论。**建议先在练习仓库上试。**

```bash
# 1. 在一个 GitHub 仓库目录里绑定项目(缺 git / 远端时会提示你新建)
openagents init

# 2. 提一个 issue(也可以是仓库里已有的 issue)
openagents issue "支持导出 CSV"          # 自动打上发现标签;建前会先复述对齐、请你确认

# 3. 为该 issue 起草 RFC,开 draft PR 等你评审(假设是 issue #42)
openagents rfc 42

# 4. 你在 draft PR 上评论评审意见,然后按评论精炼 RFC(PR #7)
openagents refine-rfc 7

# 5. 你在 PR 上打 `rfc-approved` 标签批准后,按 RFC 写代码并把 PR 转正
openagents implement 7

# 6. 就 PR 的评论 / CI 失败迭代代码
openagents iterate 7 --reason ci         # 或 --reason comment

# —— 或者,别手动串这些步骤,让状态机替你跑 ——
openagents poll                          # 扫一遍所有 open PR,按阶段自动路由
openagents watch --interval 60           # 按间隔自动循环 poll(Ctrl-C 退出)
```

什么是「从 0」的第一件事?**不是写代码,而是把需求立成 issue 并起草 RFC**——先用评审对齐「做什么」,再让 agent 动代码。

---

## 命令参考

`openagents <command>`。除 `board` 外,所有命令执行前都会先做项目绑定预检。

### 闭环单步(手动触发)

| 命令 | 作用 |
|------|------|
| `init` | 绑定 / 初始化当前目录为 OpenAgents 项目(确保流程标签就位) |
| `issue <title> [--body B] [--label L]... [--yes]` | 往当前仓库提一个 issue;默认建前先复述对齐请你确认,`--yes` 跳过(供自动化) |
| `rfc <issue> [--base main]` | 为 issue 起草 RFC 并开 draft PR(状态 → rfc-review) |
| `refine-rfc <pr>` | 按 PR 最新评审评论精炼 RFC,并回贴改动说明 |
| `implement <pr>` | RFC 获批后(PR 有 `rfc-approved` 标签)按 RFC 写代码并把 draft PR 转正 |
| `iterate <pr> [--reason comment\|ci]` | coding 阶段就 PR 的评论 / CI 失败迭代代码 |

### 编排与自动化

| 命令 | 作用 |
|------|------|
| `poll` | 扫一遍所有 open PR,按阶段自动路由(评审评论→精炼 / 批准→实现 / CI→修),一次性 |
| `watch [--interval 60]` | 按间隔循环 `poll`,直到无 open PR(Ctrl-C 退出) |
| `vigil [...]` | 守夜人模式:自主发现 issue → 派单 → 守候 PR 的全流程无人值守循环(见下文) |
| `sync-prs [--merged N] [--rebase]` | 一个 PR 合并后,手动把最新 main 并入其余 open PR(`poll` 自动路径的手动对应物) |

### 产出与发布

| 命令 | 作用 |
|------|------|
| `release [--bump patch\|minor\|major]` | 人唯一的宏观决策点:预检(无 BLOCKED / needs-human 且 main CI 绿)通过则把 main 当前 HEAD 物化成 `release/vX.Y.Z` 分支 + tag |
| `board` | 在本地浏览器打开「成果看板」,可视化呈现各 issue/PR 的成果与状态(不要求 git / 远端) |

### 流程标签一览

| 标签 | 含义 |
|------|------|
| `openagents` | 发现标签——`issue` 命令自动附加,`vigil` 默认按它门控发现 |
| `rfc-approved` | 人批准 RFC 的信号——`implement` / `poll` 据此放行写代码 |
| `needs-human` | agent 卡住、诚实升级,挂起等人介入 |

---

## 两层并行

OpenAgents 把「并行」分成两个互补的层面:

1. **issue 层并行(自治模式)** —— 不同 issue 之间互不相关,各自一个独立 worktree + 一个 agent 求解,天然并行。`vigil` 负责调度。这是「issue 层面的并行」。
2. **feature 层并行(协同模式)** —— 同一个 feature(一个 spec 组)内部按 **Task** 拆分,每个 Task 有互斥的文件清单与单一 writer,多个 agent 可同时各写各的文件、互不冲突。这是「feature 层面用多 agent 协同」。

文件分配是 **设计期** 的所有权约定(写在 spec 的 frontmatter 里,`validate` 会校验文件不重叠)。运行期的 owner 强制(lease / CAS / capability)是已记录的后续工作。

---

## Spec / RFC 工具链

设计文档采用 **rust-RFC 9 段总览** 形态(Summary / Motivation / Guide-level / Reference-level / Drawbacks / Rationale & Alternatives / Prior art / Unresolved / Future),单个 spec **自包含**:理解它所必需的跨 spec 信息要就地复述,而非裸引用。spec 组的 frontmatter 还携带机器可读的 Task DAG 与文件分配。

独立的 `spec` 命令管理这些文档:

```bash
spec new <slug>          # 新建一个 spec 组(单 markdown 文件,9 段脚手架)
spec add-task <group>    # 往一个 spec 组加一个子任务
spec render              # 由各 spec 重新生成 docs/specs/OVERVIEW.md(请勿手工编辑该文件)
spec validate            # 校验:schema + 语义(必填四段非空=error;跨 spec 裸引用=warning)
spec abandon <task>      # 从快照移除一个 Task(历史仍在 git 里)
```

> CI 与本地校验用 `uv run spec` 保证跑的是当前 worktree 的代码,而非另一份 uv tool 快照。

PR 正文里的「端到端验证指路牌」会从该分支新增的 spec 自动解析渲染,让审核者一眼知道如何验收。

---

## 守夜人模式(vigil)

`vigil` 让 OpenAgents **无人值守**地跑完整闭环:循环「发现带标签的新 issue → 派单求解 → 守候 PR 的评论 / CI → 迭代」,人只需要审 PR。

```bash
openagents vigil                          # 默认按 openagents 标签门控,间隔 60s 循环
openagents vigil --once                   # 只跑一轮(发现 + poll)后退出
openagents vigil --label bug --label p0   # 自定义发现标签门控(可重复)
openagents vigil --hold spec              # 分级监督:在指定意图闸门停下等人
openagents vigil --hold spec,merge        # 可组合:spec(RFC 批准前停)/ merge(合并前停)
```

特性:标签门控的 issue 发现、「发现段 + 守候段」两段循环、单 issue 错误隔离(单轮出错不拖垮整个循环)、对已关闭 PR/issue 识别终止信号、崩溃后从孤儿 run 恢复、`gh` 瞬时错误指数退避重试。

全新仓库可以直接 `vigil`(无需先 `init`)——进主循环前会自举一次流程标签,使无人值守进程能自恢复。

---

## 发布(release)

`release` 是人唯一需要做的宏观决策点。它对持续推进的 `main` 做预检:

- 无处于 `BLOCKED` / `needs-human` 的工作
- `main` 的 CI 为绿

预检通过则把 `main` 当前 HEAD 物化成一个版本(`release/vX.Y.Z` 分支 + tag);不通过则按原因设非零退出码、不发布。

```bash
openagents release             # 默认 patch 递增(从最新 vX.Y.Z tag;无 tag 则起点 v0.1.0)
openagents release --bump minor
```

---

## 成果看板(board)

```bash
openagents board
```

以人为中心、面向**成果**呈现:在本地浏览器打开一个看板,可视化各 issue / PR 的状态与产出。这是「人面向成果而非代码细节」理念的载体,未来前端的主视觉范围也聚焦于此。

---

## 项目结构

```
openagents/
├── cli.py            # 唯一命令入口:仅解析参数 + 分发,业务逻辑下沉到各模块
├── config.py         # 项目绑定 / 上下文解析(ProjectContext)
├── orchestrator.py   # 编排核心:start_rfc / refine_rfc / implement / iterate
├── messages.py       # PR/评论消息总线:poll / watch,按阶段路由事件
├── vigil.py          # 守夜人主循环(发现段 + 守候段)
├── reviewer.py       # 自动评审闸(驱动状态流转)
├── github.py         # gh CLI 封装:issue/PR/标签/评论/CI 状态,瞬时错误重试
├── state.py          # 持久状态机(.openagents/state.json):各 run 的 status
├── workspace.py      # 每 issue 独立 worktree + 分支隔离
├── identity.py       # 本地 agent 身份(评论签名,区分自评论与真人评论)
├── rebase.py         # 合并后扇出 rebase 其余 open PR
├── indexheal.py      # 冲突时重渲 OVERVIEW 的索引自愈
├── release.py        # release 预检 + 物化版本
├── results.py        # 成果看板渲染
├── align.py          # 建 issue 前的前门对齐(复述请人确认)
├── hold.py           # vigil 分级监督闸门解析
├── e2e.py            # PR 正文端到端验证指路牌
├── backends/         # coding agent 后端适配
│   ├── base.py       #   抽象后端接口(兼容不同 cli-agent)
│   └── claude_code.py#   Claude Code 后端
└── spec/             # spec / RFC 工具链(独立 `spec` 命令)
    ├── cli.py model.py render.py schema.py validate.py graph.py mutate.py signpost.py

docs/specs/           # 全部 spec(rust-RFC 9 段)+ 自动生成的 OVERVIEW.md
scripts/              # 各 RFC/Spec 的端到端验证脚本 e2e-*.sh
tests/                # 单元测试
```

---

## 本地开发

```bash
uv sync --extra dev
uv run pytest          # 单元测试
uv run ruff check .    # 代码检查(行宽 100)
```

代码规范(详见 [`CLAUDE.md`](./CLAUDE.md)):

- **提交信息**:Conventional Commits —— `<类型>(<范围>): <描述>`;类型 feat/fix/refactor/chore/docs/test/ci/style/perf/build,范围 backend/cli/ci/deps/docs。subject 不要以大写 token 开头(如 `RFC-0001` 会被 commitlint 拦,用小写 `spec-0024` 或以中文起头)。
- **Git 钩子**:lefthook —— pre-commit(lint)+ commit-msg(commitlint)。
- **首次推送分支**:`git push -u origin <branch>` 设置 upstream。
- **代码注释**:每一层级引用对应的 RFC/Spec ID(见 `.claude/skills/rfc-driven-development/references/code-comment-conventions.md`)。
- **Python 函数参数**:禁止位置参数(`/` 语法);private 函数(`_` 开头)参数禁止默认值,调用方必须显式传参。

CI 在「指向 main 的 PR」上触发——main 即主干,新分支从 `origin/main` 拉出。

---

## 设计文档

本项目 RFC/spec 驱动开发,所有设计文档见 [`docs/specs/`](./docs/specs/),总览见自动生成的 [`docs/specs/OVERVIEW.md`](./docs/specs/OVERVIEW.md)。整个项目的起点是 [Spec-0001(MVP issue→PR 闭环)](./docs/specs/0001-mvp-issue-to-pr-loop.md)。
