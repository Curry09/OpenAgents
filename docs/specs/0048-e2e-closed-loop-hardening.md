---
number: "0048"
title: 补齐 e2e 完整实现闭环：证据闸判定收口 + 真实 git fixture
issue: 123
slug: e2e-closed-loop-hardening
summary: Spec-0040 已把「定稿 runbook→executor 真跑→证据 commit→证据闸门控合并」接进主流程，但 ui(skipped) 形态判定含糊、证据缺乏归属校验、全链路只有 mock 单测无真实 git fixture——本组只补这三处「有骨架无实证」的缝隙，不重设计骨架。
e2e:
  form: cli
  intent: 证明本组补的三处缺口真的堵上了：① outcome=skipped（ui 形态）与跨 PR 证据必须被证据闸结构化硬 FAIL（不再含糊过 LLM 判断）；② 有一条基于真实 git commit/push 的闭环脚本，证明 e2e PASS 放行、FAIL 阻断两条路径在非 mock 环境下都成立。
  acceptance:
    - 喂一份 outcome=skipped（ui 形态）的 result.md 给 evidence_gate.review_evidence → 断言直接 passed=False 且 feedback 含「ui」「Phase 1」与「cli/api/backend」改声明提示，且不调用 backend.run。
    - '把 PR #5 的 result.md 复制进 PR #6 的证据目录喂给 evidence_gate.review_evidence(pr_number=6) → 断言 passed=False 且 feedback 含「不属于当前 PR」，不调用 backend.run。'
    - 跑 scripts/e2e-spec-0048-e2e-closed-loop-fixture.sh：真实临时 git 仓库（bare remote）+ 真实 Workspace/Orchestrator + fake backend，驱动 messages._evidence_gate 完整路径 → 断言 PASS 放行不 iterate 且证据 commit 在 git log 可查、FAIL 走 iterate(reason="e2e") 不 merge 但证据 commit 仍在（durable）。
tasks:
  - id: T1
    title: 证据闸判定收口：skipped(ui) 与跨 PR 证据显式硬 FAIL
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/evidence_gate.py
      - tests/test_evidence_gate.py
    scope: 'review_evidence 在派 LLM 前新增两项结构化短路判定（复用 executor._render_evidence 已产出的稳定文本格式，不改任何接口签名）：① 解析 result.md 的「结论：{outcome}」行，outcome=skipped（当前只有 ui 形态会产出）→ 不派 agent，直接判 FAIL，feedback 明确提示「Phase 1 不支持 ui 浏览器形态，请把 spec 的 e2e.form 改声明为 cli/api/backend 之一，或转人工验收」；② 解析 result.md 头部「# 端到端执行证据（PR #{n}）」，n 与调用方 pr_number 不一致 → 不派 agent，直接判 FAIL，feedback 提示「证据不属于当前 PR（记录 PR #{n}，期望 #{pr_number}）」。两条判定均落在 tautology guard 第④道防线（对齐既有第③道「证据缺失即 FAIL」）。'
    acceptance: 单测覆盖：outcome=skipped → passed=False 且 feedback 含「ui」与「cli/api/backend」提示、不触发 backend.run；PR 号不符 → passed=False 且 feedback 含「不属于当前 PR」、不触发 backend.run；outcome=passed 且 PR 号一致 → 仍走既有 LLM 判定路径（零回归，照常调 backend.run）；既有「证据缺失即 FAIL」（防线③）用例不受影响。ruff + pytest 通过。
  - id: T2
    title: 真实 git 闭环 fixture 脚本（本地 bare remote，PASS/FAIL 两条路径）
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: true
    files:
      - scripts/e2e-spec-0048-e2e-closed-loop-fixture.sh
    scope: 新增脚本，复用 scripts/e2e-spec-0039-vigil-claim-dedup.sh 的 LIVE/OFFLINE 双路径声明约定（不新造范式）：先跑离线段（ruff+pytest 全套），再用真实临时目录 `git init --bare` 当 origin + 真实 Workspace/Orchestrator + fake AgentBackend（确定性可控 summary）+ 打桩 github 模块（不依赖网络/gh 登录——本组要证的是「git 落盘 + 门控判定」而非 GitHub API 集成，后者已被既有 spec/测试覆盖），驱动 messages.Messages._evidence_gate 的完整生产路径，断言：① e2e PASS → 不 iterate，且证据文件确实以真实 git commit 落进分支历史（`git log` 可查）；② e2e FAIL → iterate(reason="e2e") 被调、不 merge，但证据 commit 仍然存在（durable，供人审计）；③ 缺 result.md（模拟 executor 写入前置条件被破坏）→ 证据闸硬 FAIL 且 feedback 可操作；④ 跨 PR 证据（把另一 PR 目录下的 result.md 复制进本 PR 证据目录）→ 命中 T1 新守卫，硬 FAIL。脚本显式 echo 断言了什么、跳过了什么（不触真实 gh/网络，诚实降级说明）。
    acceptance: 本地 `bash scripts/e2e-spec-0048-e2e-closed-loop-fixture.sh` 可跑通、退出码 0；四条断言全部基于真实文件系统 + 真实 `git log`（不是纯内存 mock）；PASS 路径能在 git log 里找到证据 commit；FAIL 路径 merge_pr（打桩）未被调用且证据 commit 仍存在；跨 PR 证据与 skipped 两个反例都命中 T1 的硬 FAIL 分支（feedback 文案匹配）。
  - id: T3
    title: UI 形态支持边界文档化（docstring + README）
    status: pending
    priority: P2
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: true
    files:
      - openagents/orchestrator.py
      - openagents/messages.py
      - README.md
    scope: 在 `messages._evidence_gate`（编排接线处）与 `orchestrator.finalize_runbook`/`commit_evidence`（说明书定稿/证据提交处）的 docstring 补一句「当前仅 cli/api/backend 真实起系统验证；ui 声明会被证据闸判定为结构化 FAIL（Spec-0048/T1）并提示改形态，不会被误判 PASS」；在根 README.md 新增一节「e2e 形态支持现状」，列出已支持（cli/api/backend，独立 executor 真起系统）与未支持（ui 浏览器，留 Phase 2）、以及未支持时的确定性行为（证据闸硬 FAIL + 可操作提示，而非静默跳过或误判 PASS）。
    acceptance: README.md 新增小节存在，且可用关键词「Phase 1」「ui」「FAIL」grep 命中；orchestrator.py / messages.py 对应 docstring 更新处引用 Spec-0048；纯文档/注释改动，ruff check + ruff format --check 通过，既有测试零回归（无需新增测试）。
