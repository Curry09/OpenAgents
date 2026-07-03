---
number: "0046"
title: 评审裁决按「实质内容」去重（同结论·理由不同照发）
issue: 116
slug: review-dedup-by-content
summary: '把 _post_review_decision 的去重从「同结论=重复」改成「同结论且同反馈才算重复」——多轮 REWORK 理由各异时中间轮裁决评论不再被吞、人盯 PR 能看清每轮卡点演变，同时保留 PR #61「33 条相同 PASS」的防刷屏去重。'
tasks:
  - id: T1
    title: reviewer.extract_decision_content：裁决内容纯解析器
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/reviewer.py
      - tests/test_reviewer.py
    scope: "在 reviewer.py 新增纯函数 extract_decision_content(*, body) -> DecisionContent|None 及 frozen dataclass DecisionContent{kind_line, verdict_line, feedback_norm}，与 render_decision 互为正逆：以稳定抬头 ## 评审闸裁决 为锚，取 - 类型：/ - 裁决：两行 + 「反馈摘要」三反引号块的规范化正文（逐行 strip、丢空行、\\n 连接；PASS 空反馈→''），对含署名尾巴的 comment.body 与纯 rendered 均稳；非裁决评论→None。无副作用、不依赖 github/identity、全关键字参数。"
    acceptance: 单测（test_reviewer，hermetic）断言：render_decision→extract 往返一致；含 identity 签名尾巴的 comment.body 仍正确抽出三段且 feedback_norm 排除签名；PASS 裁决 feedback_norm=='' ；两段仅缩进/空行不同的反馈规范化后相等；非裁决 markdown（无抬头）→None。
  - id: T2
    title: orchestrator._decision_already_posted：按结论+反馈内容去重
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: '改 orchestrator._decision_already_posted：去重身份从「抬头+类型+裁决」三行升级为 reviewer.extract_decision_content(body=rendered) 得到的 DecisionContent。筛同 kind 裁决评论、取最近一条比对——仅当 verdict_line 与 feedback_norm 均相同才判重复；结论同但反馈不同（issue #116 场景）→ 照发。沿用 Spec-0022/RFC-0018 的 best-effort fail-open：list_comments 或解析异常降级为照发。_post_review_decision 调用点与 _progress 文案微调，不改 reviewer/github/identity。'
    acceptance: '单测（test_orchestrator，monkeypatch github.list_comments/identity/reviewer，hermetic）断言：既有 code REWORK(理由A)后本轮 code REWORK(理由B≠A) 照发 post_signed_comment（issue #116 修复）；既有 PASS 且反馈相同→本轮同 PASS 跳过（PR #61 防刷屏保留）；同结论同反馈的 REWORK 跳过；PASS↔REWORK 翻转照发；rfc 与 code 互不抑制；list_comments 抛错时不抛出、降级照发且 ReviewDecision 不受影响。'
---

# 0046 · 评审裁决按「实质内容」去重（同结论·理由不同照发）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把评审裁决回贴 PR 时的去重粒度，从**「同结论（PASS / REWORK）= 重复」**收紧成**「同结论**且**同反馈内容 = 重复」**。当前 `orchestrator._decision_already_posted` 只按「抬头 + `- 类型：` + `- 裁决：`」三行判重，等于「只要上一条同 kind 裁决也是 REWORK，本轮 REWORK 就被判重复、跳过不发」——于是一个 PR 攒了多轮**理由各异**的 code REWORK 才挂 `needs-human` 时，人在评论区只看得到**第 1 轮**的裁决 + 最后的「🤖 卡住了」，中间每轮真正在改 / 新暴露的卡点全被吞。本 feature 让去重的匹配特征**额外纳入「反馈摘要」正文的规范化内容**：只有结论**与**反馈都相同才算重复（照旧防 PR #61「33 条相同 PASS」刷屏），结论同但理由不同则照发（人需要看到每轮演变）。改动落在一个 reviewer 纯解析器（格式归属方）+ orchestrator 去重策略两个 Task，`files` 互斥。

## Motivation

