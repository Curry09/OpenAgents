# Spec-0060 证据：新栈 `oa solve` 子命令在真实 CLI 可见可达

取证类别：① UI 直接看得到——新增的 `solve` 子命令是产品对外行为（用户可在真实 CLI 调用），
此处以真 app（`uv run openagents ...`）跑出的命令列表 + 子命令帮助为证。

> 说明：**真实 issue 冒烟**（`oa solve <真实 issue>` 驱动真 LLM 走完 plan→implement→review→deliver
> 并让 PR CI 全绿）是 issue 第 5 条验收，spec 明确将其归为 Phase-3 人验/runbook（非 CI 确定性闸，
> 需真 LLM + 真 GitHub issue + worktree）。本文件只证「新栈 CLI 表面真实可达」这一可见成果；
> 端到端跑通一个真实 issue 因需真 LLM 环境，留 Phase-3 runbook，未在此验证。

## `openagents --help`（`solve` 出现在命令列表）

```
usage: openagents [-h] <command> ...

RFC 驱动的多 Agent 框架：拉取 issue → 派单 agent → 提 PR。

positional arguments:
  <command>
    init           绑定/初始化当前目录为 OpenAgents 项目
    rfc            为一个 issue 起草 RFC 并开 draft PR
    backfill-rfc   扫存量代码路径反推 spec 并开 draft PR
    refine-rfc     按 PR 最新评审评论精炼 RFC
    implement      RFC 获批后按 RFC 实现代码并转正 PR
    solve          [新栈] 用 solve_issue recipe 端到端求解一个 issue
    iterate        就 PR 的 comment/CI 反馈迭代代码
    issue          往当前项目仓库提一个 GitHub issue
    reply-comment  以本 agent 身份（带签名）回复某 PR 的评论
    poll           拉取并处理所有 PR 的新评论（一次性）
    watch          按间隔循环 poll（自动化拉取）
    board          启动本地成果看板
    vigil          守夜人模式：自主监控 issue → 派单 → 守候 PR
    vigil-all      多仓库统管：按配置文件并发守夜一组仓库（复用 vigil）
    release        把 main 当前 HEAD 发布为一个版本（预检通过后物化）

options:
  -h, --help       show this help message and exit
```

## `openagents solve --help`（新栈子命令表面）

```
usage: openagents solve [-h] [--base BASE] [--pr PR] issue

positional arguments:
  issue        issue 编号

options:
  -h, --help   show this help message and exit
  --base BASE  分支基线（默认 main）
  --pr PR      已有 PR 编号（用于注入评审历史；缺省自动按分支查找）
```
