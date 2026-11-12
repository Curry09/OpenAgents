---
number: "0026"
title: README 最简用法:紧跟安装方法之后新增 Quickstart 段
issue: 75
slug: readme-quickstart-after-install
summary: 在 README「安装」之后、「快速上手」之前插入一段「最简用法 / Quickstart」,把最短可用路径 init → issue → vigil 放最前,并点明日常只用 issue+vigil、poll/watch/rfc 等是不发现新 issue 的单步调试工具。只动 README 文案与结构,不改任何 CLI 行为。
tasks:
  - id: T1
    title: 插入最简用法/Quickstart 段并同步目录锚点
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - README.md
    scope: 在 README「## 安装」之后、「## 快速上手」之前插入「## 最简用法 / Quickstart」段(三行 init/issue/vigil 代码块 + 三条职责要点);若目录需补锚点则同处一并补,仅改 README.md。
    acceptance: README.md 含「## 最简用法 / Quickstart」标题,位于「## 安装」之后、「## 快速上手」之前;新段代码块同时含 openagents init/issue/vigil 三行,并写明 poll/watch/rfc 不发现新 issue;不改动安装节与快速上手节正文。
  - id: T2
    title: e2e 脚本断言 Quickstart 段位置
    status: done
    priority: P2
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0026-readme-quickstart.sh
    scope: 新增纯文档校验 e2e 脚本:断言 README 含 Quickstart 标题、位于安装与快速上手之间、代码块含 init/issue/vigil 三行;不调用真实 CLI/GitHub。
    acceptance: bash scripts/e2e-spec-0026-readme-quickstart.sh 全绿:断言 README.md 存在「## 最简用法 / Quickstart」且行号在「## 安装」之后、「## 快速上手」之前,并含 openagents init/issue/vigil 三行;无外部依赖可稳定复跑。
---

# 0026 · README 最简用法:紧跟安装方法之后新增 Quickstart 段

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

在 `README.md` 的「安装」一节之后、「快速上手:从 0 跑通一个 issue」一节之前,新增一段简短的「最简用法 / Quickstart」。这段把**最短可用路径**摆到 README 显眼处:`openagents init` → `openagents issue "你的需求"` → `openagents vigil`,并用一两句话点明职责划分——日常只需 `issue` + `vigil`;`poll` / `watch` / `rfc` 等是单步调试工具、**不发现新 issue**;在 GitHub 网页直接提 issue 也可以,但需打 `openagents` 标签且本地要有 `vigil` 进程在跑。本组**只动 README 的结构与这段文案**,不触碰任何 CLI 命令的行为或职责划分。

## Motivation

新用户(包括项目作者本人)按现有 README 上手时,容易把 `issue` / `watch` / `poll` 误当成一条日常流程顺着用,结果踩坑。现状的命令职责(以 `README.md`「命令参考」表与各命令实现为准)是:

- **`openagents issue <title>`** 只在 GitHub 建一个 issue 并自动附加 `openagents` 发现标签——它**不写本地 state**、不派单、不开 PR。
- **`openagents poll`** 扫一遍所有 **open PR**(即已派单、已有 run 的 PR)按阶段路由;**`openagents watch`** 只是按间隔循环 `poll`。两者都**只处理本地已有的 open run,不发现新 issue**。
- 于是「提完 issue 直接 `poll`」会得到「处理 0 个事件」、`watch` 因无 open PR 秒退,让人误以为工具坏了。

真正的一站式入口是 **`openagents vigil`**(守夜人:自主发现 issue → 派单 → 开 PR → 守候迭代),`poll` / `watch` / `rfc` / `implement` 等只是把这条闭环拆开后的单步调试工具。这个「`vigil` 是日常入口、其余是调试拆解件」的职责划分,在当前 README 里不够显眼——「快速上手」一节直接铺开了 `rfc → refine-rfc → implement → iterate → poll → watch` 的六步手动串联,把调试用的拆解件当成了首屏教程,新手第一眼看到的就是最长、最易踩坑的那条路,而不是最短可用路径。

