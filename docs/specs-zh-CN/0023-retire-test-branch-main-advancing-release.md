---
number: "0023"
title: 退役 test 分支:main 持续推进 + release/vX.Y.Z 版本分支发布
issue: 68
slug: retire-test-branch-main-advancing-release
summary: 退役 test 分支,反转旧的「test 门控」模型:main 成为日常自动流转分支(reviewer 闸+CI 全绿后自动合入,持续推进),发版时把 main 发布到 release/vX.Y.Z 分支并打 vX.Y.Z tag(版本号从最新 tag 自动递增,默认 patch)。人的触点从 promote 改为 release;promote.py 重命名重定向为 release.py,全链路 base 默认 test→main,去掉 test 分支自举,CI 仅 main 触发。
tasks:
  - id: T1
    title: github 层:base 默认 main + 去 test 分支自举
    status: done
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
    scope: create_pr base 默认 test→main;ensure_prerequisites 不再建 test 分支(收敛为只预建流程标签);无调用方的 ensure_branch 连同其 3 个单测整体删除;branch_ci_green 不变。
    acceptance: 单测断言 create_pr 默认透传 --base main;ensure_prerequisites 只编排流程标签预建;ensure_branch 及其单测已删除;branch_ci_green 行为不变。
  - id: T2
    title: orchestrator + vigil:base 默认 main
    status: done
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
    scope: DEFAULT_BASE test→main;start_rfc/changed_spec_group 随之以 main 为基线;vigil 文档注释更新为 main。
    acceptance: 单测断言 start_rfc 默认 base=main 透传 create_pr;changed_spec_group base=main;vigil 注释无 test 残留。
  - id: T3
    title: promote→release 模块:建 release/vX.Y.Z 分支 + 打 tag + 版本递增
    status: done
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
    scope: promote.py 重命名为 release.py;release(*, state, bump) 预检(无 BLOCKED run ∧ 无 needs-human open PR ∧ branch_ci_green(main))通过则读最新 vX.Y.Z tag 按 bump 递增(无 tag→v0.1.0)、建 release/vX.Y.Z 分支、打 tag 并 push;新增版本号解析/递增纯函数;删 promote.py/test_promote.py。
    acceptance: 单测打桩 github/state/子进程:BLOCKED run→released=False;needs-human PR→False;main CI 非绿→False;全过→建分支+打tag+推且 version 正确;无 tag→v0.1.0;bump=minor/major 生效。
  - id: T4
    title: CLI:release 子命令 + base 默认 main
    status: done
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
    scope: rfc/vigil 的 --base 默认 test→main;promote 子命令→release 子命令(_cmd_promote→_cmd_release,新增 --bump {patch,minor,major} 默认 patch),路由 release.release 并按 ReleaseResult 设退出码。
    acceptance: 单测断言 --base 默认值为 main;release 子命令路由到 release.release 并按结果设退出码;--bump 透传 release()。
  - id: T5
    title: CI 工作流 + indexheal 测试 + 旧 spec 0012 收尾
    status: done
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - .github/workflows/ci.yml
      - tests/test_indexheal.py
      - docs/specs/0012-test-branch-gated-flow.md
      - openagents/messages.py
      - openagents/state.py
      - scripts/e2e-spec-0023-release-flow.sh
    scope: ci.yml 触发分支 [main,test]→[main];test_indexheal base test→main(断言 origin/main);0012 正文加被取代横幅指向 0023;清理 messages.py/state.py 注释里 promote→release、test 体验服→main 的文档漂移;补 e2e 脚本。
    acceptance: ci.yml on.pull_request.branches 仅含 main;indexheal 测试断言 origin/main 合并;spec validate 无 error。
---

# 0023 · 退役 test 分支:main 持续推进 + release/vX.Y.Z 版本分支发布

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

退役长期存在的 `test` 体验服分支,把日常自动流转的目标从 `test` 反转到 `main`:issue→PR 改从 `main` 切出、以 `main` 为 base,经同样的 reviewer 闸 + CI 闸自动合回 `main`,`main` 由此持续推进。正式发版单独走一条 `release/vX.Y.Z` 分支并打 `vX.Y.Z` tag(版本号从最新 tag 语义化递增,默认 patch)。人的门控触点从 `promote`(把 test 快进到 main)后移为 `release`(决定发一个版本)。

## Motivation

**现状:test 分支门控流程(完整复述,不要求读者去翻别的 spec)。** OpenAgents 此前跑一套「test 分支门控流程」:

- `test` 是一条长期存在的「体验服」分支。每个 issue 被领取后,agent 从 `test` 切出工作树,起草改动,开 PR 时 **PR base 锁定 `test`**。PR 经 N 个 reviewer 并行评审(裁决聚合为全票 PASS)+ CI 全绿后,**自动合回 `test`**。于是 `test` 不断累加,成为「最新可体验」版本。
- `main` 不参与日常流转,处于冻结状态。它只在人执行 `openagents promote` 时,被从 `test` **快进**(fast-forward)一次。`promote` 前跑三条预检,全过才扬升:① 没有挂起(`STATUS_BLOCKED`)的 run;② 没有打了 `needs-human` 标签的 open PR;③ `test` 分支 HEAD 的 CI 全绿。
- 人只有两个触点:「提 issue」和「promote 上线」。中间 issue→PR→合回 test 全自动。

为支撑上面的流程,代码里有几处「test 专属」逻辑:全链路 base 默认值(`orchestrator.DEFAULT_BASE`、`cli` 的 `--base`、`github.create_pr` 的 `base`)都是 `"test"`;冷启动时 `ensure_prerequisites` 会幂等兜底创建 `test` 分支(否则全新仓库缺 `test` 会导致 prepare 永久失败);索引自愈 `indexheal` 也以 `origin/test` 为合并基线。

