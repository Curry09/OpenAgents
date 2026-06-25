---
number: "0023"
title: 退役 test 分支:main 持续推进 + release/vX.Y.Z 版本分支发布
issue: 68
slug: retire-test-branch-main-advancing-release
summary: 退役 test 分支,反转 Spec-0012 模型:main 成为日常自动流转分支(reviewer 闸+CI 全绿后自动合入,持续推进),发版时把 main 发布到 release/vX.Y.Z 分支并打 vX.Y.Z tag(版本号从最新 tag 自动递增,默认 patch)。人的触点从 promote 改为 release;promote.py 重命名重定向为 release.py,全链路 base 默认 test→main,去掉 test 分支自举,CI 仅 main 触发。
tasks:
  - id: T1
    title: github 层:base 默认 main + 去 test 分支自举
    status: in-progress
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0012/T2
        type: supersedes
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
      - tests/test_ensure_prerequisites.py
  - id: T2
    title: orchestrator + vigil:base 默认 main
    status: in-progress
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0012/T5
        type: supersedes
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
      - openagents/vigil.py
  - id: T3
    title: promote→release 模块:建 release/vX.Y.Z 分支 + 打 tag + 版本递增
    status: in-progress
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to:
      - ref: 0012/T4
        type: supersedes
    parallel: false
    files:
      - openagents/release.py
      - tests/test_release.py
      - openagents/promote.py
      - tests/test_promote.py
  - id: T4
    title: CLI:release 子命令 + base 默认 main
    status: in-progress
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to:
      - ref: 0012/T6
        type: supersedes
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
  - id: T5
    title: CI 工作流 + indexheal 测试 + 旧 spec 0012 收尾
    status: in-progress
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - .github/workflows/ci.yml
      - tests/test_indexheal.py
      - docs/specs/0012-test-branch-gated-flow.md
---

# 0023 · 退役 test 分支:main 持续推进 + release/vX.Y.Z 版本分支发布

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据，正文为各 Task 设计 prose。 -->

## 总览（feature overview）

> 本节自包含:读完即可理解本 feature 全貌,无需打开其它 spec。

### 现状:test 分支门控流程

OpenAgents 现在跑的是一套「test 分支门控流程」,关键点如下(这里完整复述,不要求读者去翻别的 spec):

- **`test` 是一条长期存在的「体验服」分支。** 每个 issue 被领取后,agent 从 `test` 切出工作树,起草改动,开 PR 时 **PR base 也锁定 `test`**。PR 经过 N 个 reviewer 并行评审(裁决聚合为全票 PASS)+ CI 全绿后,**自动合回 `test`**。于是 `test` 不断累加,成为「最新可体验」的版本。
- **`main` 不参与日常流转,处于冻结状态。** 它只在人执行 `openagents promote` 时,被从 `test` **快进**(fast-forward)一次。`promote` 前跑三条预检,全过才扬升:① 没有挂起(`STATUS_BLOCKED`)的 run;② 没有打了 `needs-human` 标签的 open PR;③ `test` 分支 HEAD 的 CI 全绿。
- **人只有两个触点:**「提 issue」和「promote 上线」。中间 issue→PR→合回 test 全自动。

为支撑上面的流程,代码里有几处「test 专属」逻辑:全链路的 base 默认值(`orchestrator.DEFAULT_BASE`、`cli` 的 `--base`、`github.create_pr` 的 `base`)都是 `"test"`;冷启动时 `ensure_prerequisites` 会幂等地兜底创建 `test` 分支(否则全新仓库缺 `test` 会导致 prepare 永久失败);索引自愈 `indexheal` 也以 `origin/test` 为合并基线。

### 问题:为什么要改

「体验服」这层中介不再被需要。期望的新工作方式是:**`main` 自己就持续推进**(不再需要一条 `test` 在前面缓冲),而**正式发版**单独走一条 `release` 分支。这样人的门控点从「每一次把 test 上线到 main」**后移到「决定发一个版本」**——main 平时一直向前,发版才是人做宏观决策的时刻。

### 方案:模型反转 + 发布物化为版本

把上面的角色**整体反转一格**:

| 角色 | 现状(被取代) | 本 feature |
|------|------|------|
| 日常自动流转分支(issue→PR 的 base、自动合入目标) | `test`(体验服) | **`main`** |
| 人工门控的发布目标 | `main`(被 promote 快进) | **`release/vX.Y.Z`** |
| 人的门控触点 | `promote` | **`release`** |

落到改动:

