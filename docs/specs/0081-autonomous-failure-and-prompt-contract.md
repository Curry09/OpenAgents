---
number: "0081"
title: 自治失败收口与单份 Prompt 契约
issue: 0
slug: autonomous-failure-and-prompt-contract
summary: 移除 needs-human 控制协议、标签终态、人工阶段与 hold 入口，以有限重试和 automation-failed 机器终态闭合无人值守状态机；同时规定大段动态材料只经 context 传输一次，并以运行时重叠校验和 stdin 传输阻止 prompt 重复与 argv 膨胀。
e2e:
  intent: 证明所有生产角色的一次调用只携带一份动态材料，Claude Code 子进程不在 argv 暴露或复制 prompt；证明模型拒绝、协议错误、连续崩溃、零进展和超时均在有限调用内收敛到可解释的 automation-failed，同一事实不再调用模型，而材料事实变化后可由自动化自行复活，整个活动运行面不再产生或消费 needs-human。
  method: 运行 scripts/e2e-spec-0081-autonomous-failure-and-prompt-contract.sh；脚本用记录型 backend 覆盖 triage、draft、architecture、implement、reply、test、review、merge 的真实组装路径，以唯一 sentinel 断言最终 prompt 中只出现一次，并以 Popen seam 断言 prompt 只经 stdin；随后在临时 SQLite 队列与假 forge 上分别注入可重试崩溃、旧 needs-human 输出、零进展和事实变化，断言调用次数有界、automation-failed 标签与带 fingerprint 的签名诊断落地、未变事实不重派、变化事实自动清除失败态并重新入队；最后扫描活动源码、模板、CLI help 与桌面类型，除专用迁移脚本外不得出现 needs-human、OWNER_HUMAN 或 --hold。
architecture:
  objective: 让 OpenAgents 的无人值守循环既不把无法完成的工作甩给人工终态，也不因相同输入无限重试；同时消除角色指令与上下文重复携带造成的 token 浪费、argv 上限和进程列表暴露。
  constraints:
    - 合并、CI、证据戳、分支归属与交付真实性等确定性安全硬闸不得因移除人工出口而降级或跳过。
    - 瞬时 backend、网络、进程和协议失败只能在既有有界预算内重试；耗尽后必须停止模型调用并留下机器可读原因。
    - automation-failed 必须绑定不含自身标签的事实 fingerprint；只有相关事实变化或显式重试才可复活，不能按 tick 自动重烧。
    - 活着且持锁的 IN_FLIGHT 任务不得被看门狗终止化或重领；硬超时后的持有者失败仍走同一有界重试路径。
    - 大段动态载荷只有 context 一个所有者；task 只含稳定角色指令和短标量定位符，最终模型输入每段动态材料至多一份。
    - Claude Code prompt 必须经 stdin 传入，argv 不含 prompt 正文；stream-json 输出、工具事件、token usage 与 watchdog 行为保持不变。
    - 旧仓库状态必须有显式、幂等、可审计的迁移路径，升级不能让既有挂起对象静默重新开工。
  non-goals:
    - 不承诺所有 issue 都能由模型完成，也不把 automation-failed 包装成成功。
    - 不移除人类评论回复能力；人仍可补充事实，但自动流程不以等待人作为必经状态。
    - 不改变各角色的业务判断边界、模型选择或本轮瘦身实验的角色拆分方案。
    - 不在本 spec 引入无限自反思、跨 subject 共享重试预算或新的外部队列服务。
  candidates:
    - id: rename-only
      layer: forge-label
      boundary:
        - needs-human label
      evidence:
        - 当前 engine envelope、human owner、hold、watchdog、release 和 desktop 都依赖同一人工语义
      tradeoffs: 改名成本低，但仍是等待人的旧状态机，且无法解决无界重派和 prompt 重复。
    - id: always-retry
      layer: vigil-reconciliation
      boundary:
        - queue attempts
        - watchdog
      evidence:
        - 当前 poison task 已需要 MAX_ATTEMPTS 防止持续占槽
      tradeoffs: 表面无人介入，实际会对相同事实无限烧模型并淹没队列。
    - id: fingerprinted-machine-failure
      layer: runtime-contract-and-orchestrator
      boundary:
        - prompt envelope
        - engine protocol
        - vigil state machine
        - forge projection
      evidence:
        - vigil 已有稳定 facts fingerprint、attempt stamp、队列 attempts 与持锁回收原语
        - GLM FP8 issue 17 的 E2BIG 与 1800 秒外层超时两次被投影成 needs-human，但修复传输、恢复 checkpoint 和网络后同一工作最终合并，证明它们是可恢复机器故障而非必须由人裁决的业务状态
      tradeoffs: 迁移面较大，但能复用现有确定性原语，把停止与复活都绑定到可观测事实。
    - id: role-by-role-prompt-cleanup
      layer: agent-prompts
      boundary:
        - individual Template placeholders
      evidence:
        - Architect 已有局部单份化修补，而 Curator、Drafter、Triager 与 Replier 仍可重复载荷
        - issue 17 的 Architect 输入由约 145 KB 且完整 Spec 出现两次降到 73,834 bytes 且只出现一次后即可正常启动，但 backend 仍受 argv 单参数约 128 KiB 上限约束
      tradeoffs: 可降低当前 token，但没有运行时不变量，新增角色或调用点很容易回归。
  selected: fingerprinted-machine-failure
  affected-components:
    - runtime.engine 与 runtime.context 的单份输入协议
    - ClaudeCodeBackend 的 stdin 传输
    - agents 与 recipes.stages 的动态载荷组装
    - recipes.vigil 的分类、重试、看门狗、失败投影与复活
    - forge 标签、runtime state、release 与 desktop 观测
    - agent_config、CLI、默认配置和旧状态迁移
  failure-modes:
    - 重叠校验过宽误把短标量或公共措辞当成重复载荷时，backend 不会被调用并给出具体冲突段，测试必须覆盖允许的短标量。
    - stdin 写入失败、子进程提前退出或管道关闭时，backend 必须按原有非零调用失败上抛，不能吞错或丢 watchdog 回收。
    - failure fingerprint 若包含 automation-failed 标签本身会自触发复活；计算时必须显式排除失败投影字段。
    - 到达重试上限后若先删队列行再写 forge，forge 短暂失败会重置 attempts；必须先原子落失败投影，再删队列行。
    - 旧 needs-human 对象若未迁移而运行时又不再识别，可能意外重启；升级前检查必须 fail-closed，迁移命令完成后才允许 vigil 启动。
    - 旧 human 配置若被静默改成 skip 会降低安全闸；加载器必须拒绝并指导改成 agent，不能猜测迁移意图。
