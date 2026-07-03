# Spec-0048 成果演练：reviewer rubric 对照 PR #105 骨架冒充场景

> 本文件由 `scripts/e2e-spec-0048-anti-design-as-implementation-review.sh` 自动生成（成果测试，理念 8）。所有 review 任务文本均取自**真实产品代码** `openagents/reviewer._task_for(...)`，非人工誊抄。

## PR #105 复刻场景（骨架冒充完整实现）

PR #105 声称把 e2e 升级为一条新链路（spec 声明 e2e 意图 → implement 写代码 → finalize_runbook 定稿说明书 → executor agent 独立真跑 → 固化证据 → evidence_gate 门控 merge），并**确实**新增了 `executor.py`/`evidence_gate.py`、把证据闸插在 `review_code PASS` 后 `merge_pr` 前、补了一批模块级单测——**看起来像已实现**。但 diff/评论没有证明最关键的产品闭环：executor 是否被主流程**自动触发**？`result.md` 是否**自动产生并 commit**？evidence_gate 读的是真实证据还是假设证据？有没有正/反例 fixture？——即「架构骨架冒充完整实现」。

## 新 rubric 逐条覆盖每个缺口

| PR #105 场景缺口 | reviewer 对照追问锚点 | 挂在哪道闸 |
| --- | --- | --- |
| 只新增 openagents/executor.py 模块，但主流程无任何函数/状态分支走到它（无接线） | `主流程触发点` | code |
| executor 只被自己的模块级单测调用，不被既有编排链路调用（dead / unwired module） | `被调用证据` | code |
| 声称 executor 会自动产出 result.md 并 commit 回 PR，但 diff 里没有任何自动产出/提交证据 | `artifact 自动产生并 commit` | code |
| 没有正例证明 e2e PASS 放行、也没有反例证明 e2e FAIL 阻止 merge | `正例·反例` | code |
| 只测了 parser/render/decision 等局部函数，未覆盖真实集成路径 | `集成路径而非局部函数` | code |
| 缺任一闭环证据时应判 REWORK，理由固定话术 | `只实现骨架，未证明完整链路` | code |
| 设计闸前移把关：spec 承诺自动化链路却没把闭环讲清（触发时机/调用方/artifact 落点/失败路径/正·反例验收） | `自动化 spec 防过度承诺` | rfc |
| 声明诚信：宣称实现了自动化执行/门控能力却拿不出真实产物或集成证据 | `宣称实现了自动化执行/门控能力` | code |

结论：换成硬化后的 rubric，reviewer 拿到的对照清单**逐条命中** PR #105 骨架冒充场景的每个缺口，足以把这类 PR 导向 `VERDICT: REWORK`，理由「只实现骨架，未证明完整链路」——不再靠 reviewer 恰好较真才发现。

## 真实 code review 任务全文（reviewer._task_for(kind="code")）

