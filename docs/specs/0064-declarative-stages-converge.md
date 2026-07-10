---
number: "0064"
title: 收敛 recipes 到 vigil+issue：声明式 stages YAML 定义 agent/human/skip 阶段归属
issue: 161
slug: declarative-stages-converge
summary: 把 recipes 层 6→3 收敛（stages/vigil/backfill），人面向入口收敛为 vigil+issue+backfill-rfc+release，用一份声明式 .openagents/openagents.yml（agents/stages 三态/release）作「用哪些 agent + 每道闸归谁把关」的单一真源，阶段抽成 Vigil 类外的独立自由函数由 run_vigil 按 stages 策略路由，并给 CI/e2e/review 三闸接上「失败→派 implementer 迭代→下轮从 conflict 重进」的统一打回回环。
e2e:
  intent: 证明「声明式 stages 策略路由 + recipes 层 6→3 收敛」的架构契约在离线确定性链路上成立——同一 issue 环，喂不同 .openagents/openagents.yml，agent_config 加载出的三态策略能真正驱动 run_vigil 分支（agent→调 stage 函数 / human→停等人 / skip→跳过），「不许零闸」守卫拦掉 review:skip+merge:agent，conflict/merge:skip 被拒；CI/e2e/review 失败经统一回环派 implementer 迭代、下轮从 conflict 重进；确定性硬闸（head 前移/证据戳/round_cap）不受 stages 管辖恒在；收敛后 recipes/ 仅剩 stages/vigil/backfill，人面向仅 vigil/issue/backfill-rfc/release + 隐藏 reply-comment。
  method: "形态：纯后端配置 + 编排 + CLI 收敛，无 product-facing 前端可导航；自检工具列表无 Playwright /\nChrome DevTools MCP，故不设浏览器 e2e，改用离线确定性测法（沿用 Spec-0060/0061/0062 同款）：\n1. 配置层针对性 pytest（假 YAML 串，不触真实仓库/网络）：agent_config 解析 agents/stages/release/\n   defaults/repos + 内建默认全回落 + 每仓 override 合并；三态每闸合法取值校验（conflict/merge 拒\n   skip、rfc 仅 agent/skip、硬闸名进 stages 直接 reject）；「不许零闸」守卫拒 review:skip+merge:agent；\n   rfc:skip 出显式告警。\n2. 编排层针对性 pytest（假 backend 喂 canned 结构化裁决，不触真实 LLM/网络/仓库）：run_vigil 按\n   注入 config 的三态断言 agent/human/skip 三分支；合并流水线 conflict→ci→e2e→review→merge 序；\n   CI/e2e/review 失败→派 implementer→下轮从 conflict 重进的回环；stages 关不掉确定性硬闸。\n3. grep 锚点（e2e 脚本）：recipes/ 仅剩 {stages,vigil,backfill,__init__}.py；全库对已删\n   recipes（solve_issue/merge_pr/poll_comments/rfc_lifecycle/fleet）与 agents.planner 的裸 import\n   零命中；stages 九原子函数均显式收参（无位置参数、无 private 默认值）；agent 回评论盖签名闭环\n   （identity.post_signed_comment 漏签 edit 补，非只 warn）。\n4. 真实自主环冒烟（dogfood，Phase-3 人验 / runbook，非 CI 确定性闸）：oa vigil 用一份最小\n   openagents.yml（rfc:skip + merge:human）跑通一个 issue→PR、PR CI 全绿——作为成果验收（理念 8）\n   在 runbook 记录，不塞进离线脚本。\n脚本：scripts/e2e-spec-0064-declarative-stages-converge.sh（ruff check + ruff format --check +\n针对性 pytest + grep 锚点），被 PR e2e signpost 采集。\n"
