---
number: "0021"
title: 修复 reviewer 长回复截断在 VERDICT 之前→UNPARSED→假非PASS 空耗 rounds 误触 needs-human
issue: 63
slug: reviewer-truncated-verdict-fix
summary: 修 reviewer 长回复被截断在 VERDICT 行之前、导致解析失败（UNPARSED）被误判成「非 PASS」、白白空耗 vigil rounds 甚至误触 needs-human 的 bug。做法：裁决 token 前置、按首行解析、区分「评审本身无效」与「真 REWORK」、加单次重解析与诚实升级。只改 reviewer 解析与编排层容错，不改裁决标准本身。
tasks:
  - id: T1
    title: reviewer 侧:前置裁决 token + 首行解析 + 区分「评审无效」+ 单次重解析
    status: done
    priority: P0
    tags:
      - backend
      - reviewer
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/reviewer.py
      - tests/test_reviewer.py
    scope: 强化 _RUBRIC_TAIL 要求 VERDICT 置于回复最前面（任何论证之前）;_parse_verdict 首行/首段优先解析、无果再回退全文匹配;review() 对解析为 UNPARSED 的 reviewer 单次重跑 backend.run;ReviewDecision 新增布尔字段 actionable 区分「真 REWORK（解析出 REWORK/RETHINK 且有实质 ISSUES 正文）」与「评审无效（非 PASS 仅因裁决无法解析/无可操作条目）」;render_decision 把「评审无效」与「REWORK」分别渲染。仅关键字参数、private 函数显式传参。
    acceptance: 单测打桩 AgentBackend——截断好评（无 VERDICT 重跑仍无）→passed=False 且 actionable=False，verdicts 含 UNPARSED 占位且长度=N;带 ISSUES 真 REWORK→passed=False、actionable=True、feedback 含 ISSUES;首行 VERDICT:PASS + 正文裸 REWORK 字样→解析为 PASS;首跑 UNPARSED 重跑 PASS→backend.run 被调两次最终 passed=True，重跑仍 UNPARSED→只重跑一次落「评审无效」;全 PASS→passed=True、actionable=False、feedback="";render_decision 对「评审无效」与「REWORK」渲染不同文案;既有用例回归全绿;ruff check + ruff format --check + pytest 通过。
  - id: T2
    title: 编排层:评审无效不吃 round、空反馈不空转、独立重试上限后诚实升级
    status: done
    priority: P0
    tags:
      - backend
      - orchestration
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
      - openagents/state.py
      - tests/test_state.py
    scope: _process_rfc_review / _process_coding 在 not passed 时按 decision.actionable 分流——真 REWORK 照旧 rounds++ + refine_rfc/iterate（行为逐字节不变）;「评审无效」不 rounds++、不 refine/iterate，改用独立小重试计数（env OPENAGENTS_MAX_REVIEW_RETRIES，默认 2），未超则本轮返回 review-invalid 事件等下一轮重评，超过则以「reviewer 输出无法解析」真实理由走 _block 打 needs-human（gate 携带可区分标记）;State/RunRecord 新增独立于 rounds 的 review-invalid 计数字段（默认 0、向后兼容），配套 increment_review_invalid 并在既有 reset_rounds 同点归零。仅关键字参数、private 函数显式传参。
    acceptance: 单测 monkeypatch github.* + 注入打桩 ReviewDecision——截断好评（passed=False、actionable=False）在 spec/merge 两闸不调 increment_rounds、不调 refine_rfc/iterate，返回 reason="review-invalid";真 REWORK 照旧 increment_rounds + refine_rfc/iterate(detail=feedback);连续达 MAX_REVIEW_RETRIES 次评审无效→_block 打 needs-human 且 gate 标识可区分于真 REWORK 的 block;review-invalid 计数随 implement / reset_rounds 同点清零;env 缺省/非法/<1→回落默认 2;零回归——默认全 PASS→merge→done、真 REWORK→rounds++→iterate、攒满 MAX_ROUNDS→_block 既有用例全绿;ruff check + ruff format --check + pytest 通过。
---

# 0021 · 修复 reviewer 长回复截断在 VERDICT 之前→UNPARSED→假非PASS 空耗 rounds 误触 needs-human

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