---

# 0048 · 补齐 e2e 完整实现闭环：证据闸判定收口 + 真实 git fixture

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

Spec-0040（issue #104，PR #105）已经把 OpenAgents 的 e2e 从「实现者顺手写脚本、`implement` 里跑一次、
贴条不门控」升级为「定稿 runbook → 独立 executor 真跑系统 → 证据固化并 commit → 证据闸对照 RFC 意图
门控合并」，并把这条链路接进了 `messages._process_coding`（代码 reviewer 全票 PASS 之后、`merge_pr` /
hold-merge 之前）。**骨架和接线都是真的、已经在跑**——但逐行核对代码与测试后发现三处「有骨架无实证」
的缝隙：① `ui` 浏览器形态（Phase 1 明确不支持）被 executor 判 `skipped` 后，证据闸没有专门处理，会把
含糊的「结论：skipped」文本原样丢给 LLM 去猜 PASS/FAIL；② 证据闸只按目录路径读证据，没有核对证据文件
自称的 PR 号是否与本轮判定的 PR 一致，留了一道「误用他 PR 残留证据」的口子；③ 全部现有测试（含号称
「闭环演练」的 `scripts/e2e-spec-0040-runbook-driven-evidence-gate.sh`）都在 `messages`/`orchestrator`
层用 monkeypatch 打桩，从未有一条脚本用真实 git commit/push 走通「executor 写证据 → commit_evidence
落盘 → evidence_gate 读最新证据」这条链路。本组**只补这三处缝隙**，不改 Spec-0040 的接口契约与状态机。

## Motivation

**背景（就地复述，不靠裸引用承载必要信息）。** OpenAgents 是 RFC/spec 驱动的多 agent 框架：守夜人
`messages.Messages.poll` 扫描 open 状态的 run，`_process_coding`（`messages.py:451`）是代码合并前的核心
闸：CI 绿 + `review_code` 全票 PASS 后（`messages.py:502-503`），先插入证据闸 `self._evidence_gate(record=record)`
（`messages.py:508`），证据闸放行（返回 `None`）才继续走 `hold.at_merge` 夯住或 `github.merge_pr`
（`messages.py:516-518`）；证据闸 FAIL 则短路返回 `iterate(reason="e2e")` 事件（回合 +1，攒满 `MAX_ROUNDS`
挂起 `_block(gate="e2e")`，见 `messages.py:598-601`）。这条门控本身是真实存在的、已经在生产路径上——不
是本组要修的问题。

