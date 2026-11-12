---
number: "0061"
title: 架构重构（批次二）：立起 vigil/poll_comments/fleet 三条 recipe + triager/replier agent + utils 全量稳定面
issue: 145
slug: agents-recipes-flows
summary: 承接 Spec-0060 批次一的架构契约（一切需判断的操作走 agent、recipe 只按结构化裁决路由、runtime 留最小硬闸、utils 归确定性原语），把留给后续批次的三条 recipe（vigil 发现→分诊→派单循环 / poll_comments PR 新人类评论回应 / fleet 多仓库并发）与两个 agent（triager 吸收 align+issuecheck 的 issue 对齐/冲突自检判断、replier 吸收评论回复判断）additive 立起，并把 utils 从批次一的 git/github 两个薄再导出扩成覆盖 release/notes/hold/skip/results/identity/config/envcheck/fleet_config 的完整稳定 import 面——让新栈能自足编排一个 issue 从发现到交付的全生命周期，不再直接 import 旧模块。仍 additive、不删旧 orchestrator/vigil/messages/fleet 及其测试桩（其删除与旧 spec 作废留最终收敛批次）。
e2e:
  intent: 证明批次二架构契约在离线确定性链路上成立——vigil recipe 只按 triager 结构化裁决路由（actionable→dispatch / 否→_park）、去重三闸确定性滤新；poll_comments 只做拉新人类评论→replier→签名回帖→游标推进纯控制流、单 PR 失败错误隔离；fleet 复用旧 Fleet 监管器扇出新栈 vigil；triager/replier 零逻辑、三 recipe 不直调 gh/git/subprocess。
  method: |
    形态：纯后端编排，无 product-facing 前端可导航；自检工具列表无 Playwright / Chrome DevTools MCP，
    故不设浏览器 e2e，改用离线确定性测法：
    1. 契约路由 + 各层针对性 pytest（假 backend 喂 canned 结构化裁决，不触真实 LLM/网络/仓库）：
       vigil 分诊路由 + 去重三闸；poll_comments 游标推进/错误隔离；fleet 扇出 + worker；CLI 三命令解析转发。
    2. 零逻辑 / 零 IO grep 锚点（e2e 脚本）：triager/replier 只含 Template( + OUTPUT_SCHEMA 且无
       def/subprocess；三 recipe 无 subprocess、不直接 import 原始 openagents.github/workspace（只经 utils）。
    3. 真实多仓守夜冒烟（dogfood，Phase-3 人验 / runbook，非 CI 确定性闸）：oa vigil-new / oa fleet
       跑通、PR CI 全绿——作为成果验收（理念 8）在 runbook 记录，不塞进离线脚本。
    脚本：scripts/e2e-spec-0061-agents-recipes-flows.sh（ruff check + ruff format --check +
    针对性 pytest + grep 锚点），被 PR e2e signpost 采集。
tasks:
  - id: T1
    title: utils 全量稳定 import 面（薄再导出确定性原语）
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/github.py
      - openagents/utils/git.py
      - openagents/utils/release.py
      - openagents/utils/notes.py
      - openagents/utils/hold.py
      - openagents/utils/skip.py
      - openagents/utils/results.py
      - openagents/utils/identity.py
      - openagents/utils/config.py
      - openagents/utils/envcheck.py
      - openagents/utils/fleet_config.py
    scope: 把 utils 从批次一的 git/github 两个薄再导出，扩成覆盖 release/notes/hold/skip/results/identity/config/envcheck/fleet_config 的完整稳定面；全部薄再导出旧模块，不复制不改动（奥卡姆）。git 新增 remote_branch_exists 免实例自由函数。
    acceptance: 新栈可只 import openagents.utils.* 拿到 github/git/identity/fleet_config 等全部确定性原语；旧模块与其 11 个测试桩零改动；ruff 绿。
  - id: T2
    title: triager + replier agent（零逻辑 Template 提示词）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/agents/triager.py
      - openagents/agents/replier.py
    scope: triager 吸收 align.restate + issuecheck.check 的 issue 对齐/冲突自检判断（fail-open）；replier 吸收 _HUMAN_UNBLOCK_TASK 的评论回复判断。均 string.Template PROMPT + OUTPUT_SCHEMA，零控制流。
    acceptance: triager 出 {actionable,reason}；replier 出 {reply,resolved}；模块无 def/subprocess（判断纯下放 prompt）；engine.run_agent 可派。
  - id: T3
    title: vigil + poll_comments + fleet recipe（纯控制流）+ 循环上下文组装
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - openagents/recipes/poll_comments.py
      - openagents/recipes/fleet.py
      - openagents/runtime/context.py
    scope: vigil 发现→triager 分诊→派单 solve_issue（去重三闸留 recipe）；poll_comments 拉新人类评论→replier→签名回帖→游标推进；fleet 复用旧 Fleet 监管器扇出新栈 vigil。context 加 for_triage/for_reply 模块级组装。
    acceptance: 三 recipe 只按 agent 结构化裁决路由、不含业务判断、不直调 git/gh/subprocess；依赖（dispatch/spawn）可注入、可 hermetic 单测；ruff 绿。
  - id: T4
    title: CLI additive 接线新栈守候/守夜/舰队三命令
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_agents_triager_replier.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_poll_comments.py
      - tests/test_recipe_fleet.py
      - tests/test_cli_new_stack.py
      - scripts/e2e-spec-0061-agents-recipes-flows.sh
    scope: 新增 _new_runtime_state_for / _new_vigil_for 工厂 + poll-comments / vigil-new / fleet 三子命令；旧 vigil/vigil-all/poll 路由零改动，两栈并存。各层针对性单测 + 离线 e2e 脚本（ruff+pytest+grep 锚点）。
    acceptance: 三新命令解析并分发；vigil-new 每轮跑发现+守候；fleet 同 vigil-all 跳过 cwd preflight；旧命令行为不变。scripts/e2e-spec-0061-agents-recipes-flows.sh 全绿。
---

# 0061 · 架构重构（批次二）：立起 vigil/poll_comments/fleet 三条 recipe + triager/replier agent + utils 全量稳定面

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

批次二在批次一（Spec-0060）立起的新栈骨架（agents/recipes/runtime/utils 四层 + `solve_issue` 单 issue 竖切）之上，additive 补齐三条**循环型** recipe（`vigil` 发现→分诊→派单、`poll_comments` 回应 PR 新人类评论、`fleet` 多仓库并发）与两个新 agent（`triager` issue 分诊、`replier` 评论回应），并把 utils 扩成覆盖 `release/notes/hold/skip/results/identity/config/envcheck/fleet_config` 的完整稳定 import 面。至此新栈可自足编排「一个 issue 从被发现到交付、及 PR 上人机对话」的全生命周期，不再直接 import 旧模块。仍严格 additive：旧 `orchestrator/vigil/messages/fleet` 及其 ~11 个测试桩零改动，两栈并存，删旧与作废旧 spec 留最终收敛批次。

## Motivation

批次一只交付了「单 issue 一次求解」的 `solve_issue`，但产品要的自主闭环还差三段循环：**发现**（去 GitHub 拉 issue 主动派单）、**对话**（人在 PR 上追问时 agent 回应）、**规模**（一次守多个仓库）。这三段在旧栈分别是 `vigil.py`（248 行）/`messages.py`（964 行阶段状态机）/`fleet.py`，它们把「判断」（issue 讲清没？评论想要什么？）和「机械」（去重、路由、进程编排）糅在一起，正是本次重构要拆开的东西。

批次二的动机就是把这三段按批次一的分界线重新立起来：**需要判断的下放 agent（triager/replier），客观机械留确定性代码（recipe 控制流 + gates 硬闸 + utils 原语）**。同时补全 utils 稳定面——批次一只再导出了 git/github，recipes 一旦要拉评论、判身份、读 fleet 配置就又得 import 旧模块，稳定面不闭合，故本批一次补齐到「新栈只 import `openagents.utils.*` 即可」。

## Guide-level explanation

三条 recipe 各是一条**纯控制流**竖切，只做「调 engine 派 agent + 按 agent 结构化裁决路由 + 调确定性 utils/gates 兜底」，自己不含业务判断、不直调 git/gh/subprocess：

- **`recipes.vigil`**：逐轮 `github.list_issues(labels)` → 对每个**新** issue（去重三闸：无 run 记录 且 远端无分支 且 未挂 needs-human）派 `triager` 出 `actionable` 裁决 → True 则 `dispatch`（默认建 worktree + 组 Context + 跑 `solve_issue`），False 则打 needs-human + 贴对齐理由挂起。每轮末尾再跑一次守候段 `poll_comments`。
- **`recipes.poll_comments`**：逐轮 `github.list_open_prs()` → 对每个 PR 取「游标之后的新人类评论」（`identity.new_human_comments` 按签名滤掉一切机器评论）→ 派 `replier` 出 `{reply, resolved}` → `identity.post_signed_comment` 盖签名回帖 → 推进游标。签名 + 游标两道确定性机制杜绝「回复被下轮当成新评论」的自触发死循环。
- **`recipes.fleet`**：为每个 `RepoPlan` 各起一隔离子进程跑新栈 `vigil`（cwd 隔离，因为 gh 绑进程 cwd）。进程监管（fan-out/日志聚合/崩溃隔离/Ctrl-C）与新旧栈无关，直接复用旧 `fleet.Fleet` 监管器，本模块只提供「子进程目标构造新栈 vigil」这一件新事。

两个 agent 都是零逻辑的 `string.Template` PROMPT + `OUTPUT_SCHEMA`：`triager` 把 issue 复述成三段并做修法冲突自检（**fail-open**，拿不准就放行），`replier` 读一条人类评论决定怎么回、要不要改代码（`resolved` 表诉求是否已充分解决）。

CLI additive 加 `poll-comments`/`vigil-new`/`fleet` 三命令与 `_new_vigil_for` 工厂（fleet 子进程与 CLI 同源接线），旧 `vigil`/`vigil-all`/`poll` 路由一行不动。

## Reference-level explanation

**分界线（与批次一逐字一致）**：判断→agent、机械→确定性代码。落到本批的判定：

- **留在 recipe 的确定性闸不是判断**：vigil 去重三闸（run 记录/远端分支/needs-human 标签存在性）、poll_comments 游标水位线 + 签名过滤——都是**读客观事实**（有没有、比不比 since 新、带不带签名），非「issue 好不好/评论该怎么回」这类判断，故留 recipe、不下放 agent。
- **`triager` 的 fail-open 与 `reviewer` 的 fail-closed 相反**：分诊是「进场闸」，滥拦一个健康 issue 比漏判更糟（漏判还能被 PR 评审兜住），故拿不准放行；评审是「出场闸」，故从严。
- **循环型 recipe 的上下文组装用模块级函数**：`Context` 类绑单 issue/PR 一次 run，但 vigil 逐 issue 扫、poll_comments 逐 PR 扫，无「单一 run 实例」，故 `context.for_triage/for_reply` 是模块级函数，入参是 recipe 已在去重/游标逻辑里拉到的 Issue/Comment 对象，只做纯组装、不二次读 github。
- **run 记录用批次一的 `RuntimeState`**（独立文件 `runtime-state.json`）：vigil 的派单去重 + poll_comments 的评论游标都落它，与旧 `state.json` 文件级零冲突。身份解析 `_agent_id_for` 仍走旧 `State`（env>state>生成），使新旧栈同进程身份一致。
- **`utils` 全是薄再导出**：release/notes/hold/skip/results/identity/config/envcheck/fleet_config 各只 `from openagents.<mod> import ...` 再 `__all__` 暴露，不复制不改动旧模块一行（奥卡姆，理念 1）。唯一新增确定性原语是 `git.remote_branch_exists`（免实例自由函数，vigil 去重闸需要而旧 `Workspace` 只有实例方法）。
- **`fleet` 复用旧 `Fleet` 监管器**：`from openagents.fleet import Fleet, _QueueWriter, default_queue`——进程 fan-out/日志前缀聚合/崩溃隔离/Ctrl-C 是纯机制，重写即重复（违奥卡姆）；本模块只换 per-repo 目标 `_run_repo`，让它经 `cli._new_vigil_for` 构造**新栈** vigil。

**接线单一点**：`cli._new_vigil_for(ctx)` 一次构造 backend/RuntimeState/agent_id 并返回 `(Vigil, poll 偏函数)`，CLI `vigil-new` 与 fleet 子进程 `_run_repo` 同调它，保证守夜进程内 backend/state/身份一致。

## Drawbacks

- **两栈并存期的认知负担与体量**：新 `vigil`/`poll_comments`/`fleet`/`triager`/`replier` 与同名旧模块并列，读者需知道「谁是新栈」。缓解：模块 docstring 首行标 Spec-0061 + 明说与旧模块的关系；CLI help 前缀 `[新栈]`。
- **`poll_comments` 未覆盖旧 `messages.poll` 的全部闸**：旧 poll 的 mergeability/CI/e2e/review/merge 全套阶段闸，新栈把「一个 issue 的完整求解」收进同步 `solve_issue`，poll_comments 只做「人在 PR 上追问→回应」。这是**有意的职责重划**（理念 1），但意味着新栈当前不驱动「已开 PR 的自动合并流水线」——留待后续批次把该流水线也按新分界线重立。
- **utils 薄再导出让 import 面比实现面大一层**：多一跳间接。缓解：再导出模块极短（纯 import + `__all__`），且换来「旧模块与 11 个测试桩零改动」的巨大回归安全，净收益为正。
- **`replier` 本批在 repo 根 work_dir 运行**：深度「据评论改代码」需 PR worktree，本批只闭合回应/答疑（见 Unresolved）。

## Rationale and alternatives

- **备选 A：物理搬迁旧模块进 utils（而非薄再导出）**。会一次性改动 identity/github/fleet_config 等的 import 路径，连带打翻 ~11 个测试桩，且与「additive、旧栈零改动」的批次纪律冲突。批次一 Spec-0060 备选 B 已把物理搬迁明确推迟到收敛批次，本批沿用薄再导出。
- **备选 B：poll_comments 逐字移植旧 messages.poll 的 964 行状态机**。违背重构目的（判断与机械仍糅在一起），且把旧栈的全部历史包袱搬进新栈。选择按新分界线**重立**一条职责单一的评论回应竖切，把「PR 自动合并流水线」的重立留后续批次。
- **备选 C：fleet 重写进程监管**。纯重复旧 `Fleet`（违奥卡姆）。选择复用监管器、只换 per-repo 目标。
- **备选 D：vigil 派单动作写死在 recipe 里**。则单测必触真 git/后端。选择把 `dispatch` 作可注入依赖（默认 `dispatch_solve`），与 fleet 的可注入 `spawn` 同构，recipe 保持 hermetic 可测。

## Prior art

- **Spec-0060（批次一）**：确立四层分界线与 `solve_issue`/`engine`/`gates`/`Context`/`RuntimeState`，本批直接承接。
- **旧 `vigil.py`（RFC-0004/0007）**：发现三路分流（fresh/resume/None）+ 去重三闸 + per-issue 错误隔离 + once/long-running 双模，本批的 `recipes.vigil` 保留其去重/隔离/双模骨架，把「precheck_issue 冲突判断」换成 `triager` agent 裁决。
- **旧 `messages.py`（RFC-0012/Spec-0032）**：`identity.new_human_comments`「仅新评论 + 仅无签名人类评论」两道硬约束化解自循环，本批 `poll_comments` 直接复用该原语作去重。
- **旧 `fleet.py`（Spec-0027）**：一仓一进程的 cwd 隔离论证与 `Fleet` 监管器，本批复用。
- **`string.Template` 选型**：批次一已论证（不可存的 f-string / 与 JSON 例冲突的 `.format` / 无 schema 的 `.md` 均被排除），本批两 agent 沿用。

## Unresolved questions

- **replier 深度改代码需 PR worktree**：本批 replier 在传入 work_dir（repo 根）运行，闭合「回应/答疑」；「据评论真改代码并 push」需先 `Workspace.ensure` 检出 PR 分支的 worktree，留后续批次（届时 poll_comments 需按 PR→issue→worktree 建映射）。
- **新栈缺「已开 PR 自动合并流水线」**：旧 messages.poll 的 CI/mergeability/review/merge 闸尚未在新栈重立，故 vigil-new 目前「派单求解 + 回应评论」但不自动推进合并。何时、以何种 recipe 形态重立该流水线，留后续批次。
- **新旧两套 state 何时统一**：`runtime-state.json` 与 `state.json` 并存，最终迁移还是弃旧，随 vigil 完整迁移的收敛批次决定（承批次一同一 Unresolved）。
- **triager 与旧 issuecheck 的过期认领回收未纳入**：旧 vigil 的署名认领便签 + 过期回收（Spec-0039/0049）本批 vigil 未搬（去重只用「远端分支存在」粗闸）；跨后端认领归属判定何时进新栈 vigil，留后续批次。

## Future possibilities

- **PR 自动合并流水线新栈化**：把旧 messages.poll 的 mergeability/CI/e2e/review/merge 按分界线重立成一条 `recipes.merge_pr`（deterministic 闸留 recipe，评审判断走 reviewer agent），补齐新栈的「守候→合并」闭环。
- **replier 升级为「据评论改代码」**：接 PR worktree 后，replier 从「回应」升级到「回应 + 迭代交付」，复用 `solve_issue` 的 deliver + head 前移硬闸。
- **认领归属 + 过期回收进新栈 vigil**：把 `identity.latest_claim` + 过期阈值搬进 `recipes.vigil` 去重闸，支持多后端跨进程认领。
- **收敛批次**：物理搬迁旧模块进 utils/删旧 orchestrator/vigil/messages/fleet + 作废其 spec，两栈合一。

