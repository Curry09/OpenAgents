---
number: "0082"
title: 最小目标保持与生成交付流
issue: 0
slug: minimal-objective-delivery-flow
summary: 增加 minimal 与 generate-only 交付流：两者都先写紧凑 Spec；前者一次验收，后者由受约束 executor 直接产出 PR 并机械合并，用于无质量闸的隔离生成实验。
architecture:
  objective: 在保留现行 standard 流的同时，提供一条以原 issue 为最终权威的最小交付流，固定为紧凑 Spec、一次实现、一次成果验收三次判断调用；困难目标不得通过缩小 Spec 自动变成 PASS。
  constraints:
    - 原 issue 标题与正文始终进入 Spec Writer、Implementer 和 Acceptance Reviewer 的上下文；Spec 只能选择实现路径，不能降低原目标。
    - Spec Writer 无法给出覆盖完整目标的可实施方案时必须返回 BLOCKED；Acceptance Reviewer 只能返回 PASS、PARTIAL 或 FAIL，只有 PASS 可产生合并授权。
    - minimal 流不调用 Architect、Tester、传统 Reviewer 或 Merger LLM；CI、仓库完整性、head 绑定和合并前复读仍由确定性硬闸保留。
    - standard 流默认行为与已有配置保持兼容。
    - generate-only 保留 Spec Writer，移除 Implementer 与 Acceptance 主观角色；只保留 compact objective digest、head、证据戳、worktree、PR SHA 和冲突等结构性硬闸，质量验证移到实验后离线执行；不得套用 standard 的全仓 docs/specs/OVERVIEW 派生完整性门禁。
  non-goals:
    - 取代适合高风险或跨团队变更的 standard 多阶段流。
    - 用关键词或字段存在性机械判断语义目标是否满足。
    - 在本次引入自动返工循环；PARTIAL/FAIL 明确终止，交由新事实或后续决策重新启动。
  candidates:
    - id: stage-skips-only
      layer: configuration
      boundary:
        - architecture/e2e stage ownership
      evidence:
        - 现有配置已经允许跳过 architecture 与 e2e
      tradeoffs: 改动小，但仍使用面向 Spec 的传统 Reviewer 和 Merger LLM，无法表达 PARTIAL，也无法钉住原 issue。
    - id: vigil-minimal-profile
      layer: orchestration
      boundary:
        - solve/review/merge decisions
        - existing worktree/PR/CI/gates
      evidence:
        - 现有 Vigil 已集中拥有 queue、claim、forge、恢复、审计和确定性硬闸
        - 实验 trace 显示主要坍塌来自多个主观角色逐层重写目标，而不是基础调度能力缺失
      tradeoffs: 需要在状态机内维护两个清晰分支，但能复用单一调度真相并把 minimal 的角色序列做成可测试契约。
    - id: independent-minimal-runner
      layer: orchestration
      boundary:
        - separate queue and delivery lifecycle
      evidence:
        - 独立 runner 可以物理隔离流程实验
      tradeoffs: 会复制 queue、claim、forge、恢复和审计链，形成第二套真相并扩大运行风险。
  selected: vigil-minimal-profile
  affected-components:
    - openagents/utils/agent_config.py：声明 standard/minimal flow 并透传单仓与 fleet plan。
    - openagents/agents/spec_writer.py、acceptance.py、implementer.py、executor.py：紧凑目标契约、一次实现、原 issue 成果裁决与无验证受约束执行。
    - openagents/recipes/stages.py、vigil.py：三拍路由、PARTIAL/FAIL 终止和机械合并。
    - tests 与 e2e 脚本：角色序列、失败闭合、标准流兼容和无额外 LLM 调用。
  failure-modes:
    - Spec Writer 仍把目标改写成更弱版本；通过把原 issue 原文同时交给 Acceptance Reviewer，并规定 Spec 无权覆盖 issue，PARTIAL/FAIL 不合并来限制影响。
    - Acceptance Reviewer 又做全仓架构审计；其任务只允许检查原失败、变更文件和声明证据，超出必须给出具体证据缺口，不得借扩展侦察延后裁决。
    - minimal profile 意外走入 architecture/e2e/rework/merger 分支；以记录型 backend 断言完整角色序列恰为 spec_writer、implementer、acceptance。
    - PARTIAL 被映射为 REWORK 并再次调用 Implementer；minimal 路径直接写 automation-failed 终态，不产生 review-changes-requested。
    - generate-only 又退化成全能 Implementer 或自验收；以角色序列严格为 spec_writer、executor 且零 acceptance/reviewer/tester/merger 固定边界。
    - 干净冻结 seed 的 docs/specs/OVERVIEW 尚未渲染或与候选树不同步，旧全仓门禁使 generate-only 在未改该树时仍无法合并；generate-only 只复读本 issue 的 compact objective digest，standard/minimal 的仓库级门禁保持不变。
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: 一个已有失败 issue 在 flow=minimal 下由记录型 backend 返回 READY、实现成功、Acceptance PASS。
      expected: 只调用 spec_writer、implementer、acceptance；不调用 architect、tester、reviewer、merger；PASS 绑定当前 head 后由机械合并路径收口。
      observation: 离线 e2e 输出角色序列、review-approved 标签和 merge 调用，序列与预期完全相等。
    - id: BC2
      polarity: negative
      stimulus: Acceptance Reviewer 对已实现 PR 返回 PARTIAL。
      expected: PR 不获 review-approved、不进入返工循环、不合并；落 automation-failed 及原始 PARTIAL 理由。
      observation: 一次 acceptance 后终止，forge 探针无 merge 调用且有机器失败投影。
    - id: BC3
      polarity: negative
      stimulus: Spec Writer 判断完整 issue 在当前仓库边界内不可实施并返回 BLOCKED。
      expected: 不创建 PR、不调用 Implementer；issue 直接记录明确 blocker 并机器终止。
      observation: 角色序列只有 spec_writer，create_pr 与后续角色调用均为零。
    - id: BC4
      polarity: positive
      stimulus: 未配置 flow 或显式 flow=standard。
      expected: 现有 Drafter→Architect→Implementer→Reviewer→Merger 行为不变。
      observation: 既有 Vigil、stage、agent config 测试全部通过，并新增兼容性断言。
    - id: BC5
      polarity: positive
      stimulus: 多个已有 issue 在 flow=generate-only、parallel=4 下进入 Vigil，curator 已给出 blocked_by 关系。
      expected: 每个可执行 issue 只调用 spec_writer、executor；依赖未关闭者等待，独立 issue 并发；PR 无质量角色调用，合并经串行机械临界区完成。
      observation: 记录型 backend 中无 implementer/acceptance/tester/reviewer/merger，依赖 facts 控制可执行集合，merge_pr 调用均经过同一锁。
    - id: BC6
      polarity: positive
      stimulus: 一个冻结 seed 的 docs/specs/OVERVIEW 与 standard 候选树不同步，但 generate-only issue 只新增 docs/objectives contract 与实现文件。
      expected: 合并只复读当前 issue 的 compact objective digest，不调用全仓 repository-integrity；同一条件下 standard/minimal 仍保留原门禁。
      observation: generate-only 记录测试把 repository-integrity 设为抛错探针仍完成机械 merge，compact digest 复读照常发生。
  repository-invariants:
    - minimal 的 PASS 必须绑定当前 head；head 前移后裁决自动失效。
    - PARTIAL、FAIL、BLOCKED 不能调用 merge，也不能伪装成 review-changes-requested 触发自动返工。
    - minimal/standard 的 repository-integrity 保持启用；generate-only 仅保留 compact objective digest、head-advanced、evidence-stamp 与 merge-allowed 等结构性硬闸，不把全仓派生索引当质量门禁。
    - standard 是缺省值，存量 openagents.yml 无需修改即可保持原行为。
  exemptions: []
