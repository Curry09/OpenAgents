"""Spec-0043/T2: issue 进 RFC 前的自洽性自检——判读标题/正文是否有「会直接影响修法」的冲突。

vigil 发现段派单 start_rfc 起草 spec 之前，用注入的 backend 判读 issue 的**标题与正文**是否
存在会直接影响修法方向的内在逻辑冲突（issue #111 划定五类：①标题修法≠正文修法；②根因≠建议
修法；③互斥修法未取舍；④问题是 A 修的是 B；⑤已知取舍未声明）。命中则不起草 spec，改由调用方
（orchestrator）打 needs-human + 贴对齐评论请人取舍——把「进 RFC 前先看 issue 自不自洽」这道
原本靠人肉的闸下沉为自动流水线里的硬谓词（issue #106→PR #107 事故：标题=sha 缓存、正文=hold-merge
冻结，若按标题起草会做出与正文/最终实现南辕北辙的 spec）。

本模块是纯逻辑——「草稿进、结构化裁决出」+「渲染对齐评论」，不持有任何 I/O：不碰 GitHub、不碰
argparse、不读 stdin（理念 1/10 解耦），backend 依赖注入、打桩可测。形态刻意对齐 align.py
（Spec-0020：Draft dataclass + `_MARK_*` 标记回解析 + backend 注入 + 生成与判定分离）与 reviewer.py
（RFC-0012：backend judge → 结构化裁决）——但容错方向相反：reviewer「疑罪从严 fail-closed」，
本模块取「疑无从宽 fail-open」（无法解析出明确冲突 → 放行照常起草）。issue #111 明确警告过度触发
（拦下健康 issue、逼人白确认、噪声淹没人的宏观把控）比漏判更违背意图，且本闸是**建议性**的——即便
漏判，人仍在审 PR 时兜底，故偏向「宁可漏判、不可滥拦」（见 spec Rationale 备选 3）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openagents.backends.base import AgentBackend

# Spec-0043/T2：判读输出的稳定标记——既是喂给 backend 的输出契约，也是 _parse_verdict 回解析的锚点
# （对齐 align.py 的 `_MARK_*` 套路）。CONFLICT 行只认「是/否」，冲突点/候选修法各占若干行。
_MARK_CONFLICT = "冲突："
_MARK_POINT = "冲突点："
_MARK_FIX = "候选修法："

# Spec-0043/T2：只有明确写「冲突：是」才判有冲突（fail-open）。肯定集合窄而稳，避免正文里偶现
# 的「是」污染裁决——必须是 CONFLICT 行紧跟的裁决值。
_AFFIRMATIVE_CONFLICT = {"是", "yes", "true", "有"}

# Spec-0043/T2：判读指令——要求后端严格按标记格式输出，并内嵌 issue #111 划定的五类冲突 +
# 「不吹毛求疵」负面清单，让判读聚焦「会直接影响修法方向」的冲突（措辞可随实测样本再调，见
# spec Unresolved）。裁决行置首，冲突点/候选修法各若干行——即便被截断，丢的也是尾部而非裁决头。
_CHECK_TASK = (
    "你是独立的 issue 自洽性审核员。请只读下面这个 issue 的标题与正文，判断它是否存在"
    "「会直接影响修法方向」的内在逻辑冲突——即：若不先跟人对齐，agent 就可能据此生成"
    "错误方向的 spec / 错误实现。只抓以下五类会直接影响实现方向的冲突：\n"
    "① 标题主张的修法 ≠ 正文主张的修法；\n"
    "② 根因分析 ≠ 建议的修法；\n"
    "③ 存在两个互斥的修法但 issue 未取舍；\n"
    "④「问题是 A、要修的却是 B」；\n"
    "⑤ 存在已知取舍但 issue 未声明是否接受。\n"
    "【不吹毛求疵】个别措辞不统一、非关键背景略啰嗦、不影响修法方向的轻微歧义——一律判"
    "『冲突：否』放行，不要打扰人。过度触发（把健康 issue 判成冲突）比漏判更糟。\n"
    "【硬性格式】严格按以下格式输出，第一行必须是裁决行，理由写在其后：\n"
    f"{_MARK_CONFLICT}<是 或 否>\n"
    f"{_MARK_POINT}<若有冲突，一条冲突点的人话描述；每条冲突点单独一行>\n"
    f"{_MARK_FIX}<若有互斥修法，一个候选修法；每个候选修法单独一行，供人取舍>\n"
    "只在确有『会直接影响修法方向』的冲突时才写『冲突：是』并列出冲突点；否则写『冲突：否』。"
)


@dataclass(frozen=True)
class IssueDraft:
    """Spec-0043/T2：待判读的 issue 快照——标题 + 正文（与 align.Draft 同构的冻结 dataclass）。"""

    title: str
    body: str


@dataclass(frozen=True)
class ConflictVerdict:
    """Spec-0043/T2：判读裁决——是否有会直接影响修法的冲突 + 冲突点 + 候选修法。

    has_conflict: 是否命中「会直接影响修法方向」的冲突（fail-open：仅在明确『冲突：是』+
        至少一条冲突点时为 True）。
    conflicts: 每条 = 一个冲突点的人话描述（供渲染给人看）。
    candidate_fixes: 互斥的候选修法（供人取舍其一或说明合并方案）；可能为空（有冲突但未列出
        清晰候选时仍拦，靠 conflicts 说明）。
    """

    has_conflict: bool
    conflicts: tuple[str, ...] = ()
    candidate_fixes: tuple[str, ...] = ()


# Spec-0043/T2：对齐评论固定文案——标题句 + 摘标签指引（镜像 blocknote.build 的「给人看的
# 结构化挂起评论」形态：标题 + 分段列表 + 指引，无签名、无 IO，签名交调用方）。
_HEADER = "🔀 这个 issue 在修法方向上可能存在内在冲突，建议先对齐再进 RFC"
_POINTS_HEADER = "检测到的冲突点："
_FIXES_HEADER = "候选修法（请取舍其一或说明合并方案）："
_GUIDANCE = (
    "我已打上 `needs-human` 暂缓自动起草。请在 issue 里确认取舍（或补充说明后**摘掉 "
    "`needs-human` 标签**），我再进 RFC/spec。"
)


def check(*, draft: IssueDraft, backend: AgentBackend) -> ConflictVerdict:
    """Spec-0043/T2：调注入的 backend 判读 issue 是否有会直接影响修法的冲突（不打印、不做 IO）。

    backend 以关键字参数注入（遵 CLAUDE.md 参数规范）；判读文本由 _parse_verdict 按稳定标记
    组织成 ConflictVerdict。解析容错 fail-open：无法解析出明确「有冲突」信号（缺标记 / 空串 /
    格式跑偏 / 写了『冲突：是』却没列出任何冲突点）→ has_conflict=False（放行照常起草）。
    """
    result = backend.run(
        work_dir=Path.cwd(),
        task=_CHECK_TASK,
        context=f"标题：{draft.title}\n正文：{draft.body}",
    )
    return _parse_verdict(text=result.summary)


def build_alignment_comment(*, verdict: ConflictVerdict) -> str:
    """Spec-0043/T2：把裁决渲染成结构化 markdown 对齐评论正文（纯函数，不含签名、无 IO）。

    含：标题句 + 冲突点列表 + 候选修法取舍列表 + 「已打 needs-human，请对齐后摘标签」指引。
    绝不含「🤖 卡住了」等 PR 失败文案（这是 issue 级「请取舍」，非 PR 级求救）。候选修法为空时
    省略该段（有冲突点即可请人对齐）。签名由调用方（orchestrator 经 identity.sign）盖。
    """
    lines = [_HEADER, ""]
    if verdict.conflicts:
        lines.append(_POINTS_HEADER)
        lines.extend(f"- {point}" for point in verdict.conflicts)
        lines.append("")
    if verdict.candidate_fixes:
        lines.append(_FIXES_HEADER)
        lines.extend(f"- {fix}" for fix in verdict.candidate_fixes)
        lines.append("")
    lines.append(_GUIDANCE)
    return "\n".join(lines)


def _parse_verdict(*, text: str) -> ConflictVerdict:
    """Spec-0043/T2：把 backend 的标记输出解析成 ConflictVerdict；容错 fail-open。

    按标记逐行拆：`冲突：` 行的值落进 _AFFIRMATIVE_CONFLICT 才算有冲突意向；`冲突点：` /
    `候选修法：` 各行剥前缀后收集为非空条目。**只有**「明确判有冲突意向 **且** 至少列出一条
    冲突点」才 has_conflict=True——写了『冲突：是』却没给任何冲突点，视为格式跑偏、fail-open
    放行（避免空拦），把「宁可漏判、不可滥拦」写进解析容错（spec Rationale 备选 3）。
    """
    conflict_intent = False
    conflicts: list[str] = []
    candidate_fixes: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(_MARK_CONFLICT):
            value = stripped[len(_MARK_CONFLICT) :].strip().lower()
            conflict_intent = value in _AFFIRMATIVE_CONFLICT
        elif stripped.startswith(_MARK_POINT):
            point = stripped[len(_MARK_POINT) :].strip()
            if point:
                conflicts.append(point)
        elif stripped.startswith(_MARK_FIX):
            fix = stripped[len(_MARK_FIX) :].strip()
            if fix:
                candidate_fixes.append(fix)
    has_conflict = conflict_intent and bool(conflicts)
    if not has_conflict:
        # fail-open：没有明确冲突信号 → 放行，不带半吊子冲突点/候选修法。
        return ConflictVerdict(has_conflict=False)
    return ConflictVerdict(
        has_conflict=True,
        conflicts=tuple(conflicts),
        candidate_fixes=tuple(candidate_fixes),
    )
