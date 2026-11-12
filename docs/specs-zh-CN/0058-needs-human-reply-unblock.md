---
number: "0058"
title: needs-human 死锁自愈：人类回复越水位线即撤 label 复位续跑
issue: 163
slug: needs-human-reply-unblock
e2e:
  intent: 证明 needs-human 不再是单向死锁——挂起的 subject 收到一条越过水位线的无签名人类评论后，一轮守夜内 label 被撤、subject 从 TERMINAL 复位为可推进态并能走到后续闸；而只有我方签名评论时保持 TERMINAL（防自触发）。
  method: |
    形态：纯后端编排（form=cli），无 product-facing 前端可导航；自检工具列表无 Playwright / Chrome DevTools
    MCP，故不设浏览器 e2e，改用离线确定性测法（不触真实 LLM）：
    1. 打桩 github：一个挂 needs-human 的 PR + 评论流最后一条为**无签名**人类评论（越过 park 签名理由评论的
       水位线）；反复 run_vigil(once=True) 单 tick 驱动 → 断言该 tick 内调了 remove_label 撤 needs-human，
       且 _classify 对复位后的现态判非 TERMINAL（落 reply/后续流水线支，能走到后续闸）。
    2. 对照：另一 PR 挂 needs-human 但最新评论为我方签名 → 断言不调 remove_label、保持 TERMINAL。
    3. 跑 scripts/e2e-spec-0058-needs-human-reply-unblock.sh 离线段全绿：ruff check + ruff format --check +
       pytest -q 全套通过。
