"""Spec-0058/T2：跨 issue 调度的标签代数（纯函数，无 IO）——blocked-by 解析 / sched-ready 派生 / 对账。

标签是这张 issue DAG 的**持久唯一真值**（issue #150）：每条「下游 ← 上游」落成下游的
`blocked-by:#<上游号>` 标签；一个 issue 无任何**未满足**上游即派生 `sched-ready`。本模块是围绕
这份标签真值的纯代数——解析、派生、把「边集 + 当前标签」对账成**幂等**的 add / remove 动作，
不含任何 IO（不发网络、不碰 github；落标签的副作用由 orchestrator.schedule 编排、messages 门控只读）。

镜像 github.py 流程标签「单一来源」思路：只有 `schedule`（命令 + vigil 保鲜）写这两类标签，
`messages` 门控只 `has_unsatisfied_block` 读——避免多处写标签漂移（见 spec Reference-level「标签契约」）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openagents.scheduler import ScheduleVerdict

# Spec-0058/T2：标签契约常量（唯一真值的字面量）。blocked-by:#<N> 表本 issue 有一条未满足的上游边
# 指向 #N（可挂多个）；sched-ready 表本 issue 无任何未满足上游、可入执行波次（供未来 #137 执行器消费）。
BLOCKED_BY_PREFIX = "blocked-by:#"
SCHED_READY = "sched-ready"


def parse_blocked_by(*, labels) -> set[int]:
    """Spec-0058/T2：从标签名集合解析出所有 `blocked-by:#<N>` 的上游号（纯解析）。

    只认前缀命中且后段为纯数字的标签；其它标签（openagents / sched-ready / 任意人类标签）忽略。
    """
    upstreams: set[int] = set()
    for label in labels or []:
        if not isinstance(label, str) or not label.startswith(BLOCKED_BY_PREFIX):
            continue
        tail = label[len(BLOCKED_BY_PREFIX) :].strip()
        if tail.isdigit():
            upstreams.add(int(tail))
    return upstreams


def has_unsatisfied_block(*, labels) -> bool:
    """Spec-0058/T2：messages 门控读侧——本 issue 是否还挂任一 `blocked-by:#N`（纯存在性检查）。

    「满足」由保鲜轮据 open 集剪除后体现（上游 closed → 保鲜摘掉该 blocked-by），门控本身**不发网络**
    判 open——挂着 blocked-by 就视为未满足、挡写码；标签滞后一轮只是「慢一轮」而非「错」（读时自愈，
    见 spec Reference-level「满足判定」）。
    """
    return bool(parse_blocked_by(labels=labels))


def blocked_by_label(*, upstream: int) -> str:
    """Spec-0058/T2：拼一条 `blocked-by:#<上游号>` 标签名（落标签动作与解析共用同一前缀，避免漂移）。"""
    return f"{BLOCKED_BY_PREFIX}{upstream}"


@dataclass(frozen=True)
class LabelPlan:
    """Spec-0058/T2：一次对账产出的标签动作——每个 issue 号 → 要 add / remove 的标签名集合。

    adds / removes 都是 {issue_number: {label_name, ...}}，只含「与当前标签有差异」的动作（幂等：
    已就位的标签不进 adds、本不在的标签不进 removes）。空集的 issue 不出现在 dict 里。
    """

    adds: dict[int, set[str]] = field(default_factory=dict)
    removes: dict[int, set[str]] = field(default_factory=dict)


def plan_labels(
    *,
    verdict: ScheduleVerdict,
    open_issue_numbers: set[int],
    current_labels: dict[int, set[str]],
) -> LabelPlan:
    """Spec-0058/T2：把边集 + 当前标签对账成**幂等** add / remove 动作。

    - **只对上游仍 open 的边保留 blocked-by**：上游已不在 open 集（合并 / 关闭）的边视为已满足，其
      blocked-by 进 removes（自动剪边解封的铁证）；
    - **无剩余 blocked-by 者派生 sched-ready**、有剩余则 remove sched-ready；
    - **幂等**：只有当「目标标签集」与「当前标签集」有差异时才产出 add / remove，故同一世界重复跑
      不产生标签抖动（见 spec 决策「标签是唯一真值」）。

    open_issue_numbers：当前 open 的 issue 号集（满足判定的口径）；current_labels：每个待排 issue 的
    当前标签名集合（读侧由 orchestrator 从 github 取）。只对 current_labels 覆盖到的 issue 对账。
    """
    # 每个下游 issue → 它当前**应挂**的、上游仍 open 的 blocked-by 上游号集。
    desired_blocks: dict[int, set[int]] = {}
    for edge in verdict.edges:
        if edge.upstream in open_issue_numbers:
            desired_blocks.setdefault(edge.downstream, set()).add(edge.upstream)

    adds: dict[int, set[str]] = {}
    removes: dict[int, set[str]] = {}
    for issue_number, labels in current_labels.items():
        want = {blocked_by_label(upstream=up) for up in desired_blocks.get(issue_number, set())}
        have = {label for label in labels if label.startswith(BLOCKED_BY_PREFIX)}
        add = want - have
        remove = have - want
        # sched-ready 派生：目标上「无任何 blocked-by」即应带 sched-ready，反之应摘。
        has_sched_ready = SCHED_READY in labels
        if not want:
            if not has_sched_ready:
                add.add(SCHED_READY)
        elif has_sched_ready:
            remove.add(SCHED_READY)
        if add:
            adds[issue_number] = add
        if remove:
            removes[issue_number] = remove
    return LabelPlan(adds=adds, removes=removes)
