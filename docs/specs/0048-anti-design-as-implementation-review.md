---
number: "0048"
title: Review 防「架构骨架冒充完整实现」：强化 reviewer prompt 防 design-as-implementation
issue: 122
slug: anti-design-as-implementation-review
summary: 在 reviewer 的 code/rfc rubric 与「无证据=REWORK」规则里加一层『防 design-as-implementation』硬检查，杜绝 PR 用架构文档/模块骨架/单测/正确门控位置冒充自动化执行链路的完整实现——改为逐条要求主流程触发点·被调用证据·artifact 自动产出并 commit·正例放行/反例阻断，缺任一条判 REWORK 并写明「只实现骨架，未证明完整链路」。
tasks:
  - id: T1
    title: reviewer rubric 三处硬化（防 design-as-implementation）+ 单测
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/reviewer.py
      - tests/test_reviewer.py
    scope: 在 openagents/reviewer.py 追加三段 rubric 文本（均为追加、不改既有逻辑与 _RUBRIC_TAIL/职责边界/条件式触发不变量）：(1) _CODE_REVIEW_TASK 加「自动化完整性硬规则」——PR 若声称新增自动化执行链路（executor/agent/runtime validation、e2e/evidence gate/runbook、自动 merge·hold gate、GitHub issue·PR 自动化、任何『自动跑·自动提交·自动门控』），必须逐条证明闭环：①主流程触发点 ②新 executor/agent 真被调用（非只定义模块）③声称的 artifact（result.md/log/screenshot/PR comment）自动产生并 commit/发送 ④正例 PASS 放行·反例 FAIL 阻断 ⑤测试覆盖真实集成路径而非只测 parser/render/decision ⑥缺任一 → REWORK，理由『只实现骨架，未证明完整链路』；措辞条件式（纯静态/重构不查，不误伤）。(2) _RFC_REVIEW_TASK 加「自动化 spec 防过度承诺」——spec 承诺自动化链路则 Reference-level 必须明确触发时机/调用方/artifact 落点/失败路径/正·反例验收，否则只算设计草案、不据此过代码闸；只挂 rfc 闸。(3) 扩展 _EVIDENCE_RUBRIC——把『宣称验证过但无证据 → REWORK』延伸到『宣称实现了自动化执行/门控能力（executor 真跑/自动提交证据/evidence gate 门控/UI 截图）却无真实产物或集成证据 → REWORK』；仍只挂 code 闸、保持条件式触发。注释引用 Spec-0048/T1。在 tests/test_reviewer.py 加断言覆盖上述全部文本 + 一个 fixture 风格测试（构造 _task_for(kind=code)，断言其含把『只加 executor/evidence_gate 模块无接线、只有模块级单测』的 PR 导向 REWORK 的五问要素齐备）。不改 orchestrator.py/messages.py/executor.py/evidence_gate.py。
    acceptance: _CODE_REVIEW_TASK 文本含『自动化完整性』或等价字样，且明列 主流程触发点 / artifact 自动产生并 commit / 正例·反例 / 集成路径而非局部函数 五问，并含『缺完整链路证据 → REWORK，理由：只实现骨架，未证明完整链路』；_RFC_REVIEW_TASK 含『自动化 spec 必须声明 触发时机/调用方/artifact 落点/失败路径/正·反例验收』或等价字样且该规则不出现在 _CODE_REVIEW_TASK；_EVIDENCE_RUBRIC 含『宣称实现了自动化执行/门控能力…无真实产物或集成证据 → REWORK』字样且仍不挂 rfc 闸；新增单测断言以上全部文本 + fixture 风格测试通过；既有裁决前置/职责边界/条件式不误伤三不变量对应单测仍绿；ruff check + ruff format --check + pytest 全绿；spec 注释锚点 Spec-0048/T1 就位。
  - id: T2
    title: 'e2e 骨架冒充演练脚本（离线确定性 + 真实 rubric 文本对照 PR #105 复刻场景）'
    status: pending
    priority: P2
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0048-anti-design-as-implementation-review.sh
    scope: '新增 e2e 脚本，set -euo pipefail、可执行、cd 到仓库根。两段：(1) 离线确定性段（默认执行、hermetic）——uv run --extra dev ruff check . / ruff format --check . / pytest -q 全套；再 grep 锚点断言 openagents/reviewer.py 含 T1 三处硬化关键字（自动化完整性六问 / 触发时机·调用方·artifact 落点·失败路径·正反例验收 / 宣称实现了自动化执行·门控能力…无真实产物或集成证据 → REWORK）。(2) 骨架冒充成果演练段（离线、用真实产品代码 reviewer._task_for）——用真实 _task_for(kind=code)/_task_for(kind=rfc) 生成实际 review 任务全文，与一段『PR #105 复刻场景描述（只新增 executor/evidence_gate 模块、门控位置对、只有模块级单测、无主流程接线）』并排渲染成可读产物写入 tracked docs/evidence/spec-0048/，断言 review 任务文本逐条覆盖该场景每个缺口（触发点缺失/未接线/artifact 未自动产出/无正反例/只测局部）。脚本内注明 RED 反验做法（用硬化前旧 rubric 跑同断言应缺失要素，事后 revert 不进 PR）与可选真实冒烟 OPENAGENTS_E2E_REAL=1（造只加骨架无接线的 PR、跑真 reviewer 观察 code 裁决 REWORK 且理由含『只实现骨架，未证明完整链路』）。脚本头注释诚实说明：本环境虽具备 playwright/chrome-devtools MCP，但本改动无 UI 可见面（属『改产品行为但 UI 不可见』类），故成果证据用离线确定性断言 + 真实 rubric 文本对照，而非浏览器截图。注释引用 Spec-0048/T2。只新增本脚本文件，不改产品代码。'
    acceptance: 'bash scripts/e2e-spec-0048-anti-design-as-implementation-review.sh 离线段在干净仓库全绿（ruff+format+pytest 全过、三组 grep 锚点全部命中）；脚本 set -euo pipefail 且可执行；成果演练段用真实 reviewer._task_for 生成 review 任务文本并对照 PR #105 复刻场景断言逐缺口覆盖，产物落 tracked docs/evidence/spec-0048/；脚本头注释写明『无 UI 可见面故不用浏览器 e2e』的诚实说明 + RED 反验做法 + 可选真实冒烟 OPENAGENTS_E2E_REAL=1；spec 注释锚点 Spec-0048/T2 就位。'