`_evidence_gate`（`messages.py:555-601`）的实际步骤：

```text
① orchestrator.finalize_runbook(pr_number)  —— 读 spec 的 e2e 粗规划，派实现者 backend 定稿
   docs/e2e-results/<pr>/runbook.md 并 commit+push（orchestrator.py:588-629）；无粗规划返回 None，
   证据闸空过（非交互 PR 零回归）。
② executor.run_executor(...)  —— 独立 agent 读 runbook，按形态（cli/api/backend）真跑系统，把结构化
   结果写进 evidence_dir/result.md（executor.py:94-128、180-208，_write_evidence 总是执行、不因异常
   跳过）。
③ orchestrator.commit_evidence(pr_number)  —— 把 evidence_dir 里的改动 commit+push（orchestrator.py:
   631-644，workspace.commit_and_push 内部无改动即跳过 commit、仍 push，见 workspace.py:64-72）。
④ evidence_gate.review_evidence(...)  —— 派独立证据闸 agent 拿 RFC 意图对照 evidence_dir/result.md
   判 PASS/FAIL（evidence_gate.py:80-104）。
```

**这条链路本身是通的**——`tests/test_messages.py:511-597` 的 `test_evidence_gate_pass_merges` /
`test_evidence_gate_fail_iterates_e2e_no_merge` / `test_evidence_gate_fail_over_k_blocks_e2e` /
`test_evidence_gate_empty_pass_when_no_plan` 分别断言了 PASS→merge、FAIL→iterate(e2e)不merge、FAIL攒满
K→block(gate=e2e)、无粗规划→空过 merge 四条路径。issue #123 里担心的「主流程是否自动触发 executor」
「谁提交 evidence」「谁触发 evidence_gate」在当前代码里都有明确、单一的答案（如上①-④），**不是本组的
问题**——issue 提出时对照的是 PR #105 早期状态，之后的补丁提交（`33f0d03` 统一 runbook 形态声明
producer/consumer 契约、`f7280c9` 修复 executor 证据写入契约、及 `messages.py`/`orchestrator.py` 的编排
接线）已经把主链路接完整。本组要修的是三处**逐行核对后发现的、真实存在的**缝隙：

**缝隙①：`ui` 形态判定含糊，可能被误判 PASS。** `executor.py:35-37,141-142` 明确「本组（Phase 1）落地
的非浏览器运行时形态」只有 `cli`/`api`/`backend`，`ui` 走 `_run_by_form` 的 `if form == _UI_FORM:` 分支
（`executor.py:141-142`）直接返回 `ExecutorResult(outcome=OUTCOME_SKIPPED, form="ui", notes=_UI_PHASE2_NOTE)`
——**不派 agent**。但 `_write_evidence`（`executor.py:180-193`）对任何 outcome 都无条件把结果渲染进
`result.md`（`_render_evidence`，`executor.py:196-208`，含一行「- 结论：skipped」）。问题在 `evidence_gate.
review_evidence`（`evidence_gate.py:80-104`）：它只检查 `result_file.is_file()`（`:96`），文件存在就直接
把整份 `result.md` 交给独立证据闸 agent 去读、去判 `VERDICT: PASS|FAIL`（`_EVIDENCE_REVIEW_TASK`，
`evidence_gate.py:44-55`）——**完全没有对 `outcome=skipped` 做结构化短路**。这意味着一个声明了 `ui` 形态
粗规划的 PR，其证据闸裁决完全取决于证据闸 agent 怎么解读「结论：skipped，ui 浏览器形态本组不实现，留待
Phase 2」这段文本——它可能读出「显式跳过=不算失败=偏向 PASS」，也可能读出「没真跑=未达成=FAIL」，是
**非确定性的**。这正是 issue #123 第 5 条「如果 Phase 1 不支持 ui，就不要写得像完整支持…不支持时是
skipped、REWORK，还是 needs-human，应明确」要求的：当前代码里这个决策**没有被显式做出**，是隐式委托给
了一次 LLM 调用的运气。