verification:
  behavior-cases:
    - id: prompt-payload-single-copy
      polarity: positive
      stimulus: 用含唯一长 sentinel 的 issue、评论、Spec、evidence 和 ready issue 快照运行每个生产角色组装路径
      expected: backend 收到的 task 不含该动态载荷、context 含且仅含一份，最终组装 prompt 中 sentinel 恰好出现一次
      observation: 记录型 backend 捕获的 task/context 与 _build_prompt 结果
    - id: duplicate-payload-rejected-before-dispatch
      polarity: negative
      stimulus: 调用 run_agent 时让同一段非短动态文本同时经 Template placeholder 和 context 注入
      expected: 抛 AgentOutputError，错误指出重复段，backend 调用数为零
      observation: tests/test_runtime_engine.py 的异常与 spy 计数
    - id: prompt-not-in-argv
      polarity: negative
      stimulus: 传入超过典型 ARG_MAX 风险长度且带秘密 sentinel 的 prompt
      expected: Popen argv 不含 sentinel 或 prompt 正文，stdin 完整收到一次输入，stream-json 结果照常解析
      observation: tests/test_backend_claude_code.py 的 Popen seam 与结果断言
    - id: bounded-failure-convergence
      polarity: positive
      stimulus: 同一 subject 连续触发 backend 崩溃、协议错误或 agent 旧 needs_human envelope
      expected: 不超过 MAX_ATTEMPTS 次调用即落 automation-failed、删除队列行并记录 category/attempts/fingerprint；后续相同事实 tick 不再调用 backend
      observation: 临时队列、假 forge 标签/评论与 backend 调用计数
    - id: changed-facts-auto-revive
      polarity: positive
      stimulus: automation-failed 后改变 issue 正文、PR head、CI、评论或依赖完成度之一
      expected: 新 fingerprint 与失败戳不同，Vigil 自动清除失败投影并按新事实重新分类；不要求任何人工专用信号
      observation: 假 forge 调用序与重新入队记录
    - id: live-holder-not-terminalized
      polarity: negative
      stimulus: claimed 行超龄但对应 flock 仍由存活 agent 进程持有
      expected: 只记录 stalled telemetry，不加 automation-failed、不删行、不重领；持有者退出后才由回收与重试规则接管
      observation: 多进程锁 e2e 的标签、队列 owner 与并发调用数
    - id: legacy-state-fails-closed-until-migrated
      polarity: negative
      stimulus: 仓库存在旧 needs-human label、blocked run 或 stages owner=human
      expected: vigil 启动给出迁移诊断且零 agent 调用；迁移命令幂等改写 label/state 后可启动，human 配置仍须显式改为 agent
      observation: 迁移脚本前后 forge/state/config 快照与进程退出码
  repository-invariants:
    - 活动 Python、TypeScript、默认配置、README 和 CLI help 中除专用迁移脚本及历史 specs/evidence 外不再出现 needs-human、NeedsHumanRequest、OWNER_HUMAN 或 --hold。
    - engine 不再接受任何角色级人工控制 envelope；包含 needs_human 的模型输出只能成为普通协议错误并进入有界失败路径。
    - automation-failed 是失败事实的 forge 投影，不是要求人回复的状态；诊断文案不得承诺“等你”“摘标签即继续”或“交人接手”。
    - 同一未变化 fingerprint 最多消费一次动作尝试组和一个幂等失败诊断；进程级重试总数不超过既有 MAX_ATTEMPTS。
    - failure fingerprint 排除 automation-failed 标签、签名失败评论和本地队列元数据，但覆盖所有会改变下一步动作的远端事实。
    - 所有 prompt 组装测试断言动态载荷单份，Claude Code argv 仅含可执行名、模式和输出控制参数。
  exemptions: []