tasks:
  - id: T1
    title: 配置层：.openagents/openagents.yml schema + 加载器
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/agent_config.py
      - tests/test_agent_config.py
    scope: 新建 utils/agent_config.py：沿用 fleet_config 的 ruamel.yaml+jsonschema 声明式校验解析 version/agents/stages/release/defaults/repos（整份可省全回落内建默认），产出 resolved dataclasses（AgentPolicy/StagePolicy 三态/ReleasePolicy/RepoPlan）；每闸按闸校验合法取值（conflict/merge 拒 skip、rfc 仅 agent/skip、硬闸名进 stages 直接 reject）+「不许零闸」跨字段守卫（拒 review:skip+merge:agent）+ rfc:skip 显式告警 + 每仓 override 合并。additive，无消费者改动。
    acceptance: hermetic 可测（喂 YAML 串断言解析结果/校验错误，不触真实仓库网络）；整份省略→全默认；review:skip+merge:agent 组合 reject；conflict/merge:skip reject；硬闸名进 stages reject；rfc:skip 出告警；每仓 override 合并生效；ruff 绿。
  - id: T2
    title: 九阶段抽成 Vigil 类外独立自由函数：recipes/stages.py
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/stages.py
      - tests/test_recipe_stages.py
    scope: 把 triage/rfc/implement/review/conflict/ci/e2e/deliver/merge 九个阶段抽成 Vigil 类外的独立自由函数，各自显式收 backend/state/ctx（禁位置参数、private 禁默认值）。judgment 段（triage→triager、rfc→drafter、review→reviewer）派既有 agent、机械段（ci/e2e 读 github check/证据戳、conflict/deliver git 交付、merge github 合并）走 utils/gates。rfc 阶段收敛 planner+drafter 为单一起草函数（drafter 承接、planner 死代码留 T6 删）。additive，从 solve_issue/merge_pr/poll_comments 逐字重立为原子函数，旧文件零改动。
    acceptance: 九原子函数各 hermetic 可测（假 backend 喂 canned 裁决，不触真实 LLM/网络/仓库）；各函数显式收参、无位置参数、private 无默认值；rfc 阶段单一起草函数只依赖 drafter；ruff 绿。
  - id: T3
    title: run_vigil 策略路由编排 + CI/e2e/review 打回回环
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
      - tests/test_recipe_vigil.py
    scope: Vigil 类散成自由函数 run_vigil(*, backend, state, work_dir, config, ...)：按 T1 的 stages 三态策略路由取代 solve_issue 写死的 plan→impl→review→deliver——每可配阶段查 owner（agent→调 T2 stage 函数 / human→打 needs-human 停等人 / skip→跳过）；合并流水线按 conflict→ci→e2e→review→merge 序，给 CI/e2e/review 三闸接『失败→派 implementer 迭代→下轮从 conflict 重进流水线』统一回环（非原地重试）。agent→backend 映射从 config.agents 取。fleet 多仓折入为每仓一次 run_vigil 调用。确定性硬闸（head 前移/证据戳/round_cap）恒在、不受 stages 管辖。
    acceptance: 策略路由 hermetic 可测（注入 config 三态断言 agent/human/skip 三分支）；conflict→ci→e2e→review→merge 序 + 三闸打回回环覆盖；conflict 在读 CI 前先判 mergeable 非 CONFLICTING/DIRTY/UNKNOWN；硬闸不受 stages 关；ruff 绿。
  - id: T4
    title: backfill-rfc path 驱动单列：recipes/backfill.py
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/backfill.py
      - tests/test_recipe_backfill.py
    scope: 把 rfc_lifecycle 的 backfill_rfc 抽成独立 recipe recipes/backfill.py（不进 issue 环、与 vigil 发现段正交）：复用 T2 stages 的 rfc 起草原子 + drafter 的 backfill mode，扫存量代码路径反推 spec 并开 draft PR（实现在前/设计在后）。additive。
    acceptance: hermetic 可测（假 backend + 假代码路径，不触真实仓库）；不触发 vigil 发现段；复用 stages.rfc 起草而非重复实现；ruff 绿。
  - id: T5
    title: CLI 面收敛四命令 + 隐藏 reply-comment + 签名后校验硬化
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/utils/identity.py
      - tests/test_cli_new_stack.py
    scope: 人面向入口收敛为 vigil/issue/backfill-rfc/release 四命令：删 rfc/refine-rfc/implement/iterate/solve/poll/watch/vigil-all/fleet 九命令（并入 vigil，cli 改接 recipes.run_vigil）；reply-comment 降隐藏内部命令（仍走 utils.identity.post_signed_comment）；vigil/issue 读 .openagents/openagents.yml（经 T1 loader），--hold/--skip/--base/--interval 仍可单次覆盖；release 保持确定性动作直连 utils.release（无 agent）、issue 直连 github.create_issue。identity.post_signed_comment 硬化为『回复加签名 + 同步后校验漏签 edit 补（不能只 warn）』闭合防自循环闭环（约束③）。
    acceptance: 人面向仅 vigil/issue/backfill-rfc/release + 隐藏 reply-comment；oa 全命令解析分发；YAML 单一真源 + flag 单次覆盖并存；漏签由 edit 补（非只 warn）；无对旧九命令路由的残留；ruff 绿。
  - id: T6
    title: 删 5 旧 recipe + planner 合并 + 测试桩收敛 + docs 再生成
    status: done
    priority: P1
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/solve_issue.py
      - openagents/recipes/merge_pr.py
      - openagents/recipes/poll_comments.py
      - openagents/recipes/rfc_lifecycle.py
      - openagents/recipes/fleet.py
      - openagents/agents/planner.py
    scope: 删 5 个旧 recipe（solve_issue/merge_pr/poll_comments/rfc_lifecycle/fleet，逻辑已溶入 T2 stages.py / T3 vigil.py / T4 backfill.py）+ 删 agents/planner.py（合并进 drafter）；连带收敛直测这些旧模块的测试桩（test_recipe_solve_issue/merge_pr/poll_comments/rfc_lifecycle/fleet 等，行为已被 test_recipe_stages/vigil/backfill 覆盖）与 dogfood/runbook 引用的旧命令；spec render/graph 再生成 OVERVIEW/ARCHITECTURE。删旧只在 T5 CLI 全量改接后发生。
    acceptance: recipes/ 仅剩 stages/vigil/backfill/__init__；全库 grep 对已删 recipe 与 agents.planner 的裸 import 零命中；全量 pytest 绿；spec validate 无 error；OVERVIEW/ARCHITECTURE drift-free。