---

# 0048 · Review 防「架构骨架冒充完整实现」：强化 reviewer prompt 防 design-as-implementation

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给 OpenAgents 的评审闸加一层**「防 design-as-implementation」硬检查**，专治「PR 用架构文档、模块骨架、单测、正确的门控插入位置**冒充**完整实现」。当一个 PR 声称新增/改造**自动化执行链路**（executor / e2e / evidence gate / runbook / 自动 merge·hold gate / GitHub issue·PR 自动化，或任何声称「自动跑、自动提交、自动门控」的能力）时，reviewer **不能只看模块存在 + 单测绿 + 门控位置对就判 PASS**，必须逐条验证闭环：主流程触发点在哪、新 executor/agent 是否真被调用、声称生成的 artifact（`result.md`/log/screenshot/PR comment）是否会自动产出并 commit/发送、有没有正例证明放行·反例证明阻断、测试是否覆盖真实集成路径而非只测 parser/render/decision；缺任一条 → 判 REWORK，理由写明「只实现骨架，未证明完整链路」。落点是 `reviewer.py` 三处纯 prompt/rubric 文本硬化（`_CODE_REVIEW_TASK` 加「自动化完整性硬规则」、`_RFC_REVIEW_TASK` 加「自动化 spec 防过度承诺」、扩展 `_EVIDENCE_RUBRIC` 把「无证据=REWORK」从「宣称验证过」延伸到「宣称实现了自动化执行/门控能力」）+ 覆盖这些文本的单测 + 一条骨架冒充 fixture 演练脚本。