**根因复现（issue #116 / Drifting12345/LLMwiki4rolePlay PR #6，就地完整复述，不要求读者去翻别的 spec）。** OpenAgents 的评审闸每轮（每个 poll interval，只要 record 仍在 coding/rfc-review 阶段）重跑一次 reviewer，并经 `orchestrator._post_review_decision` 把裁决作为一条署名评论回贴 PR，用来恢复人对评审闸的可观测性（RFC-0018，理念 8）。发之前走 `_decision_already_posted` 去重（Spec-0022/T3），**避免同一裁决每轮重发刷屏**。

问题出在**去重粒度太粗**。`_decision_already_posted`（`openagents/orchestrator.py:561`）的做法是：从本轮 `reviewer.render_decision` 的输出里抽三行作为匹配特征——抬头行 `## 评审闸裁决`、类型行 `- 类型：{rfc/code}`、裁决行 `- 裁决：{✅ PASS / ❌ REWORK / ⚠️ 评审无效}`——再去 PR 上找**最近一条同 kind** 裁决评论，只要它含**同一裁决行**就判「重复」跳过。docstring 明写「**不逐字节比对**票数/反馈措辞」。而 `render_decision`（`openagents/reviewer.py:190`）渲染出的正文是：

```
## 评审闸裁决
- 类型：代码
- 裁决：❌ REWORK
- 票数：3 票中 0 票 PASS
- 票型：REWORK / REWORK / REWORK
- 反馈摘要：
```
（这里是聚合 feedback：ISSUES / 每条验证标准卡在哪）
```
```

去重只看「类型 + 裁决」两行 → **连续两轮都是 code REWORK 时，即使第二轮的 ISSUES / 理由跟第一轮完全不同，「反馈摘要」块被完全忽略**，被判「同结论 = 重复」而跳过不发。

**实例（PR #6，默认攒满 3 轮 code REWORK 才挂 needs-human，各轮理由各异）：** `13:18` 一条 code REWORK，理由 = 「EntityWithContent 继承不符 / 章-场 pattern 缺失 / `_validate_specs` CWD bug」；`13:34` 的挂起消息里又是一条 REWORK，理由**完全不同** = 「`_validate_specs:65` 崩溃 bug + 8 个 task 零实现」。中间那轮**独立裁决评论缺失**——因为它跟第 1 轮同为 REWORK，被去重吞掉。人只看到第 1 轮的理由，后续每轮真正在解决 / 新暴露的问题被静默吞掉，看不清卡点怎么演变。

**去重当初为什么存在（反向约束，别把它删掉）。** Spec-0022/T3 引入这层去重，是为了止住「PR 长期 open、裁决不变刷屏」——实例 PR #61 的 14 个冲突 spec 文件让代码闸每轮重判 PASS，刷出 **33 条一模一样的 `## 评审闸裁决 ✅ PASS`**。那个止血目标是对的，只是**粒度太粗**：它把「理由变了的 REWORK」也当成了「相同裁决」。

**所以要改的是粒度，不是有无。** 期望行为：每一轮评审（尤其 REWORK）只要**反馈 / 内容跟上一条同 kind 裁决不同**，就贴出独立裁决评论；只有结论**与**反馈都真·相同才去重。这样既让人盯 PR 能看清每轮卡点演变，又不退回 PR #61 的刷屏。

## Guide-level explanation

对使用者（盯 PR 的人），行为只增不减，且都在评论区可见：

| 场景 | 改前（按结论去重） | 改后（按内容去重） |
|------|------|------|
| 连续两轮 code REWORK，**理由不同** | 第 2 轮被判重复、**吞掉**（bug） | 第 2 轮**照发**独立裁决评论（理由变了 = 人要看到） |
| 连续多轮裁决 **PASS 且反馈相同**（PR #61） | 去重、只留 1 条 | **仍去重**、只留 1 条（防刷屏不回退） |
| 同 kind 上一条 REWORK → 本轮**同样理由**再 REWORK | 去重 | **仍去重**（真·相同，无新信息） |
| PASS ↔ REWORK 结论翻转 | 照发 | 照发（不变） |
| rfc 闸 与 code 闸 裁决 | 互不抑制（kind 隔离） | 互不抑制（不变） |