tasks:
  - id: T1
    title: 单份 Prompt Envelope 与 needs-human 模型协议退役
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - openagents/runtime/engine.py
      - openagents/runtime/context.py
      - openagents/backends/claude_code.py
      - openagents/agents/admitter.py
      - openagents/agents/architect.py
      - openagents/agents/curator.py
      - openagents/agents/deliver.py
      - openagents/agents/drafter.py
      - openagents/agents/implementer.py
      - openagents/agents/merger.py
      - openagents/agents/replier.py
      - openagents/agents/reviewer.py
      - openagents/agents/tester.py
      - openagents/agents/triager.py
      - openagents/recipes/stages.py
      - tests/test_runtime_engine.py
      - tests/test_runtime_context.py
      - tests/test_runtime_context_issue_reply.py
      - tests/test_backend_claude_code.py
      - tests/test_agents_architect.py
      - tests/test_agents_deliver.py
      - tests/test_agents_docstring_rule.py
      - tests/test_agents_drafter.py
      - tests/test_agents_merger.py
      - tests/test_agents_prompts.py
      - tests/test_agents_replier_issue.py
      - tests/test_agents_triager_replier.py
      - tests/test_recipe_stages.py
      - tests/test_prompt_contract.py
    scope: >-
      把 engine/backend 之间的调用明确为 instructions task + dynamic context 单份 envelope：角色 Template 只保留稳定指令和短标量，issue 正文、评论、Spec、快照、反馈与 evidence 统一由 context 带标题的 section；engine 在派 backend 前对渲染 task/context 做规范化重叠检查，拒绝重复的非短动态段。ClaudeCodeBackend 改用 claude -p 从 stdin 读取最终 prompt，argv 不再携带正文，并保持 stream、watchdog、工具事件与 usage。删除 NeedsHumanRequest、needs_human envelope 识别和角色提示中的人工出口；旧 envelope 作为 schema/protocol error 上抛。
    acceptance: >-
      单测覆盖每个生产角色真实调用路径的 sentinel 单份计数、重复载荷在 backend 前被拒绝、短 ID/branch 公共标量不误报；Popen spy 证明超长 prompt 只写 stdin 一次且 argv 无正文，正常/非零/超时/usage 路径无回归；engine 对旧 needs_human JSON 报协议错误且不再暴露 NeedsHumanRequest。
  - id: T2
    title: Fingerprint 绑定的自治失败收口与自动复活
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - openagents/runtime/gates.py
      - openagents/runtime/legacy.py
      - openagents/runtime/state.py
      - openagents/runtime/token_usage.py
      - openagents/utils/blocknote.py
      - openagents/utils/forge.py
      - openagents/utils/gitea.py
      - openagents/utils/github.py
      - openagents/utils/notes.py
      - openagents/utils/release.py
      - openagents/utils/workspace.py
      - openagents/desktop/daemon.py
      - apps/desktop/src/renderer/src/types.ts
      - apps/desktop/src/renderer/src/nav/pending.ts
      - apps/desktop/src/renderer/src/nav/pending.test.ts
      - tests/conftest.py
      - tests/test_blocknote.py
      - tests/test_blocknote_hold_merge.py
      - tests/test_desktop_daemon.py
      - tests/test_ensure_prerequisites.py
      - tests/test_gitea_driver.py
      - tests/test_github.py
      - tests/test_github_remove_label.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil_admit.py
      - tests/test_recipe_vigil_queue.py
      - tests/test_recipe_vigil_timing.py
      - tests/test_release.py
      - tests/test_runtime_gates.py
      - tests/test_runtime_state_converge.py
    scope: >-
      以 automation-failed 替换人工终态并重写 Vigil 收口：triage 拒绝、无效依赖建议、连续认领失败、硬超时、零进展超龄和动作异常都归一成 category/attempts/fingerprint 的幂等签名诊断；同 fingerprint 停止重派，事实变化自动清投影并从头分类。IN_FLIGHT 存活持锁者只告警不终止化。forge prerequisites、release、runtime state、token status 和 desktop 待看统一消费机器失败语义；删除 blocknote 等只服务人工挂起的展示面。
    acceptance: >-
      queue/fingerprint/watchdog 测试证明失败调用有界、先落 forge 后删行、同事实零重派、任一动作相关事实变化自动复活、存活持锁者绝不被失败化或双跑；release 拒绝未解决的 automation-failed；desktop 展示 automation-failed 而无人工等待文案；相关 Python 与 TypeScript 测试全绿。
  - id: T3
    title: 人工 stage owner、hold CLI 与配置表面清退
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - openagents/cli.py
      - openagents/data/openagents.yml.template
      - openagents/utils/agent_config.py
      - openagents/utils/fleet.py
      - openagents/utils/hold.py
      - openagents/utils/skip.py
      - tests/test_agent_config.py
      - tests/test_cli.py
      - tests/test_cli_new_stack.py
      - tests/test_hold.py
      - tests/test_skip.py
    scope: >-
      从 stage schema、resolved policy、默认模板和路由删除 human owner；删除 --hold、旧 Hold 值对象及 hold/skip 冲突逻辑，保留 skip 但继续执行不许零安全闸约束。含 human 的现有 YAML 必须给出带阶段名的 fail-closed 迁移错误，不能静默变成 skip；CLI help、init 输出和 fleet 透传同步清理。
    acceptance: >-
      loader 只接受各阶段的 agent/skip 合法子集，human 配置报可操作错误且零副作用；oa vigil --help 不再暴露 --hold，传旧参数非零退出；默认模板可 round-trip 并保持全自动安全默认；删除模块后无活动 import 悬空，CLI/config 测试全绿。
  - id: T4
    title: 旧状态迁移、当前文档与端到端退役证明
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - README.md
      - docs/e2e-results/0081-autonomous-failure-and-prompt-contract.md
      - docs/specs/0081-autonomous-failure-and-prompt-contract.md
      - scripts/e2e-spec-0058-needs-human-reply-unblock.sh
      - scripts/e2e-spec-0081-autonomous-failure-and-prompt-contract.sh
      - scripts/migrate-needs-human-state.py
      - tests/test_migrate_needs_human_state.py
    scope: >-
      提供显式幂等迁移器：发现旧 needs-human forge 对象或 blocked runtime run 时，先生成审计计划，再经显式 apply 将其映射为 automation-failed 并保留原理由；human YAML 不自动改写，只报告路径与阶段。更新 README 当前行为，退役旧 reply-unblock e2e，新增单份 prompt、有限失败、事实变化复活、旧状态启动阻断和活动源码扫描的综合 e2e。历史 spec/evidence 保留原文作为设计史。
    acceptance: >-
      迁移 dry-run 零写入、apply 可重复且第二次 no-op，部分 forge 失败可安全重跑；未迁移旧对象时 vigil fail-closed 且不派模型，迁移后 e2e 全绿；活动代码/模板/README/CLI help 扫描除迁移脚本外无 needs-human/NeedsHumanRequest/OWNER_HUMAN/--hold；spec validate、render、graph --check 全绿。