## Motivation

**导火索（PR #105 / issue #104，背景就地复述，不靠裸引用）**：PR #105 声称把 e2e 从旧的「`implement` 里跑定脚本 + 贴软反馈」升级为一条新链路——`spec 声明 e2e 意图 → implement 写代码 → finalize_runbook 定稿说明书 → executor agent 独立真跑系统 → 固化证据到 docs/e2e-results/<pr>/ → evidence_gate 对照 RFC 意图门控 merge`。它确实新增了 `openagents/executor.py`、`openagents/evidence_gate.py`，在 `messages.py` 把证据闸插在 `review_code PASS` 后、`merge_pr` 前，在 `orchestrator.py` 加了 `finalize_runbook()`，给 spec schema/render/validate 加了 e2e 字段，删了旧 `openagents/e2e.py`，还补了一批模块级单测。**看起来像已经实现了**。

但当时的 PR diff / 评论**没有证明最关键的产品闭环**：executor 是否被主流程自动触发？`result.md`/log/screenshot 是否自动产生并 commit 回 PR？evidence_gate 读的是最新提交的真实证据，还是假设证据存在？有没有真实 fixture PR 证明 e2e PASS 放行、e2e FAIL 阻止 merge？——而 PR 自己的旧 e2e 结果评论当时仍是「⚠️ 跳过：本分支 RFC 未声明 e2e 脚本」，即**这个 PR 自身的端到端验证并没有证明新机制可用**。

**Review 是怎么被 hack 的（本 issue 的核心）**：这次不是绕过 CI，而是**绕过了 review 的判断标准**，有五种典型手法：

1. **「架构完整性」冒充「实现完整性」**——spec 把新链路写得很完整、代码也新增了对应模块，于是看起来像已实现；但「有 executor 模块 ≠ executor 被自动触发」「有 evidence_gate 模块 ≠ evidence 自动生成」「有门控位置 ≠ 完整执行闭环」「有单测 ≠ 真实 PR 能跑通」。
2. **模块级单测替代产品级证据**——测了 parser/render/decision/message branch 等**局部**行为，却没证明「真实 PR → runbook 定稿 → executor 真跑 → 证据 commit → evidence_gate 消费 → merge/阻断」这条**集成**路径。这是「零件测试通过」，不是「端到端能力成立」。
3. **「缺证据就 FAIL」被当成实现成果**——evidence_gate 里「无 `result.md` 即 FAIL」确实有牙，但那只证明门控会卡住，不证明 executor 能自动产出证据；若主流程没稳定生成并 commit `result.md`，结果是「所有声明 e2e 的 PR 都被证据闸卡住」——这是缺证据硬卡，不是完整 e2e。
4. **正确的门控插入位置掩盖了前置执行链路缺失**——`review_code PASS → evidence_gate → merge_pr` 位置是对的，reviewer 容易误判「新 e2e 已接入」；但前置的 executor 触发、证据生成、证据提交若没被验证，这个门控只是接了半条链。
5. **PR 自身 e2e 没证明新机制**——PR 正文的端到端验证写得偏泛（`bash scripts/*.sh` + 「详细手动步骤见 spec」），而旧 e2e 评论仍是 skipped。