1. **全链路 base `test`→`main`。** issue→PR 改为从 `main` 切出、以 `main` 为 PR base,经同样的 reviewer 闸 + CI 闸(**这两道闸的内部逻辑不动**,只换 base)自动合回 `main`。`main` 由此成为持续推进的日常分支。
2. **去掉 `test` 分支的冷启动自举。** `main` 是默认分支、恒存在,无需任何兜底创建;`ensure_prerequisites` 里建 `test` 那段删除(流程标签如 `needs-human` 的幂等预建保留)。
3. **`promote` 改为 `release`,动作从「快进 main」变为「物化一个版本」。** 预检三条**原样照搬**(只把「`test` CI 全绿」换成「`main` CI 全绿」),通过后:读取已发布的最新 `vX.Y.Z` tag,按 `--bump`(默认 patch)语义化递增出新版本号(仓库无任何 tag 时起点 `v0.1.0`),然后 ① `git push origin main:refs/heads/release/vX.Y.Z` 用 main 当前 HEAD 物化一条发布分支,② 打 `git tag vX.Y.Z` 并推送,钉死一个不可变快照。

### 边界(不做什么)

- **不建 GitHub Release 页面**(YAGNI);只建 `release/vX.Y.Z` 分支 + 打 git tag。
- **不改 reviewer 评审闸 / CI 闸 / messages 路由的内部逻辑**,只把它们依赖的 base 从 test 切到 main。
- **不重写被取代的旧 spec**;它作为「test 门控时代」的历史快照保留,仅加一行被取代横幅,形式化的替代关系由本组各 Task 的 `supersedes` 字段承载。
- 版本号一律语义化三段 `vX.Y.Z`,默认 patch 位递增,`--bump minor|major` 可选。

### Task 分解一览

- **T1** github 层:`create_pr` base 默认→main、删 `test` 自举。
- **T2** orchestrator + vigil:`DEFAULT_BASE`→main。
- **T3** `promote.py`→`release.py`:预检(对 main)+ 建 release 分支 + 打 tag + 版本递增(依赖 T1)。
- **T4** CLI:`promote` 子命令→`release`(+`--bump`)、`--base` 默认→main(依赖 T2、T3)。
- **T5** 收尾:CI 触发分支→`[main]`、indexheal 测试→origin/main、旧 spec 加被取代横幅。

## T1 · github 层:base 默认 main + 去 test 分支自举

### Scope

create_pr base 默认 test→main;ensure_prerequisites 不再建 test 分支(收敛为只预建流程标签);`ensure_branch` 函数因此再无调用方,整体删除(连同其 3 个单测,奥卡姆);branch_ci_green 不变(release 预检对 main 用);test_ensure_prerequisites 改为断言只编排标签、不再调 ensure_branch。

### Design

Spec-0012 决策 8 让 `ensure_prerequisites` 兜底建一条长期 `test` 分支当体验服;模型反转后 `main` 恒存在(默认分支),无需任何自举,这段逻辑连同 `ensure_branch(name="test", from_ref="main")` 一并删除——根除「全新仓库缺 test 分支致 prepare 永久失败」这一整类问题的来源也随之消失。流程标签(needs-human 等)的幂等预建与 `branch_ci_green` 保持原样:前者仍是闸门所需,后者从「promote 对 test 取绿」平移为「release 对 main 取绿」,函数签名/语义不动,仅调用方传参改变(解耦,理念 10)。`create_pr` 的 `base` 默认值是全链路 base 的最底层来源,改这一处 + 各上层默认(T2/T4)即完成 test→main 的彻底切换。

### Acceptance

单测:create_pr 默认透传 --base main;ensure_prerequisites 只编排流程标签预建(不再建分支);ensure_branch 函数及其单测已删除;branch_ci_green 行为不变。

## T2 · orchestrator + vigil:base 默认 main

### Scope

DEFAULT_BASE test→main;start_rfc/changed_spec_group 随之以 main 为基线;vigil 文档注释(决策2)更新为 main。

### Design

`orchestrator.DEFAULT_BASE` 是 worktree 基线与 PR base 的单一常量来源(Spec-0012 决策 2 设为 test),改为 main 后,issue→PR 的工作树从 main 切出、PR 也以 main 为 base,经 reviewer 闸 + CI 全绿自动合回 main——main 由此成为持续推进的日常分支。`indexheal` 的自愈合并基线由 `cli.py` 透传 `DEFAULT_BASE`,故改这一常量即让 `git merge origin/main` 自动跟随,无需单独改 indexheal 源码(其测试断言在 T5 更新)。`vigil.py` 的 `base` 由 CLI 注入、自身无默认值,仅决策 2 的文档注释提及 test,随之订正,签名不变。

