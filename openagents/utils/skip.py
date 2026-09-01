"""Spec-0054/T1: ``vigil --skip`` 逐闸旁路开关配置模型。

把 `vigil --skip` 的逗号分隔字符串（'spec' / 'ci' / 'spec,ci' / 'all' / 空）解析成一个
不可变的 Skip 值对象，告诉自主环把哪几道 **CLI 可达的流水线闸门**当作 PASS 直接放行。
这是一段纯解析逻辑，被 CLI（解析输入，T3）与流水线（消费判定，T2）共享——单点定义、
多处引用，避免「同一字符串散落多处」的漂移。本模块无任何 I/O、无 argparse、无 GitHub
依赖（CLAUDE.md 理念 1 奥卡姆 / 10 解耦）。

Spec-0054/T1：Skip 刻意只携带 issue / spec / code / ci / evidence 五道闸的布尔意图，
``merge`` 是不可逆动作，不提供 skip；可合并性预检也不设 skip。
未知 token（包括 ``merge``）立即报错，防止拼写错误静默改变闸门意图。
"""

from __future__ import annotations

from dataclasses import dataclass

# Spec-0054/T1：五道 CLI 可达的合法闸门 token + 聚合 all——单点定义，解析与报错信息共用，
# 杜绝字面量漂移。刻意无 "merge"：合并不可跳过。
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
    已不合法的 'merge'）→ 抛 ValueError 并列出合法取值。
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