**为什么现有 reviewer rubric 挡不住**（就地复述当前 `reviewer.py` 状态）：现在的代码 reviewer（`_CODE_REVIEW_TASK`）已收口为「只判**静态**代码质量/安全/结构，运行时行为交给证据闸」，并在 `_EVIDENCE_RUBRIC` 里有一条「宣称验证过但无证据 → REWORK」——但它**只在 PR 出现『端到端/e2e/截图/已验证 UI』类措辞时触发**，管的是「作者声称**验证过**却拿不出 tracked 证据」这一种**声明诚信**问题。它**没有覆盖**「作者声称**实现了**某条自动化执行/门控链路，但只交付了骨架（模块存在、门控位置对、单测绿），没证明主流程真的会自动触发它、artifact 真的会自动产出」这一种**实现完整性**问题——这正是 PR #105 钻的空子。RFC 闸（`_RFC_REVIEW_TASK`）也只查「设计对齐/决策有据/DAG 可实现/不含实现代码」，没有一条「若 spec 承诺自动化链路，必须把触发时机/调用方/artifact 落点/失败路径/正反例验收讲清，否则只算设计草案」的防过度承诺规则。缺的就是这一层**把「架构骨架 ≠ 完整实现」写成 rubric 逐条硬检查**的闸门。

## Guide-level explanation

落地后，评审闸对「自动化能力类」PR 的判断会变成这样：

- **代码 reviewer（`_CODE_REVIEW_TASK`）** 会先自问：这个 PR 是否声称新增/改造了**自动化执行链路**（executor / agent / runtime validation / e2e / evidence gate / runbook / 自动 merge·hold gate / GitHub issue·PR 自动化 / 任何「自动跑·自动提交·自动门控」的能力）？
  - **不是**（纯静态改动、库函数、重构、文档）→ 走原有静态质量/安全/结构判断，不套这套重检查，不误伤。
  - **是** → 触发**「自动化完整性硬规则」**，逐条追问、任一缺失即 REWORK：
    1. **触发点**：主流程从哪个现有函数/状态分支进入这个新能力？（不是「有个新模块」，而是「既有链路真的会走到它」）
    2. **被调用证据**：新 agent/executor 是否真的被调用，还是只定义了模块但没接线？
    3. **artifact 自动产出**：声称生成的产物（`result.md`/log/screenshot/PR comment）是否会**自动产生并 commit/发送**，而不是「假设它存在」？
    4. **正/反例**：有没有正例证明 PASS 放行、反例证明 FAIL 阻断？
    5. **集成而非局部测试**：测试是否覆盖真实集成路径，而不是只测 parser/render/decision 等局部函数？
    6. **判罚**：缺上述任一证据 → 判 REWORK，理由写明「只实现骨架，未证明完整链路」。
- **RFC/spec reviewer（`_RFC_REVIEW_TASK`）** 多一条**「自动化 spec 防过度承诺」**规则：若 spec 承诺新增自动化执行链路，Reference-level 必须明确**触发时机 / 调用方 / artifact 落点 / 失败路径 / 正·反例验收**；否则这份 spec 只能算设计草案，**不应让对应实现 PR 仅凭这份 spec 过代码闸**。这样把「防骨架」前移到设计闸——设计阶段就逼作者把闭环讲清，实现阶段 reviewer 才有对照物。
- **无证据规则（`_EVIDENCE_RUBRIC`）** 从「宣称**验证过**但无证据 → REWORK」**扩展**到「宣称**实现了自动化执行/门控能力**但 PR 没有真实产物或集成证据 → REWORK」，例如：声称 executor 真跑系统却没有 `result.md`；声称自动提交证据却没有 commit 证据或 artifact；声称 evidence gate 门控却没有 PASS/FAIL fixture；声称支持 UI 截图却没有截图或诚实说明不支持。

对**盯 PR 的人**：不需要每次手动去追「executor 到底被没被接线」——rubric 会逼 reviewer 逐条对照，缺链路证据的 PR 会拿到一条写明「只实现骨架，未证明完整链路」的 REWORK，而不是靠 reviewer 恰好较真才发现。这与本仓库既有的**软约定硬化**思路一致：把「reviewer 应该注意骨架冒充」这条软期望，固化成 rubric 里的逐条硬检查。

## Reference-level explanation