tasks:
  - id: T1
    title: 实现 minimal 三拍交付流
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/agent_config.py
      - openagents/data/openagents.yml.template
      - openagents/agents/spec_writer.py
      - openagents/agents/acceptance.py
      - openagents/agents/implementer.py
      - openagents/agents/executor.py
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - tests/test_agent_config.py
      - tests/test_agents_prompts.py
      - tests/test_recipe_stages.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil.py
    scope: 新增 standard/minimal/generate-only profile；minimal 保持紧凑 Spec→一次实现→Acceptance，generate-only 固定为紧凑 Spec→受约束 executor→机械合并；保留结构硬闸、依赖调度和 standard 兼容。
    acceptance: 配置 round-trip；minimal 序列严格为 spec_writer→implementer→acceptance；generate-only 严格为 spec_writer→executor 且零质量判断角色，开发可按 issue DAG 并发而 merge 串行；BLOCKED 不开 PR，相关 pytest 通过。
  - id: T2
    title: 验证 minimal 流角色序列与失败闭合
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0082-minimal-objective-delivery-flow.sh
    scope: 提供离线可重复成果脚本，运行 minimal 的 PASS、PARTIAL、BLOCKED 与 standard 兼容行为测试，并输出角色序列和确定性 gate 结果。
    acceptance: 脚本非交互运行成功；PASS 序列只有三角色，PARTIAL/FAIL/BLOCKED 零合并且无返工，standard 既有测试不回归；退出码和关键断言可供 CI 与审计复跑。