---

# 0064 · 收敛 recipes 到 vigil+issue：声明式 stages YAML 定义 agent/human/skip 阶段归属

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

`openagents/recipes/` 现有 6 个模块（`fleet`/`merge_pr`/`poll_comments`/`rfc_lifecycle`/`solve_issue`/`vigil`），CLI 暴露 16 个子命令。这些命令里 `rfc`/`refine-rfc`/`implement`/`iterate`/`solve`/`poll`/`watch`/`vigil-all`/`fleet` 其实都是 `vigil` 每轮自动做的事的「手动单步版」；「跑哪些 agent、每个 agent 接哪个后端、每个阶段归谁把关」硬编码散在各 recipe 与 `gates.py` 的 `--hold`/`--skip` flag 里，无单一真源；`review` 焊在 `solve_issue` 的 for 循环、`triage` 焊在 `Vigil` 类方法里，阶段不可单独寻址。

本 spec 做三件相互咬合的事：**(1) 人面向入口收敛为 `oa vigil`（自主环）+ `oa issue`（创造工作）+ `oa backfill-rfc`（path 驱动追溯）+ `oa release`（仓库级发版）四个正交触发**（其余九条自动化环切片命令并入 `vigil`，`reply-comment` 降为隐藏内部命令）；**(2) 用一份声明式 YAML `.openagents/openagents.yml` 作「用哪些 agent + 每道闸归谁把关」的单一真源**——`agents` 段声明每个角色接哪个后端（理念 2 去中心化，同项目可混接 Claude Code / Codex / nexau），`stages` 段用 `agent`/`human`/`skip` 三态声明每个阶段归属，加载器按闸校验合法取值并守「不许零闸」；**(3) 把每个阶段抽成 `Vigil` 类外的独立自由函数**（`recipes/stages.py`），由一个**按 `stages` 策略路由的编排点** `run_vigil`（`recipes/vigil.py`）组合，并给 CI/e2e/review 三道闸接上统一的「失败→派 implementer 迭代→下轮从 conflict 重进流水线」回环。收敛后 `recipes/` 层从 6 文件收窄到 3（`stages.py`/`vigil.py`/`backfill.py`）。

## Motivation

**现状（就地复述，不靠跨 spec 引用）**：Spec-0060/0061/0062/0063 已把新栈立成四层——`agents/`（零逻辑 Template 提示词，如 `triager`/`drafter`/`reviewer`/`implementer`/`replier`/`deliver`）、`recipes/`（纯控制流）、`runtime/`（`engine.run_agent` + `gates.py` 最小硬闸 + `context`/`state`）、`utils/`（`git`/`github`/`identity`/`fleet_config`/`release` 等确定性原语）。旧 flat 层已删空、两栈合一。当前 `recipes/` 有 6 个模块：`solve_issue`（issue 竖切求解 plan→impl→review→deliver）、`merge_pr`（合并流水线阶段机：可合并性预检/CI/e2e 证据闸/review/merge + hold/skip 短路）、`poll_comments`（拉新人类评论→replier→签名回帖）、`rfc_lifecycle`（`start_rfc`/`backfill_rfc`/`refine_rfc`/`implement`/`iterate` 五入口）、`vigil`（`Vigil` 类：发现→分诊→派单 + 每轮守候段调 `poll_comments`+`merge_pr`）、`fleet`（多仓库子进程扇出）。CLI 16 命令直连它们。

**四个为什么**：

1. **入口分散违背理念 1（奥卡姆）**——`rfc`/`refine-rfc`/`implement`/`iterate`/`solve`/`poll`/`watch`/`vigil-all`/`fleet` 都是 `vigil` 每轮自动做的事的「手动单步版」，人要记住 9 个手动步骤命令，心智负担过重。人真正要的宏观触发只有三个正交动作：跑自主环、提一个 issue、拿 path 反推存量代码的 spec。

2. **阀门策略是一次性 CLI flag、无单一真源**——`--hold`（停下等人）/`--skip`（当 PASS 放行）散在 `gates.py` 的 `_HOLD_GATES=("spec","merge")`/`_SKIP_GATES=("ci","code","evidence","spec")` 里，每次实验都得记 flag、跨运行不留痕。没有一处能一眼看出「这个项目的每道闸归谁把关」。