**缝隙②：证据闸不核对证据的 PR 归属，留了误用口子。** `evidence_gate.review_evidence` 拿到
`evidence_dir`（由 orchestrator 计算并透传，`evidence_gate.py:71-77` `evidence_dir_for`）后只看该目录下
有没有 `result.md`（`:96`），**从不解析 `result.md` 内容里 executor 自己写的「# 端到端执行证据（PR
#{pr_number}）」头**（该头由 `executor._render_evidence:199` 渲染，字符串现成可读）与调用方传入的
`pr_number` 是否一致。当前生产路径下（`messages._evidence_gate` 每轮都按顺序①→④重新生成 `runbook.md`/
`result.md`）这个口子不会被触发；但这只是**调用顺序带来的偶然安全**，不是 `evidence_gate` 自身的不变
量——`evidence_gate.py` 模块 docstring 明写「只依赖 `AgentBackend` + 文件系统，不 import executor /
orchestrator」（`:12-14`），也就是说它被设计成**可被其它调用方独立复用**的模块；一旦有第二个消费方（例如
未来的人工重放工具、或某个绕过 `_evidence_gate` 的调用路径）传入了一个装着别的 PR / 陈旧证据的
`evidence_dir`，`review_evidence` 会照单全收，拿别人的证据去判本 PR 的意图达成——这正是 issue #123 第 4
条「证据过旧 / 不属于当前 PR 时不会被误用」明确要求防的。tautology guard 目前只有三道防线（意图在 RFC
锁死、executor 独立、证据 reviewer 独立核对，Spec-0040 Reference-level）——都是防「自定说明书自己
过」，没有一道是防「读错证据目录」。

**缝隙③：全部现有验证都是 mock，没有一条真实 git fixture。** `tests/test_messages.py:483-597` 的四个
证据闸测试全部通过 `monkeypatch.setattr` 打桩 `messages_module.executor.run_executor`、
`messages_module.evidence_gate.review_evidence`（`_patch_gate`，`:489-509`），以及打桩
`_FakeOrchestrator.finalize_runbook`/`commit_evidence`（`:83-88`）——即「`messages._evidence_gate` 按顺序
调用了这四个函数」这件事本身被测了，但**这四个函数各自的真实实现（真起 agent、真写文件、真 git commit/
push）从未在同一条测试里被串联执行过**。号称「闭环演练」的 `scripts/e2e-spec-0040-runbook-driven-
evidence-gate.sh`（第 2 段，`:28-109`）确实调了 `executor.run_executor` / `evidence_gate.review_evidence`
两个真实函数（不是打桩），但传入的 `work_dir`/`evidence_dir` 只是 `tempfile.TemporaryDirectory()`
（`:50-51`）——**不经过 `Workspace`/`Orchestrator`，不涉及任何 git 操作**，也就完全没有走到
`orchestrator.finalize_runbook`/`commit_evidence` 里的 `workspace.commit_and_push`（`orchestrator.py:
619-623,640-643`）。也就是说，issue #123 第 3 条「证据 artifact 会自动 commit 回 PR」这件事，**在当前
仓库里没有任何一条测试或脚本真正验证过**——它是否真的把 commit push 出去了，完全依赖对 `workspace.
commit_and_push` 单元测试的信任传递，没有一条端到端路径把「executor 写证据」到「git log 里出现一条证据
commit」这段因果链实际跑一遍。对照仓库里另一个真做到「真实 git/gh 集成」的先例
`scripts/e2e-spec-0039-vigil-claim-dedup.sh`（`OA_E2E_LIVE=1` 时真建 scratch 仓库、真 push、真读
`git ls-remote`，见该脚本 `:8-19`），Spec-0040 的闭环脚本明显缺这一段。

**核心结论。** 三处缝隙的共同根：**证据闸的判定逻辑目前信任两件本不该被无条件信任的事**——「LLM 读到
含糊文本时会做出我们期望的保守判断」「evidence_dir 里的东西一定属于且只属于当前这次判定」；以及
**「commit 回 PR」这一步从未被真实验证过，只有单元测试层面的信任传递**。本组把前者从「隐式信任 LLM」
升级为「结构化短路判定」（T1），把后者从「零验证」升级为「一条基于真实 git 的闭环 fixture」（T2），并
把「Phase 1 只支持 cli/api/backend」这件事从「代码注释里写着但外部读者未必找得到」升级为「README 里
明确写、且行为上有确定性保证」（T3）。

## Guide-level explanation

**场景一：某 PR 的 spec 声明了 `ui` 形态的 e2e 粗规划（如给一个新的前端表单页面）。**

- **现状（本组修复前）**：代码 reviewer PASS 后，`finalize_runbook` 正常定稿 runbook（声明 `form:
  ui`）；`executor.run_executor` 识别到 `ui` → 不派 agent，直接判 `skipped`，把「结论：skipped，ui
  浏览器形态本组不实现，留待 Phase 2」写进 `result.md`；`commit_evidence` 照常把这份证据 commit 进 PR；
  `evidence_gate.review_evidence` 派一个独立证据闸 agent 去读这份「结论：skipped」的 `result.md`，让它
  自己判 `VERDICT: PASS` 还是 `VERDICT: FAIL`——**结果不确定**，可能这条 PR 就这么被误判 PASS 合并了，
  而它的 UI 行为其实从没被任何 agent 真正操作过。
