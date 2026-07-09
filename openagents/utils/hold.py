"""Spec-0020/T2: vigil --hold 闸门配置模型。

把 `vigil --hold` 的逗号分隔字符串（'spec' / 'merge' / 'spec,merge' / 空）解析成一个
不可变的 Hold 值对象，告诉流水线在哪几道**意图闸门**停下等人。这是一段纯解析逻辑，
被 CLI（解析输入，T4）与流水线（消费判定，T3）共享——单点定义、多处引用，避免「同一
字符串散落多处」的漂移。本模块无任何 I/O、无 argparse、无 GitHub 依赖（CLAUDE.md 理念
1 奥卡姆 / 10 解耦）。

Spec-0020/T2：Hold 刻意只携带 at_spec / at_merge 两个布尔意图（对应 issue #59 列出的两道
闸门，没有第三种），不做开放枚举集合以保持最小。未知 token 立即报错而非静默忽略——否则
`--hold spc`（拼错）会被当成「全不停」从而悄悄丢掉监督，违背安全默认。
"""

from __future__ import annotations

from dataclasses import dataclass

# Spec-0020/T2：两道合法闸门 token——单点定义，解析与报错信息共用，杜绝字面量漂移。
_GATE_SPEC = "spec"
_GATE_MERGE = "merge"
_VALID_GATES = (_GATE_SPEC, _GATE_MERGE)


@dataclass(frozen=True)
class Hold:
    """Spec-0020/T2：不可变闸门意图——在 spec 闸 / merge 闸是否停下等人。"""

    at_spec: bool = False
    at_merge: bool = False


# Spec-0020/T2：「全不停」默认实例——无 --hold 时使用，等价于现状全自动 vigil 行为。
NONE = Hold()


def parse_hold(*, raw: str | None) -> Hold:
    """Spec-0020/T2：把 --hold 原始串解析成 Hold。

    空串 / None → 默认 Hold（at_spec=at_merge=False，全不停）；逗号分隔的 spec / merge
    （容忍多余空格与大小写）→ 对应布尔置位；未知 token → 抛 ValueError 并列出合法取值。
    """
    if raw is None:
        return NONE
    tokens = [token.strip().lower() for token in raw.split(",") if token.strip()]
    if not tokens:
        return NONE
    at_spec = False
    at_merge = False
    for token in tokens:
        if token == _GATE_SPEC:
            at_spec = True
        elif token == _GATE_MERGE:
            at_merge = True
        else:
            valid = " / ".join(_VALID_GATES)
            raise ValueError(f"未知的 --hold 闸门 {token!r}；合法取值：{valid}")
    return Hold(at_spec=at_spec, at_merge=at_merge)
