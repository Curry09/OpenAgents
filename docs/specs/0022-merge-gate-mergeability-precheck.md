---
number: "0022"
title: 代码闸可合并性预检 + poll 错误隔离 + 裁决评论幂等
issue: 62
slug: merge-gate-mergeability-precheck
summary: 代码闸（merge gate）三处加固：合并前预检 PR 可合并性（不可合并直接跳过、不空转崩溃 poll）、poll 阶段隔离单个 PR 的错误不拖垮整轮、裁决评论幂等避免刷屏重复 PASS。迁移自旧 metadata（原无 summary，按标题与任务补齐）。
tasks:
  - id: T1
    title: github.mergeability：查询 PR 可合并性（mergeable / mergeStateStatus）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: 在 github.py 新增只读查询 mergeability(*, pr_number)，经 _gh_json 跑 gh pr view <n> --json mergeable,mergeStateStatus，返回 frozen dataclass Mergeability{mergeable, merge_state_status}，字段保持 GitHub 原值大写字符串不归一化；判定语义留给 T2。结构镜像 is_merged/is_closed/check_status，全关键字参数、纯读无副作用。
    acceptance: 单测（monkeypatch _run_gh/_gh_json，hermetic）断言：DIRTY/CONFLICTING、CLEAN/MERGEABLE、UNKNOWN/UNKNOWN 三组字段均如实回传且 UNKNOWN 不抛错；_gh_json 返回非 dict 或缺字段抛 GithubError；传给 gh 的参数恰为 pr view <n> --json mergeable,mergeStateStatus。
  - id: T2
    title: 代码闸可合并性预检 + poll 单 PR 错误隔离
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
    scope: 改 messages.py 两处。(1) _process_coding 最前插入可合并性预检：mergeStateStatus==DIRTY 或 mergeable==CONFLICTING 视为真冲突，复用 rebase.CONFLICT_COMMENT 经 identity.post_signed_comment 发一次 rebase 提示后走 _block(gate="merge")，返回 reason="unmergeable"；UNKNOWN return None 下轮重查；CLEAN 照走 CI→reviewer→merge。(2) poll 逐 record 把 _process_run 包进 try/except，捕获后追加 reason="error" 事件并 continue、不改 state、不拖垮整轮。
    acceptance: 单测（monkeypatch github/identity/orchestrator，hermetic）断言：DIRTY/CONFLICTING→不调 review_code/merge_pr、post_signed_comment 恰 1 次且 body 为 rebase.CONFLICT_COMMENT、record 置 STATUS_BLOCKED+needs-human、事件 reason=="unmergeable"；第二轮该 record return None（恰一条评论回归）；UNKNOWN 不评审不 block 不发评论；CLEAN 零回归走既有路径；某 record 抛 GithubError 时 poll 不抛、产 reason=="error" 事件且其余 record 照常处理。
  - id: T3
    title: 裁决评论幂等：同一裁决不每轮重发
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: 改 orchestrator._post_review_decision：发评论前用 github.list_comments（只读）查既有评论，靠 reviewer.render_decision 稳定抬头「## 评审闸裁决」+ kind 识别裁决评论，按裁决结论（PASS/非 PASS）去重——最近一条同 kind 裁决结论与本轮相同则跳过（_progress 记一句），不同或无既往裁决则照发；list_comments 或比对异常一律降级照发（fail-open，best-effort 旁路）。不按正文逐字节比对、不改 reviewer/github。
    acceptance: 单测（monkeypatch github.list_comments/identity.post_signed_comment/reviewer，hermetic）断言：既有同 kind PASS 裁决时本轮 PASS 不再调 post_signed_comment（同结论跳过）；PASS↔非 PASS 翻转照发；无既往裁决首次照发；rfc 与 code 裁决互不抑制（kind 隔离）；list_comments 抛错时不抛出、降级照发且 ReviewDecision 不受影响。
---

# 0022 · 代码闸可合并性预检 + poll 错误隔离 + 裁决评论幂等

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给代码闸（merge gate）做三处加固，对症 issue #62 暴露的「不可合并 PR 让 poll 空转又崩溃、还把同一裁决刷成几十条评论」：(1) 在跑 reviewer 之前先预检 PR 与 base 的真实可合并性，真冲突一次性进 blocked + needs-human + 留一次 rebase 提示，不再每轮空转；(2) 给 poll 逐 record 处理加错误隔离，单个 PR 失败（含 merge_pr 抛错）只记一条错误事件并继续，不拖垮整轮；(3) 让裁决评论幂等，同一裁决结论不每轮重发。三件事分解为 T1（github 叶子查询）→ T2（代码闸预检 + 错误隔离）与正交的 T3（裁决去重）。