- **修复后（T1）**：`evidence_gate.review_evidence` 在派 agent 之前先解析 `result.md` 的「结论：」行，
  发现 `skipped` 就不再犹豫——直接返回 `passed=False`，`feedback` 明确写「Phase 1 不支持 ui 浏览器
  形态，请把 spec 的 e2e.form 改声明为 cli/api/backend 之一，或转人工验收」。这条 FAIL 会走
  `iterate(reason="e2e")` 把提示喂回实现者：要么改声明形态（如果这次改动其实有 CLI/API 侧可验证的
  行为)，要么等 Phase 2，要么找人工验收——**不会被静默放行**，也不会含糊挂起等 LLM 猜。

**场景二：evidence_gate 被第二个消费方直接调用（不经过 `messages._evidence_gate`），传入的
`evidence_dir` 其实是另一个 PR 遗留的旧目录。**

- **现状（本组修复前）**：只要目录下有 `result.md` 就会被当真，独立证据闸 agent 拿着别的 PR 的证据去判
  这次的 RFC 意图，裁决可能碰巧对（意图相似）也可能完全错判。
- **修复后（T1）**：`review_evidence` 解析 `result.md` 头部记录的 PR 号，与调用方传入的 `pr_number` 不
  一致 → 直接 `passed=False`，`feedback`「证据不属于当前 PR」，不浪费一次 agent 调用，也不给错误裁决
  可乘之机。

**场景三：验证「证据真的 commit 回了 PR」这件事本身。**

- **现状（本组修复前）**：只能读代码、读单元测试，无法用一条命令看到「证据文件真的进了 git 历史」。
- **修复后（T2）**：`bash scripts/e2e-spec-0048-e2e-closed-loop-fixture.sh` 建一个真实临时 git 仓库当
  `origin`，真实 `Workspace`/`Orchestrator` 在这个仓库的 worktree 里跑一遍 `_evidence_gate` 完整四步，
  跑完直接 `git log` 该分支——证据 commit 是否存在、PASS/FAIL 两条路径下 `merge_pr`（打桩）是否分别被
  调用/不被调用，都是脚本里对**真实文件系统 + 真实 git 历史**的断言，不是对内存 mock 调用次数的断言。

## Reference-level explanation

### 修复范围：只补三处缝隙，不动 Spec-0040 的接口契约

本组显式不做的事（避免过度设计，理念 1）：不改 `executor.run_executor` / `evidence_gate.
review_evidence` / `orchestrator.finalize_runbook` / `orchestrator.commit_evidence` 的函数签名；不改
`messages._evidence_gate` 的调用顺序或返回约定（`None`=放行，`dict`=短路）；不新增 `status`；不改
`MAX_ROUNDS`/`rounds` 的计数规则；不在 Phase 1 里实现 `ui` 浏览器执行（那是 Spec-0040 Future
possibilities 里明确留给 Phase 2 的范围）。

### T1：证据闸判定收口（`openagents/evidence_gate.py`）

在 `review_evidence`（`evidence_gate.py:80`）现有的「先查 `result_file.is_file()`」之后、「派 agent」
之前，插入两步新的结构化解析（复用 `executor._render_evidence` 已经产出的稳定格式，不新增文件或字段）：

```text
result.md 现有格式（executor._render_evidence 产出，evidence_gate.py 新增两处正则解析）：
  # 端到端执行证据（PR #{pr_number}）      ← 新解析：PR 归属校验
  ...
  - 结论：{outcome}                        ← 新解析：outcome=skipped 短路判定
  ...
```

- 新增 `_PR_HEADER_RE`（匹配 `PR #(\d+)`）与复用/新增 `_OUTCOME_LINE_RE`（匹配 `结论：(passed|failed|
  skipped)`），解析失败（匹配不到）不新增 FAIL 分支——按现状继续走 LLM 判定（不因新增校验引入误挡）。
- `outcome == "skipped"` → 直接 `EvidenceDecision(passed=False, feedback=<Phase 1 不支持 ui，请改声明
  cli/api/backend 或转人工>)`，不调用 `backend.run`。
- PR 号解析成功且 `!= pr_number` → 直接 `EvidenceDecision(passed=False, feedback=<证据不属于当前 PR>)`，
  不调用 `backend.run`。