判重从「同结论」升级成「**同结论 且 同反馈**」：把「反馈摘要」块的**规范化正文**也纳入匹配特征，只有全部相同才算重复。无对外签名 / 命令 / 配置变化；去重仍是**尽力而为旁路**（查询或解析抖动一律 fail-open 降级为照发，宁可多一条也不漏发裁决）。

## Reference-level explanation

落到改动，分解为 2 个 Task（DAG：`T1 → T2`；`files` 互斥，各 Task 单一 writer）。核心是把「一条裁决评论的**去重身份**」从「结论」扩成「**结论 + 规范化反馈**」，并把提取这份身份的格式知识收在 reviewer（`render_decision` 的归属方，理念 10 解耦）。

**T1 — reviewer 暴露裁决内容的纯解析器（叶子，无依赖）。**
在 `openagents/reviewer.py` 新增一个纯函数（无副作用、不依赖 github/identity，与 `render_decision` 互为正逆）：

```python
@dataclass(frozen=True)
class DecisionContent:
    kind_line: str      # "- 类型：代码"
    verdict_line: str   # "- 裁决：❌ REWORK"
    feedback_norm: str  # 规范化后的反馈摘要正文；PASS / 无反馈时为 ""

def extract_decision_content(*, body: str) -> DecisionContent | None:
    """从一段可能含署名尾巴的评论 markdown 里，解析出裁决的去重身份。
    非裁决评论（无稳定抬头 `## 评审闸裁决`）→ None。"""
```

- **为什么放 reviewer**：`render_decision` 的输出格式（抬头 / `- 类型：` / `- 裁决：` / 三反引号包裹的「反馈摘要」块）是 reviewer 的领域知识；它的**逆向提取**也应由 reviewer 拥有，orchestrator 只消费 `DecisionContent`、不再自己 splitlines 抠 reviewer 文案（现状是 orchestrator 内联解析，反而隐式耦合了 reviewer 格式）。
- **能吃 rendered 也能吃评论正文**：`extract_decision_content` 对**纯 rendered**（本轮）和**含署名尾巴的 comment.body**（PR 上既有评论，`identity.post_signed_comment` 会在正文后追加签名）都要稳。实现上以稳定抬头 `## 评审闸裁决` 为锚，取「反馈摘要」块 = 「`- 反馈摘要：` 之后第一对 ``` 三反引号之间」的文本，故尾部签名天然被排除。
- **feedback_norm 规范化**：逐行 strip、丢空行、`\n` 连接（whitespace/换行不敏感的比较，避免措辞未变仅缩进/空行漂移就误判「不同」）；PASS（`decision.feedback == ""`，render 不产「反馈摘要」块）→ `feedback_norm == ""`。
- 全关键字参数（CLAUDE.md 禁位置参数）。

**T2 — orchestrator 去重按内容比对（依赖 T1）。**
改 `openagents/orchestrator.py` 的 `_decision_already_posted`（`561`），去重身份从「三行」升级为 `DecisionContent`：

1. 用 `reviewer.extract_decision_content(body=rendered)` 拿本轮身份 `cur`（拿不到就 fail-open 照发）。
2. `github.list_comments`（只读，已有）筛**同 kind** 裁决评论（`extract_decision_content` 解析成功且 `kind_line == cur.kind_line`）。
3. 无同 kind → 返回 `False`（照发）。
4. 取最近一条（`created_at` ISO 8601 字典序 `max`），解析出 `prev`。
5. **重复 iff `prev.verdict_line == cur.verdict_line` 且 `prev.feedback_norm == cur.feedback_norm`**——结论**与**反馈都相同才算重复；结论同但反馈不同（issue #116 场景）→ 返回 `False` 照发。
6. **fail-open 不变**（沿用 Spec-0022 决策、RFC-0018 决策 2）：`list_comments` 或任何解析异常 → `_post_review_decision` 既有 `try/except` 降级为照发，评审闸与下游不受影响。

`_post_review_decision`（`533`）的调用点、best-effort 语义、`_progress` 文案（可微调为「同结论**同反馈**裁决评论已存在，跳过重发」）保持不动。**不改** reviewer 的 `render_decision` 输出、不改 github/identity。