---

# 0081 · 自治失败收口与单份 Prompt 契约

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

OpenAgents 将不再把模型或流水线无法完成的工作投递给 `needs-human`。短暂错误继续在严格预算内重试；相同远端事实下耗尽预算、确定性拒绝或零进展，则收敛为带原因、尝试次数与事实 fingerprint 的 `automation-failed` 机器终态。这个终态不要求人回复：相关事实一旦变化，自动化会清除旧失败投影并重新判断；事实不变则不再消耗模型。

同一变更还将模型输入收敛为单份 prompt envelope。角色 task 只放稳定职责与短标量，issue、评论、Spec、快照、反馈和 evidence 等动态材料只放 context；engine 在派发前拒绝重复段，Claude Code 通过 stdin 接收最终 prompt，避免 token 重复、命令行长度上限和进程列表暴露。

## Motivation

当前系统把 `needs-human` 同时当作模型的一等控制输出、Vigil 终态、队列毒丸出口、看门狗出口、人工 stage owner 的承载、发布拦截条件和桌面最高优先级。这使“自动化做不到”与“必须等人做决定”被焊成同一件事。实际无人值守实验中，模型进程被杀、端点抖动、协议解析失败或同一状态零进展并不等价于需要产品判断；挂人工标签既掩盖了机器失败类别，也让后续恢复依赖人摘标签。