- 两步都不匹配（PR 号一致、outcome 是 passed/failed）→ 照旧派 agent 判定（零回归）。

### T2：真实 git 闭环 fixture 脚本（`scripts/e2e-spec-0048-e2e-closed-loop-fixture.sh`）

复用 `scripts/e2e-spec-0039-vigil-claim-dedup.sh` 已验证过的「离线段 + 真实副作用段，脚本内显式 echo
当前跑的是哪一段」约定（不新造范式，理念 1）。与 spec-0039 的差别：spec-0039 的「真实」指真实 `gh`/
GitHub API；本组的「真实」收窄到**真实 git commit/push/文件系统**（用 `git init --bare` 建本地临时
`origin`，不依赖网络或 `gh auth`），因为本组要证的是「evidence 是否真的落进 git 历史、evidence_gate 是
否读到最新证据」，GitHub API 集成不是本组范围（已被其它既有 spec/测试覆盖）。脚本结构：

```text
[1/2] 离线确定性验证 —— ruff check/format + pytest 全套（含 T1 新增单测）。
[2/2] 真实 git 闭环演练 ——
  a) 建临时目录：`git init --bare` 出一个 origin 仓库 + 一份真实 worktree（复用 Workspace）。
  b) 用 fake AgentBackend（按预设 summary 回应，同 Spec-0040 闭环脚本手法）+ 打桩 github 模块
     （merge_pr/mergeability/check_status 等，避免依赖真实 GitHub），真实驱动一遍
     messages.Messages._evidence_gate 完整四步（① finalize_runbook ② run_executor ③ commit_evidence
     ④ review_evidence）。
  c) 断言①（PASS 路径）：fake backend 对 executor 与证据闸都回应「达成」→ 断言不触发 iterate、
     `git log <branch> -- docs/e2e-results/<pr>/result.md` 能查到证据 commit。
  d) 断言②（FAIL 路径）：fake backend 对证据闸回应 `VERDICT: FAIL` → 断言触发
     `iterate(reason="e2e")`、`merge_pr`（打桩）未被调用，但证据 commit 依然存在于 git 历史
     （durable，供人审计——FAIL 不等于「假装没跑过」）。
  e) 断言③（缺证据）：清空 evidence_dir 后调 review_evidence → 硬 FAIL（既有防线③，回归性断言）。
  f) 断言④（跨 PR 证据，T1 新增防线）：把另一个 PR 的 result.md 复制进本 PR 的 evidence_dir →
     review_evidence(pr_number=本PR) 硬 FAIL 且 feedback 含「不属于当前 PR」。
```

### T3：UI 形态边界文档化（`openagents/orchestrator.py` / `openagents/messages.py` / `README.md`）

纯文档/注释改动：`messages._evidence_gate` 与 `orchestrator.finalize_runbook`/`commit_evidence` 的
docstring 各补一句指向 T1 的行为保证；README.md 新增「e2e 形态支持现状」一节，人类读者（不进代码）也能
看到「cli/api/backend 已支持、ui 未支持、未支持时是确定性 FAIL 而非静默跳过」。

### DAG 与文件分配

```mermaid
graph TD
    T1[T1 证据闸判定收口：skipped(ui) + 跨PR归属]
    T2[T2 真实 git 闭环 fixture 脚本]
    T3[T3 UI 形态边界文档化]
    T1 --> T2
    T1 --> T3
```

| Task | 拥有文件（互斥） | depends-on |
|---|---|---|
| T1 | `openagents/evidence_gate.py`, `tests/test_evidence_gate.py` | — |
| T2 | `scripts/e2e-spec-0048-e2e-closed-loop-fixture.sh` | T1 |
| T3 | `openagents/orchestrator.py`, `openagents/messages.py`, `README.md` | T1 |

（T1 是唯一的行为改动，T2/T3 都依赖它才能分别断言/描述其新行为；T2、T3 文件互斥，可并行。）

### e2e 脚本路径

`scripts/e2e-spec-0048-e2e-closed-loop-fixture.sh`（T2 交付，被 PR 指路牌拾取）。

### 本组自身的 e2e 粗规划（吃自己的狗粮）