summary: '修 needs-human 单向死锁：图驱动守夜（Spec-0065）里 `_classify` 分支① `needs-human ∈ labels → TERMINAL → 轮询停止`，撤销的唯一路径是人**手摘 label**；人在被挂 PR 上回复评论无效——因为①短路在②（最新评论是人发的 → reply）之前。这违背决策5（agent 先 comment、人审核后流程续跑）与 park 卡点评论对用户的承诺（「说清楚后 谓词自动活过来」），与 #140（卡住无自愈）同类。修法：在生产者单 subject 判定 `_consider`（vigil.py）里、 `_sense` 之后 `_classify` 之前插一段**解挂预处理**——当 subject 挂着 `needs-human` 且**最新评论不是我方 签名**（= 有人在 park 理由评论之后说了话，越过水位线）时，撤掉 `needs-human` label 并把它从本 tick 已感知 的 facts 里剥掉，使 `_classify` 当轮即从头重判（②reply → ③…⑪ 合并流水线保守重进一遍）。水位线在新模型里 不再是 state 里的 `block_watermark` 字段，而是「最新一条评论是不是我方签名」这个 `_sense` 已算出的活事实 （park 理由评论必签名、且恒为 park 时最后一条，故任何更新的**无签名**人类评论都天然越过它）；防自触发靠 `latest_comment_is_ours` 的签名判定，机器自己的签名评论永不解挂。承 Spec-0032（#89）在旧 flat 栈实现、 于 Spec-0062/0064 收敛迁移时丢失的解挂闭环，在图驱动栈里以「撤 label」这一单一原语重建。'
tasks:
  - id: T1
    title: 生产者解挂预处理：needs-human + 最新评论非我方签名 → 撤 label + 剥 facts，本 tick 从头重判续跑
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
    scope: 在 `_consider`（openagents/recipes/vigil.py:1472）的 `_sense` 之后、`_classify` 之前新增解挂预处理 `_unblock_if_replied`：当 `_LABEL_NEEDS_HUMAN in facts.labels` 且 `not facts.latest_comment_is_ours`（有人在 park 签名理由评论之后越水位线说话）时，按 subject 类型调 `github.remove_label`（PR）/ `github.issue_remove_label`（issue）撤掉 needs-human，并用 `dataclasses.replace` 把该 label 从本 tick 已感知的 facts 里剥掉，使当轮 `_classify` 即在「已无 needs-human」现态上从头重判（②reply→③…⑪ 合并流水线保守重进）。撤 label 是唯一状态复位（不写 state 字段）；`_log` 记录据哪条解挂。`_classify` 保持纯函数不动（解挂是副作用，只在生产者侧、`_classify` 之外，与护栏一 attempt 戳同构）。防自触发天然内建于 `latest_comment_is_ours` 的签名判定。# Spec-0058/T1。
    acceptance: pytest tests/test_recipe_vigil.py 通过。断言：(a) needs-human + 最新评论为无签名人类评论 → `_unblock_if_replied` 调 remove_label/issue_remove_label 撤 needs-human，返回的 facts.labels 不含 needs-human，随后 `_classify` 判非 TERMINAL（落 ACTIONABLE:reply 或后续流水线支）；(b) needs-human + 最新评论为我方签名 → 不撤 label、facts 原样、`_classify` 仍 TERMINAL（防自触发 + 幂等：park 后无人回复不解挂）；(c) 未挂 needs-human → 预处理原样透传；(d) PR subject 走 remove_label、issue subject 走 issue_remove_label；(e) 撤 label 后同 tick `_classify` 能走到②/后续闸（复位为可推进态）。ruff check + ruff format --check 干净。
  - id: T2
    title: 解挂路径测试 + 修正旧「needs-human 恒 TERMINAL」断言 + 离线 e2e 脚本
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tests/test_recipe_vigil.py
      - scripts/e2e-spec-0058-needs-human-reply-unblock.sh
    scope: 在 tests/test_recipe_vigil.py 新增解挂路径测试（覆盖 T1 acceptance 的 a–e）；定位并修正/替换现有把「needs-human 投影后恒 TERMINAL / 恒 blocked」钉死的断言（issue 指 test_recipe_vigil.py:450-455 的旧栈等价物；在图驱动栈里即断言 needs-human subject 经 `_consider` 后仍 TERMINAL 的用例），改为反映「越水位线人类回复 → 解挂 → 可推进」的新路径（保留「park 后无人回复 / 仅我方签名评论 → 仍 TERMINAL」作为对照，防回归写反）。新增离线 e2e 脚本 scripts/e2e-spec-0058-needs-human-reply-unblock.sh：反复 `run_vigil(once=True)` 单 tick 驱动，喂一个挂 needs-human 的 PR + 一条越水位线无签名人类评论，断言一轮内 label 被撤、subject 复位为可推进态（advance 能走到后续闸）；再喂只有我方签名评论的对照 PR，断言不解挂。脚本离线段跑 ruff check + ruff format --check + pytest -q 全绿。# Spec-0058/T2。
    acceptance: pytest tests/test_recipe_vigil.py 全绿且含至少一条断言「run=needs-human + 一条越水位线无签名人类评论 → 下一轮 status 变可推进态且能走到后续闸」、一条「机器自己的签名评论不触发解挂」、一条修正后的「park 后无人回复仍 TERMINAL」对照。bash scripts/e2e-spec-0058-needs-human-reply-unblock.sh 退出码 0（离线确定性，不触真实 LLM / 无浏览器）。
---

# 0058 · needs-human 死锁自愈：人类回复越水位线即撤 label 复位续跑

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给图驱动守夜补上「人类回复 → 自动撤 `needs-human` → 谓词复活续跑」的闭环，消除 `needs-human` 单向死锁。
当一个挂着 `needs-human` 的 subject 上出现**越过水位线的、无我方签名的人类新评论**时，下一轮（乃至当轮）守夜
撤掉该 label、把 subject 从 TERMINAL 复位为可推进态，随后合并流水线（conflict→CI→e2e→review→merge）正常推进。
实现只碰一个生产文件 `openagents/recipes/vigil.py`（新增一段解挂预处理）+ 一个测试文件，复用现有
`github.remove_label` / `github.issue_remove_label` 与 `_sense` 已算出的 `latest_comment_is_ours` 签名事实，
不新增 state 字段、不新增模块（理念 1 奥卡姆）。