**问题:为什么要改。** 「体验服」这层中介不再被需要。期望的新工作方式是:**`main` 自己就持续推进**(不再需要一条 `test` 在前面缓冲),而**正式发版**单独走一条 `release` 分支。这样人的门控点从「每一次把 test 上线到 main」**后移到「决定发一个版本」**——main 平时一直向前,发版才是人做宏观决策的时刻。

## Guide-level explanation

把上面三个角色**整体反转一格**:

| 角色 | 现状(被取代) | 本 feature |
|------|------|------|
| 日常自动流转分支(issue→PR 的 base、自动合入目标) | `test`(体验服) | **`main`** |
| 人工门控的发布目标 | `main`(被 promote 快进) | **`release/vX.Y.Z`** |
| 人的门控触点 | `promote` | **`release`** |

对使用者:平时和以前一样提 issue,agent 自动把改动合进 `main`;想发版时跑一次 `openagents release [--bump patch|minor|major]`,它在预检全过后用 `main` 当前 HEAD 物化一条 `release/vX.Y.Z` 分支并打不可变 tag。

## Reference-level explanation

落到改动,分解为 5 个 Task(DAG 见下;`files` 互斥,各 Task 单一 writer):

1. **T1 github 层** — `create_pr` 的 `base` 默认值是全链路 base 的最底层来源,test→main。`ensure_prerequisites` 里兜底建 `test` 分支那段删除(`main` 是默认分支、恒存在,无需自举),`ensure_branch` 因此再无调用方,连同其 3 个单测整体删除(奥卡姆);`branch_ci_green` 不变(release 预检对 main 用),流程标签(needs-human 等)的幂等预建保留。
2. **T2 orchestrator + vigil** — `orchestrator.DEFAULT_BASE` 是 worktree 基线与 PR base 的单一常量来源,test→main。`indexheal` 自愈合并基线由 `cli.py` 透传 `DEFAULT_BASE`,故改这一常量即让 `git merge origin/main` 自动跟随;`vigil.py` 的 `base` 由 CLI 注入、自身无默认值,仅文档注释订正。
3. **T3 promote→release 模块**(依赖 T1) — 预检三条(无 BLOCKED run ∧ 无 needs-human open PR ∧ 目标分支 CI 全绿)原样照搬,只把取绿对象从 test 换成 main。动作侧从「快进 main」改为「物化一个版本」:`_latest_version()` 用 `git tag --list 'v*'` 取最大 `vX.Y.Z`(语义化排序);`_next_version(latest, bump)` 按 `bump∈{patch,minor,major}` 递增(无 tag→`v0.1.0`);`git push origin main:refs/heads/release/vX.Y.Z` 新建发布分支 + `git tag vX.Y.Z` 钉死不可变快照。`ReleaseResult(released, version, reason)` 取代 `PromoteResult`。
4. **T4 CLI**(依赖 T2、T3) — CLI 是人的唯一触点收敛处。`promote` 子命令整体改名 `release`,`_cmd_release` 新增 `--bump` 透传;`rfc`/`vigil` 的 `--base` 默认值与 T2 的 `DEFAULT_BASE` 一同 test→main。
5. **T5 收尾**(无依赖,可并行) — `ci.yml` 的 `pull_request.branches` 去掉 test(release 分支由已绿的 main 物化、不接 PR);`test_indexheal` 桩断言 `origin/test`→`origin/main`;Spec-0012 加被取代横幅;清理 messages.py/state.py 文档漂移。

**端到端验证**:`bash scripts/e2e-spec-0023-release-flow.sh`(离线跑 ruff + pytest,演示 base=main + release 物化)。

依赖 DAG:`T1 → T3`,`T2 → T4`,`T3 → T4`,T5 独立。

## Drawbacks

- 去掉「体验服」缓冲后,合进 `main` 的改动直接成为最新主干,失去一层「先在 test 攒一攒再上线」的缓冲带——但 reviewer 闸 + CI 全绿闸不变,质量门槛未降低。
- 引入 `release/*` 分支 + tag 两套发布物,概念上比单纯「快进 main」多一层。

## Rationale and alternatives

- **为什么反转而非微调**:旧模型里 `main` 冻结、靠人 promote,人被绑在「每次上线」的细节上;反转后人只在「发版」这个宏观决策点介入,符合 OpenAgents「人做宏观把控」的目标。
- **备选:建 GitHub Release 页面**。否决(YAGNI):只建 `release/vX.Y.Z` 分支 + 打 git tag 已满足「不可变快照 + 可回滚」;Release 页面是后续可加项(见 Future possibilities)。
- **备选:版本号用日期/构建号**。否决:语义化三段 `vX.Y.Z`(默认 patch 递增)对人最直观,且 `_next_version` 是纯函数便于 hermetic 测试。
- **不动评审/CI/messages 内部逻辑**,只换它们依赖的 base——把 blast radius 收到最小(解耦,理念 10)。

## Prior art

语义化版本(SemVer `vX.Y.Z`)与「主干持续推进 + 版本分支发布」是业界主流发布模型(如多数库走 trunk-based + tagged release)。本 feature 取其「主干向前、tag 钉版本」的核心,不引入更重的 release train 流程。

## Unresolved questions

无。预检三条、版本递增语义、发布物形态(分支 + tag)均已在本组确定。

## Future possibilities

- 在 `release/vX.Y.Z` 之上自动建 GitHub Release 页面 / 生成 changelog(当前 YAGNI)。
- `release` 预检可扩展为可配置策略(如要求最低覆盖率)。

