---
number: "0009"
title: 合并后自动 rebase 其他 open PR
issue: 24
slug: auto-rebase-open-prs-on-merge
summary: 一个 PR 合并进 main 后，自动把其余还开着的 PR rebase 到最新 main，省去手动 rebase。含 github 层 list_open_prs/update_branch、扇出模块、合并后集成和手动 sync-prs 命令。
tasks:
  - id: T1
    title: github 层 `list_open_prs` + `update_branch`
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: 在 github.py 新增两个模块函数:list_open_prs()(gh pr list --state open --json number,url,解析为 PR 列表)与 update_branch(*, pr_number, rebase=False)(gh pr update-branch <n> [--rebase],成功返回 True、「已是最新」吞掉返回 False、冲突/其它失败抛 GithubError)。复用既有 _run_gh / _gh_json / PR。函数体注释引用 RFC-0009。
    acceptance: 单测覆盖 list_open_prs 解析(含空列表)、update_branch 三态(updated→True / already-up-to-date→False / 冲突→GithubError);ruff + pytest 全绿。
  - id: T2
    title: '`rebase_open_prs` 扇出模块'
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/rebase.py
      - tests/test_rebase.py
    scope: 新建 openagents/rebase.py,实现 rebase_open_prs(*, merged_pr_number=None, rebase=False):调 github.list_open_prs、排除 merged_pr_number、逐个 github.update_branch;冲突(GithubError)时 github.post_comment 贴冲突提示评论并继续;返回 [{pr_number, result}]。冲突评论文案以模块常量定义。注释引用 RFC-0009。
    acceptance: 单测(monkeypatch github.list_open_prs / update_branch / post_comment)覆盖:正常更新、排除已合并 PR、up-to-date 归类、冲突→留言且不中断后续、空 open 列表;ruff + pytest 全绿。
  - id: T3
    title: '`messages.poll` 合并后扇出集成'
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
    scope: 在 messages._process_run 侦测到 is_merged、置 STATUS_DONE 后追加 rebase.rebase_open_prs(merged_pr_number=pr_number);merged 事件可附带同步结果。其余路由逻辑不变。注释引用 RFC-0009。
    acceptance: 单测断言「侦测到合并时调用了 rebase.rebase_open_prs 且传入正确 merged_pr_number」(monkeypatch rebase 函数);既有 poll 用例不回归;ruff + pytest 全绿。
  - id: T4
    title: '`openagents sync-prs` 手动命令'
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: 在 cli.build_parser 注册 sync-prs 子命令(--merged、--rebase),新增 _cmd_sync_prs handler 延迟 import 并调 rebase.rebase_open_prs,打印结果摘要;接入 _dispatch handlers 表。注释引用 RFC-0009。
    acceptance: 单测断言参数解析与 handler 透传(monkeypatch rebase.rebase_open_prs,校验 merged_pr_number / rebase 入参与退出码);ruff + pytest 全绿。
  - id: T5
    title: 端到端脚本
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-rfc-0009-auto-rebase.sh
    scope: 新增 scripts/e2e-rfc-0009-auto-rebase.sh:在一个测试仓库建两个 open PR、合并其一、运行 openagents sync-prs --merged <n>(或一轮 poll),校验另一 PR 分支已并入最新 main(gh pr view --json mergeStateStatus 或对比 commits),并演示冲突场景下的留言。脚本含前置条件与运行说明(对齐既有 scripts/e2e-rfc-000X-*.sh 风格)。
    acceptance: 脚本可独立运行并打印每步结果;README/RFC 给出启动说明;bash -n 语法检查通过。
---

# 0009 · 合并后自动 rebase 其他 open PR

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

当一个 PR 合并进 `main` 后,自动把其余仍然开着的 PR 逐个 rebase（`gh pr update-branch`）到最新的 `main`,省去人工逐个手动 rebase。落地为四层:github 层新增 `list_open_prs` / `update_branch`,`rebase.py` 扇出模块统一编排「列出 open PR→排除已合并者→逐个更新分支→冲突留言不中断」,`messages.poll` 在侦测到合并时自动触发扇出,以及一个手动 `openagents sync-prs` 命令兜底。

## Motivation

OpenAgents 是去中心化多 Agent 协作框架,同一时刻常有多个 issue 各自派发了 agent、各开着一个 PR 并行推进。当其中一个 PR 先合进 `main` 后,其余 open PR 的分支基线就落后了:它们仍基于旧的 `main`,后续若直接合并容易产生过期 diff 或与新主干冲突。

在没有自动化之前,这件事要么靠人逐个去点 GitHub 的「Update branch」按钮,要么等到该 PR 自己被处理时才发现需要 rebase——前者把人重新绑回了「每次合并都要善后」的细节,与 OpenAgents「人做宏观把控、不做代码层面细节」的目标相悖;后者则让冲突暴露得太晚。

期望的工作方式是:**一旦有 PR 合入 `main`,框架自动把其余 open PR 拉到最新主干上**;能自动 rebase 的就直接更新分支,遇到冲突无法自动解决的,就在那个 PR 上留一条评论提示需要人/agent 介入,且不阻断对其余 PR 的处理。这样多 PR 并行时主干始终是各分支的最新基线,冲突尽早暴露在对应 PR 上。

## Guide-level explanation

对使用者:平时照常提 issue、让 agent 并行开 PR。当任意一个 PR 合进 `main`,框架的轮询(`messages.poll`)会自动对其余 open PR 发起一轮 rebase——能更新的分支自动更新,更新不了(冲突)的 PR 上会收到一条评论说明冲突、需要介入,其它 PR 不受影响继续被更新。