见 frontmatter `e2e` 块：形态 `cli`（本组交付物是后端 Python + shell 脚本，无前端可导航/截图，同
Spec-0040 的判断——形态跟着交付物走，而非跟着工具走）；意图与验收行为对应 T1/T2 的三条断言。
**自检工具后的取舍**：本会话已自检工具列表，**不具备** Playwright / Chrome DevTools 等浏览器 MCP
工具（`ToolSearch` 无匹配）；但即便具备，本组交付物（`evidence_gate.py` 正则解析 + shell fixture
脚本 + README/docstring 文档）本身也无前端可导航/截图/断言 console·network——`ui` 形态无处施展，
`cli` 是唯一适配交付物的选择，与工具是否可用无关。

## Drawbacks

- T1 在 `evidence_gate.review_evidence` 里新增两条基于文本格式的正则解析，`result.md` 的渲染格式
  （`executor._render_evidence`）从此变成一份 `evidence_gate.py` 隐式依赖的契约——若未来改 `executor`
  的渲染文案（比如把「结论：」改成别的措辞），必须同步改 T1 新增的解析正则，否则两处静默失配（退化为
  「匹配不到→照旧派 agent」，不是硬崩溃，但会悄悄失去新加的两道防线）。缓解：两个模块已经共享
  `RESULT_FILENAME` 字面量常量的先例（`executor.py:62` / `evidence_gate.py:31`，模块 docstring 明写
  「二者不互相 import，各持字面量」），本组延续同一约定，风险与既有设计一致，非新增风险类型。
- T2 的真实 git fixture 比 T1 之前「全内存 mock」的测试运行更慢（多几秒 `git init`/`commit`/`push` 到
  本地 bare 仓库的开销），且不接入 CI（与仓库里其它 `scripts/e2e-spec-*.sh` 现状一致，只在离线段的
  `pytest` 部分被 CI 覆盖，闭环演练段是人工审阅/dogfood 用）。
- T3 的 README 声明需要人工保持与代码行为同步——Phase 2 真加上 `ui` 支持后，如果忘记回来改这一节，会
  从「诚实的边界声明」退化成新的「名不副实」（issue #123 本来就是在批评这种退化）。

## Rationale and alternatives

**为什么只修补不重设计。** Spec-0040 的骨架（说明书驱动 + 独立执行 + 证据评审门控）已经通过 RFC 评审、
实现、合并，且逐行核对后确认主链路（触发点、runbook 定稿、真跑、证据 commit、门控合并）是真实接通的
——issue #123 提出时对照的是更早的 PR 状态。本组遵循奥卡姆剃刀（理念 1）：只修「逐行核对后找到的、真实
存在的」三处缝隙，不因为 issue 标题说「完整实现闭环」就去重新发明骨架。

**T1 备选：让 `executor` 直接把 `ExecutorResult` 结构化传给 `evidence_gate`（改函数签名加 `outcome`
参数），而非在 `evidence_gate` 内部反解析 `result.md` 文本。** 更「类型安全」，但会破坏 Spec-0040 刻意
维持的「executor 与证据闸不互相 import、只共享文件系统」解耦（理念 10，`evidence_gate.py:12-14` 明
写），且 `orchestrator.finalize_runbook` 目前只往 `messages` 透传路径（`RunbookHandle`），不透传
`ExecutorResult` 对象——要传就要改 `RunbookHandle`/`_evidence_gate` 的调用链，波及面从「一个文件内新增
两个正则」放大到「三个模块的接口都要改」。否决：解析 `result.md` 现成的稳定文本格式（本就是给人和
agent 读的证据文件），零接口变更，最小化，且与 T1 描述的「防线③」（证据缺失硬判 FAIL）本就是同一种
「先结构化短路、再考虑派 agent」的既有风格，一致性更好。

**T2 备选：像 spec-0039 一样用真实 `gh` + scratch GitHub 仓库做 LIVE fixture。** 更贴近生产环境，但引入
网络依赖与 `gh auth` 前置条件——无网络/未登录环境会整体降级到离线段，失去「本组新增部分」的确定性覆盖；
而本组要证明的是「evidence 是否真的落进 git 历史 + evidence_gate 是否读到最新证据」，这两件事只需要真实
的 `git commit`/`git log`，不需要真实的 GitHub API（GitHub 集成层面的正确性已经被 `github.py` / `gh` 相关
的既有单测与 spec-0039 的 LIVE 路径覆盖，不是本组的空白）。否决真实 `gh` 路径，选本地 `git init --bare`：
更小、更快、不新增外部依赖，仍然是「真实 git 副作用」而非内存 mock。