3. **跑哪些 agent、每个 agent 接哪个后端硬编码在 recipe 里**——`backends/` 目前只有 `claude_code`，但理念 2 要求「同一项目里不同 Agent 背后接的 coding agent 可能不同，既有 Claude Code 又有 Codex 等」。现状无处声明「implementer 用 Codex、reviewer 用 Claude Code」。

4. **阶段没解耦、不可单独寻址**——`review` 焊在 `solve_issue` 的 for 循环里、`triage` 焊在 `Vigil` 类方法里；且 `planner` 与 `drafter` 两个 agent 做同一件「起草 spec」的事（新旧栈并存残留，`planner` 是 Spec-0060 的 `_DRAFT_RFC_TASK` 内联串降级，`drafter` 是 Spec-0062 承接五入口起草判断的后来者，二者重复）。阶段不可单独寻址，就没法对它设「谁把关」。

**真缺口（本 spec 必补）**：`merge_pr` 现在 CI 挂了只 `return {"reason": "ci"}`、review REWORK 只 `return {"reason": "review"}`——**发现了但不自动派 implementer 重改**（旧栈靠手动 `iterate --reason ci` 打回，收敛后该命令没了）。`vigil` 守候段拿到事件也没动作。CI/e2e/review 三道闸必须接上统一的「失败→派 implementer 迭代→下轮从 conflict 重进流水线」回环，否则收敛掉手动 `iterate` 后自动环会在「报错但不修」处空转。

## Guide-level explanation

收敛后，一个用户面对的心智模型是：**四个正交命令 + 一份可选 YAML**。

**四个命令**：

- `oa vigil` —— 自主环。每轮从 GitHub 拉标签门控 issue，读 `.openagents/openagents.yml` 决定「跑哪些 agent、每个阶段归谁」，自动走 发现→分诊→（起草 spec→实现→评审→交付）→守候（回应评论 + 推进合并）整环。今天要手动敲的 `rfc`/`implement`/`iterate`/`poll`/`watch`/`vigil-all`/`fleet` 都是它一轮里的一步，不再单列。
- `oa issue` —— 人主动往仓库提一个 issue（独立创造工作的动作，直连 `github.create_issue`）。
- `oa backfill-rfc <path>` —— path 驱动追溯：指着一段存量代码反推出 spec 并开 draft PR（实现在前、设计在后）。与 issue 驱动的 vigil 环正交——vigil 发现段扫的是 issue，不是待补文档的代码路径，故单列一个入口。
- `oa release` —— 仓库级、跨 issue 的发版动作（人决定何时把 main 当前 HEAD 物化成版本）。是确定性动作、无 agent，不是某个 issue 的流水线阶段，故单列顶层策略而非进 `stages`。

`reply-comment` 保留但降为**隐藏/内部命令**——它是被派出的子 agent（解冲突 agent 等）盖签名回评论的唯一出口，删了会破坏防自循环闭环（见 Reference-level 约束③），但不占人的心智。

**一份 YAML**——`.openagents/openagents.yml` 整份可省（全回落内建默认），日常极简配置例：

```yaml
version: 1
stages:
  rfc:   skip     # 小改不走 RFC，直接实现（打 no-rfc 意图；加载器会显式告警）
  merge: human    # 合并停下等人点头
```

完整配置声明「每个角色接哪个后端」+「每道闸归谁」：

```yaml
version: 1
agents:                          # 理念 2：同项目可混接不同 coding agent
  triager:     { backend: claude_code }
  drafter:     { backend: claude_code }   # 起草 spec（= 原 planner，已合并）
  implementer: { backend: codex }         # 例：实现阶段换 Codex
  reviewer:    { backend: claude_code }
stages:                          # agent=自动化拥有此闸 | human=停等人 | skip=不设此闸
  triage:   agent    # 可不可派单（human=每个新 issue 停下等人点头）
  rfc:      agent    # 起草 spec：agent | skip（skip=不写直接实现）
  conflict: agent    # rebase 解冲突：agent | human（不可 skip）
  ci:       agent    # CI 闸：agent(红→自动打回 implementer) | human(红→停) | skip
  e2e:      agent    # 端到端：agent | human | skip
  review:   agent    # 评审 PASS/REWORK：agent | human | skip
  merge:    human    # 合并把关：agent(CI 绿自动合) | human（不可 skip）
release: manual      # 顶层策略，不进 stages；auto=main 绿+无 BLOCKED 自动物化
defaults: { interval: 60, base: main, labels: [openagents] }
repos:               # 多仓库统管（收编 fleet.yml；单仓库整段可省）
  - path: .
  - path: ../other-repo
    base: develop
    stages: { merge: agent }   # 每仓可覆盖单个阶段
```

`--hold`/`--skip`/`--base`/`--interval` 仍可对**单次运行**覆盖 YAML——「单一真源」指声明式默认收敛到一处，不是消灭所有 flag。