**依赖 DAG：** `T1 → T2`（T2 消费 T1 的 `extract_decision_content` / `DecisionContent`）。

**文件分配（同组互斥，单一 writer）：**

| Task | files | 依赖 |
|------|-------|------|
| T1 | `openagents/reviewer.py`, `tests/test_reviewer.py` | — |
| T2 | `openagents/orchestrator.py`, `tests/test_orchestrator.py` | T1 |

```mermaid
graph LR
  T1["T1 reviewer.extract_decision_content<br/>(格式归属方·纯解析器)"] --> T2["T2 orchestrator._decision_already_posted<br/>(按内容去重)"]
```

**端到端验证（理念 8·成果=评论区能看清每轮不同 REWORK）：** e2e 脚本 `scripts/e2e-spec-0046-review-dedup-by-content.sh`，三段、默认全程 hermetic（不触网 / 不调真实 LLM / 不碰真实 gh）：

1. **离线确定性验证（默认）** — `ruff check` + `ruff format --check` + `uv run --extra dev pytest -q`，覆盖 T1（解析器：rendered / 含签名 comment.body / PASS 空反馈 / 非裁决评论→None / 规范化对齐）与 T2（issue #116 两轮理由不同 REWORK 照发；PR #61 同 PASS 去重；同理由 REWORK 去重；PASS↔REWORK 翻转照发；kind 隔离；list_comments 抛错 fail-open 照发）。
2. **离线成果演练（默认，浏览器优先）** — 用**真实**的 `reviewer.render_decision` + `_decision_already_posted` 跑一段脚本内内存评论区场景：round1 code REWORK（理由 A）→ round2 code REWORK（理由 B ≠ A）→ round3/4 相同 PASS，捕获「哪几条真被发出来」，把发出的裁决评论按时间线拼成一份**模拟 PR 会话** 静态 HTML。**若具备浏览器 MCP（Playwright / chrome-devtools，由 agent 在脚本外驱动）**：`navigate` 打开该 HTML → `snapshot` + `take_screenshot` → 断言「理由 A」与「理由 B」两条 REWORK 裁决**都可见**、PASS 只出现 1 条、console/network 无报错（正是人盯 PR 该看到的成果）。**无浏览器 MCP 时降级**为对该 HTML 做文本断言（grep 理由 A ∧ 理由 B 各 1 次、PASS 仅 1 次），**不跳过成果验证**。
3. **真实冒烟（可选，`OPENAGENTS_E2E_REAL=1`）** — 提示如何在 scratch 仓库造一个连续两轮 code REWORK、理由各异的 PR，跑 vigil 观察 PR 评论区出现**两条**不同 REWORK 裁决评论（改前只有 1 条）。

> **关于「浏览器 e2e vs 后端特性」的自检**：本 feature 无产品自有前端，其「成果」落在 GitHub PR 评论区（外部页面，真实复现需 live 凭证 + 跑通整条 orchestrator 循环，不适合放进确定性 e2e 脚本）。故采用与 Spec-0043/T4 同款做法：把**真实产品输出**（去重后实际发出的裁决评论正文）渲染成静态 HTML，用浏览器 MCP 导航 + 截图 + 断言来验「人盯 PR 会看到每轮不同 REWORK」这一成果——既用上浏览器工具，又保持确定性、不依赖 live GitHub。

## Drawbacks

- 去重身份变长（结论 + 规范化反馈），比对成本略增（仍是 O(评论数) 的内存字符串比较，可忽略）。
- feedback_norm 规范化只做 whitespace 无关化；若 reviewer 未来在 feedback 里塞入每轮必变的易变量（如时间戳 / 随机 id），会让每轮都判「不同」而退回刷屏。当前 `render_decision` 的 feedback 无此类易变量（Spec-0041/T3 的 `_distill_feedback` 已剥掉 reviewer 内心独白/scratchpad），风险低；若日后引入需在 T1 规范化里剔除。
- 提取依赖 `render_decision` 的「反馈摘要 + 三反引号块」输出结构；该结构变了要同步改 T1 解析器。用 T1 单测把「render → extract 往返一致」钉死，可及时暴露漂移。