---

# 0082 · 最小目标保持开发流

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

增加可选 `flow: minimal`。它把单 issue 的主观交付链固定为三次调用：Spec Writer 冻结原 issue 并写一份紧凑可实施 Spec；Implementer 一次实现；Acceptance Reviewer 直接回放原失败并对原 issue 判 `PASS / PARTIAL / FAIL`。只有 PASS 能授权确定性合并；BLOCKED、PARTIAL、FAIL 都终止，不用缩 scope 或反复审计换取“成功”。

同时增加实验用 `flow: generate-only`：仍先写同一 compact Spec，但后续只派一次受约束 coding executor，随后跳过 CI、e2e、Acceptance、Reviewer 与 Merger LLM，由结构硬闸机械合并。它用于观察无质量闸时模型自然产出，merged 不代表目标已验证。

## Motivation

现行 Vigil 在一个 issue 上依次运行 Drafter、Architect、可能的 redraft、Implementer、Reviewer、可能的 re-implement/re-review、Merger。真实运行表明，这条链容易把“守住原目标”变成“逐层证明当前 Spec 自洽”：Architect 可以要求去掉难以闭合的部分，Drafter 通过标记 non-goal 或 future work 缩小交付，Reviewer 最后只对缩水后的 Spec 判 PASS。与此同时，每个角色重新读取相同源码、重新验证相同边界，简单变更也产生上百次工具调用。

最小流要验证另一种假设：对于已经通过需求面准入的单 issue，不再需要一个设计委员会式流水线。需要的是一份短而不可缩水的目标契约、一个负责落地的开发者、一个站在原 issue 一侧的成果验收者。若底层只读或当前能力不足，正确结果是 BLOCKED/PARTIAL，而不是退化成一个易通过的 prompt 改动。

## Guide-level explanation

配置 `flow: minimal` 后，用户仍以相同方式给 issue 打发现标签、让 Vigil 建 worktree 和 PR。不同之处只有判断链：

1. **Spec Writer** 收到原 issue 原文，最多做有界定位，写一份单 Task 为主的紧凑 Spec。Spec 必须包含“原始目标契约”和可证伪验收；它可更换实现路径，不可删除目标。完整方案做不到时返回 `BLOCKED`，Vigil 在 issue 上记录 blocker，不开 PR。
2. **Implementer** 读取这份 Spec 和同一份 issue 原文，直接实现。验证优先回放原失败；禁止为了证明“很严谨”扩展成无关的全仓、全版本或全文件系统调查。
3. **Acceptance Reviewer** 不重做架构设计，只回答原失败是否在当前 head 上消失。`PASS` 表示完整满足；`PARTIAL` 表示有价值但未完整解决；`FAIL` 表示无效或回归。后两者都停止且不合并。

`generate-only` 在第 1 步后改走 **coding executor**：只执行 compact Spec 的唯一实现任务，禁止重写目标、评审、自测和扩展调查；commit/push 后直接进入机械 PR 队列。Vigil 现有 curator 负责 issue `blocked_by` DAG，`--parallel 4` 只并发依赖已满足的 issue；同一 base 的不可逆 merge 由临界区串行化。

通过后不再调用 Merger LLM。Vigil 复读 CI、head 绑定、仓库完整性和 review-approved 标签，然后直接调用 forge 的幂等 merge 原语。

## Reference-level explanation

配置新增顶层 `flow`，合法值 `standard | minimal`，缺省 `standard`。resolved `AgentConfig` 与 `RepoPlan` 都携带该值，保证单仓和 fleet 不丢配置。