## Reference-level explanation

### 分界线（承前四批，逐字一致）

留确定性代码（recipe 控制流 + `runtime.gates` 硬闸 + `utils` 原语）的是**读客观事实**：可合并性（GitHub 给的 mergeable 位）、CI 结论（check 的 conclusion）、e2e 证据戳（head_sha 匹配否）、hold/skip 命中、认领便签过期。下放 agent 的是**主观判断**：issue 讲清没/该不该做（triager）、RFC 正文写什么（drafter）、这版能不能过评审（reviewer）、评论想要什么（replier）、冲突怎么 rebase（deliver）。**`stages` 三态是「这道闸归谁」而非「谁执行检测」**：`ci: agent` 指「自动化拥有此闸——检测仍是客观读 check，红了自动打回 implementer」，**不是**让 agent 去判 CI 过没过。

### 配置层：`.openagents/openagents.yml` schema + 加载器（T1）

沿用 `utils/fleet_config.py` 的 `ruamel.yaml` + `jsonschema` Draft202012 声明式校验模式，新建 `utils/agent_config.py`。顶层键 `version`/`agents`/`stages`/`release`/`defaults`/`repos` 全可选（整份省略→内建默认）。加载器产出 resolved dataclasses（`AgentPolicy`{role→backend}、`StagePolicy`{stage→owner 三态}、`ReleasePolicy`、`RepoPlan`），并做：

- **每闸按闸校验合法取值**（不是所有闸都收全三态）——见下表「合法取值」列。非法值（如 `merge: skip`、`conflict: skip`、`rfc: human`）报 schema error。
- **确定性硬闸名进 `stages` 直接 reject**——`head-advanced`/`evidence-stamp`/`round-cap` 等 `gates.py` 硬闸名不是可配阶段，写进 `stages` 即报错（强化分层，见约束②）。
- **「不许零闸」跨字段守卫**——拒绝 `review: skip` + `merge: agent`（+ ci 放行）这类「未审未测直接盲合进 main」组合（类比 `fleet_config` 的既有矛盾校验）。天然兜底：理念 5「PR 需人审」——只要 `merge: human` 在，跳 agent-review 就站得住。
- **`rfc: skip` 显式告警**——允许跳（撞理念 4 先改 RFC 再改代码），但加载器打显式告警，别让全局默认悄悄关掉框架的 RFC 卖点（约束①）。
- **每仓 override 合并**——`repos[].stages` 覆盖顶层 `stages` 单个阶段（沿用 fleet_config 的 defaults 合并模式）。

### 阶段原子函数：`recipes/stages.py`（T2）

把九个阶段抽成 `Vigil` 类外的独立自由函数，各自**显式收 backend/state/ctx**（符合 CLAUDE.md「禁位置参数、private 函数禁默认值、调用方显式传参」约定）：

| stage | 实现 | 进 `stages` 策略点？ | 合法取值 | 说明 |
|---|---|---|---|---|
| `triage` | agent 函数（triager） | ✅ | agent/human/skip | 可不可派单 |
| `rfc`（起草 spec） | agent 函数（drafter） | ✅ | agent/skip | 合并 planner+drafter |
| `implement` | agent 函数（implementer） | ❌ 恒 agent | — | 按获批 spec 写码 |
| `conflict` | agent 函数（deliver rebase） | ✅ | agent/human | 冲突必须解，不可 skip |
| `ci` | 确定性闸读（github check） | ✅ | agent/human/skip | agent=红自动打回；非「agent 判 CI」 |
| `e2e` | 确定性闸读 + executor 跑 | ✅ | agent/human/skip | 单独可跳（skip） |
| `review` | agent 函数（reviewer） | ✅ | agent/human/skip | PASS/REWORK |
| `deliver` | agent 函数（deliver git 交付） | ❌ 恒 agent | — | git 交付 |
| `merge` | 确定性动作（github merge） | ✅ | agent/human | 不可 skip |

`rfc` 阶段收敛 `planner`+`drafter` 为单一起草函数（drafter 已承接五 mode 起草判断，planner 是重复的死代码，T6 删）。

### 编排点：`run_vigil` 策略路由 + 打回回环（T3）

`Vigil` 类散成自由函数 `run_vigil(*, backend, state, work_dir, config, ...)`——stage 都显式收参后，类只剩「打包依赖 + 主循环」，无肉，散开更符合奥卡姆。**关键**：抽函数是必要条件不是目的，必须同时有一个**按 `stages` 策略路由的编排点**取代今天 `solve_issue` 写死的 `plan→impl→review→deliver`——对每个可配阶段查 owner：`agent`→调 agent 版 stage 函数；`human`→停在此闸打 needs-human 挂起等人；`skip`→跳过。只抽不组合，`review: skip` 依然无处落。agent→backend 映射从 `config.agents` 取（理念 2）。多仓 `fleet` 收编为「每仓一次 `run_vigil` 调用」，不需要类。