## Motivation

**现状（Spec-0065 图驱动栈）。** 守夜的推进由纯函数 `_classify`（`openagents/recipes/vigil.py:686`）的一张
机械分支表决定，第一支就是终态判定：

```python
# vigil.py:734-737
if in_flight:
    return _Verdict(kind=_IN_FLIGHT)
if facts.merged or facts.closed or _LABEL_NEEDS_HUMAN in facts.labels:
    return _Verdict(kind=_TERMINAL)          # ← 分支①：needs-human 一挂即终态
if not facts.latest_comment_is_ours:
    return _Verdict(kind=_ACTIONABLE, action=_ACT_REPLY)   # ← 分支②：人有新话
```

`_TERMINAL` 在生产者 `_consider`（`vigil.py:1504`）里直接 `return 0`——不入队、不叫任何 agent、轮询对这个
subject 彻底空转。`needs-human` 是 agent 的**一等出口**（`_classify` docstring `vigil.py:706` 明写：agent 判断
「我没辙 / 这要人来定」就自己打 label + 留理由，当场 TERMINAL、停轮询、零多余 LLM 调用），设计上这很对——
但它**唯一的撤销路径是人手摘 label**。`_park_needs_human`（`vigil.py:2886`）的理由评论甚至在教人「说清楚后
摘掉 label」，其 docstring（`vigil.py:2892`）也只设想「人照做（**只摘 label、不评论**）之后谓词重新活过来」。

**缺口。** 决策5（CLAUDE.md 设计理念）要的是「agent 先 comment、**人审核后流程续跑**」；park 卡点评论对
用户做出的承诺是「回复一条 / 说清楚后自动续跑」。可代码从未兑现这条：

- 分支①（needs-human→TERMINAL）**短路在**分支②（人有新话→reply）**之前**。人在被挂 PR 上回复一条评论、
  却没手摘 label 时，①仍判 TERMINAL，subject 一动不动——**人回复救不回**。
- 于是 `needs-human` 沦为**单向死状态**：进得去（agent 主动打 / 看门狗兜底打），出不来（除非人手工操作 label
  或手改状态）。任何升级到 needs-human 的 PR/issue 都是**永久死锁**，与 memory 记录的 #140（git-in-harness
  责任真空、卡住无自愈）同类：升级 = 终点，缺「人给指导 → 自动续跑」的闭环。

**旧栈曾有、收敛时丢了。** Spec-0032（issue #89，`e2e-spec-0032-needs-human-comment-unblock.sh`）在旧 flat
栈里实现过「人类评论越过挂起水位线即解挂」的读侧（`identity.new_human_comments`，`utils/identity.py:94`，
docstring 至今写着「created_at 严格大于 `since`（挂起水位线 block_watermark）……服务 blocked 解挂」）。该读侧
函数**至今仍在**，但在 Spec-0062（合并流水线迁新栈）/0064（recipes 6→3 收敛）/0065（vigil 原地重写为图驱动）
的连续迁移中，**触发解挂的那一步丢失、未重建**——读侧还在，写侧（撤销终态）没了。本 spec 只治这一条通用死锁，
在图驱动栈里以最小原语重建它，不动 agentic 准入面、不动 park / 看门狗 / attempt 戳三条护栏。

（触发场景来源 PR #162（Spec-0064，`block_gate=bad-ci-after-e2e`）已由 ruff `extend-exclude` 单独修掉；那是
**这一次**卡住的具体病因，本 spec 治的是「卡住之后再也出不来」这个通用机制，两者正交。）

## Guide-level explanation

一句话：**「人在被挂 subject 上说了话」本身就是解挂信号**，守夜看到就撤 `needs-human`、让谓词自然复活。

站在用户视角，修好后的闭环是：