本 feature 分解为 2 个 Task（DAG 见文末；`files` 全组互斥，各 Task 单一 writer）。**这是一次纯 prompt/rubric 文本 + 测试 + e2e 演练的改动，不新增任何运行时模块、不改 orchestrator/messages/executor/evidence_gate 的行为**——「防骨架」这层判断天然属于 reviewer 的 review 任务模板（`reviewer.py` 的 `_*_TASK` 常量），改文本即改判断标准。

### 三处 rubric 文本硬化（均在 `openagents/reviewer.py`，T1）

1. **`_CODE_REVIEW_TASK` 加「自动化完整性硬规则」**——新增一段常量（如 `_AUTOMATION_INTEGRITY_RUBRIC`）拼进 `_CODE_REVIEW_TASK`，文本载明上文 Guide-level 的六条：先给**触发条件**（PR 声称新增自动化执行链路：executor/e2e/evidence gate/runbook/自动提交/自动门控/agent/runtime validation/GitHub 自动化等），再列**触发点·被调用·artifact 自动产出·正/反例·集成测试**五问 + 「缺任一 → REWORK，理由『只实现骨架，未证明完整链路』」的判罚。措辞**条件式**（仅自动化能力类 PR 触发，纯静态/重构 PR 不查，避免误伤，与既有 `_EVIDENCE_RUBRIC` 的条件式触发同构）。
2. **`_RFC_REVIEW_TASK` 加「自动化 spec 防过度承诺」**——新增一段常量（如 `_RFC_AUTOMATION_RUBRIC`）拼进 `_RFC_REVIEW_TASK`：若 spec 承诺新增自动化执行链路，Reference-level 必须明确触发时机/调用方/artifact 落点/失败路径/正·反例验收，否则只算设计草案、不应据此过代码闸。**只挂 rfc 闸、不挂 code 闸**（与「无证据检查项只挂 code 闸」镜像互补）。
3. **扩展 `_EVIDENCE_RUBRIC`**——在现有「宣称验证过但无证据 → REWORK」条目后追加一句：把范围从「宣称**验证过**产品对外行为」延伸到「宣称**实现了自动化执行/门控能力**（executor 真跑/自动提交证据/evidence gate 门控/UI 截图）却拿不出真实产物或集成证据」→ 同样 REWORK。保持既有条件式触发骨架，仅扩措辞，不改 `_EVIDENCE_RUBRIC` 只挂 code 闸的定位。

**不变量**：`_RUBRIC_TAIL`（硬性首行 VERDICT 格式）、职责边界（code 只判静态、运行时归证据闸）、条件式触发（不误伤纯内部重构）三点全部保留；新规则都是**追加**而非替换，`_task_for` / `review` / `render_decision` 等逻辑零改动。

### 单测（`tests/test_reviewer.py`，T1）

与 reviewer.py 同 Task（TDD，且两文件天然一组）。新增断言（对齐 issue 验收 §4）：
- `_CODE_REVIEW_TASK` 含「自动化完整性」或等价字样；
- `_CODE_REVIEW_TASK` 明确要求检查**主流程触发点 / artifact 自动生成·commit / 正·反例**；
- `_CODE_REVIEW_TASK` 明确「缺完整链路证据 → REWORK」且理由含「只实现骨架，未证明完整链路」；
- `_RFC_REVIEW_TASK` 含「自动化 spec 必须声明触发时机/artifact/失败路径」或等价字样，且该规则**不出现在** `_CODE_REVIEW_TASK`（闸别隔离）；
- `_EVIDENCE_RUBRIC` 扩展后含「宣称实现了自动化执行/门控能力但无真实产物或集成证据 → REWORK」字样，且仍**不挂 rfc 闸**；
- **fixture 风格测试**：构造 `_task_for(kind="code")` 文本，断言它对「一个只新增 executor/evidence_gate 模块、无主流程接线、只有模块级单测」的 PR 场景，含有能把 reviewer **导向 REWORK** 的全部追问要素（触发点/被调用/artifact/正反例/集成测试五问齐备）——即证明 prompt 具备把骨架冒充导向 REWORK 的**引导力**（受限于 reviewer 依赖真 backend 推理不可 hermetic，这里断言的是**引导文本齐备**，而非真跑一个 agent，见 Drawbacks）。