**合并流水线定稿顺序**：`conflict → CI → e2e → review → merge`。每道闸 = (检测者) + (没过时的修复者) + (修完从流水线顶重进)：

| 顺序 | 闸 | 检测者 | 没过打回给谁 | 可跳过 |
|---|---|---|---|---|
| ① | conflict / behind | 确定性读 mergeable 位 | deliver agent 去 rebase | 否（前置） |
| ② | CI/CD | 确定性读 check 结论 | **implementer 打回重改** | skip ci |
| ③ | e2e | 确定性读证据戳（或真跑） | implementer 打回重改 | ✅ 单独可跳 |
| ④ | review | reviewer agent 判断（最贵） | implementer 打回重改（REWORK） | skip code |
| ⑤ | merge | —（github merge） | — | hold=停等人 |

排序三原则：**便宜的在前**（读 API 位 < LLM 评审）、**客观闸在前判断闸在后**、**前置依赖在前**。**conflict 必须在 CI 前不只是成本、是硬依赖**：PR 冲突（`mergeable=false` / `mergeStateStatus=DIRTY`）时 GitHub 造不出 merge ref，`pull_request` 的 CI 没东西可跑或只有陈旧 head 结果 → 冲突没解时 CI 绿/红不可信；且 push 刚完 `mergeable=null`（后台异步计算）/`UNKNOWN` 时既不能判冲突也不能信 CI，须等下轮。故**读 CI 前必先确认 mergeable 既非 CONFLICTING/DIRTY 也非 UNKNOWN/null**（现状 `gates.is_conflicting`/`is_mergeable_unknown` 已提供判读，`merge_pr` 已在读 CI 前短路）。

**打回回环（本 spec 补的真缺口）**：给 CI/e2e/review 三闸接统一回环——失败**不再只 `return {"reason": ...}`**，而是派 `implementer` 迭代改代码，改完**下轮从 conflict 重进流水线**（不是原地重试——改完代码 base 可能又变，须从冲突客观复检重进；`github.merge_pr` 不可合并时拒绝是最后兜底）。

### 约束（不可让步，硬编进校验/分层）

- **① `rfc: skip` 撞理念 4**——允许跳，但当按 issue 粒度的显式选择或至少加载器打显式告警，别放进全局默认悄悄关掉 RFC 卖点。
- **② 确定性硬闸永不进 `stages`**——head 前移 / 证据溯源戳（`assert_evidence_stamp`）/ `round_cap` 死循环上限恒机器、恒在（防 #140 空转的安全底线，`skip` 关不掉）。`stages`（可配阶段）与 `gates.py`（硬底线）词分开以强化分层，加载器把硬闸名写进 `stages` 判 error。
- **③ 防自循环闭环不可拆**——agent 回评论必带隐藏签名 `<!-- openagents:agent=xxx -->`（agent 与人可能共用同一 gh 账号，只能靠 body 签名区分、不能靠作者）；`poll_comments` 靠它过滤「只回无签名的新人类评论」。`reply-comment` 降隐藏命令后，盖章仍由 `identity.post_signed_comment` 保证「回复时加签名 + 同步后校验（漏签则 edit 补上，不能只 warn）」，否则自问自答死循环重现。

### Task DAG + 文件分配

`files` 全组两两不相交——协同模式无冲突的根（理念 6，单一 writer 所有权）。

| Task | depends-on | 拥有的 files | 交付 |
|------|-----------|-------------|------|
| **T1** | — | `openagents/utils/agent_config.py`, `tests/test_agent_config.py` | 配置层：schema + 加载器 + 三态校验 + 不许零闸守卫（additive） |
| **T2** | — | `openagents/recipes/stages.py`, `tests/test_recipe_stages.py` | 九阶段抽成 `Vigil` 类外自由函数（additive） |
| **T3** | T1, T2 | `openagents/recipes/vigil.py`, `tests/test_recipe_vigil.py` | `run_vigil` 策略路由 + CI/e2e/review 打回回环 + fleet 折入 |
| **T4** | T2 | `openagents/recipes/backfill.py`, `tests/test_recipe_backfill.py` | backfill-rfc path 驱动单列（additive） |
| **T5** | T3, T4 | `openagents/cli.py`, `openagents/utils/identity.py`, `tests/test_cli_new_stack.py` | CLI 面收敛四命令 + 隐藏 reply-comment + 签名后校验硬化 |
| **T6** | T5 | `openagents/recipes/solve_issue.py`, `openagents/recipes/merge_pr.py`, `openagents/recipes/poll_comments.py`, `openagents/recipes/rfc_lifecycle.py`, `openagents/recipes/fleet.py`, `openagents/agents/planner.py` | 删 5 旧 recipe + planner（合并进 drafter）+ 收敛测试桩 + docs 再生成 |