修复一个 reviewer 长回复被截断在 `VERDICT` 行之前、被误判成「非 PASS」的 bug（issue #63，现象 PR #61 / issue #58）。reviewer 是「读 RFC/diff → 给裁决 token」的无状态函数,模型常把一大段论证写在前面、`VERDICT` 拖到末尾,长回复在 token 之前就被截断,`_parse_verdict` 找不到 token 返回 None、按「疑罪从严」归一化为 UNPARSED 并计为非 PASS——于是一篇**全是好评**的回复被当成 REWORK,下游编排层 `rounds++` 并喂回空反馈、空耗 vigil rounds,攒满 `MAX_ROUNDS=3` 后 `_block` 误打 `needs-human`。做法分两层:reviewer 侧把裁决 token 前置 + 首行优先解析 + 单次重解析,并在裁决结果里区分「评审本身无效」与「真 REWORK」;编排层据此分流,评审无效不吃 round、不空转迭代,用独立重试上限兜住、超限后以**真实**理由诚实升级。只改 reviewer 解析与编排层容错,**不改裁决标准本身**。

## Motivation

根因在 reviewer 与编排两侧的薄弱点(issue #63):

1. **裁决 token 容易被截断**:`_RUBRIC_TAIL` 虽写了「回复必须以 VERDICT 开头」,但模型实际把论证写在前面、VERDICT 拖到末尾,长回复在 token 之前就被截断(摘要都断在半句话)。
2. **解析失败被语义坍缩**:`_parse_verdict` 找不到 token 返回 None,`review()` 按「疑罪从严」归一化成 UNPARSED 并计为非 PASS——全是好评的回复被当成 REWORK。
3. **误触 needs-human 的发生地在编排层**(messages.py 的非 PASS 处理):非 PASS 一律 `rounds++` + `refine_rfc/iterate(decision.feedback)`。当 feedback 是没有缺陷条目的好评时,写代码 agent 无从下手、改了个寂寞,下一轮 reviewer 又被截断 → 永远收敛不到可解析 PASS → 攒满 `MAX_ROUNDS=3` → `_block` → 误打 `needs-human`(即便内容本可通过)。

**为什么要改**:这是一个真实的假阳——好评被当打回、人被无谓地拉进来。要同时根治两类误判:① 评审无效不该消耗「真 REWORK」的 rounds 预算;② 空/无可操作反馈不该驱动 refine/iterate 空转。修复链有源头(reviewer 能如实说出「这是无效评审,不是 REWORK」)和执行端(编排层据此决定是否吃 round、是否迭代、超限如何收口),二者缺一不可,故两个 Task 同列 P0。

## Guide-level explanation

把修复想成「三道防线 + 一处分流」:

- **防线一(别被截断)**:rubric 硬性要求**第一行必须是 `VERDICT: <token>`**,论证写在裁决之后——即便被长度截断,丢的是论证尾部而非裁决头部。
- **防线二(首行解析)**:`_parse_verdict` 先在首行/首段找 `VERDICT:` token,首段无果再回退全文匹配(向后兼容老格式)。首行命中即采信,避免正文里偶现的 "REWORK" 字样(如引用别人的评审)污染裁决。
- **防线三(单次重解析)**:对解析为 UNPARSED 的那个 reviewer 再跑一次 `backend.run`(仅一次)。截断是随机的,重跑有相当概率拿到可解析裁决。
- **分流(编排层)**:reviewer 把裁决分成三类——`passed`(全 PASS)、`actionable REWORK`(有带正文的 REWORK/RETHINK,有东西可改)、`评审无效`(非 PASS 仅因裁决无法解析/无可操作条目)。编排层照旧让真 REWORK 吃 round + 喂回反馈,让评审无效**不吃 round、不空转**,用一个独立小重试上限兜住,超限后以「reviewer 输出无法解析」这一真实理由打 needs-human。

对使用者:盯 PR 的人在评论里能一眼区分「⚠️ 评审无效(裁决无法解析,reviewer 输出疑被截断)」与「❌ REWORK」——看到的是「评审坏了,去看 reviewer/截断」,而非「代码被打回 3 轮」。

## Reference-level explanation

落到改动,分解为 2 个 Task(`files` 互斥,各 Task 单一 writer):

1. **T1 reviewer 侧**(无依赖,P0,修复链源头) — `openagents/reviewer.py` / `tests/test_reviewer.py`。三道防线全部落在 reviewer 内:
   - **前置裁决(rubric 强化)**:`_RUBRIC_TAIL` 的「以 VERDICT 开头」升级为硬性「第一行必须是 `VERDICT: <token>`,在任何 REASON/ISSUES/论证之前」(裁决与论证分离)。
   - **首行优先解析**:`_parse_verdict(*, summary) -> str | None` 解析顺序改为「首行/首段优先 → 全文 `_VERDICT_RE` / 裸 token 回退」,签名不变。
   - **单次重解析**:`review(*, backend, work_dir, kind, pr_number, n) -> ReviewDecision` 聚合时,对解析为 UNPARSED 的那个 reviewer 再跑一次 `backend.run`(仅一次);PASS/REWORK/RETHINK 不重跑。
   - **裁决三分类**:`ReviewDecision` 新增布尔字段(暂名 `actionable`,默认值保证既有构造点向后兼容)。判定 predicate:`actionable := (not passed) and ∃ verdict ∈ {REWORK, RETHINK} 且对应 summary.strip() 非空`;否则若 `not passed` 则为 invalid。passed/feedback/verdicts 三字段既有语义纯增量保持不变。
   - **render_decision(*, decision, kind) -> str**:对「评审无效」渲染区别于「REWORK」的文案,签名不变。
2. **T2 编排层**(依赖 T1,P0) — `openagents/messages.py` / `tests/test_messages.py` / `openagents/state.py` / `tests/test_state.py`。两道闸共用的 not-passed 分流(`_process_rfc_review` 的 RFC 评审闸 与 `_process_coding` 的代码评审闸,逻辑同构):
   ```
   if decision.passed:            # 不变（打标签/implement 或 merge）
       ...
   elif decision.actionable:      # 真 REWORK —— 行为逐字节不变
       rounds = increment_rounds(...)
       if rounds >= MAX_ROUNDS: _block(gate)
       else: refine_rfc/iterate(detail=decision.feedback)
   else:                          # 评审无效（裁决无法解析 / 无可操作反馈）
       invalid = increment_review_invalid(...)      # 独立计数，不碰 rounds
       if invalid >= MAX_REVIEW_RETRIES:
           _block(gate, reason="review-unparseable") # 诚实升级
       else:
           return {... "reason": "review-invalid"}   # 不动 rounds、不 refine，等下一轮重评
   ```
   关键不变量:评审无效**绝不** `rounds++`、**绝不** refine/iterate;真 REWORK 路径逐字节保留(既有用例即回归护栏)。新增 env 旋钮 `OPENAGENTS_MAX_REVIEW_RETRIES`(默认 2,缺省/非法/<1 回落默认),镜像 `_configured_max_rounds`。`State` 新增 `increment_review_invalid(*, issue_number) -> int`(镜像 `increment_rounds`),并在既有 `reset_rounds` 同点把该计数一并归零;`RunRecord` 新增对应字段(默认 0,向后兼容旧记录),计数独立于 `rounds` 但同生命周期(implement / 解挂时清零)。

**端到端验证**:本组改动属纯单元层(无新增独立 e2e 脚本),验证靠两套单测全绿——`tests/test_reviewer.py`(打桩 AgentBackend,覆盖截断好评 / 真 REWORK / 首行优先 / 单次重解析 / 全 PASS / render 文案)+ `tests/test_messages.py` + `tests/test_state.py`(monkeypatch github.* + 注入打桩 ReviewDecision,覆盖两闸分流 / 计数清零 / env 回落 / 零回归),并跑 `ruff check` + `ruff format --check` + `pytest`。

依赖 DAG:`T1 → T2`(T2 的输入契约是 T1 提供的 `ReviewDecision.actionable` 与「评审无效」语义)。

## Drawbacks

- `ReviewDecision` 多一个 `actionable` 字段、`State`/`RunRecord` 多一个 review-invalid 计数,概念上比「非 PASS 一律 rounds++」多一层分流。
- 极端持续截断下,评审无效达独立上限后仍会 `_block` 打 needs-human——没有做到「绝对永不 block」,而是用「真实理由 + 成本可控」换取了不冒充假 REWORK。

## Rationale and alternatives

- **裁决前置 vs 硬截断 backend 输出**(选前置):硬截 `AgentResult.summary` 到固定长度看似直接,但若 VERDICT 本在末尾反而**更易丢 token**,且要改动 reviewer 对 backend 输出的契约。把裁决顶到首行 + 首行解析,从根上让「被截断」不再波及裁决。
- **单次重解析 vs 不重试**(选单次):不重试最简,但单条截断好评仍会落「评审无效」、把压力全压给编排层兜底。一次重跑成本可控(N 默认 1)、能从概率上消解大部分随机截断;不做无限重试——那是编排层的独立重试上限,职责分层。
- **新增 actionable 字段 vs 复用 `feedback == ""`**(选显式字段):仅凭 feedback 是否为空会和「REWORK 但 reviewer 没写 ISSUES」混淆(那种 feedback 是占位文案、非空但不可操作)。显式布尔字段语义清晰、单测可断言,且让编排层不必重新解析 verdicts。
- **独立重试计数 vs 复用 MAX_ROUNDS 兜底**(选独立计数):复用 rounds 改动最小,但「评审无效也累加 rounds、攒满仍 _block」与 issue 期望「不吃 round」直接相悖,且继续混淆「reviewer 坏了」与「代码该打回」。独立计数让两类失败各有预算、各有诚实的升级理由。
- **达上限后 _block vs 永不 block(只重试)**(选 _block):永不 block 最贴近「绝不误判好评」,但极端持续截断会无限轮询、持续烧 backend。给评审无效一个独立小上限,达上限后以真实理由(reviewer 输出无法解析)升级给人,既兜住成本、又不冒充假 REWORK。
- **本轮返回事件等下一轮 vs 同轮立即重评**(选等下一轮):同轮立即重跑 review 会拉长单次 poll 墙钟,且 T1 已在 reviewer 内做过一次重解析(分层不重复);poll 是周期性的,等下一轮天然、简单,符合 messages「薄路由」定位。
- **不动裁决标准/CI/messages 内部主逻辑**,只在既有 not-passed 路径上「按 actionable 劈成两支」——把 blast radius 收到最小(解耦,理念 10)。

## Prior art

「裁决与论证分离、把机器可解析的结论顶到输出最前面」是 LLM-judge / 结构化输出的常见稳健化手法(避免长输出截断丢结论);「区分『判定器本身失效』与『判定为负』」也是评测系统区分 invalid 与 negative 的通行做法。本 feature 沿用 vigil-reviewer 既有的 PASS/REWORK/RETHINK 三裁决 rubric(RFC-0012)与 `UNPARSED_VERDICT`(RFC-0018),只在其上增加「评审无效」这一可观测分类,不引入新的裁决体系。

## Unresolved questions

- 「实质 ISSUES 正文」的阈值:目前按 `summary.strip()` 非空判可操作。若 reviewer 给了 `VERDICT: REWORK` 但正文极短/无 ISSUES 是否也归「评审无效」由人定;本组先采「有裁决 token 的 REWORK/RETHINK 即可操作」的保守口径,极端空 REWORK 留待实跑数据校准。
- `OPENAGENTS_MAX_REVIEW_RETRIES` 默认值(暂定 2)是否够:2 次重评在多数情况足以拿到可解析裁决;若实跑偏紧/偏松可调该 env 默认,先按 2 上线据 e2e 数据校准。
- 持续评审无效达上限后的收口选「_block 打 needs-human(reviewer 输出无法解析)」;若团队更希望「永不 block、只无限重评」,需接受极端持续截断下的 backend 成本——本组采前者(成本可控 + 诚实升级),此点留待人确认。

## Future possibilities

- 把「评审无效率 / 重解析命中率」纳入可观测指标,据真实截断分布动态调 `MAX_REVIEW_RETRIES` 默认与 rubric 措辞。
- 若后续 backend 支持更长输出或流式裁决,可进一步弱化重解析依赖。

