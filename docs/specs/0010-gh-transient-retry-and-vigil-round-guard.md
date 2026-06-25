---
number: "0010"
title: gh 瞬时错误重试 + 守夜循环单轮容错
issue: 0
slug: gh-transient-retry-and-vigil-round-guard
summary: 给跟 GitHub 打交道加韧性：gh 命令遇到瞬时错误时指数退避重试，守夜循环每一轮用 try/except 兜底，单轮出错不拖垮整个循环。
tasks:
  - id: T1
    title: '`_run_gh` 瞬时错误重试 + 指数退避'
    status: done
    priority: P1
    tags:
      - reliability
      - cli
      - resilience
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: 在 `_run_gh` 内部加重试循环；新增 `_is_transient_gh_error` 纯函数与模块级常量（`_GH_RETRY_MAX_ATTEMPTS`、`_GH_RETRY_BACKOFF_BASE`、`_GH_TRANSIENT_MARKERS`）；捕获并归一化 `subprocess.TimeoutExpired` 为 `GithubError`。对外签名/返回类型不变。
    acceptance: stderr 含 `HTTP 504`/`Gateway Timeout` 等首次失败、第二次成功→最终成功，`subprocess.run` 调 2 次、`time.sleep` 调 1 次；持续瞬时失败→重试 `_GH_RETRY_MAX_ATTEMPTS` 次后抛 `GithubError`；`subprocess.TimeoutExpired`→视为瞬时重试、耗尽后抛 `GithubError`（非 TimeoutExpired）；非瞬时非零（如 `not found`）→不重试、立即抛 `GithubError`、`subprocess.run` 仅调 1 次；`allow_returncodes` 放行码（如 pending=8）→不触发重试、行为同现状；`time.sleep` 被 monkeypatch 零真实等待；既有 `tests/test_github.py` 全部用例仍通过。
  - id: T2
    title: '`vigil.run` 单轮 try/except 兜底'
    status: done
    priority: P1
    tags:
      - reliability
      - cli
      - resilience
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/vigil.py
      - tests/test_vigil.py
    scope: 把 `run` 循环体抽成 `_run_one_round(labels, base)`；长驻模式用 try/except 包裹、单轮 `Exception` 失败记日志并 `continue`；`once` 模式直接调用、异常上抛；`KeyboardInterrupt` 仍走既有干净退出。
    acceptance: 长驻模式（`once=False`）第一轮 `discover_and_dispatch`/`poll` 抛 `GithubError`/通用 `Exception`→记日志、不抛出、进入下一轮；`once=True` 单轮抛异常→异常照旧向上传播（不被吞）便于 cron/CI 得非零退出；`KeyboardInterrupt`→仍打印「✓ 守夜人已停止」并干净返回、不被单轮兜底误捕；正常路径（无异常）行为与现状逐字一致；既有 `tests/test_vigil.py` 全部用例仍通过。
---

# 0010 · gh 瞬时错误重试 + 守夜循环单轮容错

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给 OpenAgents 与 GitHub 交互的两条关键路径加韧性：（1）底层 `_run_gh`（封装 `gh` CLI 的子进程调用）遇到**瞬时错误**（如 `HTTP 504`、`Gateway Timeout`、网络抖动、超时）时，按指数退避**自动重试**，而非首错即抛；（2）守夜循环 `vigil.run` 的**每一轮**用 try/except 兜底，单轮发现/轮询出错只记日志并续下一轮，不让一次偶发失败拖垮长驻进程。两处改动都不改对外签名与正常路径行为，仅在错误路径上增加容错。

## Motivation

OpenAgents 的 agent 自动流转高度依赖 `gh` 命令：领 issue、开 PR、读评论、查 CI 状态全走 `_run_gh`。而 GitHub API 与 `gh` CLI 在实践中会出现**瞬时**故障——`HTTP 5xx`、`Gateway Timeout`、连接重置、命令超时——这些故障**重试一次往往就成功**。当前 `_run_gh` 把任何非零退出（除 `allow_returncodes` 放行的码外）一律归一化为 `GithubError` 立即抛出，把本可自愈的瞬时抖动升级成硬失败，沿调用链冒泡，常常直接终结一整轮自动流转。

守夜循环 `vigil.run` 是长驻进程：周期性 `discover_and_dispatch`（发现并派发 issue）+ `poll`（轮询 PR 评论/状态）+ `sleep`。当前循环体里任一步抛异常（哪怕只是某一轮里某个 issue 触发了上面那种 gh 瞬时错误），异常会逃出整个 `while` 循环，**整个守夜进程崩溃退出**——直到有人手动重启。对一个目标是「无人值守持续推进」的进程，这种「单点故障即全停」是不可接受的。

两个问题同源（瞬时故障被放大成致命故障），但作用在不同层级：T1 在最底层把瞬时 gh 错误**就地消化掉**；T2 在最外层给守夜循环**加一层兜底网**，即使有漏网的异常也只损失一轮、不损失整个进程。两层叠加得到「尽量自愈 + 自愈失败也不致命」的纵深防御。

## Guide-level explanation

对使用者，行为变化只在「出问题时更稳」，正常路径完全无感：