1. 某 PR 被挂 `needs-human`（agent 主动打或看门狗兜底打），park 留下一条**签名**的理由评论说明卡点。
2. 人读完，在该 PR 上**回复一条评论**（给指导 / 说「继续」/ 修正需求），**不必再去手摘 label**。
3. 下一轮守夜（`_consider` 逐 subject 判定时）发现：这个 subject 挂着 `needs-human`，**而最新一条评论不是我方
   签名的**——说明有人在 park 之后说了话。守夜据此判定为「解挂信号」：撤掉 `needs-human` label，把它从本 tick
   已读到的现态里剥掉。
4. 同一轮里 `_classify` 立刻在「已无 needs-human」的现态上重判：分支②（人有新话）→ replier 回应人的评论并推进
   游标；回应后最新评论变回我方签名 → 后续轮次落到合并流水线（③依赖 → ⑤⑥冲突 → ⑦⑧CI → ⑨e2e → ⑩⑪review/
   merge），**保守地从头把 PR 重验一遍**再合并。

**水位线在图驱动模型里是一个活事实，不是一个存储字段。** 旧栈把「什么时候挂起的」存进 `state.block_watermark`，
再用 `new_human_comments(since=block_watermark)` 比对。新栈的哲学是「GitHub = 领域真相」（Spec-0065）：park 的
理由评论**必签名**（`_park_needs_human` docstring `vigil.py:2894` 把签名纪律钉死，正是为了不把自己的话当成人说
的），且它是 park 那一刻的**最后一条**评论。于是「最新一条评论是不是我方签名」（`_sense` 已算出的
`latest_comment_is_ours`，`vigil.py:391/645`）**恰好等价于**「park 之后有没有人越过水位线说话」——无需另存
watermark，无需第二次读。**防自触发**天然内建：`latest_comment_is_ours` 靠签名判定（`_latest_is_ours` →
`identity.parse_agent_id`），机器自己后来盖的任何签名评论都把 `latest_comment_is_ours` 顶回 True，解挂不会
自触发（这也让重建后的解挂步骤幂等：撤一次 label 后再无更新的无签名评论，下一 tick 不再重撤）。

## Reference-level explanation

**改动落点：生产者单 subject 判定 `_consider`（`openagents/recipes/vigil.py:1472`）。** 它已经是「从
`_producer_tick` 里切出来只为让四值分流可单测、且错误隔离的 try 边界正好包住一个 subject」的函数，解挂预处理
放这里，天然获得单测性 + 单 subject 错误隔离。

新增一个纯度可控的解挂步骤（拟名 `_unblock_if_replied`），在 `_sense` 之后、`_classify` 之前调用：

```text
def _consider(...):
    observed = _sense(config=config, subject=subject)
    observed = _unblock_if_replied(observed=observed, subject=subject, agent_id=agent_id)  # ← 新增
    verdict  = _classify(facts=observed.facts, in_flight=subject in in_flight)
    ...

def _unblock_if_replied(*, observed, subject, agent_id) -> _Observed:
    facts = observed.facts
    if _LABEL_NEEDS_HUMAN not in facts.labels:
        return observed                      # 没挂起 → 原样返回
    if facts.latest_comment_is_ours:
        return observed                      # 最新是我方签名（含刚 park 的理由）→ 无人越水位线 → 不解挂
    # 有人在 park 理由评论之后说了话（越过水位线）→ 撤 needs-human，本 tick 即从头重判
    _remove_needs_human(subject=subject)     # PR 走 github.remove_label / issue 走 issue_remove_label
    _log(message=f"⟳ {subject}：人类越水位线回复，撤 {_LABEL_NEEDS_HUMAN}，复位续跑")
    return replace(observed, facts=replace(facts, labels=facts.labels - {_LABEL_NEEDS_HUMAN}))
```

