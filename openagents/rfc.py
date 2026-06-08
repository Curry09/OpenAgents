"""RFC 文档语义：从一份 RFC Markdown 抽取「端到端验证」线索并渲染指路牌。

RFC-0008: PR 正文「端到端验证」指路牌（从 RFC 自动生成）

只懂 RFC 文档结构的纯模块——不感知 git / GitHub / orchestrator（理念 10 解耦）。
对外暴露三件事（见 RFC-0008 接口契约）：
- `extract_e2e`：从 RFC 全文抽取脚本路径与一行预期，缺失置 None，绝不抛错。
- `render_signpost`：把抽取结果渲染成「## 端到端验证」段落，逐 bullet 降级兜底。
- `signpost_for`：读文件 + 解析文件名编号 + 抽取 + 渲染的便捷封装，出错返回 None。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# RFC-0008 决策 5：脚本路径限定在「集成测试」子段、预期限定在「手动验证」子段内抽取，
# 避免误命中文档其他位置出现的脚本名 / 文字。
_INTEGRATION_HEADING = "集成测试"
_MANUAL_HEADING = "手动验证"

# RFC 文件名形如 NNNN-slug.md，开头四位数字即 RFC 编号。
_RFC_FILENAME_RE = re.compile(r"^(\d{4})-")
# 集成测试段内的脚本相对路径：scripts/….sh，取首个。
_SCRIPT_RE = re.compile(r"scripts/[^\s`)」]+\.sh")
# 子段标题（### X），下一处任意级别标题（# 开头）即子段结束。
_HEADING_LINE_RE = re.compile(r"^#{1,6}\s")


@dataclass(frozen=True)
class E2EHints:
    """RFC-0008：从 RFC 抽出的端到端验证线索。

    字段缺失即置 None，渲染时各自降级为指向 RFC 的提示。
    """

    script_path: str | None  # 集成测试脚本相对路径；无则 None
    expected: str | None  # 手动验证首步的一行预期效果；无则 None


def extract_e2e(*, rfc_text: str) -> E2EHints:
    """Extract e2e hints (script path + one-line expectation) from RFC text.

    RFC-0008 决策 5：纯字符串解析，缺失字段置 None，绝不抛错。
    """
    # 1. 集成测试子段内取首个脚本路径。
    integration_body = _section_body(rfc_text=rfc_text, heading=_INTEGRATION_HEADING)
    script_path = _first_script_path(text=integration_body)

    # 2. 手动验证子段内取首步的一行预期。
    manual_body = _section_body(rfc_text=rfc_text, heading=_MANUAL_HEADING)
    expected = _first_expected(text=manual_body)

    return E2EHints(script_path=script_path, expected=expected)


def render_signpost(*, rfc_number: int, hints: E2EHints) -> str:
    """Render the「## 端到端验证」signpost Markdown block.

    RFC-0008 决策 5：按 hints 各字段有无逐 bullet 降级——缺脚本/缺预期时该 bullet
    降级为指向 RFC 的提示，而非省略或报错。
    """
    rfc_id = f"RFC-{rfc_number:04d}"

    # 1. 「跑」bullet：有脚本则给可直接执行的命令，否则指回 RFC 集成测试段。
    if hints.script_path:
        run_line = f"- 跑：`bash {hints.script_path}`"
    else:
        run_line = f"- 跑：见 {rfc_id}「{_INTEGRATION_HEADING}」"

    # 2. 「预期」bullet：有一行预期则直接给出，否则指回 RFC 手动验证段。
    if hints.expected:
        expected_line = f"- 预期：{hints.expected}"
    else:
        expected_line = f"- 预期：见 {rfc_id}「{_MANUAL_HEADING}」"

    # 3. 「详细步骤」bullet：恒指向 RFC 手动验证段（单一来源，不复制全文）。
    detail_line = f"- 详细手动步骤见 {rfc_id}「{_MANUAL_HEADING}」"

    return "\n".join(["## 端到端验证", run_line, expected_line, detail_line])


def signpost_for(*, rfc_path: Path) -> str | None:
    """Read an RFC file and render its e2e signpost.

    RFC-0008：读 rfc_path → 从文件名解析 NNNN → extract_e2e → render_signpost。
    文件不可读 / 文件名解析不出编号时返回 None（不抛错）。
    """
    # 1. 解析文件名中的 RFC 编号；解析不出则放弃（返回 None）。
    number = _rfc_number_from_name(name=rfc_path.name)
    if number is None:
        return None

    # 2. 读文件全文；不可读则放弃（返回 None）。
    try:
        rfc_text = rfc_path.read_text(encoding="utf-8")
    except OSError:
        return None

    # 3. 抽取并渲染指路牌。
    hints = extract_e2e(rfc_text=rfc_text)
    return render_signpost(rfc_number=number, hints=hints)


def script_path_for(*, rfc_path: Path) -> str | None:
    """Read an RFC file and return its e2e script relative path (or None).

    RFC-0013：读 rfc_path → extract_e2e（复用 RFC-0008）→ 返回 hints.script_path。
    文件不可读 / 无集成测试脚本时返回 None（不抛错）。与 signpost_for 对称：把「读文件 +
    RFC 语义解析」收在 rfc.py，orchestrator 不做文件 IO（理念 10 解耦）。
    """
    try:
        rfc_text = rfc_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return extract_e2e(rfc_text=rfc_text).script_path


def _rfc_number_from_name(*, name: str) -> int | None:
    """从 RFC 文件名（NNNN-slug.md）解析整型编号；不匹配返回 None。"""
    match = _RFC_FILENAME_RE.match(name)
    if match is None:
        return None
    return int(match.group(1))


def _section_body(*, rfc_text: str, heading: str) -> str:
    """取 `### {heading}` 子段的正文（到下一处任意级别标题为止）；无该子段返回空串。"""
    lines = rfc_text.splitlines()
    target = f"### {heading}"

    # 1. 定位子段标题行。
    start = None
    for index, line in enumerate(lines):
        if line.strip() == target:
            start = index + 1
            break
    if start is None:
        return ""

    # 2. 自标题行之后收集，遇下一处标题（# 开头）即止。
    body: list[str] = []
    for line in lines[start:]:
        if _HEADING_LINE_RE.match(line):
            break
        body.append(line)
    return "\n".join(body)


def _first_script_path(*, text: str) -> str | None:
    """集成测试子段正文里取首个 scripts/….sh；无则 None。"""
    match = _SCRIPT_RE.search(text)
    return match.group(0) if match else None


def _first_expected(*, text: str) -> str | None:
    """手动验证子段正文里取首步的一行预期；无则 None。

    首步为首个有序/无序列表项；若该项含「→」箭头，取末个箭头之后的预期部分，
    否则取整项文本。结果压成单行。
    """
    for raw in text.splitlines():
        line = raw.strip()
        # 1. 命中首个列表项（`1. …` 或 `- …` / `* …`）。
        item = re.match(r"^(?:\d+\.|[-*])\s+(.*)$", line)
        if item is None:
            continue
        step = item.group(1).strip()
        if not step:
            return None
        # 2. 「行为 → 预期」式步骤取末个箭头后的预期；否则取整步文本。
        if "→" in step:
            step = step.rsplit("→", 1)[1].strip()
        return step or None
    return None