## Motivation

**根因复现（issue #62 / PR #61，完整复述，不要求读者去翻别的 spec）。** 当前代码闸 `messages._process_coding` 进闸前**完全不看 PR 可合并性**：只要 CI 绿 + reviewer 裁决 PASS 就直接 `github.merge_pr`（messages.py:230，该调用**无 try/except**）。而 `merge_pr` 遇冲突会经 `_run_gh` 抛 `GithubError`，`poll()` 逐 record 循环（messages.py:117-125）也不兜异常 —— 于是一旦某个 PR 不可合并，**整轮 poll 直接崩**。又因进闸前不查可合并性，每个 interval 会重跑一遍 reviewer（白烧一次 agent 运行）→ 又判 PASS → 又 merge 失败 → 又崩。

实例 PR #61：14 个 `docs/specs/*/metadata.yaml` 是**内容冲突**（`mergeable=CONFLICTING`、`mergeStateStatus=DIRTY`），自动 rebase 救不回来（`update-branch` 非真 rebase，heal 自愈只重渲 OVERVIEW.md、动不了 metadata），结果它被重复判 PASS 33 次、刷出 33 条一模一样的 `## 评审闸裁决 ✅ PASS`、永远合不进去。

**为什么要改。** 这条恶性循环有三个独立病灶，恰对应 issue #62 的三条验收期望：闸进闸前不查可合并性（空转源头）、poll 不兜单 record 异常（整轮崩源头）、裁决回贴无条件每轮发（刷屏源头）。三者需分别止血。

**裁决刷屏的来历。** RFC-0018 让 reviewer 闸把裁决回贴 PR（恢复人对评审闸的可观测性），但回贴是**无条件每轮发**：只要 record 仍在 coding/rfc-review 阶段、每个 interval 重跑一次 reviewer，就重发一条裁决评论。PR 长期 open 且裁决不变时（不限于冲突场景）便会刷屏。

## Guide-level explanation

三处加固各自独立、互不依赖运行时状态：

| 病灶（issue #62） | 现象 | 本 feature 的对治 |
|------|------|------|
| 进闸前不查可合并性 | 真冲突 PR 每轮重跑 reviewer 空转 | T1 提供只读查询 + T2 预检短路、一次性进 blocked |
| poll 不兜单 record 异常 | 单个 PR 失败掀翻整轮 poll | T2 给逐 record 处理加错误隔离 |
| 裁决回贴无条件每轮发 | 同一裁决刷成几十条 PASS | T3 按裁决结论去重、同结论跳过 |

对使用者：行为只增不变 —— 真冲突的 PR 会被一次性标 `needs-human` 并附一条 rebase 提示（而非反复空转），其余 PR 照常走 CI→reviewer→merge；poll 不再因单个坏 PR 整轮挂掉；PR 评论区不再被相同裁决刷屏。无对外签名变更，无需任何配置或命令变化。

## Reference-level explanation

落到改动，分解为 3 个 Task（DAG 见下；`files` 互斥，各 Task 单一 writer）：

1. **T1 github.mergeability（叶子能力，无依赖）** — 在 `openagents/github.py` 新增只读查询，结构上**镜像既有 `is_merged`（512）/ `is_closed`（540）/ `check_status`（492）**：经唯一收口点 `_gh_json` 跑 `gh pr view <n> --json mergeable,mergeStateStatus`，自带 RFC-0010 的瞬时错误重试，零额外依赖、零新外部数据源（理念 1 奥卡姆）。返回值用一个小的 frozen dataclass（仿 `CheckStatus` 的轻量结构体）承载两个原始字段，而**不**回退成裸 tuple —— 让调用方按字段名读、避免位置歧义。字段保持 GitHub 原值大写字符串（`"DIRTY"` / `"CONFLICTING"` / `"UNKNOWN"` 等），不在本层做任何归一化或布尔判定（把「哪种组合算不可合并」留给 T2，理念 10 解耦）。建议签名：

   ```python
   @dataclass(frozen=True)
   class Mergeability:
       mergeable: str            # GitHub 原值：MERGEABLE / CONFLICTING / UNKNOWN
       merge_state_status: str   # GitHub 原值：CLEAN / DIRTY / BLOCKED / BEHIND / UNKNOWN / ...

   def mergeability(*, pr_number: int) -> Mergeability: ...
   ```

   全部关键字参数（CLAUDE.md 禁止位置参数），纯读无副作用、不改 state。错误处理沿用既有风格：`_gh_json` 返回非 dict 或缺字段 → 抛 `GithubError`（与 `is_merged`/`is_closed` 逐字一致）；`UNKNOWN`（GitHub 异步尚未算完）是**合法返回值**，照实回传、本层不视为错误，是否等待由 T2 决策。