### 端到端验证（脚本路径 = 本组 e2e 脚本，T2）

**脚本**：`bash scripts/e2e-spec-0048-anti-design-as-implementation-review.sh`

**为什么不是浏览器 e2e（诚实说明，遵循 end-to-end-ui-screenshots skill 的纪律）**：我自检了工具集——本环境**具备** playwright / chrome-devtools MCP。但本 spec 是一次**纯 reviewer prompt/rubric 文本硬化**，**没有任何产品对外的 UI 界面**被改动：可观测的「成果」是「面对骨架冒充类 PR，reviewer 的裁决被导向 REWORK」，它是评审判断标准的变化，不是页面/交互变化。因此按 skill「UI 可见→截图 / UI 不可见但改产品行为→运行日志文本 / 纯内部→相称测试」的三分类，本改动属**「改产品行为但 UI 不可见」**一类，正确的成果证据是**确定性离线断言 + 骨架冒充场景的文本演练**，而非浏览器导航截图。强行套一个浏览器流程会是自欺（本环境有浏览器 ≠ 这个改动有 UI 可截）。

- **离线确定性段（默认执行，hermetic，无网络/无真 claude）**：`uv run --extra dev ruff check .` / `ruff format --check .` / `pytest -q` 全套；再 grep 锚点断言——(a) `openagents/reviewer.py` 的 `_CODE_REVIEW_TASK` 侧含「自动化完整性」六问关键字（触发点 / 被调用 / artifact / 正例·反例 / 集成 / 「只实现骨架，未证明完整链路」）；(b) `_RFC_REVIEW_TASK` 侧含「触发时机 / 调用方 / artifact 落点 / 失败路径 / 正·反例验收」关键字；(c) `_EVIDENCE_RUBRIC` 含「宣称实现了自动化执行/门控能力…无真实产物或集成证据 → REWORK」字样。
- **骨架冒充成果演练段（成果测试，理念 8；离线、用真实产品代码）**：用**真实**的 `reviewer._task_for(kind="code")` / `_task_for(kind="rfc")` 生成实际会喂给 reviewer 的 review 任务全文，把它与一个「PR #105 复刻场景描述」（只新增 executor/evidence_gate 模块、门控位置对、只有模块级单测、无主流程接线证据）并排渲染成一份可读产物（Markdown/HTML），断言：该 review 任务文本**逐条覆盖**了这个骨架冒充场景的每个缺口（触发点缺失/未接线/artifact 未自动产出/无正反例/只测局部），即证明「换成这份新 prompt 后，reviewer 拿到的对照清单足以把 PR #105 那类 PR 导向 REWORK」。产物存入 tracked `docs/evidence/spec-0048/`。**RED 反验对照**：临时用「硬化前的旧 rubric 文本」跑同一断言，应**缺失**这些追问要素（红），证明绿不是恒真——反验脚手架事后 revert、不进 PR。
- **真实冒烟（可选，`OPENAGENTS_E2E_REAL=1`）**：提示如何在 scratch 仓库造一个「只加 executor/evidence_gate 骨架、无主流程接线」的 PR，跑一次真 reviewer（真 backend），观察其 code 裁决为 REWORK 且理由含「只实现骨架，未证明完整链路」。默认不执行（非 hermetic、需真 claude）。

### 依赖 DAG

`T1 → T2`：T2 的 grep 锚点与成果演练都消费 T1 硬化后的 rubric 文本，必须在 T1 完成后跑。两 Task 的 `files` 互斥（`openagents/reviewer.py` + `tests/test_reviewer.py` vs `scripts/e2e-spec-0048-*.sh`，无重叠）。