若想手动触发(例如刚手动合了一个 PR,或想立即对齐所有分支),可以跑:

```
openagents sync-prs [--merged <已合并PR号>] [--rebase]
```

`--merged` 指定刚合并的 PR 号(会从待更新列表中排除它自身),`--rebase` 选择用 rebase 方式更新分支。命令会打印每个 PR 的处理结果摘要。

## Reference-level explanation

落到改动,分解为 5 个 Task(DAG 见末尾;各 Task 的 `files` 互斥,单一 writer):

1. **T1 github 层 `list_open_prs` + `update_branch`**(无依赖) — 在 `github.py` 新增两个模块函数,作为整套扇出的底层能力。`list_open_prs()` 执行 `gh pr list --state open --json number,url`,解析为 `PR` 列表(空列表也正确返回)。`update_branch(*, pr_number, rebase=False)` 执行 `gh pr update-branch <n> [--rebase]`,三态语义:成功更新返回 `True`、「已是最新」吞掉返回 `False`、冲突或其它失败抛 `GithubError`。复用既有 `_run_gh` / `_gh_json` / `PR`。

2. **T2 `rebase_open_prs` 扇出模块**(依赖 T1) — 新建 `openagents/rebase.py`,实现 `rebase_open_prs(*, merged_pr_number=None, rebase=False)`:调 `github.list_open_prs` 取全部 open PR、排除 `merged_pr_number` 自身、逐个调 `github.update_branch`;某个 PR 冲突(`GithubError`)时调 `github.post_comment` 在该 PR 贴一条冲突提示评论(文案以模块常量定义)并**继续处理后续 PR**,不整体中断;返回 `[{pr_number, result}]` 列表,result 区分「更新成功 / 已是最新 / 冲突」三类。

3. **T3 `messages.poll` 合并后扇出集成**(依赖 T2) — 在 `messages._process_run` 中,侦测到 `is_merged`、把 run 置为 `STATUS_DONE` 之后,追加调用 `rebase.rebase_open_prs(merged_pr_number=pr_number)`;`merged` 事件可附带同步结果。其余路由逻辑保持不变。

4. **T4 `openagents sync-prs` 手动命令**(依赖 T2) — 在 `cli.build_parser` 注册 `sync-prs` 子命令(参数 `--merged`、`--rebase`),新增 `_cmd_sync_prs` handler:延迟 import `rebase` 后调 `rebase.rebase_open_prs`,打印结果摘要;接入 `_dispatch` 的 handlers 表。

5. **T5 端到端脚本**(依赖 T3、T4) — 新增 `scripts/e2e-rfc-0009-auto-rebase.sh`:在一个测试仓库建两个 open PR、合并其一、运行 `openagents sync-prs --merged <n>`(或一轮 poll),校验另一 PR 分支已并入最新 `main`(`gh pr view --json mergeStateStatus` 或对比 commits),并演示冲突场景下的留言。脚本含前置条件与运行说明,对齐既有 `scripts/e2e-rfc-000X-*.sh` 风格。

**端到端验证**:`bash scripts/e2e-rfc-0009-auto-rebase.sh`(建双 PR、合并其一、sync-prs 后校验另一分支已对齐最新 main，并演示冲突留言)。

依赖 DAG:`T1 → T2`,`T2 → T3`,`T2 → T4`,`T3 → T5`,`T4 → T5`。

## Drawbacks

- 每次合并都触发对所有 open PR 的扇出更新,PR 数量很多时会产生一批 `gh pr update-branch` 调用(N 个 open PR ⇒ N 次更新);但更新本身是幂等的(已最新即跳过),量级与 open PR 数线性。
- 自动 rebase 可能改写各 open PR 分支的提交基线,正在该分支上手工操作的人/agent 需要重新拉取。

## Rationale and alternatives

- **为什么放在 github 层加 `update_branch` 而不在扇出模块里直接拼 `gh` 命令**:把「调一次 gh 更新一个分支」收敛成 github 层的单一三态函数(True/False/抛错),扇出模块只编排、不关心 gh 细节,职责解耦(理念 10)、便于 monkeypatch 做 hermetic 单测。
- **为什么冲突时留言而非中断**:多 PR 并行场景下,一个 PR 冲突不应阻断其余 PR 的对齐;留言把「需要人/agent 介入」的信号留在对应 PR 上,符合 OpenAgents 以 PR/comment 为消息载体的协作模型。
- **为什么同时提供自动(poll 集成)与手动(sync-prs)两条入口**:自动路径覆盖常态(agent 合并触发);手动命令兜底人工合并或需要立即对齐的场景,二者共用同一 `rebase_open_prs`,无重复逻辑。
- **备选:不自动 rebase,只在 PR 被处理时按需更新**。否决:冲突暴露太晚,且把善后重新压回每个 PR 的处理流程。

## Prior art

GitHub 原生提供 PR 的「Update branch」按钮与 `gh pr update-branch` 命令,以及仓库设置里的「require branches to be up to date before merging」。本 feature 复用 `gh pr update-branch` 作为底层动作,把「合并后批量对齐其余 open PR」这一编排自动化,属于 trunk-based 开发中「保持各分支基于最新主干」的常见实践。

## Unresolved questions

无。三态更新语义、冲突留言而不中断、自动 + 手动双入口均已在本组确定。

## Future possibilities

- 冲突留言可升级为自动派发一个 agent 去解决该 PR 的 rebase 冲突。
- 扇出可加并发/限流策略,应对 open PR 数量很大的仓库。