DAG 形状：T1 ∥ T2 无依赖可并行（皆 additive、hermetic 可测）→ T3 汇合（读 T1 config、组 T2 stage）→ T4 复用 T2 rfc 原子 → T5 CLI 改接（新栈已就位）→ T6 删旧（无人再 import 旧 recipe）。additive 的 T1/T2/T4 先行，destructive 的 T5→T6 严格串行，每步跑全量 pytest + ruff 作硬闸，任一红即停。

### e2e 脚本

`scripts/e2e-spec-0064-declarative-stages-converge.sh`——ruff check + ruff format --check + 针对性 pytest（配置层三态校验/不许零闸/每仓 override；编排层 agent·human·skip 三分支 + 打回回环 + 硬闸不受管辖）+ grep 锚点（`recipes/` 仅剩 stages/vigil/backfill；对已删 recipe/planner 裸 import 零命中；九原子函数显式收参；签名闭环）。形态为纯后端配置/编排/CLI 收敛、无 product-facing 前端，故不设浏览器 e2e，沿用前四批离线确定性测法（见 frontmatter `e2e` 块）。

## Drawbacks

- **单批体量大、review 面宽**：跨新增配置层 + 阶段抽函数 + 编排重写 + CLI 收敛删九命令 + 删 5 recipe/1 agent，是继 Spec-0062 后又一次大收敛。缓解：DAG 把 additive（T1/T2/T4）与 destructive（T5/T6）严格分层，每层全量 pytest+ruff 硬闸，删旧只在 CLI 已改接（无人再 import 旧 recipe）后发生。
- **配置层多一个真源、多一层解析**：引入 `.openagents/openagents.yml` 后，「每道闸归谁」从代码常量变成运行时配置，读代码不再能直接看出行为——须连着看 YAML。缓解：整份可省、全回落内建默认（= 今天的硬编码行为），不写 YAML 的用户零感知；且加载器把非法组合挡在启动期。
- **三态语义有认知成本**：`agent`/`human`/`skip` 三态 × 每闸合法取值不同（conflict/merge 不可 skip、rfc 仅 agent/skip），用户可能记混。缓解：加载器按闸校验并给明确 error 文案；Guide-level 附完整注释样例。
- **`rfc: skip` 给了绕过 RFC 卖点的口子**：即便有告警，长期开着 skip 会侵蚀理念 4。缓解：只当按 issue 粒度显式选择 + 加载器显式告警，不进全局默认（约束①）。
- **打回回环可能与 reviewer 恒 REWORK 叠加放大轮次**：CI/e2e/review 三闸都能触发 implementer 迭代，坏情况下多闸交替打回。缓解：`gates.round_cap` 死循环上限恒在（不受 stages 管），跑满即兜底 raise。

## Rationale and alternatives

- **备选 A：策略继续用 CLI flag（`--hold`/`--skip`）、不引入 YAML**。改动最小、无新真源。**否决**：flag 是一次性的、跨运行不留痕、无处一眼看全「每道闸归谁」，且无法表达「每个 agent 接哪个后端」（理念 2）。选择声明式 YAML 作单一真源，flag 降为单次覆盖。
- **备选 B：只抽阶段函数、不做策略路由编排点**。省掉 `stages` 三态与加载器。**否决**：抽函数是必要条件不是目的——只抽不组合，`review: skip` 依然无处落，阶段可寻址却不可配。必须同时有按 `stages` 路由的 `run_vigil`。
- **备选 C：把 CI/e2e/review 也做成「agent 判断闸」**（让 agent 读日志判 CI 过没过）。看似统一。**否决**：撞约束②——CI/e2e 的**检测**恒是确定性读（github check / 证据戳），`agent` 只表示「自动化拥有此闸、红了自动打回」，不是让 agent 主观判客观事实。检测者与所有者是两件事。
- **备选 D：`stages` 也收编确定性硬闸**（head 前移/证据戳/round_cap 允许 `skip`）。配置更「完整」。**否决**：撞约束②——硬闸是防 #140 空转的安全底线，`skip` 关不掉才是它存在的意义；可配阶段与硬底线必须分层。硬闸名进 `stages` 判 error。
- **备选 E：`planner` 与 `drafter` 并存不合并**。少动一个 agent。**否决**：二者都「起草 spec、不写实现代码」，是新旧栈残留重复；drafter 已承接五 mode 起草判断，planner 是死代码。合并成单一起草 stage 更符合奥卡姆。
- **备选 F：recipes 层收敛但不删旧文件、保留两栈回退**。更安全。**否决**：Spec-0062 已完成两栈合一，再留旧 recipe 就是回到并存中间态、增认知负担与 import 间接层；删旧只在 CLI 全量改接后发生、且前置 grep 零 import 硬证据。

## Prior art