**T1 的「跨 PR 归属」备选：不加文本解析校验，而是让 `orchestrator` 保证永远不会把错的 `evidence_dir`
传给 `evidence_gate`（信任调用方而非被调用方自我校验）。** 当前生产路径下确实如此（`_evidence_gate`
每轮按顺序重新生成证据），但 `evidence_gate.py` 模块被设计成可独立复用（不 import
executor/orchestrator）——只信任调用方等于把「防线」画在了模块边界之外，任何新消费方都得自己重新记得
这条不变量。否决「信任调用方」，选择在 `evidence_gate` 自身加一道防线，让「不属于当前 PR 的证据不会被
误用」成为模块自身的保证，而不是调用约定的君子协定（与 issue #71 运行期 owner 检查的思路同构：把软
约定硬化）。

**是否要加时间维度的「证据过旧」校验（而非只做归属校验）：评估后本组不做。** 当前调用顺序（同一轮内
`finalize_runbook`→`executor`→`commit_evidence`→`review_evidence` 顺序执行、`_write_evidence` 每次都
覆写 `result.md`）已经结构性保证「不会读到本轮之前的旧证据」——不存在一个当前代码路径会触发「证据过
旧」这个风险。为一个不存在的风险构建时间戳/commit-sha 比对机制违反奥卡姆剃刀（理念 1）。若未来
`evidence_gate` 出现脱离 `_evidence_gate` 独立调用的新消费方，再按需补——记入 Unresolved questions。

## Prior art

- **Spec-0040**（`docs/specs/0040-e2e-runbook-driven-evidence-gate.md`，issue #104，PR #105）：本组直接
  前身，骨架来源；本组把其中「证据闸判定」「真实性验证」两处已知不足补上，关键机制已在 Motivation 就地
  复述（非裸引用）。
- `scripts/e2e-spec-0039-vigil-claim-dedup.sh`（`:8-32`）的 LIVE/OFFLINE 双路径 + 脚本内显式声明当前跑
  哪条路径的约定：T2 直接复用同一约定，不新造范式。
- `evidence_gate.py:33-36` 已有的「证据缺失即 FAIL」（tautology guard 防线③）与 `reviewer.py` 的「疑罪
  从严」（无法解析裁决即 FAIL）：T1 新增的两条判定与它们是同一种设计哲学——**能结构化短路判定的地方，
  不要委托给一次不确定的 LLM 调用**。

## Unresolved questions

- **executor 产出的 `*.log`/截图是否要强制结构化。** issue #123 第 2 条期望 `docs/e2e-results/<pr>/`
  下稳定产出 `*.log`；当前 `_EXECUTOR_TASK`（`executor.py:66-77`）只是提示 agent「把每一步的命令、观察、
  输出写进证据目录」，是否真的写出独立 `*.log` 文件是 agent best-effort、无文件命名或数量的机器校验
  （`result.md` 是唯一被 `_write_evidence` 保证一定产出的硬证据）。本组认为这是比「判定含糊」「零真实
  验证」更小的问题（`result.md` 已经是证据闸判定的唯一依据、且必然存在），先不纳入本组范围，留给用户
  拍板是否值得单独立项。
- **T2 的本地 git fixture 是否要接入 CI 默认执行。** 现状是仓库里全部 `scripts/e2e-spec-*.sh` 都不在
  `.github/workflows/ci.yml` 里默认跑（只有其内部的离线段 `pytest` 部分被 CI 覆盖，闭环演练段是人工
  审阅/dogfood 用）。T2 遵循这个现状，不默认接入 CI——如果用户希望改变这个仓库级惯例，应该是一个独立
  决策，不在本组范围内顺带做。
- **时间维度的证据陈旧校验**：见 Rationale「是否要加时间维度…评估后本组不做」，记录为待重新评估项——
  若未来出现 `evidence_gate` 被 `_evidence_gate` 之外的路径独立调用，需要回来补。

## Future possibilities

- Phase 2 给 `ui` 形态接浏览器 MCP（Playwright / Chrome DevTools，Spec-0040 Future possibilities 原定
  方向）落地后，T1 新增的「`outcome=skipped` → 硬 FAIL」分支需要替换成真正派浏览器 executor 的路径，
  T3 的 README 声明需要同步更新为「ui 已支持」。
- executor 证据产物结构化（强制 `*.log`/截图命名约定 + schema 校验，呼应 Unresolved 第一条）：把「证据
  是否完整」从「agent 自觉写」搬到「机器可判」，与本组 T1「从含糊 LLM 判断搬到结构化短路判断」是同一
  哲学的延伸。
- 若 `evidence_gate` 未来被多个消费方（如人工重放/审计工具）独立调用，再补时间维度的证据陈旧校验
  （呼应 Unresolved 第三条 + Rationale 里的取舍）。
