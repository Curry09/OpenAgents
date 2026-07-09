---
number: "0062"
title: 架构重构（收敛批）：全量迁移 RFC 生命周期 + PR 合并流水线到新栈，删旧两栈合一
issue: 145
slug: agents-recipes-converge
summary: 承接 Spec-0060/0061 立起的 agents/recipes/runtime/utils 新栈，一次性把仍 100% 留在旧栈的两大块——orchestrator 的 RFC 生命周期(rfc/backfill/refine/implement/iterate)与 messages 的 PR 合并流水线(mergeability/CI/e2e/review/merge 阶段机)——按既定分界线(判断走 agent、机械留确定性 recipe/gates/utils)重立为新栈 recipe，CLI 全量改接新栈，再物理搬迁 utils 原语并删掉 orchestrator/messages/vigil/fleet/align/issuecheck 六个旧模块、重写其测试桩、作废旧 spec，实现两栈合一。
tasks:
  - id: T1
    title: RFC 生命周期 recipes + drafter agent（additive）
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/rfc_lifecycle.py
      - openagents/agents/drafter.py
      - tests/test_recipe_rfc_lifecycle.py
      - tests/test_agents_drafter.py
    scope: 把 orchestrator 的 start_rfc/backfill_rfc/refine_rfc/implement/iterate 五条 RFC 生命周期按分界线重立为 recipes.rfc_lifecycle：判断（起草 RFC / 反推 spec / 按评论精炼）下放 drafter agent（零逻辑 Template），机械（认领标签/开 draft PR/转正/写文件）留 recipe 经 utils/engine。additive，旧 orchestrator 零改动。
    acceptance: 五个 recipe 入口 hermetic 可测（假 backend 喂 canned 裁决，不触真实 LLM/网络/仓库）；drafter 零 def/subprocess；ruff 绿。
  - id: T2
    title: merge_pr recipe + 合并流水线 gates（additive）
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/merge_pr.py
      - openagents/runtime/gates.py
      - tests/test_recipe_merge_pr.py
    scope: 把 messages.poll 的阶段状态机（mergeability 预检 / CI 闸 / e2e 证据闸 / review / merge + hold/skip 对称短路 + closed-run 复活 + 冲突自愈）按分界线重立为 recipes.merge_pr：deterministic 闸留 recipe/runtime.gates，评审判断走既有 reviewer agent、冲突自愈走既有 git delivery agent。additive，旧 messages 零改动。
    acceptance: merge_pr hermetic 可测，覆盖 merged/blocked/ci/review/e2e/reopened/error 全路由；hold/skip 对称短路；ruff 绿。
  - id: T3
    title: vigil 认领归属+过期回收 + 守候段接 merge_pr
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - openagents/recipes/poll_comments.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_poll_comments.py
    scope: vigil 去重闸加署名认领便签 + 过期回收（identity.latest_claim + 阈值，多后端跨进程认领）；vigil 每轮守候段从 poll_comments 扩为「poll_comments 回应评论 + merge_pr 推进合并」，闭合发现→求解→回应→合并全环。
    acceptance: vigil 守候段驱动合并推进；认领便签/过期回收 hermetic 可测；ruff 绿。
  - id: T4
    title: CLI 全量改接新栈 + 删旧路由
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli_new_stack.py
    scope: rfc/backfill-rfc/refine-rfc/implement/iterate/poll/watch/vigil/vigil-all 九条命令全部改接 recipes.*；删 _orchestrator_for 工厂、messages.Messages import、旧阶段机路由；合并新旧命令名（vigil-new 收编为 vigil、poll-comments 收编为 poll 的评论段）。
    acceptance: 所有 CLI 命令走新栈 recipe；oa 全命令解析并分发；无 import openagents.orchestrator/messages；ruff 绿。
  - id: T5
    title: 物理搬迁 utils 原语 + 删旧六模块
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/utils/identity.py
      - openagents/utils/release.py
      - openagents/utils/notes.py
      - openagents/utils/hold.py
      - openagents/utils/skip.py
      - openagents/utils/results.py
      - openagents/utils/config.py
      - openagents/utils/envcheck.py
      - openagents/utils/fleet_config.py
      - openagents/utils/fleet.py
    scope: 把 identity/release/notes/hold/skip/results/config/envcheck/fleet_config 的实现从旧模块物理搬迁进 openagents/utils/*（不再是薄再导出）；Fleet 进程监管器搬进 utils.fleet；随后删 orchestrator/messages/vigil/fleet/align/issuecheck 六个旧模块并让 recipes.fleet 改 import utils.fleet。
    acceptance: 无任何模块 import openagents.orchestrator/messages/vigil/fleet/align/issuecheck（grep 零命中）；六模块文件删除；ruff 绿。
  - id: T6
    title: 测试收敛 + 旧 spec 作废 + docs 再生成
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: false
    files:
      - tests/test_orchestrator.py
      - tests/test_messages.py
      - tests/test_vigil.py
      - tests/test_fleet.py
      - tests/test_align.py
      - tests/test_issuecheck.py
    scope: 删/重写直测旧六模块的 ~29 个测试桩（行为已被新栈 recipe 测试覆盖的直接删，仍有价值的迁到对应 recipe 测试）；作废旧 spec（0004/0007/0012/0027/0032/0039/0049 等，spec abandon）；spec render/graph 再生成 OVERVIEW/ARCHITECTURE 无漂移。
    acceptance: 全量 pytest 绿；无对已删模块的 import；spec validate + drift + graph --check 全绿。
---

# 0062 · 架构重构（收敛批）：全量迁移 RFC 生命周期 + PR 合并流水线到新栈，删旧两栈合一

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

前两批（Spec-0060 骨架 + Spec-0061 自主环）在 `agents/recipes/runtime/utils` 四层里立起了新栈，并让它能自足编排「一个 issue 从发现→分诊→求解→交付、及 PR 上人机对话」的自主环。但产品的另一半——**RFC 驱动开发生命周期**（`rfc/backfill-rfc/refine-rfc/implement/iterate`，共 914 行在 `orchestrator.py`）与 **PR 合并流水线**（mergeability/CI/e2e/review/merge 阶段状态机，963 行在 `messages.py`）——仍 100% 留在旧栈，新栈无任何等价物。本收敛批**一次做完**剩余全部迁移：把这两大块按既定分界线（**需判断的走 agent、客观机械留确定性 recipe/gates/utils**）重立为新栈 recipe，CLI 九条命令全量改接新栈，再把 utils 从「薄再导出」升级为**物理搬迁**并**删掉** `orchestrator/messages/vigil/fleet/align/issuecheck` 六个旧模块、重写其 ~29 个测试桩、作废对应旧 spec——实现**两栈合一**，`docs/specs` 快照里不再有并列的新旧同名模块。

## Motivation

现状：Spec-0060/0061 交付后仓库处于**两栈并存**的中间态。新栈能跑自主发现→求解→回应，但一切 **RFC 驱动**的动作（为 issue 起草 RFC 并开 draft PR、扫存量代码反推 spec、按评审精炼 RFC、RFC 获批后实现并转正、就反馈迭代）仍只有旧 `orchestrator.py` 一条实现；一切 **PR 推进合并**的动作（判可合并性、跑 CI/e2e 证据闸、评审、合并、hold/skip 短路、closed-run 复活、冲突自愈）仍只有旧 `messages.py` 的 964 行阶段状态机一条实现。CLI 里九条命令（`rfc/backfill-rfc/refine-rfc/implement/iterate/poll/watch/vigil/vigil-all`）直连这两个旧模块。

两栈并存不是稳态：读者要分辨「谁是新栈」，同名模块（新 `recipes.vigil`/`recipes.fleet` vs 旧 `vigil.py`/`fleet.py`）并列，utils 薄再导出让 import 面比实现面多一跳，~29 个测试桩仍钉在旧模块上。前两批把「删旧与收敛」显式推迟到「最终收敛批」（见两批的 Unresolved/Future 段），**本批就是那个收敛批**。用户明确要求不再分批、一波做完，故本批范围是「补齐剩余两大块 recipe + CLI 全量改接 + 物理搬迁删旧」的全集。

动机的分界线与前两批**逐字一致**：判断→agent（RFC 起草判断走 `drafter`、评审判断走既有 `reviewer`、评论回应走既有 `replier`、冲突自愈走既有 git delivery agent），客观机械留确定性代码（recipe 控制流 + `runtime.gates` 硬闸 + `utils` 原语）。

## Guide-level explanation

本批把旧栈剩余的两条主干按分界线重立成 recipe，再做一次性收敛删旧，落成六个 Task：

- **`recipes.rfc_lifecycle`（T1）**：把 orchestrator 的 `start_rfc/backfill_rfc/refine_rfc/implement/iterate` 五个入口重立为五条**纯控制流** recipe。每条只做「调 engine 派 agent 出结构化裁决 + 按裁决走确定性 utils 兜底动作」：需要判断的部分（RFC 正文怎么写、存量代码反推成什么 spec、按评论怎么精炼、获批后怎么实现）下放新 `drafter` agent（零逻辑 `string.Template` PROMPT + `OUTPUT_SCHEMA`）；机械部分（给 issue 打认领标签、开/转正 draft PR、写 spec 文件、贴公告评论）留 recipe 经 `utils.github`/`utils.identity`。
- **`recipes.merge_pr`（T2）**：把 messages.poll 的阶段状态机重立为一条 recipe。deterministic 闸（可合并性预检、CI 结论读取、e2e 证据溯源戳校验、hold/skip 对称短路、closed-run 复活水位线）留 recipe/`runtime.gates`——它们都是**读客观事实**非判断；评审「这版能不能合」的判断走既有 `reviewer` agent，冲突「怎么 rebase 解」走既有 git delivery agent。返回与旧 poll 同构的事件列表（`merged/blocked/ci/review/e2e/reopened/error` 等 reason）以便日志与断言。
- **vigil 收口（T3）**：给 `recipes.vigil` 去重闸补上旧栈的**署名认领便签 + 过期回收**（多后端跨进程认领归属），并把每轮守候段从「只回应评论」扩为「回应评论（poll_comments）+ 推进合并（merge_pr）」，闭合**发现→求解→回应→合并**全环。
- **CLI 全量改接（T4）**：九条命令改接 `recipes.*`，删 `_orchestrator_for` 工厂与 `messages.Messages` import，合并新旧命令名（`vigil-new`→`vigil`、`poll-comments` 收编进 `poll` 的评论段）。
- **物理搬迁删旧（T5）**：utils 从薄再导出升级为真实实现搬迁，`Fleet` 监管器搬进 `utils.fleet`，然后删 `orchestrator/messages/vigil/fleet/align/issuecheck` 六模块、让 `recipes.fleet` 改 import `utils.fleet`。
- **测试与文档收敛（T6）**：删/迁 ~29 个直测旧模块的测试桩，作废旧 spec，再生成 OVERVIEW/ARCHITECTURE。

## Reference-level explanation

**分界线判定（与前两批一致）**：留 recipe/gates 的都是「读客观事实」——可合并性（GitHub 给的 mergeable 位）、CI 结论（check 的 conclusion）、e2e 证据戳（head_sha 匹配否）、hold/skip 命中（配置里有没有）、复活窗口（closed_at 比不比阈值新）、认领便签存在性与过期（时间戳比阈值）。下放 agent 的都是「主观判断」——RFC 正文写什么、这版代码/RFC 能不能过评审、评论想要什么、冲突怎么 rebase。

**Task DAG + 文件分配**（`files` 全组两两不相交——协同模式无冲突的根，理念 6）：

| Task | depends-on | 拥有的 files | 交付 |
|------|-----------|-------------|------|
| **T1** | — | `recipes/rfc_lifecycle.py`, `agents/drafter.py`, `tests/test_recipe_rfc_lifecycle.py`, `tests/test_agents_drafter.py` | RFC 生命周期五 recipe + drafter（additive） |
| **T2** | — | `recipes/merge_pr.py`, `runtime/gates.py`, `tests/test_recipe_merge_pr.py` | 合并流水线 recipe + gates（additive） |
| **T3** | T1, T2 | `recipes/vigil.py`, `recipes/poll_comments.py`, `tests/test_recipe_vigil.py`, `tests/test_recipe_poll_comments.py` | vigil 认领回收 + 守候段接 merge_pr |
| **T4** | T1, T2, T3 | `cli.py`, `tests/test_cli_new_stack.py` | 九命令全量改接新栈、删旧路由 |
| **T5** | T4 | `utils/{identity,release,notes,hold,skip,results,config,envcheck,fleet_config,fleet}.py` | 物理搬迁 + 删旧六模块 |
| **T6** | T5 | `tests/test_{orchestrator,messages,vigil,fleet,align,issuecheck}.py` | 测试收敛 + 作废旧 spec + docs 再生成 |

DAG 形状：T1 ∥ T2 无依赖可并行 → T3 汇合 → T4 改接 → T5 删旧 → T6 收敛。additive 的 T1/T2 先行且 hermetic 可测（假 backend 喂 canned 裁决，不触真实 LLM/网络/仓库），destructive 的 T4→T5→T6 严格串行，且每步跑全量 pytest + ruff 作硬闸，任一红即停不推进。

**e2e 脚本**：`scripts/e2e-spec-0062-converge.sh`——ruff check + ruff format --check + 针对性 pytest（五 RFC recipe 路由 / merge_pr 全 reason 路由 / vigil 认领回收 / CLI 九命令转发）+ grep 锚点（drafter 零 def/subprocess；`grep -r 'openagents.orchestrator|messages|align|issuecheck'` 全库零命中，证明删旧彻底）。形态为纯后端编排、无 product-facing 前端，故不设浏览器 e2e，沿用前两批的离线确定性测法。

**接线单一点**：沿用 Spec-0061 的 `cli._new_vigil_for(ctx)` 一次构造 backend/RuntimeState/agent_id 的模式，T4 把 RFC 生命周期与 merge_pr 的工厂也收进单一接线点，保证同进程 backend/state/身份一致。

## Drawbacks

- **单批体量大、review 面宽**：一次改动跨 recipe 新增 + CLI 重接 + 删六模块 + 重写 ~29 测试，是本项目迄今最大的单批。缓解：DAG 把 additive（T1/T2）与 destructive（T4-T6）严格分层，每层全量 pytest+ruff 硬闸，且删旧只在 CLI 已全量改接（无人再 import 旧模块）后发生。
- **失去两栈并存的回退安全**：前两批 additive 保留旧栈作后备，本批删掉后无同进程回退，只能靠 git revert。缓解：删旧是最后一步且前置了「grep 零 import 旧模块」硬证据。
- **`messages.poll` 的部分历史语义可能在重立中漏迁**：964 行状态机含多个 Spec（0020 hold/0021 review-invalid/0031 merge-retry/0040 e2e/0042 reopened/0054 skip）叠加的分支。缓解：T2 以旧 poll 的 reason 集合为验收清单，逐 reason 建 hermetic 测试。
- **`drafter` 单 agent 承载五种起草判断**：RFC 起草/反推/精炼/实现/迭代的提示词差异大。缓解：drafter 用同一 Template 骨架 + 按 recipe 传入的 `mode` 占位符分化，仍零控制流。

## Rationale and alternatives

- **备选 A：继续分批（本批只做 merge_pr，RFC 生命周期留下批）**。是前两批的既定节奏，风险最低。**否决**：用户明确要求不再分批、一波做完；且两栈并存每多存在一批就多一批认知负担与 import 间接层。
- **备选 B：merge_pr 逐字移植 messages.poll 的 964 行状态机**。省重立成本。**否决**：违背重构目的（判断与机械仍糅在一起），把旧栈历史包袱整体搬进新栈。选择按分界线重立，deterministic 闸留 recipe、评审判断走 reviewer。
- **备选 C：utils 保持薄再导出、不物理搬迁，只删 orchestrator/messages**。删得更少、更安全。**否决**：薄再导出让 import 面比实现面多一跳，且 identity/fleet_config 等实现仍在「已宣告作废」的旧文件里，收敛不彻底。选择物理搬迁到 utils 作为实现唯一归属。
- **备选 D：drafter 判断写死在 recipe（不派 agent）**。省一个 agent。**否决**：则 RFC 起草单测必触真 LLM，且违分界线。选择下放 agent + recipe 注入 mode。

## Prior art

- **Spec-0060（批次一）**：确立四层分界线与 `solve_issue`/`engine`/`gates`/`Context`/`RuntimeState`；本批的 recipe/agent/gates 骨架直接承接。
- **Spec-0061（批次二）**：立起 `vigil`/`poll_comments`/`fleet` recipe 与 `triager`/`replier` agent、utils 稳定面、`cli._new_vigil_for` 单一接线点；本批 T3 在其 vigil 上补认领回收、T4 沿用其接线模式、T5 把其薄再导出升级为物理搬迁。
- **旧 `orchestrator.py`（RFC-0001/0005/0011/0019/Spec-0020/0025）**：RFC 生命周期五入口 + `precheck_issue`/`review_rfc`/`review_code`/`run_e2e` 的既有实现，是 T1 重立的行为基准。
- **旧 `messages.py`（RFC-0001/0012、Spec-0020/0021/0031/0040/0042/0054）**：poll 阶段状态机的 reason 集合与 hold/skip/revive 语义，是 T2 重立的验收清单。
- **旧 `vigil.py`（RFC-0004/0007、Spec-0039/0049）**：署名认领便签 + 过期回收，是 T3 补给 `recipes.vigil` 的行为基准。

## Unresolved questions

- **`drafter` 五 mode 是否需拆成多 agent**：本批先用单 agent + mode 占位符；若某 mode 的提示词膨胀到互相干扰，后续可拆。是否拆、按什么信号拆，实现 T1 时据提示词实际复杂度定。
- **新旧两套 state（`runtime-state.json` vs `state.json`）最终归一形态**：本批 T5 物理搬迁 utils，但 state 归一（择一还是合并 schema）牵涉数据迁移，是否纳入本批 T5 还是紧随其后单开一批，需用户确认（见下方澄清）。
- **`replier` 深度改代码仍未闭合**：本批 merge_pr 闭合「合并推进」，但 replier「据评论真改代码并 push」仍需 PR worktree（承 Spec-0061 同一 Unresolved），本批不含。

## Future possibilities

- **state 归一**：把 `runtime-state.json` 与 `state.json` 合并为单一 runtime 状态源，彻底消除双 state。
- **replier 升级为「据评论迭代交付」**：接 PR worktree 后复用 `solve_issue` 的 deliver + head 前移硬闸。
- **recipe 层沉淀通用编排原语**：五 RFC recipe + merge_pr + vigil 若出现重复的「派 agent→按裁决路由→utils 兜底」骨架，可抽成 runtime 层的 recipe 组合子。