**为什么是「预处理 + 剥 facts」而不是塞进 `_classify`。** `_classify` 必须保持**纯函数**（它被 worker 的
`_reconcile` 无成本反复调用；护栏一的 attempt 戳预处理也是**在 `_classify` 之外**由生产者包一层，同一理由，
见 `vigil.py:1507`）。撤 label 是有副作用的 IO，只能在生产者侧做。撤完用 `dataclasses.replace` 把 label 从
**本 tick 已读到的 facts** 里剥掉，`_classify` 当轮就在「已无 needs-human」的现态上走②reply（同 tick 续跑，
满足验收「守夜一轮内自动续跑」），无需第二次 `_sense`。（备选见 Rationale。）

**为什么撤 label 就够、不需要复位任何 state 字段。** 新栈里 `needs-human` **label 本身**就是终态的单一真源
（`_classify` 分支①只读 `facts.labels`，不读 state.status）。撤掉 label = 复位。人机对话记录留在 GitHub 评论流
（②reply 的签名回帖 + 人自己的评论）+ `_log` 行记录「据哪条解挂」，即 issue 要的 `unblock_detail` 审计信息的
落处——GitHub 是领域真相，不再往 state 里造第二份。

**保守重进而非断点续跑。** 撤 label 后不记 `block_gate` 断点、不信任旧证据，让谓词从分支②起把整条流水线
（conflict→CI→e2e→review→merge）**重验一遍**（issue「修复建议」的决策点推荐前者：确定性、无需信任旧证据）。
这是零额外代码的自然结果——`_classify` 分支表本就是从头判的。

**依赖的既有能力（全部已存在，实现期零新增读写原语）：**
- `github.remove_label(pr_number, name)`（`utils/github.py:505`）/ `github.issue_remove_label(number, name)`
  （`utils/github.py:535`）——撤 label 的两个原语（subject 是 PR 还是 issue 由 `_split_subject` 分流）。
- `_sense` 已算出的 `facts.latest_comment_is_ours`（`vigil.py:391`，经 `_latest_is_ours` →
  `identity.parse_agent_id` 签名判定）——水位线 + 防自触发一体。
- `_LABEL_NEEDS_HUMAN`（`vigil.py:221` = `github.BLOCKED_LABEL`）——终态 label 单一来源。

### DAG + 文件分配

| Task | 说明 | depends-on | files（两两不相交） |
| --- | --- | --- | --- |
| T1 | `_consider` 里新增解挂预处理 `_unblock_if_replied`：needs-human + 最新评论非我方签名 → 撤 label + 剥 facts，使本 tick `_classify` 从头重判续跑 | — | `openagents/recipes/vigil.py` |
| T2 | 解挂路径测试 + 修正旧「needs-human 恒 TERMINAL」断言 + 离线 e2e 脚本 | T1 | `tests/test_recipe_vigil.py`、`scripts/e2e-spec-0058-needs-human-reply-unblock.sh` |

T1、T2 文件集不相交（生产 vs 测试/脚本），协同模式无写冲突。

### e2e 脚本路径

`scripts/e2e-spec-0058-needs-human-reply-unblock.sh`（离线确定性；form=cli，无 product-facing 前端）。

## Drawbacks

- **水位线粒度变粗。** 用「最新评论非我方签名」替代「created_at > block_watermark」的精确比对：只要 park 之后
  最后一条评论是人发的就解挂，不区分「这条评论是不是针对本次卡点」。代价可接受——park 后正常无人会发无关评论；
  且解挂只是让流水线**重验一遍**（可逆、无副作用地重跑各闸），误解挂的最坏结果是白跑一轮闸门，远小于永久死锁。
- **agent 也能"回话"顶掉终态？** 不能——解挂只认**无我方签名**的评论；机器自己的签名评论把 `latest_comment_is_ours`
  顶回 True。唯一风险是**第三方机器人**的无签名评论（CI bot、dependabot）误触解挂；缓解见 Unresolved。
- **多摸一次 GitHub 写（撤 label）。** 仅在真解挂时发生（罕见），且被 `_consider` 的单 subject try 隔离，失败
  不拖垮整轮生产。