### Acceptance

单测:start_rfc 默认 base=main 透传 create_pr;changed_spec_group base=main;vigil 注释无 test 残留。

## T3 · promote→release 模块:建 release/vX.Y.Z 分支 + 打 tag + 版本递增

### Scope

promote.py 重命名为 release.py。release(*, state, bump) 预检(无 BLOCKED run ∧ 无 needs-human open PR ∧ branch_ci_green(main))通过则:读最新 vX.Y.Z tag 按 bump 递增(无 tag→v0.1.0,默认 patch),建分支 push origin main:refs/heads/release/vX.Y.Z,打 tag vX.Y.Z 并 push。新增版本号解析/递增纯函数。删除 promote.py/test_promote.py。

### Design

预检三条(无 BLOCKED run ∧ 无 needs-human open PR ∧ 目标分支 CI 全绿)是 Spec-0012 决策 7 的核心资产,原样照搬,只把取绿对象从 test 换成 main——它保证「评审反复不过、挂起等人」的工作不会被悄悄带进发布。动作侧从「快进 main」改为「物化一个版本」:

- **版本号**:`_latest_version()` 用 `git tag --list 'v*'` 取已发布的最大 `vX.Y.Z`(语义化排序,非字典序),`_next_version(latest, bump)` 按 `bump∈{patch,minor,major}` 递增(minor 清零 patch,major 清零 minor+patch);无任何 tag 时起点 `v0.1.0`。版本号是发布动作的纯函数输入,单独抽函数便于 hermetic 单测(不触真实 git)。
- **物化**:`git push origin main:refs/heads/release/vX.Y.Z` 以 main 当前 HEAD 新建发布分支;`git tag vX.Y.Z` + `git push origin vX.Y.Z` 钉死不可变快照。分支可后续打补丁,tag 是精确回滚点,二者互补。
- 不建 GitHub Release(YAGNI);沿用 promote 的解耦写法(github.* + 注入 state + subprocess git),三者皆可打桩。`ReleaseResult(released, version, reason)` 取代 `PromoteResult`,失败时 reason 指明被哪条预检拦下。

### Acceptance

单测打桩 github/state/子进程:BLOCKED run→released=False;needs-human PR→False;main CI 非绿→False;全过→建分支+打tag+推且 version 正确;无 tag→v0.1.0;bump=minor/major 生效。

## T4 · CLI:release 子命令 + base 默认 main

### Scope

rfc/vigil 的 --base 默认 test→main;promote 子命令→release 子命令(_cmd_promote→_cmd_release,新增 --bump {patch,minor,major} 默认 patch),路由 release.release 并按 ReleaseResult 设退出码。

### Design

CLI 是人的唯一触点收敛处。`promote` 子命令整体改名 `release`(人的宏观决策从「把 test 上线到 main」变为「把 main 发一个版本」),`_cmd_release` 新增 `--bump` 透传给 `release.release`,按 `ReleaseResult.released` 设退出码并把 `version`/`reason` 打成干净一行。`rfc`/`vigil` 的 `--base` 默认值是面向人的入口默认,与 T2 的 `DEFAULT_BASE` 一同从 test 改 main,保证显式不传 base 时全链路一致落在 main。

### Acceptance

单测:--base 默认值为 main;release 子命令路由到 release.release 并按结果设退出码;--bump 透传 release()。

## T5 · CI 工作流 + indexheal 测试 + 旧 spec 0012 收尾

### Scope

ci.yml 触发分支 [main,test]→[main](去 issue#50 的 test 注释);test_indexheal 用例 base test→main(断言 origin/main);0012 frontmatter/正文加一行「被 Spec-0023 取代:test 分支退役」。

### Design

收尾性改动,无逻辑依赖故不挂 depends-on,可与前序并行。`ci.yml` 的 `pull_request.branches` 去掉 test(issue#50 当初为覆盖 test-base PR 而加,test 退役后 release 分支由已绿的 main 物化、不接 PR,故只留 main)。`test_indexheal` 把桩断言里的 `origin/test` 改 `origin/main`,与 T2 的 `DEFAULT_BASE` 对齐(indexheal 源码本身不变)。Spec-0012 作为 test 门控时代的设计快照保留,仅在正文顶部加一行被取代横幅指向 Spec-0023;形式化的「哪个 Task 替代哪个」由本组各 Task 的 `supersedes` 字段(0012/T2、T4、T5、T6)承载,演化细节交给 git(amend/history 已退役)。

### Acceptance

ci.yml on.pull_request.branches 仅含 main;indexheal 测试断言 origin/main 合并;spec validate 无 error。

