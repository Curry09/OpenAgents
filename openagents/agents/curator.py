"""# Spec-0065/T1: agents.curator —— 依赖排序：读 ready open issue 快照 + 已有依赖边（锚点）
→ 建议 blocked_by 边集（零逻辑）。

守夜的**准入面**里唯一需要「语义判断」的一步：哪个 issue 得等哪个先做完。这判断只有读得懂
issue 语义的 LLM 才排得准——纯机械的文件重叠分析只能捕「文件冲突序」，捕不到「逻辑序」（A 先
定义接口、B 才能用，两者可能根本不碰同一文件）。故下放 agent 出**结构化的边集**，recipes
（`vigil._intake`）拿边去经 GitHub 原生 dependencies API 落 `blocked_by`；本层零调度、零落边、
零 IO，只出判断（承 agents=零逻辑 Template、recipes=控制流的分层）。

**受锚增量，不整张覆盖。** 依赖边是 GitHub 上人机共写的可变真相（人可在 UI「Mark as blocked
by」、agent 走 REST），curator 不能整张重排——会抹掉人手设的边。故已有边（`$existing_edges`）**原样
带进 prompt 作锚点**：curator 只为**尚无入边的新节点**补建议边，既有边只读、不重排、不删。这样
一致性收敛成「一次生成 + 一次 validate + 只 POST 新边」，无中间态、不与人的改动打架。

**输出契约。** 末行一个 JSON 对象 `{"edges": [...]}`，`edges` 是**建议新增**的依赖边列表，每条
`{"issue": <被挡的 issue 号>, "blocked_by": [<挡它的 issue 号>...], "rationale": "<为何这个序>"}`。
`blocked_by` 为空列表表示该 issue 独立、无入边。判定纪律沿用 fail-open：拿不准是否有依赖就**不排边**
（宁可少并行一点，也不要凭空造出假依赖冻住流转）——图错顶多让调度少并行，正确性由执行面
`deps_done` 机械复核 GitHub 现态兜底，不靠这张图。
"""

from string import Template

PROMPT = Template(
    """你是 issue 依赖排序 agent（curator）。给定当前所有待做（ready）的 open issue 快照，判断它们
之间的**逻辑先后依赖**：哪个 issue 必须等另一个先做完（PR merged）之后才能开始。

依赖的两类来源：
① 逻辑序——A 先定义/改动了 B 依赖的接口、数据模型、契约，B 必须在 A 之后（即便两者不碰同一文件）；
② 文件冲突序——A、B 会改同一批文件、并行会写冲突，需错峰（有把握时才排，拿不准归第①类判断）。

**已有依赖边是锚点，只读不改。** 下方「已有边」是人已在 GitHub UI 手设、或上轮已落的边——原样尊重、
**不要重排、不要删、不要为已有入边的 issue 再排**。你只为**当前尚无任何入边的新节点**补建议边。

判定纪律（**fail-open，宁可漏排、不可凭空造依赖**）：只有当依赖确实存在、且顺序做错会让后者跑偏
或写冲突时才排边；拿不准两个 issue 有没有先后关系，就判**独立**（不排边）。假依赖会凭空冻住本可并行
的流转，比漏排一条更糟——漏排顶多少并行一点，执行面会据 GitHub 现态复核。

最后只输出一行 JSON：
{"edges": [{"issue": <被挡 issue 号>, "blocked_by": [<挡它的 issue 号>, ...], "rationale": "<为何这个序>"}, ...]}
无任何新依赖时输出 {"edges": []}。

当前 ready open issue 快照：
$issue_snapshot

已有依赖边（锚点，只读不改）：
$existing_edges
"""
)

OUTPUT_SCHEMA = {"edges": list}

__all__ = ["PROMPT", "OUTPUT_SCHEMA"]
