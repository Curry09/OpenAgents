"""Spec-0054/T1: vigil --skip 逐闸旁路开关配置模型（与 hold.py 对称）。

把 `vigil --skip` 的逗号分隔字符串（'spec' / 'ci' / 'spec,ci' / 'all' / 空）解析成一个
不可变的 Skip 值对象，告诉自主环把哪几道 **CLI 可达的流水线闸门**当作 PASS 直接放行。
这是一段纯解析逻辑，被 CLI（解析输入，T3）与流水线（消费判定，T2）共享——单点定义、
多处引用，避免「同一字符串散落多处」的漂移。本模块无任何 I/O、无 argparse、无 GitHub
依赖（CLAUDE.md 理念 1 奥卡姆 / 10 解耦），与 openagents/hold.py 逐行同构。

Spec-0054/T1：Skip 刻意只携带 issue / spec / code / ci / evidence 五道闸的布尔意图，
**不含 at_merge**——merge（合并前夯住）只归 --hold（更严方向），跳过合并没有实质放行
语义（见 spec Rationale 备选 4）；可合并性预检也不设 skip（它只是省功早退，跳过它不放
行任何东西）。未知 token（含 'merge'，对 --skip 已不再合法）立即报错而非静默忽略——否则
`--skip spc`（拼错）会被当成「全闸开启」从而悄悄丢掉本想关的闸，与 --hold 同款安全纪律。

矛盾检测（本模块唯一的新语义）：`--hold` 与 `--skip` 若对同一道闸给出相反意图
（如 `--hold spec --skip spec`：既要停下等人又要放行跳过）立即报错而非静默取其一。
Hold 只有 at_spec / at_merge 两个意图，与 Skip 唯一可能相交的 token 是 spec。
"""

from __future__ import annotations

from dataclasses import dataclass

from openagents.utils.hold import Hold

# Spec-0054/T1：五道 CLI 可达的合法闸门 token + 聚合 all——单点定义，解析与报错信息共用，
# 杜绝字面量漂移。刻意无 "merge"：merge 归 --hold（见模块 docstring / spec 备选 4）。
_GATE_ISSUE = "issue"
_GATE_SPEC = "spec"
_GATE_CODE = "code"
_GATE_CI = "ci"
_GATE_EVIDENCE = "evidence"
_GATE_ALL = "all"
_VALID_GATES = (_GATE_ISSUE, _GATE_SPEC, _GATE_CODE, _GATE_CI, _GATE_EVIDENCE, _GATE_ALL)


@dataclass(frozen=True)
class Skip:
    """Spec-0054/T1：不可变闸门旁路意图——把哪几道 CLI 可达的闸当 PASS 直接放行。"""

    at_issue: bool = False
    at_spec: bool = False
    at_code: bool = False
    at_ci: bool = False
    at_evidence: bool = False


# Spec-0054/T1：「全不关」默认实例——无 --skip 时使用，等价于现状全闸开启的 vigil 行为。
NONE = Skip()


def parse_skip(*, raw: str | None) -> Skip:
    """Spec-0054/T1：把 --skip 原始串解析成 Skip。

    空串 / None → 默认 Skip（全 False，全闸开启）；逗号分隔的 issue / spec / code / ci /
    evidence（容忍多余空格与大小写）→ 对应布尔置位；`all` → 五道全置位；未知 token（含
    已不合法的 'merge'）→ 抛 ValueError 并列出合法取值（与 parse_hold 逐字节同款报错纪律）。
    """
    if raw is None:
        return NONE
    tokens = [token.strip().lower() for token in raw.split(",") if token.strip()]
    if not tokens:
        return NONE
    at_issue = False
    at_spec = False
    at_code = False
    at_ci = False
    at_evidence = False
    for token in tokens:
        if token == _GATE_ALL:
            at_issue = at_spec = at_code = at_ci = at_evidence = True
        elif token == _GATE_ISSUE:
            at_issue = True
        elif token == _GATE_SPEC:
            at_spec = True
        elif token == _GATE_CODE:
            at_code = True
        elif token == _GATE_CI:
            at_ci = True
        elif token == _GATE_EVIDENCE:
            at_evidence = True
        else:
            valid = " / ".join(_VALID_GATES)
            raise ValueError(f"未知的 --skip 闸门 {token!r}；合法取值：{valid}")
    return Skip(
        at_issue=at_issue,
        at_spec=at_spec,
        at_code=at_code,
        at_ci=at_ci,
        at_evidence=at_evidence,
    )


def reconcile_hold_skip(*, hold: Hold, skip: Skip) -> None:
    """Spec-0054/T1：hold 与 skip 对同一道闸的矛盾意图检测——命中即 raise ValueError。

    纯函数，无 IO。判据取「两侧共享 token 的交集非空」：Hold 只有 at_spec / at_merge 两个
    意图，Skip 无 at_merge，故唯一可能相交的闸是 **spec**——同一道 spec 闸若被同时要求
    「停下等人」（--hold spec）与「放行跳过」（--skip spec）即矛盾，报一行清楚提示（点名
    闸名 + 两种意图），绝不静默取其一。**软约定硬化**：把「别对同一闸既 hold 又 skip」从一
    句正文告诫落成一个会 raise 的纯函数，让它在 CLI 入口根本无法悄悄通过。
    """
    if hold.at_spec and skip.at_spec:
        raise ValueError(
            "spec 闸同时被 --hold（停下等人）与 --skip（放行跳过）指定，语义矛盾；二者只能取其一"
        )
