---
number: "0002"
title: OpenAgents 主动提 issue
issue: 0
slug: create-issue
summary: 让 OpenAgents 不只被动接 issue，还能主动给仓库提 issue。加 github 层 create_issue、CLI issue 子命令，并给自动发现的 issue 打上发现标签、确保标签存在。
tasks:
  - id: T1
    title: github 层 create_issue
    status: done
    priority: P1
    tags:
      - cli
      - github
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: 在 openagents/github.py 增加 create_issue(*, title, body, labels)，调用 gh issue create、解析 issue number 返回 Issue；增加 _parse_issue_number 助手；并确保所需标签存在（ensure label，原 T3 的 github 部分，决策 6）。
    acceptance: 单测覆盖——成功解析 number；带 labels 时命令含 --label；url 不可解析时抛 GithubError；gh 非零退出时抛 GithubError。
  - id: T2
    title: CLI issue 子命令
    status: done
    priority: P1
    tags:
      - cli
      - github
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: 在 openagents/cli.py 注册 issue 子命令（positional title + --body + 可重复 --label），实现 _cmd_issue 走 preflight 并调用 github.create_issue，挂入 _dispatch handlers；并在 _cmd_issue 追加模块级 DISCOVERY_LABEL="openagents" 去重排序（原 T3 的 cli 部分，决策 5/6）。
    acceptance: 单测覆盖——parser 注册了 issue；issue "T" --body B --label x --label y 正确透传给打桩的 create_issue 且走 preflight；返回码 0；--label 之外自动附加 openagents 发现标签且去重。
---

# 0002 · OpenAgents 主动提 issue

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

让 OpenAgents 从「只被动接 issue」升级为「也能主动给仓库提 issue」。在 github 层新增 `create_issue`，在 CLI 暴露 `issue` 子命令，并为自动发现/主动创建的 issue 统一打上发现标签 `openagents`（创建前确保该标签在仓库中存在），使主动提的 issue 可被后续流程按标签识别与回收。

## Motivation

OpenAgents 既有能力是「领取仓库已有 issue → 起草改动 → 开 PR」，issue 的产生完全依赖外部输入。但作为一个要「迭代自身」的产品，agent 需要能**主动把发现的问题/想法落成 issue**，让工作流形成闭环：发现 → 立 issue → 领取 → 解决 → PR。

要实现这一点缺三块：

- github 层没有「创建 issue」的封装（只有读/列 issue 与 PR 相关操作）；
- CLI 没有让人或 agent 手动提 issue 的入口；
- 主动/自动产生的 issue 需要一个稳定的**发现标签**来与人工 issue 区分，且该标签必须在仓库里真实存在（否则 `gh issue create --label` 会因标签缺失失败）。

## Guide-level explanation

使用者通过一条命令提 issue：

```
openagents issue "标题" --body "正文" --label bug --label p1
```

它走与其它命令相同的 preflight 校验，然后在 GitHub 上创建一个 issue。无论用户是否显式给 `--label`，命令都会自动追加发现标签 `openagents`（按出现顺序去重，已有则不重复），并在创建前确保 `openagents` 标签存在于仓库中。vigil 在自动发现场景下回落使用的也是这同一个常量，保证「主动提的」与「自动发现的」issue 标签口径一致。

## Reference-level explanation

落到改动，分解为 2 个 Task（DAG 见下；`files` 互斥，各 Task 单一 writer）。注:原先「发现标签 + 确保标签存在（决策 5/6）」是一个独立小 Task,但它跨改 `cli.py`(T2 拥有) + `github.py`(T1 拥有) 两个文件、无独占文件——按单一 writer 原则,其 cli 部分并入 T2、github 部分并入 T1。

1. **T1 github 层 create_issue + ensure_label** — 在 `openagents/github.py` 增加 `create_issue(*, title, body, labels)`：调用 `gh issue create`（带 labels 时命令含 `--label`），从输出 URL 解析出 issue number 并返回 `Issue`；解析逻辑抽成 `_parse_issue_number` 助手。URL 不可解析或 `gh` 非零退出时抛 `GithubError`。并新增 `ensure_label`（不存在则建、已存在则吞 `"already exists"`、其它 gh 错误照抛，决策 6），保证带 `--label openagents` 创建时标签必然存在。这是「创建 issue」的最底层能力来源。

2. **T2 CLI issue 子命令 + 发现标签**（依赖 T1）— 在 `openagents/cli.py` 注册 `issue` 子命令：positional `title` + `--body` + 可重复 `--label`；`_cmd_issue` 先走 preflight，再调用 `github.create_issue`，并挂入 `_dispatch` 的 handlers 表。引入模块级常量 `DISCOVERY_LABEL = "openagents"`；`_cmd_issue` 在用户 `--label` 之外追加 `DISCOVERY_LABEL` 并按出现顺序去重，创建前先调 `github.ensure_label(name=DISCOVERY_LABEL)`；`_cmd_vigil` 的发现回落改用同一常量（决策 5）。这是人/agent 提 issue 的唯一 CLI 入口。

**决策 5/6 复述（自包含）**：主动/自动产生的 issue 一律附带统一发现标签 `openagents`，使其可被后续流程按标签识别；为避免 `--label` 引用不存在的标签导致创建失败，创建前幂等确保该标签存在。

**端到端验证**：本组无独立 `scripts/*.sh` e2e 脚本；验证依赖各 Task 的 `tests/test_github.py`、`tests/test_cli.py` 单测（打桩 `gh` 子进程，断言命令拼装、number 解析、标签追加去重、ensure_label 调用与错误传播）。

依赖 DAG：`T1 → T2`（线性，无并行）。

## Drawbacks

- 给所有主动提的 issue 强制追加 `openagents` 标签，会在仓库标签体系里引入一个约定俗成的保留标签；若仓库已有同名标签语义不同，可能产生歧义。
- `ensure_label` 在每次创建前多一次 `gh` 调用（已存在则吞错），是创建路径上的轻微开销，但换来「标签必存在」的幂等保证。

## Rationale and alternatives

- **为什么发现标签用模块级常量而非散落字面量**：`_cmd_issue` 与 `_cmd_vigil` 共用同一常量 `DISCOVERY_LABEL`，避免「主动提」与「自动发现」两处标签口径漂移（解耦 + 单一来源）。
- **为什么创建前 `ensure_label` 而非依赖仓库预置**：全新仓库可能没有该标签，`gh issue create --label openagents` 会直接失败；幂等 `ensure_label`（吞 "already exists"）让创建路径自洽，无需人工预建。
- **备选：用 issue body 里的标记串而非 label 标识发现来源**。否决：label 是 GitHub 一等检索维度，按 label 过滤/回收 issue 远比解析 body 文本稳健。
- **解析 number 抽成 `_parse_issue_number` 助手**：把脆弱的 URL 解析与错误抛出收敛到一处，便于单测覆盖各失败分支。

## Prior art

`gh issue create` 是 GitHub 官方 CLI 的标准建 issue 入口；以 label 标记「机器人/自动来源」是社区常见做法（如各类 bot 用专属 label 标注自动产生的 issue/PR）。本 feature 沿用「专属发现 label + 幂等确保 label 存在」这一既有模式，不引入额外的元数据通道。

## Unresolved questions

无。发现标签取值（`openagents`）、去重顺序（按出现顺序）、ensure_label 的错误吞吐边界（仅吞 "already exists"）均已在本组确定。

## Future possibilities

- agent 在解决 issue 过程中发现衍生问题时，自动调用本能力分裂出子 issue。
- 发现标签可扩展为可配置项，或按来源细分（人工发现 / vigil 自动发现）多个 label。