去掉标签本身又不够。如果没有新的终止语义，毒丸任务会在每个 tick 重新入队，重复消耗模型；如果所有失败都立即终止，短暂的 429、进程退出和 CI 异步窗口又会被误判为永久失败。因此停止条件必须绑定“重试预算 + 当前事实 fingerprint”，恢复条件必须绑定“事实真的变化”，而不能绑定某个人是否说话。

模型输入另有一个更早暴露的问题：若角色 Template 已展开 issue 正文、评论或 ready 快照，调用方又把同一材料放入 `context`，backend 会把两份内容拼在同一最终 prompt。Architect 的局部修补证明可以手工消掉一处，但 Curator 的 snapshot、Drafter 的 detail/context、Triager 与 Replier 的 body/context 等路径仍允许复发。与此同时 ClaudeCodeBackend 把整条最终 prompt 放在 `argv`，长输入会撞 `ARG_MAX`，也会在进程列表里暴露正文。需要把单份所有权提升成运行时契约，而不是继续逐角色约定。

### 实验依据（2026-08-28 至 2026-08-30）

本设计不是仅由代码静态审查推导。GLM-5.2 FP8 的三题无人值守运行与后续接续实验保留了 manifest、token/tool ledger、容器和 Git/Gitea 终态；汇总报告位于 `/root/src/openagents-model-capability-threshold-experiment.md`，独立流程审计位于 `/root/src/auto-designer-experiments/20260828-harness-v2-r3-design-glm52fp8-5/openagents-process-audit-20260829.md`。与本 spec 直接相关的观测是：

- issue #17 的完整 Spec 同时进入 task/context 后，最终 prompt 约 145 KB、Spec 出现两次，三次均在 `claude` 进程启动前报 `Argument list too long`。本机最小复现为单参数 131,071 bytes 可启动、131,072 bytes 即 `errno=7 E2BIG`，所以这不是模型能力或 API 失败。
- 只把 Architect 的 Spec 改为 context 单份后，prompt 降至 73,834 bytes、Spec 只出现一次，Architect 正常启动并 PASS；但后端仍用 argv，说明角色局部去重只能缓解，stdin 才是传输根修。
- 确定性 E2BIG 被当作普通 Exception 后回退过远，使 Drafter 共跑三遍；额外两遍约浪费 4m52s 和 1,170,901 tokens。随后持续有工具活动的 Implementer 又被外层 1800 秒硬超时杀掉并挂入 `needs-human`。恢复 checkpoint、修正网络并保留 backend idle watchdog 后，同一 issue 最终实现、138 tests、review 和 merge 全部完成，最终三题仓库终态为 3/3 merged。两次 `needs-human` 因而都是机器故障的错误投影，不是缺少人工业务决定。
- 四个主/恢复容器最终均为 exit 137，但 Docker `OOMKilled=false`，且业务日志分别已经停在失败投影或 merged/frontier-empty；退出码不能直接作为业务终态，必须结合持锁、调用事件和远端事实分类。
- 流程复审确认 Curator、Drafter 的有效运行仍有同 payload 双传，Triager 与两类 Replier 也存在同文双传代码路径；针对后端/协议/遥测及 workspace/context/prompt 的 166 项检查通过，但当时没有覆盖“所有 active role 动态载荷单份”这一不变量。
- Drafter 的后续配对实验进一步证明“保留文件 checkpoint、validator 失败后另起短 repair”可在质量门全过的同时将 #16/#18 tokens 分别降低 52.2% 和 39.9%；直接恢复巨大 session 反而增加 47.4% 和 46.1%。这支撑本 spec 保留确定性 checkpoint/fingerprint、只在新事实或最小失败摘要下重试，而不是恢复或重放整段旧 prompt。
- Implementer 分段实验的有效编辑链 input 曾下降 74.9%，但只达到 81/82 tests，T3b/T4 未完成；因此本 spec 不把 Implementer 分段方案宣布为已验证优化，也不借此删除 Implementer/Reviewer，只处理已被完整反证坐实的输入传输和失败收口问题。