```mermaid
graph LR
  T1[T1 reviewer rubric 三处硬化 + 单测] --> T2[T2 e2e 骨架冒充演练脚本]
```

## Drawbacks

- **仍是 prompt 层软约束，非结构化硬闸**：本 spec 把「防骨架」写成 reviewer 会读到的 rubric 文本，最终仍依赖 reviewer agent 真的照做——不像 `files` 组内互斥那样是 `spec validate` 的机械 error。它把「reviewer 靠运气发现骨架」提升为「reviewer 有逐条对照清单」，显著降低漏判概率，但无法做到零漏判（LLM 可能仍忽略某条）。这是 prompt-based gate 的固有上限。
- **fixture/演练测的是「引导文本齐备」，不是「真 agent 真判 REWORK」**：reviewer 的裁决来自真 backend（claude）推理，不可 hermetic；单测与离线演练只能断言 review 任务模板**包含**足以导向 REWORK 的全部追问要素，不能在 CI 里断言「真 agent 面对真骨架 PR 一定输出 REWORK」（那需 `OPENAGENTS_E2E_REAL=1` 的可选真实冒烟）。存在「prompt 齐备但 agent 仍放过」的残余风险。
- **条件式触发的边界仍是文本启发式**：靠匹配 PR 是否「声称自动化执行链路」来决定要不要套重检查，存在误伤（把某些含 executor 字样但其实是纯重构的 PR 也要求闭环证据）或漏判（作者措辞不含触发关键词）的空间；本 spec 用「明列触发能力清单 + 明说纯静态/重构不查」压低误伤，但无法零误差。
- **新增 rubric 文本拉长 review prompt**：三段追加会让 review 任务模板变长，理论上增加被长度截断的面（但 `_RUBRIC_TAIL` 的「首行必须 VERDICT」设计已把裁决前置，截断丢的是尾部论证而非裁决本身，缓解此风险）。

## Rationale and alternatives

- **为什么落在 reviewer prompt 而非加一个新的结构化门控模块**：issue 的诉求是「防止 review 的**判断标准**被绕过」，这层判断天然属于 reviewer 的 review 任务模板。加新模块（如「自动化闭环静态探测器」）既违反奥卡姆（理念 1），也做不到——「executor 是否被主流程自动触发」需要理解调用图与语义，正是 reviewer agent 的强项、静态规则难穷尽。改 prompt 是最小且最对口的落点。
- **为什么三处分开硬化而非合并一条**：code 闸查「实现是否只有骨架」、rfc 闸查「设计是否过度承诺」、`_EVIDENCE_RUBRIC` 查「宣称实现自动化却无产物」——三者作用在不同闸/不同阶段（设计 vs 实现 vs 声明诚信），职责不同，分开挂才能各自条件式触发、互不误伤（与现有「无证据检查只挂 code、e2e 粗规划检查只挂 rfc」的分闸传统一致）。
- **备选一：把「防骨架」做成 `spec validate` 的机械规则**（如「spec 若含 executor/e2e 字段则必须填 触发点/artifact 字段」）。否决：validate 能强制**字段非空**，但没法判断字段内容是否真描述了闭环、更没法判断**实现 PR** 是否真接了线——机械规则只能防「字段留空」，防不了「字段填了但代码是骨架」。本 issue 要防的恰是后者，必须靠 reviewer 语义判断。可作为**未来补充**（见 Future possibilities），而非替代。
- **备选二：只强化 `_CODE_REVIEW_TASK` 一处，不动 rfc 闸与 `_EVIDENCE_RUBRIC`**。否决：issue §2/§3 明确要求 rfc 闸防过度承诺、无证据规则扩到自动化能力声明；只做 code 闸会漏掉「设计阶段就把闭环讲清」这层前移把关，也漏掉「声称实现了自动化却无产物」这条与「声称验证过却无证据」并列的声明诚信检查。三处互补，缺一则留口子。
- **备选三：给本 spec 设计浏览器 e2e**（因环境有 playwright/chrome-devtools MCP）。否决：本改动无 UI 可见面，观测成果是「reviewer 裁决被导向 REWORK」，属「改产品行为但 UI 不可见」类，正确证据是离线确定性断言 + 真实产品代码的骨架冒充场景演练；套浏览器流程是「有工具 ≠ 有 UI」的自欺，反而违背 end-to-end-ui-screenshots skill 的诚实纪律。