缺口很具体:**README 缺一段「最短路径优先」的开场**,在安装之后第一时间告诉读者「日常就两条命令:`issue` 立需求、`vigil` 守全程」,并显式澄清 `poll`/`watch` 不发现新 issue。本组补上这段文案即可,属纯文档改动。

## Guide-level explanation

读者装完 OpenAgents(读完「安装」一节),向下滚动,第一眼看到的就是「最简用法 / Quickstart」:

```bash
openagents init                 # 绑定当前目录到仓库
openagents issue "你的需求"      # 提 issue(自动打 openagents 发现标签)
openagents vigil                # 守夜人:发现 → 派单 → 开 PR → 守候迭代
```

紧跟一两句话点明用法边界:

- **日常只需 `issue` + `vigil`**:`issue` 把需求立成带 `openagents` 标签的 GitHub issue,`vigil` 一条命令跑完「发现 → 派单 → 开 PR → 守候」全程。
- **`poll` / `watch` / `rfc` 等是单步调试工具,不发现新 issue**:它们只处理本地已有的 open PR/run;提完 issue 直接 `poll` 会「处理 0 个事件」、`watch` 会秒退,那不是坏了,而是它们本就不负责发现。要跑通新需求请用 `vigil`。
- **也可以直接在 GitHub 网页提 issue**,但需手动打上 `openagents` 标签,且本地要有一个 `vigil` 进程在跑才会被发现、派单。

读者想看分步拆解(`rfc` / `refine-rfc` / `implement` / `iterate` 的逐步串联)时,紧随其后的「快速上手:从 0 跑通一个 issue」仍在原位,作为「想手动逐步理解闭环时看的详细版」。Quickstart 与快速上手由此形成「最短路径 → 详细拆解」的递进,而非两条并列、让人犹豫先看哪条。

## Reference-level explanation

**技术方案**——纯 Markdown 文档编辑,零代码、零 CLI 行为改动。