这些数字只用于证明干预层与失败语义，不外推为模型的一般成功率；不同 provider 的 token/cache 口径也不用于跨模型成本比较。

## Guide-level explanation

升级后，正常操作者只看到三类推进结果：成功推进、可重试失败、`automation-failed`。例如某个 agent 连续三次因后端进程退出而没有收工，Vigil 会在对应 issue/PR 写一条签名诊断并加 `automation-failed`：

```text
OpenAgents automation failed
category: backend-error
attempts: 3
fingerprint: 9f2a1c...
last_error: Claude Code CLI exited 137
```

只要 issue 正文、PR head、CI、依赖、有效评论等会影响下一动作的事实没有变化，后续 tick 只观察该终态，不再调用模型。如果有人补充了 issue、外部系统推了新 commit、CI 结论变化或依赖合并，新的 fingerprint 与失败戳不同，Vigil 自己清除 `automation-failed` 并重新从判定表顶部推进。这是“新证据触发自动重试”，不是“等人来解挂”。

配置里的每道可选阶段只能由 `agent` 执行或在允许处 `skip`；`human` 和命令行 `--hold` 被删除。旧配置不会被猜测性迁移：启动会点名报错，要求操作者明确选择 `agent`。旧 forge 标签和 runtime `blocked` 状态则通过一次显式迁移命令转换，因为它们代表已经停住的实际对象，静默忽略会意外重新开工。

对于模型调用，调用方仍传 `task` 和 `context`，但含义变得严格：

```text
task    = 稳定角色说明 + issue/pr 编号、mode、branch 等短定位符
context = [issue] / [comment] / [spec] / [feedback] / [evidence] 动态段，各一份
```

若同一段动态文本同时出现在两边，engine 在启动 backend 前报错。backend 最终只组装一次 guardrail、task 和 context，并通过 stdin 喂给 `claude -p`；正文不出现在 argv。

## Reference-level explanation

### 1. 单份 prompt envelope

`runtime.context` 成为所有动态材料的唯一组装层。每个 context section 使用稳定标题标识来源；Agent Template 删除 `$issue_body`、`$comment_body`、`$issue_snapshot`、`$dialogue`、`$detail`、`$spec_text` 等大段占位，只保留编号、mode、branch、命令等短标量。evidence 在 context 中追加且只追加一次。

`engine.run_agent` 在 Template 渲染后、backend 调用前执行重叠校验。校验对换行与连续空白规范化，并比较 context 中的非短段以及本次字符串 placeholder 值；若一个动态段同时完整存在于 task 和 context，抛 `AgentOutputError`，错误包含角色与截断后的段摘要。短编号、branch 名、协议关键词等允许同时出现，防止误报。这个检查是防回归硬闸，角色调用测试仍逐一证明正常路径没有重复。

`ClaudeCodeBackend` 以不含正文的 `claude -p --permission-mode ... --output-format stream-json --verbose` 启动子进程，并通过 `stdin=PIPE` 写入一次最终 prompt 后关闭。stdout 逐行读取、watchdog、子进程登记、result/usage/tool event 解析维持现有语义。stdin 写入、提前退出和 BrokenPipe 都归一为既有 backend 失败，交上游重试。