## Rationale and alternatives

- **按内容去重 vs 取消去重**：选按内容。取消去重会直接退回 PR #61 的 33 条相同 PASS 刷屏（issue 的反向约束）；按内容才同时满足「理由变了照发」和「真·相同不刷屏」。
- **纳入「反馈摘要」规范化正文 vs 逐字节比对整条 rendered**：选前者。整条 rendered 含「票数：N 票中 X 票 PASS」「票型：…」等**每轮可能微变**的字段，逐字节会因它们抖动而几乎永不判重复 → 退回刷屏。只比对「结论 + 规范化反馈」命中「同一裁决不重发」的真实意图。（是否额外纳入票型留作 Unresolved。）
- **解析器放 reviewer（T1）vs 内联在 orchestrator**：选放 reviewer。`render_decision` 的格式是 reviewer 的领域知识，其逆向提取应同处一模块（理念 10 解耦）；orchestrator 只拿 `DecisionContent` 比对，不再 splitlines 抠 reviewer 文案（现状内联解析反而隐式耦合格式）。代价是新增一个纯函数 + 一个小 dataclass（理念 1 可接受，换来可独立测试的清晰缝）。
- **规范化用「逐行 strip 后字符串比较」vs 对反馈做 hash**：二者等价，选直接字符串比较——可读、可在 `_progress`/单测里直接 diff 出「到底哪不一样」，无需为省几十字节引入 hash（理念 1）。
- **比「最近一条同 kind」vs 扫全历史去重**：选最近一条（沿用 Spec-0022/T3 现状）。目标是「不连续重发上一条相同裁决」；扫全历史会把「A→B→A」的第二个 A 也吞掉，反而丢失演变可见性。
- **去重失败默认照发（fail-open）vs 默认跳过**：默认照发，沿用 Spec-0022/RFC-0018 的 best-effort 旁路语义——宁可偶尔多一条，也不因查询/解析抖动漏发裁决、损害可观测性。

## Prior art

- 本仓 Spec-0022/T3 首次引入裁决回贴去重（按结论），止住 PR #61 的 33 条相同 PASS 刷屏；本组是其粒度修正（结论 → 结论+反馈），复用其 fail-open best-effort 骨架与 `_progress` 记账风格。
- 裁决回贴的 best-effort 旁路语义沿用 RFC-0018（裁决产生地即回贴地、任何 gh 故障不得阻断评审闸）。
- feedback 净化（剥内心独白/scratchpad，只作用于展示用 feedback）沿用 Spec-0041/T3 的 `_distill_feedback`——本组的规范化在其之上再做 whitespace 无关化，不重复其职责。
- 「把真实产品输出渲染成静态 HTML、用浏览器 MCP 导航截图断言成果」的 e2e 手法沿用 Spec-0043/T4（issue 冲突预检对齐评论的成果演练）。
- 「内容指纹去重而非精确匹配」是通用工程手法（如 email/通知系统按规范化正文哈希抑制重复），此处退化为 whitespace 无关的规范化字符串比较。

## Unresolved questions

- **去重身份是否纳入「票型」行**（`- 票型：REWORK / REWORK / PASS`）？当前设计只用「结论 + 反馈」。若两轮 REWORK 反馈恰好规范化后相同、但逐 reviewer 票型不同（如 3票→2票 REWORK），按现设计会判重复吞掉。倾向**不纳入**（票型变化通常伴随反馈变化，且票型每轮易抖动，纳入会偏向刷屏），待评审确认。

## Future possibilities

- 若未来 reviewer 给 feedback 引入结构化字段（如显式 ISSUES 列表 / 稳定 id），去重可从「规范化正文比较」升级为「按 ISSUES 集合的差异比较」，甚至在评论里高亮「本轮相较上一轮新增/消解了哪些卡点」。
- 可把「同一 PR 的裁决演变」聚合成一条 PR 级摘要（每轮 append 差异），进一步降低评论条数同时保留演变可见性（需权衡与「每轮独立评论」的取舍，当前 YAGNI）。