- **gh 命令更皮实**：以前一次 `gh` 调用撞上 GitHub 504 就直接报错中断；现在它会等一小段（指数退避：第 1 次重试等 base，第 2 次等 base×2…）后自动重试，最多 `_GH_RETRY_MAX_ATTEMPTS` 次。只有**持续**失败或**非瞬时**错误（如 `not found`、权限拒绝）才会真正抛 `GithubError`。判定「是否瞬时」由纯函数 `_is_transient_gh_error` 依据 stderr 里的标记串（`_GH_TRANSIENT_MARKERS`）决定，便于测试与扩展。
- **守夜人更耐造**：长驻模式（`once=False`）下，某一轮发现/轮询炸了，守夜人会把异常**记进日志**然后照常进入下一轮，不再整进程崩溃。一次性模式（`once=True`，给 cron/CI 用）保持「异常向上抛」语义，好让外层拿到非零退出码做告警。`Ctrl-C`（`KeyboardInterrupt`）仍走原有的干净停止路径，打印「✓ 守夜人已停止」后退出，不会被单轮兜底误吞。

## Reference-level explanation

落到改动，分解为 2 个 Task（`files` 互斥，各 Task 单一 writer）：

1. **T1 `_run_gh` 瞬时错误重试 + 指数退避**（`openagents/github.py` / `tests/test_github.py`）——
   - 在 `_run_gh` 内部把单次 `subprocess.run` 包进重试循环；
   - 新增纯函数 `_is_transient_gh_error(stderr) -> bool`，按 `_GH_TRANSIENT_MARKERS`（如 `HTTP 504`、`Gateway Timeout` 等标记串集合）匹配；
   - 新增模块级常量 `_GH_RETRY_MAX_ATTEMPTS`（最大尝试次数）、`_GH_RETRY_BACKOFF_BASE`（退避基数，第 n 次退避 = base × 2^(n-1)）；
   - 捕获 `subprocess.TimeoutExpired` 并视为瞬时（重试），耗尽后归一化为 `GithubError`（**不**向外泄露 `TimeoutExpired`）；
   - **对外签名与返回类型保持不变**——`allow_returncodes` 放行的退出码不进入重试分支，行为与现状逐字一致，保证向后兼容。
2. **T2 `vigil.run` 单轮 try/except 兜底**（`openagents/vigil.py` / `tests/test_vigil.py`）——
   - 把 `run` 的循环体抽成内部函数 `_run_one_round(labels, base)`（一轮 = 发现派发 + 轮询）；
   - 长驻模式（`once=False`）下，对 `_run_one_round` 的调用用 `try/except Exception` 包裹：捕获到通用 `Exception`（含 T1 兜底失败后抛出的 `GithubError`）则**记日志 + `continue`** 进下一轮；
   - 一次性模式（`once=True`）**直接调用**、不包 try，让异常自然上抛；
   - `KeyboardInterrupt` 不被 `except Exception` 捕获（`KeyboardInterrupt` 不是 `Exception` 子类），仍走既有干净退出路径。

**依赖关系**：T1 与 T2 **互不依赖**（`depends-on: []`），分属 github / vigil 两个解耦模块，`files` 完全不相交，可完全并行实施。依赖 DAG：无边（两个独立节点 T1、T2）。

**端到端验证**：本组改动均为单元层容错增强，验证以两个模块的单测覆盖为主——`pytest tests/test_github.py tests/test_vigil.py`（`time.sleep` 在测试中被 monkeypatch，零真实等待）。本组不新增 `scripts/*.sh` e2e 脚本。

## Drawbacks

- 重试会**放大单次 gh 调用的最坏耗时**：持续瞬时失败时，要把 `_GH_RETRY_MAX_ATTEMPTS` 次退避全部走完才最终报错，比「首错即抛」慢。通过把退避基数设小、上限设少来收敛。
- 守夜单轮兜底「吞掉」异常只记日志，可能让**反复失败的某一轮**被静默重试而不被立即注意到——依赖日志被人/告警消费来补偿。

## Rationale and alternatives

- **为什么在 `_run_gh` 这一层加重试**：它是所有 gh 调用的单一收口，改一处即让全链路受益（DRY），且瞬时/非瞬时的判定信息（stderr、退出码、超时）都集中在这里最完整。
- **为什么用 stderr 标记串判定瞬时、而非按退出码**：`gh`/底层 HTTP 的瞬时故障退出码并不稳定区分，stderr 文本里的 `HTTP 5xx`/`Gateway Timeout` 等标记更可靠；抽成纯函数 `_is_transient_gh_error` + 常量集合 `_GH_TRANSIENT_MARKERS` 便于 hermetic 测试与日后增补标记。
- **为什么守夜兜底只 `except Exception` 而不 `except BaseException`**：必须放过 `KeyboardInterrupt`/`SystemExit`，否则 `Ctrl-C` 会被误吞、守夜人停不下来。
- **为什么 `once=True` 不兜底**：一次性模式给 cron/CI 用，需要靠**非零退出码**触发告警；若也吞异常会掩盖失败。
- **备选：把重试做在每个调用点**。否决——重复且易漏，违反奥卡姆剃刀；收口到 `_run_gh` 单点最简。
- **备选：守夜整循环一个大 try/except**。否决——粒度太粗会让「应当致命的错误」也被吞；按「单轮」兜底才能「损失一轮、不损失进程」。

## Prior art

指数退避重试（exponential backoff）是与远程/网络服务交互的业界标准容错手法（HTTP 客户端、云 SDK 普遍内建）。长驻 worker「逐轮兜底、单次失败不致命」也是守护进程/事件循环的常见健壮性模式。本 feature 取其最小形态，不引入 jitter、断路器等更重机制。

## Unresolved questions

无。瞬时标记集合、退避参数、`once` 与长驻两模式的兜底边界均已在本组确定。

## Future possibilities

- 给退避加入随机 jitter，缓解多 agent 同时重试的惊群。
- 把 `_GH_RETRY_MAX_ATTEMPTS`/`_GH_RETRY_BACKOFF_BASE` 提为可配置项。
- 守夜单轮失败累计阈值触发告警/熔断（当前仅记日志）。