### 2. 模型控制协议退役

删除 `NeedsHumanRequest` 与 `{"needs_human": true, ...}` 特判。每个角色只能返回自己的 `OUTPUT_SCHEMA`：判断不通过使用既有 `REWORK`、`false`、`delivered=false` 或 `merged=false` 表达；真正的 backend/协议错误抛异常。旧模型若仍返回 needs_human，因为不符合角色 schema 而成为 `protocol_error`，由 Vigil 的统一有限重试处理，模型不再直接决定编排终态或写 forge。

`admitter` 随 `triage: human` 一同删除。人类普通评论仍由 replier 处理，它是新事实来源之一，但不承担解挂专用协议。

### 3. `automation-failed` 投影

forge 新增单一标签常量 `AUTOMATION_FAILED_LABEL = "automation-failed"`，替代活动代码中的 BLOCKED/needs-human 命名。失败诊断至少包含：`category`、`attempts`、排除失败投影后的 facts fingerprint、最后错误摘要和时间。评论使用现有 identity 签名，并按 `(subject, fingerprint, category)` 幂等；标签和评论必须先成功落 forge，队列才能删除，防止 forge 短暂失败把 attempts 清零。

失败类别至少区分：`backend-error`、`protocol-error`、`no-progress`、`invalid-input`、`invalid-dependency`、`action-timeout` 与 `deterministic-gate`。这些类别用于诊断和统计，不改变安全硬闸。

### 4. 分类、停止与复活

`_classify` 不把 `automation-failed` 无条件放在所有分支之前。它先读取最近一条有效签名失败戳：

1. 用排除 `automation-failed` 标签、失败评论、队列字段后的远端事实计算当前 fingerprint；
2. 若与失败戳相同，返回 `TERMINAL(automation-failed)`，不入队；
3. 若不同，机械移除失败标签，保留历史诊断评论，并对新事实从分类表顶部重判。

显式删除失败标签可作为运维强制重试，但不是流水线依赖的人工协议；失败戳仍在时，生产者会把“标签已被显式移除”视为一次允许重试，新的失败仍受完整预算约束。实现必须避免在每 tick 自动清理再重加。

认领异常继续使用 `_MAX_ATTEMPTS`。同一队列生命周期内未到上限回队；到上限先落失败投影再删行。agent 返回正常 schema 但远端 fingerprint 一个字节未变时盖 attempt 戳，等待异步效果的宽限期结束后落 `no-progress`，不再反复调用。QUIET 的 CI、mergeability、blockers 等自然等待仍按各自阈值处理，只有超过明确上限才转机器失败。

IN_FLIGHT 看门狗必须先验证持锁者是否活着。存活者超龄只写 telemetry/log，不加失败标签、不删 claimed 行；真正的 `_TimedBackend` 硬超时由持有者杀进程并抛错，再进入上述 attempts 规则。这样移除人工出口不会重新引入双跑。

### 5. 配置与产品表面

`OWNER_HUMAN`、所有 stage 的 `human` 枚举、`--hold`、旧 Hold 模型与 `triage: human` 对话路径全部删除。允许 skip 的阶段保持原范围；不可 skip 的 conflict/merge 仍必须 agent；`review: skip + merge: agent` 等零安全闸组合继续拒绝。含 human 的旧 YAML 报精确配置错误，禁止静默解释成 skip。

release 对未解决的 `automation-failed` run/PR fail-closed。desktop 将其显示为机器失败待看项，但文案不要求人工输入。旧阻塞便签模块和“摘标签/回复即继续”承诺退役。

### 6. 迁移与兼容

升级检查若发现旧 `needs-human` 标签或 runtime `blocked` run，Vigil 在任何 agent 调用前退出并打印迁移命令。专用脚本默认 dry-run，列出将修改的 issue/PR/run；显式 `--apply` 后为对象补 `automation-failed` 与迁移签名诊断，再移除旧标签，并把本地 run 状态改为 `failed`。顺序保证中途失败可重跑且不会让对象短暂无终态。历史 specs/evidence 保留旧词作为设计史；活动源码只允许迁移脚本持有旧字面量。

### 7. DAG 与文件所有权

`T1` 先建立模型输入和输出协议；`T2` 在其上改写失败状态机。`T3` 与 `T1` 可并行清理配置表面；`T4` 等状态机和配置都稳定后完成迁移与综合证明。各 Task 的 `files` 在 frontmatter 中互斥，避免并行 writer 冲突。