2. **T2 代码闸预检 + poll 错误隔离（依赖 T1）** — 改 `openagents/messages.py` 两处，均不新增模块、不改状态机定义（理念 1）。
   - **(1) 可合并性预检** 插在 `_process_coding` **最前**（甚至先于 CI 判断 —— 冲突 PR 连 CI 都不必等，越早短路越省）。判定：`mergeStateStatus == "DIRTY"` 或 `mergeable == "CONFLICTING"` 视为真冲突（二者在冲突场景同时出现，取或更稳）。冲突动作：先 `identity.post_signed_comment` 发一次 rebase 提示（**复用 `rebase.CONFLICT_COMMENT` 文案**，避免散落漂移；agent_id 用 `self._agent_id`），再走既有 `self._block(record=record, gate="merge")`（置 `STATUS_BLOCKED` + 打 `needs-human`），返回事件 `{"reason": "unmergeable"}`。**「恰一条评论」靠状态机短路**：`_block` 后 record 变 `STATUS_BLOCKED`，下一轮 poll 经 `_process_run` 的 blocked 分支（messages.py:168）—— 仍有 needs-human 标签即 `return None` 跳过，永不再进 `_process_coding`，故提示天然只发一次、无需额外去重状态。`UNKNOWN`（刚 push 常见）：`return None`，本轮不评审也不 block，下个 interval 重查。
   - **(2) poll 单 record 错误隔离** 把 `self._process_run(record=...)` 包进 try/except（沿用 RFC-0004 决策 8 / `rebase.rebase_open_prs`（rebase.py:55-76）的错误隔离风格）：捕获后追加一条 `{"pr_number": ..., "reason": "error", "error": <摘要>}` 事件并 `continue`，绝不让单 record 异常冒泡掀翻整轮。**不改 state**（失败可能是瞬时 gh 错误，下一轮自然重试，可观测性由 error 事件 + watch 日志承担）。包裹粒度选「整个 `_process_run`」而非「仅 merge_pr」，覆盖所有 record 处理路径。`_block` 的 `gate` 取值扩展一个 `"merge"`（现有为 `"rfc"`/`"code"`），仅用于事件标注。

3. **T3 裁决评论幂等（无依赖，与 T2 正交、可并行）** — 只改 `openagents/orchestrator.py` 的 `_post_review_decision`（裁决产生即回贴的单点收口，239-253）。发评论前先 `github.list_comments`（只读，已存在）查既有评论，靠 `reviewer.render_decision` 输出的稳定抬头 `## 评审闸裁决` + kind（rfc/code）识别裁决评论，**按裁决结论（PASS / 非 PASS）去重**：比对最近一条同 kind 裁决结论与本轮 `decision.passed`，相同则跳过（`_progress` 记一句），不同（翻转）或无既往裁决则照发。**不按正文逐字节比对**（票数渲染「N 中 X 票 PASS」或措辞每轮微变会让逐字节判「不同」而继续刷屏）。**尽力而为绝不阻断**（沿用 RFC-0018 决策 2）：`list_comments` 或比对任何异常都 `except` 后**降级为照常发送**（fail-open），仅 `_progress` 记一句，评审闸与下游 refine/iterate/merge 不被拖崩或拦住。与 T2 正交：T2 用状态机短路止住冲突 PR 源头，T3 用评论比对兜所有其它「裁决不变仍重发」场景，文件不相交、可独立验证。

**端到端验证**：本组迁移自旧 metadata，无独立 e2e 脚本；hermetic 验证由各 Task 的 `tests/test_github.py`、`tests/test_messages.py`、`tests/test_orchestrator.py`（全 monkeypatch、不触真实 gh）承担。整仓回归走 `uv run pytest`（与 CI 一致）。