本组扩展后合法值为 `standard | minimal | generate-only`。generate-only 复用 compact Spec digest、worktree 隔离、head-advanced、evidence-stamp、PR head 绑定和 forge 冲突判定；它机械写入绑 head 的 approval 标签只是状态机令牌，不表达质量 PASS。

`stages.minimal_spec` 调用新的 `agents.spec_writer`。输出为 `READY | BLOCKED`；READY 只写 `docs/objectives/issue-N.md` 固定五段 compact contract（原目标、不变量、实现路径、可证伪验收、一个实现任务），不调用标准流的 9 段 RFC/DAG/render/graph。它必须通过现有 head 前移与证据戳硬闸，随后由 `minimal_design_snapshot` 校验固定段落、120 行上限并记录字节 digest；合并前复读同一 digest。BLOCKED 不要求制造空 commit。

`_do_solve` 在 minimal 分支跳过 Architect，创建 PR 后只调用一次 Implementer；传入显式 minimal contract 和原 issue。`_sense` 在 minimal 下把独立 e2e 阶段视为已折叠进实现与验收，避免额外 Tester 调用。

`stages.acceptance` 调用新的 `agents.acceptance`，输入原 issue、候选 Spec、diff/PR 上下文和已有 evidence。输出严格枚举 `PASS | PARTIAL | FAIL`。`_do_review_or_fix` 在 minimal 下不使用 review-changes-requested 回环：PASS 生成绑 head 的 review-approved；PARTIAL/FAIL 调用现有 `_fail_automation`，理由原样持久化。

`stages.merge_mechanical` 只执行 `gates.assert_merge_allowed` 后的 forge merge 原语；`_do_merge` minimal 分支仍在动作前执行 repository-integrity 与 design-digest 硬闸。

Task DAG：

```mermaid
graph LR
  T1[配置、角色、三拍状态机与单测] --> T2[离线端到端角色序列与失败闭合]
```

离线成果脚本：`scripts/e2e-spec-0082-minimal-objective-delivery-flow.sh`。本次还会以已有实验 issue 做一次真实 Gitea + GLM 试跑，真实结果落到实验 role_runs；该运行用于评价流程，不被伪装成 hermetic CI。

## Drawbacks

minimal 流故意放弃多轮架构辩论、完整 RFC 模板和自动返工，第一次实现不完整就会以 PARTIAL 停止；吞吐更高，但一次成功率可能低于 standard。Acceptance 仍是语义判断，无法用纯代码证明模型绝不会误判。机械合并减少一次 LLM，但也不再让 Merger 临场处理硬闸之外的异常；异常统一走现有机器失败路径。

generate-only 更激进：错误、未测试或未满足目标的代码也可能被合并，因此其结果只能用于隔离实验与事后评估，不能作为生产成功率。依赖推断依赖现有 curator 与 forge 原生边；未声明的语义冲突只能在 PR mergeability 阶段暴露。

## Rationale and alternatives

选择在现有 Vigil 内增加 profile，而不是新 runner，因为队列、claim、worktree、forge、恢复、审计和硬闸都已经正确存在，复制只会制造第二套状态机。选择三个判断角色而不是两个，是为了避免 Implementer 自己给自己验收；但取消独立 Architect、Tester、传统 Reviewer 和 Merger，防止同一问题被四次重新解释。

备选“只用 stages 跳过 architecture/e2e”不足：它仍让传统 Reviewer 以当前 Spec 为权威、仍只有 PASS/REWORK、仍会自动返工，也仍调用 Merger。备选“保留 Architect 但限制工具预算”只减少时间，不改变缩目标后 PASS 的激励。

## Prior art

单 issue 单 agent 直接交付是仓库 `CLAUDE.md` 的既有理念；现有 Vigil 的 worktree 与确定性硬闸提供了可复用底座。类似 trunk-based delivery 的原则是把不可逆合并建立在少量客观门槛上，而不是让多个角色重复证明同一设计。

## Unresolved questions

本轮没有保留需要用户先决策的开放问题：minimal 明确作为可选实验 profile，standard 保持缺省；真实试跑结果再决定是否扩大使用范围。

## Future possibilities

若真实试跑证明三拍有效，可进一步把原始失败 trace 作为结构化 artifact 挂到 issue，而不是只放正文；也可统计每拍工具调用、模型延迟和 objective outcome，形成 standard/minimal 的对照。若 Acceptance 误判率高，可增加一次只针对争议证据的仲裁，但不得恢复全链重复侦察。