端到端入口为 `scripts/e2e-spec-0081-autonomous-failure-and-prompt-contract.sh`，全部使用临时仓库、临时队列和假 forge/backend，不访问真实 issue、PR 或模型服务。

## Drawbacks

`automation-failed` 仍然是一个终态标签；它解决的是“机器明确失败且停止烧钱”，并不让模型能力凭空提高。相比原先任何人摘标签即可重跑，fingerprint 绑定和迁移检查增加了状态机复杂度。运行时重叠校验也可能在边界文案上误报，因此必须把“动态段”和“短标量”的界线写成可测规则，而不能用模糊相似度。

移除 `human` owner 意味着 OpenAgents 不再提供逐阶段人工审批模式。需要人工治理的团队只能在自动化之外使用受保护分支、forge 权限或关闭自动 merge；这是有意收窄产品承诺，但属于不兼容配置变化。

stdin 改造会触及进程生命周期细节。若写端未及时关闭，Claude CLI 会等待 EOF；若同步写超长输入阻塞而 stdout 尚未消费，理论上可能形成管道背压。实现应使用 communicate 等价的安全写法或独立受控写入，同时保持流式读和 watchdog。

## Rationale and alternatives

选择 fingerprint 绑定的机器失败，是因为现有 Vigil 已有 `_Facts` 全字段稳定哈希、attempt stamp、SQLite attempts 和 flock 存活证明，所需机制大多存在；新设计只是把它们从“最终叫人”改成“同证据停止、新证据复活”。它同时满足成本上界与自治恢复，且不需要新增服务。

未选择简单把 `needs-human` 改名为 `automation-failed`：旧的“人回复/摘标签复活”和 human owner 仍会保留，概念并未摘除。未选择无限自动重试：相同 prompt 和事实的期望收益接近零，会让模型故障转化成资源事故。未选择失败后关闭 issue/PR：关闭是更强、可能误伤的人类协作动作，而失败标签保留工作成果和诊断。

Prompt 侧未选择只修当前几个重复调用点，因为 Architect 已经证明局部修补不能保护未来路径。也未选择把所有上下文直接塞回 Template：那会失去 task/context 分层，并继续让各角色自行发明格式。选择“context 单一所有权 + engine 硬闸 + 角色路径测试”，让约定、检测和证据三层一致。

Claude CLI 未继续使用 argv，因为 stdin 是其 print 模式已支持的标准输入通道，能同时消除 `ARG_MAX` 与进程列表泄露；这不减少模型 token，但保证瘦身后的单份内容可被任意长度安全传输。

## Prior art

构建系统通常按输入内容哈希缓存失败或成功结果，只有输入变化才重新执行；本 spec 的 failure fingerprint 采用同一原则。消息队列的 dead-letter queue 同样在有限投递后隔离毒丸消息，不过这里不建立第二队列，而把失败投影留在 forge 真源并允许新事实自动复活。

Claude Code 的非交互 print 模式支持从 stdin 获取 prompt；Unix 工具也普遍把大载荷放 stdin/文件、把 argv 留给控制参数。OpenAgents 现有 `runtime.context`、`engine.run_agent`、`_fingerprint`、队列 attempts 和进程锁为本方案提供了直接先例。

## Unresolved questions

1. 初版沿用现有 `_MAX_ATTEMPTS` 与各 QUIET watchdog 阈值，不在本 spec 重新调参；token usage 数据充足后再按失败类别校准。
2. 显式删除 `automation-failed` 标签是否应永久作为强制重试入口，还是后续增加独立 `oa retry <subject>` 以留下更清楚的审计事件，留待实际运维反馈。
3. 运行时重叠检测初版使用确定性完整段匹配，不做模糊语义去重；同义改写造成的 token 冗余交给后续 observability 数据判断。

## Future possibilities

可以按 `category × role × model` 聚合失败率，动态选择较短 session、备用 backend 或更严格预算；也可以把 automation-failed 事件导出到监控告警，但告警仍不成为流水线继续所必需的输入。

Prompt envelope 后续可从带标题字符串升级为结构化 section 列表，在 backend 边界统一做 token 预算、截断优先级、内容哈希与缓存复用。若多个 backend 都支持文件输入，还可以传只读 context artifact，进一步避免大文本在进程间复制。
