"""Spec-0020/T1: issue 前门对齐——把模糊想法复述成「要做 X / 边界 Y / 不做 Z」。

提 issue 前，先让注入的 backend 用大白话把 issue 草稿复述成结构化三段，供调用方（T4 的
cli）打印给人确认后才正式建 issue。这是 issue #59 两道意图层闸门里的「前门对齐」：当前
流程里人唯一的真实检查点是审 PR——代码全写完才暴露理解偏差，是最贵的纠错点；前门对齐
在想法落成正式 issue 之前先把范围对齐一次（CLAUDE.md 理念 5 人负责宏观把控）。

本模块是纯逻辑——「草稿进、复述出」+「确认判定」，不持有任何 I/O：不碰 GitHub、不碰
argparse、不读 stdin，与 CLI 参数解析、GitHub 调用解耦（CLAUDE.md 理念 1/10）。复述用
LLM 而非模板：issue #59 要的是把人脑子里模糊的话**重新组织**成边界清晰的三段，模板只能
机械回显、给不出归纳。代价是给 issue 这条线引入 backend 依赖；用依赖注入 + 打桩缓解可测
性。复述生成（要 backend）与确认判定（纯谓词）刻意拆成两件事，便于分别测试，也让 T4 的
`--yes` 自动化路径无需构造 backend 即可放行。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openagents.backends.base import AgentBackend

# Spec-0020/T1：复述三段的稳定标记——既是喂给 backend 的输出契约，也是回解析的锚点。
_MARK_WANT = "要做："
_MARK_BOUNDARY = "边界："
_MARK_NON_GOALS = "不做："

# Spec-0020/T1：肯定应答集合——确认判定只认显式肯定，其余（含空串）一律不放行（安全默认）。
_AFFIRMATIVE = {"y", "yes"}

# Spec-0020/T1：喂给 backend 的复述指令——要求严格按三行标记格式输出，便于稳定回解析。
_RESTATE_TASK = (
    "请用大白话把下面这个 issue 草稿复述成三段，帮助提 issue 的人确认范围对齐。"
    "严格按以下三行格式输出，每段一行、不要多余内容：\n"
    f"{_MARK_WANT}<我理解你要做的事>\n"
    f"{_MARK_BOUNDARY}<这件事的边界 / 范围>\n"
    f"{_MARK_NON_GOALS}<明确不做的事>"
)


@dataclass(frozen=True)
class Draft:
    """Spec-0020/T1：issue 草稿——前门对齐的输入（title/body）。"""

    title: str
    body: str


@dataclass(frozen=True)
class Alignment:
    """Spec-0020/T1：结构化复述——要做 X / 边界 Y / 不做 Z 三段。"""

    want: str
    boundary: str
    non_goals: str

    def render(self) -> str:
        """Spec-0020/T1：人类可读渲染（供 T4 打印给人确认），含三段标识。"""
        return f"我理解你{_MARK_WANT}{self.want}\n{_MARK_BOUNDARY}{self.boundary}\n{_MARK_NON_GOALS}{self.non_goals}"


def restate(*, draft: Draft, backend: AgentBackend) -> Alignment:
    """Spec-0020/T1：调注入的 backend 把草稿复述成三段 Alignment（不打印、不读输入）。

    backend 以关键字参数注入（遵 CLAUDE.md Python 参数规范）；复述文本由本模块按稳定标记
    组织成结构化对象，确认与否的判定交给独立的 `is_confirmed` 谓词，调用方负责打印与读应答。
    """
    result = backend.run(
        work_dir=Path.cwd(),
        task=_RESTATE_TASK,
        context=f"标题：{draft.title}\n正文：{draft.body}",
    )
    return _parse_alignment(text=getattr(result, "protocol_output", result.summary))


def is_confirmed(*, answer: str) -> bool:
    """Spec-0020/T1：确认判定——肯定应答放行，否定/空一律不放行（与复述生成解耦、不调 backend）。"""
    return answer.strip().lower() in _AFFIRMATIVE


def _parse_alignment(*, text: str) -> Alignment:
    """Spec-0020/T1：把 backend 的三行复述按标记拆成三段；缺段回落空串（容错）。"""
    sections = {_MARK_WANT: "", _MARK_BOUNDARY: "", _MARK_NON_GOALS: ""}
    for line in text.splitlines():
        stripped = line.strip()
        for mark in sections:
            if stripped.startswith(mark):
                sections[mark] = stripped[len(mark) :].strip()
    return Alignment(
        want=sections[_MARK_WANT],
        boundary=sections[_MARK_BOUNDARY],
        non_goals=sections[_MARK_NON_GOALS],
    )