```text
你是独立的代码审核员，与作者不共享上下文。请评审 PR #105 的代码改动。
用 `git diff` 查看本分支相对 base 的改动并读涉及文件的完整上下文。判定：是否真的实现了对应 spec 的 Task 与验收标准、有无 tautological test / 绕过真实路径、边界与安全盲点（空输入/错误路径/注入/越权）、破坏性改动（删了在用的东西、改接口未改调用方）。不纠结风格偏好（除非违反 CLAUDE.md 明文规范）。
【职责边界】你只判**静态**代码质量/安全/结构；**运行时行为（系统真跑起来是否达成意图）由证据闸负责，你不判**——不必也不应据「有没有真跑过」下裁决。
宣称验证过但无证据 → REWORK：仅当本 PR 正文/评论出现「端到端 / e2e / 截图 / 已验证 UI」类措辞（声称验证过某个产品对外行为）时才触发本检查——纯内部重构 PR（无此类措辞）不查、不误伤。触发时核对仓库里有没有对应的 tracked 证据（截图文件如 docs/evidence/** 下的图、或真实运行日志文本），且 PR 评论里有没有实跑留痕；若既无 tracked 证据、评论也无实跑留痕 → 判 REWORK，理由写明「宣称验证过但无证据」。自动化测试绿 / 后端日志替代不了真 app 证据。
延伸——宣称实现了自动化执行/门控能力（executor 真跑 / 自动提交证据 / evidence gate 门控 / UI 截图）却无真实产物或集成证据 → REWORK：把本检查从「宣称验证过某产品对外行为」延伸到「宣称实现了某条自动化执行链路却只交付骨架」，例如声称 executor 真跑系统却无 result.md、声称自动提交证据却无 commit 证据或 artifact、声称 evidence gate 门控却无 PASS/FAIL fixture、声称支持 UI 截图却无截图也无诚实说明——同样判 REWORK。
【自动化完整性硬规则】仅当本 PR 声称新增/改造了自动化执行链路（executor / agent / runtime validation、e2e / evidence gate / runbook、自动 merge · hold gate、GitHub issue · PR 自动化，或任何『自动跑 · 自动提交 · 自动门控』的能力）时才触发本检查——纯静态改动 / 库函数 / 重构 / 文档不查、不误伤。触发时逐条核对闭环，任一缺失即判 REWORK：
1. 主流程触发点：既有链路从哪个现有函数/状态分支真的会走到这个新能力？（『有个新模块』≠『主流程会走到它』）
2. 被调用证据：新 executor/agent 是否真的被调用，还是只定义了模块却没接线（dead / unwired）？
3. artifact 自动产生并 commit：声称生成的产物（result.md / log / screenshot / PR comment）是否会自动产生并 commit/发送，而不是『假设它存在』？
4. 正例·反例：有没有正例证明 PASS 放行、反例证明 FAIL 阻断？
5. 集成路径而非局部函数：测试是否覆盖真实集成路径，而不是只测 parser/render/decision 等局部函数？
缺完整链路证据 → REWORK，理由：只实现骨架，未证明完整链路。
你只读不写，禁止任何写操作（commit/push/改文件）。
疑罪从严：任一验证标准不确定是否满足 → 判 REWORK，把疑虑写进 ISSUES。
【硬性格式】你的回复第一行必须就是 `VERDICT: <token>`（token ∈ PASS/REWORK/RETHINK），在任何 REASON/ISSUES/论证之前。所有理由、证据、问题列表一律写在裁决行之后——这样即便回复被长度截断，丢的也是尾部论证而非裁决本身。
PASS 示例：
  VERDICT: PASS
  REASON: <一句话说明核对的关键验证标准>
REWORK 示例：
  VERDICT: REWORK
  ISSUES:
  - <文件:行号 + 具体问题>
  NEXT: <修复方向>

```
## 真实 rfc review 任务全文（reviewer._task_for(kind="rfc")）

```text
你是独立的 spec 审核员，与起草者不共享上下文。请评审 PR #105 的 spec 组。
按顺序读：CLAUDE.md（需求/设计理念）→ docs/specs/ 下本 PR 新增/改动的 spec 组（单文件 NNNN-slug.md：frontmatter 结构化源数据 + 正文各 Task 设计 prose）→ 其引用的来源。判定：设计是否对齐需求、关键决策是否有据、Task DAG 是否可独立实现且各 Task 文件清单互不重叠、是否含实现代码（spec 不应含实现代码）。
【e2e 粗规划硬规则】若本 PR 属前端/交互类改动（新增/改动用户可见行为、CLI 交互、HTTP 接口、前端页面等），其 spec 组必须在组级 frontmatter 声明 e2e 粗规划（e2e 块含 form/intent/acceptance，承载「要不要验、验什么」）；未声明 → 判 REWORK，把「缺 e2e 粗规划」写进 ISSUES。纯文档/重构/内部非交互改动可不声明。
【自动化 spec 防过度承诺】若本 spec 承诺新增自动化执行链路（executor / agent / runtime validation、e2e / evidence gate / runbook、自动 merge · hold gate、GitHub issue · PR 自动化，或任何『自动跑 · 自动提交 · 自动门控』的能力），其 Reference-level 必须声明 触发时机 / 调用方 / artifact 落点 / 失败路径 / 正·反例验收；否则这份 spec 只算设计草案，不应让对应实现 PR 仅凭这份 spec 过代码闸——判 REWORK，把「缺自动化闭环声明」写进 ISSUES。纯静态 / 重构 / 内部非自动化 spec 不查。
你只读不写，禁止任何写操作（commit/push/改文件）。
疑罪从严：任一验证标准不确定是否满足 → 判 REWORK，把疑虑写进 ISSUES。
【硬性格式】你的回复第一行必须就是 `VERDICT: <token>`（token ∈ PASS/REWORK/RETHINK），在任何 REASON/ISSUES/论证之前。所有理由、证据、问题列表一律写在裁决行之后——这样即便回复被长度截断，丢的也是尾部论证而非裁决本身。
PASS 示例：
  VERDICT: PASS
  REASON: <一句话说明核对的关键验证标准>
REWORK 示例：
  VERDICT: REWORK
  ISSUES:
  - <文件:行号 + 具体问题>
  NEXT: <修复方向>

```