依赖 DAG：`T1 → T2`，`T3` 独立（与 T1/T2 无依赖、可并行）。

## Drawbacks

- 预检判定阈值（`DIRTY` 或 `CONFLICTING` 即冲突）是固定取或，未来若出现别的 `mergeStateStatus` 需要拦截，需回到 T2 调参（但收口在单点，改动面小）。
- T3 按结论去重意味着「同结论但反馈正文更新」的那一版不会重贴 —— 人看到的是「结论变了」的信号，细节需到 worktree/日志查；可接受。
- 错误隔离只记事件不升级状态，理论上一个反复瞬时失败的 PR 会每轮被隔离、不主动 block；本组从简不引入计数升级状态（见 Rationale）。

## Rationale and alternatives

- **T1 小 dataclass vs 裸 tuple/dict**：选 dataclass。tuple 位置易错、dict 键名散落；dataclass 与 `CheckStatus` 同构，调用方读字段名最清晰，代价仅一个轻量类型（理念 1 可接受）。
- **T1 只取回原值 vs 本层直接给 `is_unmergeable() -> bool`**：选只取回原值，把布尔判定放 T2，github 层保持「薄 gh 封装、零业务」（理念 10）；否则阈值逻辑渗进叶子模块、未来调参要改两处。
- **T1 一次查两字段 vs 分两次查**：一次 `--json mergeable,mergeStateStatus`，省一次 gh 往返，且两字段同源快照、避免读到不一致中间态。
- **T2 预检放 `_process_coding` 最前 vs CI 之后**：选最前。冲突 PR 等 CI 无意义，越早短路越省（连 CI 轮询都免）。
- **T2 错误隔离粒度：整个 `_process_run` vs 仅 `merge_pr`**：选包整个 `_process_run`。崩点本质是「逐 record 不兜异常」，包到 record 级一次性覆盖所有路径，符合 rebase.py「单 PR 失败不拖垮整轮」风格，未来新增 gh 调用也自动受保护。
- **T2 错误隔离是否改 state（升级 needs-human）**：选不改、只记事件。失败常是瞬时（gh 限流/网络），贸然 block 会把可自愈 PR 焊死；保持下一轮自然重试。累计 N 轮升级是更主动方案，但要引入计数状态、增实体，本组从简不做。
- **T2 rebase 提示复用 `rebase.CONFLICT_COMMENT` vs 新写文案**：复用。同一「请手动 rebase」语义只应有一处文案来源，避免 RFC-0009 与本组各写一句、日后漂移。
- **T3 按裁决结论去重 vs 正文逐字节去重**：选结论。逐字节会因票数/措辞微变失效、继续刷屏；按 PASS/非 PASS 结论去重才命中「同一裁决不重发」的真实意图。
- **T3 去重放 orchestrator vs reviewer**：放 orchestrator。回贴本就收口在 `_post_review_decision`；reviewer 保持「输入 diff → 输出裁决」的纯函数、不沾 PR 评论状态（理念 10 解耦）。
- **T3 去重失败时默认照发 vs 默认跳过**：默认照发（fail-open）。宁可偶尔多一条评论，也不能因查询抖动漏发裁决、损害可观测性，与 best-effort 旁路语义一致。

## Prior art

GitHub 把 PR 可合并性拆成 `mergeable`（MERGEABLE / CONFLICTING / UNKNOWN）与 `mergeStateStatus`（CLEAN / DIRTY / BLOCKED / BEHIND / DRAFT / HAS_HOOKS / UNKNOWN / UNSTABLE）两个字段（见 `gh pr view --json` 文档与 GitHub GraphQL 对应枚举），冲突场景表现为 `mergeable=CONFLICTING` 且 `mergeStateStatus=DIRTY`；T1 如实取回这两字段。错误隔离「单 PR 失败不拖垮整轮」沿用本仓 `rebase.rebase_open_prs` 与 RFC-0004 决策 8 的既有范式；裁决回贴的 best-effort 旁路语义沿用 RFC-0018。

## Unresolved questions

无。三处加固的判定阈值、去重粒度、错误隔离粒度均已在本组确定。

## Future possibilities

- 错误隔离可扩展为「累计 N 轮失败再升级 needs-human」的主动方案（需引入计数状态，当前 YAGNI）。
- 预检判定可随 GitHub 字段演进扩展更多 `mergeStateStatus`（如 BEHIND 自动触发 rebase）。