- **插入位置**:`README.md` 现有结构为 `… → ## 安装(L111) → ## 快速上手:从 0 跑通一个 issue(L127) → …`,两节间以一条 `---` 水平分隔线相连。新段 `## 最简用法 / Quickstart` 插在「安装」节的结尾分隔线之后、「快速上手」标题之前,自身以一条 `---` 与「快速上手」隔开。最终顺序为:**安装 → 最简用法 / Quickstart → 快速上手**。「安装」一节本身与「快速上手」一节的正文均不改动(边界:不重写 README 其余章节、不动安装方法本身)。
- **新段内容**:一个三行 `bash` 代码块(`init` / `issue` / `vigil`,各带行内注释,与上方 Guide-level 一致),加三条要点说明(日常只用 `issue`+`vigil`;`poll`/`watch`/`rfc` 是不发现新 issue 的调试工具;网页提 issue 需打 `openagents` 标签且本地需有 `vigil` 在跑)。命令名、标签名、职责描述须与现有「命令参考」表、「流程标签一览」表、「守夜人模式(vigil)」一节用词一致,不引入与正文冲突的新说法。
- **不改动项**:不新增/删除/重排除「快速上手」之外的任何章节;不改「目录」锚点结构以外的内容(若新增二级标题导致「## 目录」列表需补一行链接,则同步补该行,属同一文件内的结构一致性维护,仍只动 `README.md`)。

**Task 分解(files 互斥,各 Task 单一 writer——理念 6)**:

| Task | 范围 | owns files | 依赖 |
|---|---|---|---|
| T1 | 在 README 安装之后、快速上手之前插入「最简用法 / Quickstart」段并同步目录锚点 | `README.md` | — |
| T2 | e2e 脚本:断言 Quickstart 段存在且位于安装与快速上手之间 | `scripts/e2e-spec-0026-readme-quickstart.sh` | T1 |

```mermaid
graph LR
  T1[T1 README 插入 Quickstart] --> T2[T2 e2e 顺序断言]
```

**端到端验证**:`bash scripts/e2e-spec-0026-readme-quickstart.sh`——纯文档校验,不调用任何真实 CLI / GitHub。脚本断言:(1) `README.md` 含 `## 最简用法 / Quickstart` 标题;(2) 该标题在文件中出现于 `## 安装` 之后、`## 快速上手` 之前(按行号顺序);(3) 新段代码块同时含 `openagents init` / `openagents issue` / `openagents vigil` 三行。无外部依赖,CI 可稳定复跑。

## Drawbacks

- **README 多一段、首屏变长**:在安装与快速上手之间插一段,读者要多滚一屏;但这正是把最短路径前置的代价,且新段刻意短小(三行命令 + 三条要点)。
- **两段用法说明存在重叠**:Quickstart 与「快速上手」都讲「怎么跑通一个 issue」,有少量信息重复;靠「最短路径 vs 详细拆解」的定位差异与措辞区分,接受这点冗余换取新手友好。
- **文档与命令行为的漂移风险**:若日后 `vigil` / `issue` / `poll` 的职责变了,这段文案需同步更新,否则会误导;但这是所有用法文档的固有成本,非本段独有。

## Rationale and alternatives

选「在安装之后、快速上手之前**新增**一段独立的简短 Quickstart」,是因为它在最显眼处(装完即见)给出最短可用路径,同时**完全不动**现有「快速上手」详细教程——风险最小、与 issue #75 边界(只动结构与这段文案、不重写其余章节、不动安装本身)完全吻合,且形成「最短路径 → 详细拆解」的自然递进。

- **备选 A:直接重写现有「快速上手」一节,把 `vigil` 路径塞到开头、调试命令降级到末尾**——能省掉一段、避免重复,但会大改一节既有正文、改动面与回归风险都大,且 issue 明确「不重写 README 其余章节」;否决。
- **备选 B:只在「命令参考」表里给 `vigil` 加一句「这是日常入口」备注,不新增 Quickstart 段**——改动更小,但读者要滚到很靠后的命令参考才看得到,救不了「装完第一眼就顺着 issue→poll→watch 踩坑」的核心问题;放置位置达不到 issue 要求的「安装方法之后、最前面」;否决。
- **备选 C:把 Quickstart 放到 README 最顶部(标题/简介之前)**——更显眼,但读者尚未安装就看到可执行命令,顺序不合理(issue 明确要求「紧跟安装方法之后」);否决。

## Prior art

- **「Quickstart / Getting Started 紧跟 Installation」是开源 README 的通行结构**:绝大多数 CLI 工具 README 以「Install → Quickstart(最短可用命令)→ 详细文档」排布,把最短路径前置是既有共识。本组即把该惯例落到本仓库 README。
- **本仓库内部先例**:`README.md` 现有「快速上手:从 0 跑通一个 issue」一节已是「跑通一个 issue」的教程范式;本组在其前面补一段更短的「最简用法」,是同一范式下的「极简版前置」,而非新发明。
- 命令职责划分的事实依据见 `README.md` 现有「命令参考」「编排与自动化」「守夜人模式(vigil)」各节——本组文案与之对齐复述,不引入新职责定义。

## Unresolved questions

- **新段是否要中英双标题**:暂定标题用「最简用法 / Quickstart」中英并列,与「快速上手」中文标题风格略有差异;最终标题措辞留实现期按 README 整体风格定。
- **目录(`## 目录`)是否需要补一行锚点**:取决于现有目录是否逐节列出;若需补则在 T1 内一并处理(仍只动 `README.md`),具体以实现时 README 目录结构为准。

## Future possibilities

- **README 英文版 / i18n**:若未来出英文 README,这段最简用法是最该优先翻译、最常被引用的入口段。
- **Quickstart 与 `openagents init` 输出联动**:可让 `init` 成功后在终端直接打印这三行最简用法,与 README 形成「文档—终端」一致的引导(属 CLI 改动,超出本组 docs 边界,留作后续)。