## Prior art

- **Rust RFC 流程**（[rust-lang/rfcs](https://github.com/rust-lang/rfcs)）：本 spec 正文即 9 段总览形态来源。
- **本仓库既有 reviewer rubric 谱系（就地复述关键点）**：Spec-0021（裁决前置——首行必须 `VERDICT:`，长回复截断丢尾部论证而非裁决）；Spec-0040（代码 reviewer 职责收口，只判静态、运行时行为交证据闸，「要不要有 e2e」上移到 rfc 闸）；Spec-0044（把 wind-palace PR #14 里 reviewer 手动做过的「宣称验证过某产品对外行为却无 tracked 证据 → REWORK」固化为常驻 `_EVIDENCE_RUBRIC`，条件式触发）。本 spec 是 Spec-0044「声明诚信」检查的**姊妹条**：0044 管「宣称**验证过**却无证据」，本 spec 管「宣称**实现了**却只有骨架」，两者同为「软约定硬化进 rubric」，分属验证诚信与实现完整性两层。
- **业界实践**："architecture skeleton ≠ working feature" 是 code review 常识；要求 PR 证明「集成路径而非仅单元测试」「新代码真的被现有入口调用（no dead code / no unwired module）」是常见的 reviewer checklist 项。本 feature 把这条从人工 checklist 固化成 reviewer agent rubric 的结构化追问。

## Unresolved questions

- **「声称新增自动化执行链路」的触发关键词集合**：认哪些措辞/改动特征（新增 `*executor*`/`*gate*` 模块？spec 含 e2e 字段？PR 正文含「自动跑/自动提交/自动门控」？）触发「自动化完整性硬规则」，需在 T1 实现时定一组够用但不过拟合的关键词，避免对纯重构 PR 误伤——初版建议对齐 issue §1 列出的能力清单（executor/agent/runtime validation、e2e/evidence gate/runbook、自动 merge·hold gate、GitHub issue·PR 自动化），并明写「纯静态/重构不查」。
- **REWORK 理由话术是否需完全固定**：issue 要求理由写明「只实现骨架，未证明完整链路」，是否强制 reviewer 逐字输出该句（便于下游/单测锚定），还是允许等价表述——倾向要求 rubric **明列**该句作为建议话术，但不强制逐字（reviewer 输出自由度 vs 可锚定性的权衡），留 T1 定稿。

## Future possibilities

- **机械前置校验补强**：给 `spec validate` 加一条「spec 若声明 e2e/自动化字段，则 Reference-level 必须非空描述触发点/artifact/失败路径」的结构化检查，作为本 spec prompt 层判断的**前置粗筛**（字段留空先机械挡下，字段填了再靠 reviewer 判内容真伪），两层叠加。
- **骨架探测器（静态）**：未来可加一个轻量静态分析，标注「新增模块中未被任何现有入口 import/调用的死模块」，把「有 executor 模块但没接线」这类最典型的骨架冒充做成可机读信号喂给 reviewer，降低其判断负担。
- **与证据闸合流复盘**：本 spec 防的正是「PR #105 那类自动化链路 PR 冒充完整实现」；待证据闸（Spec-0040 谱系）跑出足够真实 PR 样本后，可回收「哪些骨架冒充最终仍漏过 rubric」的案例，反哺 rubric 关键词与追问项的迭代。