## Rationale and alternatives

**选定方案：生产者预处理撤 label + 剥 facts，水位线取活事实 `latest_comment_is_ours`。** 最小改动面（一个生产
文件新增一段）、复用既有原语、不新增 state / 不新增模块、不碰 `_classify` 纯度、同 tick 续跑。

**备选 A：复活 `state.block_watermark` + `new_human_comments(since=watermark)`（照搬旧 flat 栈）。** 需要在 park
时写 watermark、解挂时比对——**造第二份真相**（GitHub 评论时间 vs state 字段），与 Spec-0065「决定打 label、
事实读原生、不复制」的哲学冲突，且多一处要对账的落盘状态。选活事实 `latest_comment_is_ours` 免去这份账。

**备选 B：把解挂并进分支②，即 `_classify` 里对 needs-human + 人有新话直接返回 ACTIONABLE:reply。** 破坏
`_classify` 纯函数契约（撤 label 是副作用），且 worker 的 `_reconcile` 也调 `_classify`，会让副作用散进 worker。
拒绝——预处理必须在生产者侧、`_classify` 之外（与护栏一 attempt 戳同构）。

**备选 C：解挂后不剥 facts，直接 `return`，等下一 tick 再判。** 也能工作，但慢一个 interval（60s），不满足验收
「守夜一轮内自动续跑」的即时性；剥 facts 让当轮即续跑，几乎零额外成本。

**备选 D：解挂后从 `block_gate` 记录的断点续跑（信任旧证据）。** issue 决策点已否决——确定性优先，保守从头
重进整条流水线，无需信任「挂起前那次证据现在还成立」。

## Prior art

- **Spec-0032 / issue #89**（`e2e-spec-0032-needs-human-comment-unblock.sh`）——旧 flat 栈的「人类评论越水位线即
  解挂」原始实现，定向复活了读侧 `identity.new_human_comments`。本 spec 是它在图驱动栈里的重建（读侧仍复用其
  签名过滤思想，只是水位线换成活事实、写侧换成撤 label）。
- **Spec-0031 / 0036**（unblock-agent-resolve / unblock-comment-read-and-reply）——旧栈解挂链路的相邻环。
- **Kubernetes level-triggered reconcile**（[k8s API conventions](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-api-machinery/controllers.md)）——
  Spec-0065 的守夜模型即照此：每 tick 从真相重算、不追边沿。解挂顺理成章表达为「现态里有人说话且仍挂 label →
  reconcile 到撤 label」，而非一个一次性事件回调。
- **memory：#140 git-in-harness 责任真空**——同类「卡住无自愈」，本 spec 是 needs-human 侧的自愈补齐。

## Unresolved questions

- **第三方无签名机器人评论是否该触发解挂？** 当前设计里 CI bot / dependabot 的无签名评论会被当成「人说话了」
  而误解挂。是否需把解挂读侧收窄到「仅 OWNER/MEMBER/COLLABORATOR 的评论」（如 admitter 认人那样，Spec-0065）？
  倾向：先不收窄（误解挂只是白跑一轮闸、可逆），留作 Future；若实测有 bot 噪声再加认人过滤。**待与用户确认。**
- **park 理由评论若被人删除**（评论流里再无我方签名的最后一条）会怎样？倾向：`latest_comment_is_ours` 读到人评论
  → 解挂，行为正确（人已介入）；无需特判。

## Future possibilities

- **认人过滤**：解挂读侧接 admitter 的 OWNER/MEMBER/COLLABORATOR 判定，彻底排除第三方 bot 噪声。
- **解挂原因入 review report**：把「据哪条评论、谁、何时解挂」结构化进统一 agent run report（Spec-0051），
  让前端成果面可见解挂事件，而不只在 `_log`。
- **看门狗兜底打的 needs-human 与 agent 主动打的**可加来源标记，解挂时对二者施以不同策略（如兜底挂的允许自动
  重试、主动挂的必须等人）。