- **Spec-0027（多仓库 vigil）与 `utils/fleet_config.py`**：既有的 `ruamel.yaml` + `jsonschema` Draft202012 声明式配置加载 + `defaults`/`repos` 合并 + 矛盾校验模式，是 T1 `agent_config.py` 直接沿用的范本（收编 `fleet.yml` 的 `repos` 段）。
- **Spec-0060/0061/0062（agents/recipes/runtime/utils 新栈三批）**：确立四层分界线（判断→agent、机械→确定性代码）、`solve_issue`/`merge_pr`/`poll_comments`/`vigil`/`fleet` recipe 与 `triager`/`drafter`/`reviewer`/`replier`/`deliver` agent、`gates.py` 最小硬闸、`cli._new_vigil_for` 单一接线点。本 spec 的阶段抽函数、编排点、删旧收敛直接承接。
- **Spec-0020（human-oversight-gates）与 `gates.hold_hits`/`skip_hits`**：`--hold`（停等人）/`--skip`（当 PASS 放行）的既有闸名白名单与短路语义，是 `stages` 三态要收编成单一真源的现状来源。
- **Spec-0055/0057（e2e 证据溯源戳）与 `gates.assert_evidence_stamp`**：e2e 闸确定性读证据戳的硬闸判定，是约束②「硬闸不进 stages」的具体对象。
- **Spec-0011（agent 身份签名）与 `utils/identity.post_signed_comment`**：隐藏签名 `<!-- openagents:agent=xxx -->` + `poll_comments` 靠它过滤人类评论的防自循环闭环，是约束③与 `reply-comment` 降隐藏命令的行为基准。
- **GitHub 合并状态语义**：[REST — pulls（`mergeable` 可为 true/false/null，null=后台计算中）](https://docs.github.com/en/rest/pulls/pulls) · [GraphQL Enums — `MergeableState`/`MergeStateStatus`（DIRTY/BEHIND/UNKNOWN/CLEAN…）](https://docs.github.com/en/graphql/reference/enums) · [Troubleshooting required status checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/troubleshooting-required-status-checks)——支撑「conflict 必须在 CI 前是硬依赖」的排序论证。
- **[rust-lang/rfcs](https://github.com/rust-lang/rfcs)**：本 spec 组级 9 段总览形态的来源。

## Unresolved questions

以下三问来自 issue #161「开放问题」，记录本 spec 的倾向，落地前需用户拍板：

- **1. `board` 命令归属**：保留为独立只读观测命令（**倾向**，将来并入前端呈现成果，理念 8）？还是塞进 `vigil` 子命令？本 spec 暂按「保留独立、不进 stages/不进本收敛范围」处理——它是只读观测、非自动化环切片，收编价值低。（`release` 已定：顶层 `release: manual|auto`，不做 stage。）
- **2. 确定性硬闸在 YAML 的暴露口径**：完全不进 YAML（**倾向**，最安全，本 spec 采此——硬闸名进 `stages` 判 error）？还是沿用 `--skip ci/evidence` 语义、允许 YAML 标 `skip` 但绝不允许标 `agent`/`human`？两者对约束②的落地方式不同，需确认。
- **3. `reply-comment` 的实现口径**：降为隐藏内部命令即可（**倾向**，仍走 `identity.post_signed_comment` 单一盖章出口）？还是彻底改走「裸 gh + 后校验补签」？本 spec 采前者，并要求 `post_signed_comment` 做「回复加签名 + 同步后校验漏签 edit 补」的硬化（约束③）。
- **4. `drafter` 单 agent 承载起草 + backfill 两种判断是否需拆**：`recipes/backfill.py`（T4）复用 drafter 的 backfill mode；若某 mode 提示词膨胀到互相干扰，后续可拆多 agent。是否拆、按什么信号拆，实现 T4 时据提示词实际复杂度定（承 Spec-0062 同一 Unresolved）。

## Future possibilities

- **落地 `codex`/`nexau` 后端**：`backends/` 目前只有 `claude_code`，本 spec 只留 `agents.<role>.backend` 的 schema 位（理念 2 去中心化的声明面）；实现另议。届时同项目混接不同 coding agent 才真正跑通。
- **`stages` 扩到更细粒度的 per-role 策略**：如「reviewer 用严格模式 / 宽松模式」「implementer 的迭代轮次上限」进 YAML，让配置面覆盖更多可调旋钮。
- **`board` 并入前端**：把只读观测命令收编进「主要视觉范围用于呈现成果」的前端（理念 8），YAML 的 `stages`/`agents` 同时作为前端可视化的策略数据源。
- **`release: auto` 物化**：本 spec 只声明顶层 `release: manual|auto` 策略位；`auto`（main 绿 + 无 BLOCKED 自动切版本）的实现另议。
- **recipe 层沉淀通用编排组合子**：`run_vigil` 的「查 owner→按三态路由（调 agent 函数 / 停等人 / 跳过）」若在多处重复，可抽成 `runtime` 层的策略路由组合子，进一步收敛。

